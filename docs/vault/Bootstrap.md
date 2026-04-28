# Install

Install Paper Crown as a uv tool. This creates the `papercrown` command in uv's
tool directory and keeps Paper Crown isolated from project virtual
environments. Releases are published as wheel assets on GitHub Releases, not
PyPI. Install the desired release with uv:

```sh
uv tool install https://github.com/nccurry/papercrown/releases/download/v1.0.0/papercrown-1.0.0-py3-none-any.whl
papercrown --help
```

Replace `1.0.0` with the release version you want. For an unreleased build from
the default branch, use `uv tool install git+https://github.com/nccurry/papercrown.git`.

If your shell cannot find `papercrown` after installation, run:

```sh
uv tool update-shell
```

Then open a new terminal.

uv installs Paper Crown's Python runtime dependencies into the tool
environment. Run `papercrown doctor` inside a project before rendering. It
checks the recipe, content, bundled resources, and local external tools such as
Pandoc, `obsidian-export`, and the native PDF runtime used by WeasyPrint.

:::: {.handout #launch-checklist title="Launch Checklist" tags="docs,setup,doctor"}
### Launch Checklist

- `uv tool install papercrown`
- `papercrown init my-book`
- `papercrown manifest`
- `papercrown doctor`
- `papercrown build`
- `papercrown verify`
::::

@handout.launch-checklist is the shortest path from a blank folder to a
rendered book.

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
the pinned `obsidian-export` release binary, and the MSYS2 Pango/GLib runtime
used by WeasyPrint. Rust is not required for the normal repository setup.

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

## Troubleshooting

:::: {.clue #external-toolchain title="External Toolchain Checks" tags="docs,setup,troubleshooting"}
### External Toolchain Checks

If rendering fails after the Python package installs, run `papercrown doctor`.
Most failures are missing or stale external tools: Pandoc, `obsidian-export`,
or the native libraries used by WeasyPrint on Windows.
::::

Use @clue.external-toolchain before chasing theme or Markdown problems.
