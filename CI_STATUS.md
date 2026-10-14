# OpenFOAM 13 CI/CD

The `codex/openfoam13-heat-transfer` branch targets OpenFOAM Foundation 13 on
Ubuntu 24.04. `.github/workflows/ci.yml` builds the server, runs three copied
OpenFOAM tutorial cases through the MCP case-runner, and builds the v13 Docker
image. `.github/workflows/release-openfoam13.yml` repeats those checks for an
`openfoam13-v*` tag, publishes the image to GHCR, and attaches a Linux binary
archive to a GitHub release.

The tutorial test shortens only temporary copies of the official tutorials and
does not modify OpenFOAM's installed tutorial files.
