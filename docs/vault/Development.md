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

Generated files are ignored. Do not commit `docs/site/`, `dist/`, `build/`,
`.papercrown-cache/`, or local virtual environments.
