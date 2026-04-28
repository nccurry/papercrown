# Development

Repository development is task-first. Use Task commands instead of calling
lower-level tools directly.

Bootstrap a checkout:

```sh
./scripts/bootstrap.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

Common tasks:

```sh
task deps
task lint
task test
task package
task package:verify
task audit:public
task check
```

`task check` is the local quality gate mirrored by CI. It checks dependency
state, linting, formatting, type checking, tests, packaging, package contents,
and the public tree audit.

## CI And Toolchain Versions

Repository-managed external tool versions live in `versions.env`. That file is
the source for Docker build arguments, workflow image names, and exact or
minimum external-tool policies in `dependencies.yaml`.

Python packages stay in `pyproject.toml` and `uv.lock`; do not copy those
versions into `versions.env`. CI images are toolchain-only: they provide
Python, uv, Task, Pandoc, native WeasyPrint libraries, and the pinned
`obsidian-export` binary. Each CI job still runs `uv sync --locked --all-groups`
against `uv.lock`.

Rust is intentionally not part of the normal build. `obsidian-export` is
installed from its pinned release binary by `task deps:install` and by the CI
builder image.

Dependency maintenance commands:

```sh
task deps:check
task deps:sync
task deps:install
```

`task deps:sync` audits drift between `versions.env`, `dependencies.yaml`,
Dockerfiles, install scripts, and workflows. If `versions.env` or
`Dockerfile.ci` changes in a pull request, CI builds a candidate builder image
inside that workflow and runs checks against it. The published builder image can
also be refreshed from the GitHub Actions UI with the manual CI Builder Image
workflow.

Generated files are ignored. Do not commit `docs/site/`, `dist/`, `build/`,
`.papercrown-cache/`, or local virtual environments.
