#!/usr/bin/env python3
"""Run short OpenFOAM 13 tutorial cases through the MCP case-runner tool."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from contextlib import nullcontext
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVER = Path(os.environ.get("OPENFOAM_MCP_SERVER", REPOSITORY_ROOT / "build/openfoam-mcp-server"))
TUTORIALS = Path(os.environ.get("FOAM_TUTORIALS", "/opt/openfoam13/tutorials"))
CASES = (
    ("incompressibleFluid/cavity", "foamRun -solver incompressibleFluid", "0.01"),
    ("fluid/cavity", "foamRun -solver fluid", "0.02"),
    ("incompressibleFluid/planarPoiseuille", "foamRun -solver incompressibleFluid", "0.01"),
)


def rpc(process: subprocess.Popen[str], request_id: int, method: str, params: dict) -> dict:
    assert process.stdin is not None and process.stdout is not None
    request = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    process.stdin.write(json.dumps(request) + "\n")
    process.stdin.flush()
    response_line = process.stdout.readline()
    if not response_line:
        raise RuntimeError(f"MCP server exited before replying to {method}")
    response = json.loads(response_line)
    if response.get("id") != request_id or "error" in response:
        raise RuntimeError(f"MCP {method} failed: {response}")
    return response


def main() -> int:
    if not SERVER.is_file():
        raise SystemExit(f"MCP server binary not found: {SERVER}")
    if not TUTORIALS.is_dir():
        raise SystemExit(f"OpenFOAM tutorials not found: {TUTORIALS}")

    retained_root = os.environ.get("OPENFOAM_MCP_TEST_CASE_ROOT")
    temp_context = (
        nullcontext(retained_root)
        if retained_root
        else tempfile.TemporaryDirectory(prefix="openfoam13-mcp-tutorials-")
    )
    with temp_context as temp_dir:
        work_root = Path(temp_dir)
        work_root.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["OPENFOAM_MCP_WORK_DIR"] = str(work_root / "mcp-work")
        process = subprocess.Popen(
            [str(SERVER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
            bufsize=1,
        )
        try:
            rpc(
                process,
                1,
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "openfoam13-tutorial-ci", "version": "1.0"},
                },
            )
            assert process.stdin is not None
            process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
            process.stdin.flush()
            tools = rpc(process, 2, "tools/list", {}).get("result", {}).get("tools", [])
            run_case_tool = next(
                (tool for tool in tools if tool.get("name") == "run_openfoam_case"), None
            )
            if run_case_tool is None:
                raise RuntimeError("MCP server did not register run_openfoam_case")
            solver_options = (
                run_case_tool.get("inputSchema", {})
                .get("properties", {})
                .get("solver", {})
                .get("enum", [])
            )

            for index, (relative_case, solver, end_time) in enumerate(CASES, start=3):
                if solver not in solver_options:
                    raise RuntimeError(f"Solver is missing from the tool schema: {solver}")
                source = TUTORIALS / relative_case
                case_dir = work_root / relative_case.replace("/", "__")
                shutil.copytree(source, case_dir)
                control_dict = case_dir / "system/controlDict"
                contents = control_dict.read_text()
                contents, replacements = re.subn(
                    r"(?m)^(\s*endTime\s+)\S+(\s*;)",
                    rf"\g<1>{end_time}\g<2>",
                    contents,
                    count=1,
                )
                if replacements != 1:
                    raise RuntimeError(f"Could not shorten endTime in {relative_case}/system/controlDict")
                control_dict.write_text(contents)
                if not (case_dir / "system/blockMeshDict").is_file():
                    raise RuntimeError(f"Tutorial has no local blockMeshDict: {relative_case}")

                print(f"Running {relative_case} with {solver} (endTime={end_time})", flush=True)
                response = rpc(
                    process,
                    index,
                    "tools/call",
                    {
                        "name": "run_openfoam_case",
                        "arguments": {"case_path": str(case_dir), "solver": solver},
                    },
                )
                result = response.get("result", {})
                if result.get("isError"):
                    content = "\n".join(item.get("text", "") for item in result.get("content", []))
                    raise RuntimeError(f"Tutorial failed: {relative_case}\n{content}")
                logs = "\n".join(item.get("text", "") for item in result.get("content", []))
                if "OpenFOAM case completed successfully" not in logs:
                    raise RuntimeError(f"Tutorial did not report success: {relative_case}\n{logs}")
                if "End" not in (case_dir / "solver.log").read_text(errors="replace"):
                    raise RuntimeError(f"Solver log has no normal end marker: {relative_case}")
                print(f"PASS {relative_case}", flush=True)

            return 0
        finally:
            if process.stdin is not None:
                process.stdin.close()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr is not None else ""
                raise RuntimeError(f"MCP server exited with {process.returncode}:\n{stderr}")
            if process.stderr is not None:
                process.stderr.close()


if __name__ == "__main__":
    raise SystemExit(main())
