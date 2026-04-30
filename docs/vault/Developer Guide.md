# Developer Guide

Repository development is task-first. Use Task commands instead of calling
lower-level tools directly so local work, CI, packaging, docs, and release
checks stay aligned.

## Common Tasks

```sh
task deps
task lint
task test
task package
task package:verify
task check
```

`task check` is the local quality gate mirrored by CI. It checks dependency
state, linting, formatting, type checking, tests, packaging, and package
contents.

For the package layout and subsystem ownership map, see [[Architecture]].

:::: {.clock #release-gate title="Release Gate" tags="docs,development,release"}
### Release Gate

Before release, run the same checks CI expects: dependency diagnostics, lint,
formatting, type checking, tests, packaging, package verification, public audit,
and docs build.
::::

## Toolchain Versions

Repository-managed external tool versions live in `versions.env`. That file is
the source for Docker build arguments, workflow image names, and exact or
minimum external-tool policies in `dependencies.yaml`.

Python packages stay in `pyproject.toml` and `uv.lock`; do not copy those
versions into `versions.env`. CI images are toolchain-only: they provide
Python, uv, Task, Pandoc, native WeasyPrint libraries, and the pinned
`obsidian-export` binary. Each CI job still runs `uv sync --locked --all-groups`
against `uv.lock`.

Dependency maintenance commands:

```sh
task deps:check
task deps:sync
task deps:install
```

`task deps:sync` audits drift between `versions.env`, `dependencies.yaml`,
Dockerfiles, install scripts, and workflows.

Generated files are ignored. Do not commit `docs/site/`, `dist/`, `build/`,
`.papercrown-cache/`, or local virtual environments.

## Windows PDF Runtime

Paper Crown uses MSYS2 UCRT64 Pango/GLib for WeasyPrint on Windows. Installed
users should run `papercrown doctor` in a project to detect missing or stale
native PDF runtime libraries. In a repository checkout, the maintainer setup
path is:

```powershell
task deps:install
task deps
```

The older `GTK3-Runtime Win64` package is unsupported for Paper Crown. If
`C:\Program Files\GTK3-Runtime Win64\bin` appears before MSYS2 in `PATH`, or
GLib resolves from that directory, dependency checks warn because that runtime
can trigger noisy GLib-GIO UWP app-info warnings during PDF builds.

## Repository Bootstrap

:::: {.art-slot role="splash" placement="bottom-half" art="papercrown-docs/splashes/splash-repository-bootstrap-launch-panel.png"}
::::

Maintainers working from a source checkout can use one bootstrap command.
Bootstrap only makes sure Task is available, then hands off to
`task deps:install`.

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

On Linux, macOS, WSL, or Git Bash:

```sh
./scripts/bootstrap.sh
```

After bootstrap, use Task for repository work:

```sh
task deps
task docs:build
task check
```

:::: {.clue #external-toolchain title="External Toolchain Checks" tags="docs,development,troubleshooting"}
### External Toolchain Checks

If rendering fails after the Python package installs, run `papercrown doctor`.
Most failures are missing or stale external tools: Pandoc, `obsidian-export`,
or the native libraries used by WeasyPrint on Windows.
::::
