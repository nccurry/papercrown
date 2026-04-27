# Install

Install Paper Crown as a uv tool. This creates the `papercrown` command in uv's
tool directory and keeps Paper Crown isolated from project virtual
environments.

```sh
uv tool install papercrown
papercrown --help
```

If your shell cannot find `papercrown` after installation, run:

```sh
uv tool update-shell
```

Then open a new terminal.

Run `papercrown doctor` inside a project before rendering. It checks the recipe,
content, bundled resources, and local external tools such as Pandoc,
`obsidian-export`, and the native PDF runtime used by WeasyPrint.

## Repository Bootstrap

Maintainers working from a source checkout can use one bootstrap command.
Bootstrap only makes sure Task is available, then hands off to
`task deps:install`.

## Windows

Run this from PowerShell at the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

The Windows bootstrap prefers `winget install Task.Task` when Task is missing.
After Task is available it runs:

```powershell
task deps:install
```

`task deps:install` installs or verifies uv, Python dependencies, Pandoc,
Rust, obsidian-export, and the MSYS2 Pango/GLib runtime used by WeasyPrint.

## Linux, macOS, WSL, And Git Bash

Run this from the repository root:

```sh
./scripts/bootstrap.sh
```

On Git Bash for Windows, the shell bootstrap delegates to
`scripts/bootstrap.ps1` if Task is missing. On Linux, macOS, and WSL it installs
Task into `$HOME/.local/bin` when needed and then runs `task deps:install`.

## After Repository Bootstrap

The most useful maintenance commands are:

```sh
task deps
task docs:build
task check
```
