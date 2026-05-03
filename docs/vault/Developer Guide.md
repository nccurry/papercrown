# Developer Guide

Repository work is task-first. Use Task commands so local checks, CI,
packaging, docs, and release workflows stay aligned.

## Common Tasks

```sh
task deps
task lint
task test
task package
task package:verify
task check
```

`task check` is the local quality gate mirrored by CI. It checks dependencies,
linting, formatting, type checking, tests, packaging, and package contents.

For subsystem ownership, see [[Architecture]].

:::: {.clock #release-gate title="Release Gate" tags="docs,development,release"}
### Release Gate

Before release, run dependency diagnostics, lint, formatting, type checking,
tests, packaging, package verification, public audit, and docs build.
::::

## Toolchain

Repository-managed external tool versions live in `versions.env`. Python
dependencies live in `pyproject.toml` and `uv.lock`.

```sh
task deps:check
task deps:sync
task deps:install
```

Generated files are ignored. Do not commit `docs/site/`, `dist/`, `build/`,
`.papercrown-cache/`, virtual environments, or `Paper Crown/` output trees.

## Windows PDF Runtime

Paper Crown uses MSYS2 UCRT64 Pango and GLib for WeasyPrint on Windows.
Installed users can run `papercrown doctor` in a project to detect missing or
stale native PDF runtime libraries.

Maintainers in a checkout can run:

```powershell
task deps:install
task deps
```

The older `GTK3-Runtime Win64` package is unsupported. If it appears before
MSYS2 in `PATH`, dependency checks warn because it can cause noisy GLib-GIO
warnings during PDF builds.

## Repository Bootstrap

Bootstrap ensures Task is available, then hands off to `task deps:install`.

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

On Linux, macOS, WSL, or Git Bash:

```sh
./scripts/bootstrap.sh
```

After bootstrap:

```sh
task deps
task docs:build
task check
```

:::: {.clue #external-toolchain title="External Toolchain Checks" tags="docs,development,troubleshooting"}
### External Toolchain Checks

If rendering fails after the Python package installs, run `papercrown doctor`.
Most failures are missing Pandoc, `obsidian-export`, or native WeasyPrint
libraries.
::::
