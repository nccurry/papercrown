<p align="center">
  <img src="docs/assets/papercrown-readme-hero.svg" alt="Folded paper crown above Markdown pages" width="760">
</p>

<h1 align="center">Paper Crown</h1>

<p align="center">
  <a href="https://github.com/nccurry/papercrown/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/nccurry/papercrown/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://github.com/nccurry/papercrown/actions/workflows/pages.yml"><img alt="Docs" src="https://github.com/nccurry/papercrown/actions/workflows/pages.yml/badge.svg"></a>
  <a href="https://github.com/nccurry/papercrown/actions/workflows/release.yml"><img alt="Release" src="https://github.com/nccurry/papercrown/actions/workflows/release.yml/badge.svg"></a>
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Version 1.0.0" src="https://img.shields.io/badge/version-1.0.0-2aa7a1">
  <img alt="License AGPL-3.0-or-later" src="https://img.shields.io/badge/license-AGPL--3.0--or--later-blue">
</p>

Paper Crown builds polished TTRPG PDFs and static web exports from Markdown
content that lives anywhere on disk. A recipe points at one or more content
vaults, chooses a theme, and declares the chapters to assemble.

Documentation: [https://nccurry.github.io/papercrown/](https://nccurry.github.io/papercrown/)

## Install

Paper Crown is distributed as an installed `papercrown` command. Install the
released CLI with uv:

```sh
uv tool install papercrown
papercrown --help
```

If your shell cannot find `papercrown` after installation, run:

```sh
uv tool update-shell
```

Then open a new terminal. Paper Crown installs its Python runtime dependencies
into the uv tool environment. Builds also use external tools such as Pandoc and
`obsidian-export`; run `papercrown doctor` inside a project to check the local
machine before rendering.

## Quick Start

The installed `papercrown` command is the supported product interface.

Create a new project:

```sh
papercrown init my-book
cd my-book
papercrown manifest
papercrown doctor
papercrown build
papercrown verify
```

Or run against the bundled public example from a repository checkout:

```sh
papercrown manifest examples/starfall/recipes/starfall-field-guide.yaml
```

## Repository Bootstrap

Repository development is task-first. Bootstrap installs Task if it is missing,
then lets `task deps:install` install and verify the maintainer toolchain.

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap.ps1
```

Linux, macOS, WSL, or Git Bash:

```sh
./scripts/bootstrap.sh
```

After bootstrap, use Task for repository work:

```sh
task deps
task docs:build
task check
```

## CLI

```text
papercrown build [RECIPE]
papercrown manifest [RECIPE]
papercrown doctor [RECIPE]
papercrown verify [RECIPE]
papercrown deps check
papercrown init [PATH]
papercrown themes list
papercrown themes copy NAME DEST
```

If no recipe argument is provided, Paper Crown reads `papercrown.yaml` in the
current directory and uses its `default_recipe`.

Common build options:

```sh
papercrown build book.yaml --scope book --profile print
papercrown build book.yaml --scope sections --jobs auto
papercrown build book.yaml --chapter primer
papercrown build book.yaml --target web
```

Generated files live under one caller-owned tree:

```text
<output_dir>/Paper Crown/<output_name>/
  pdf/book/
  pdf/sections/
  pdf/individuals/
  web/
  cache/
```

`output_dir` and `output_name` are recipe fields. `output_dir` may be absolute
or relative to the recipe file.

## Recipes

Minimal recipe:

```yaml
title: Starfall Field Guide
output_dir: ../output
output_name: starfall-field-guide
theme: clean-srd

vaults:
  rules: ../vault

chapters:
  - kind: file
    title: Primer
    source: rules:Primer.md
```

Content paths are not assumed to be inside the package or repository. Vaults,
art directories, theme directories, and output directories can all point at
arbitrary filesystem locations.

## Themes

List bundled themes:

```sh
papercrown themes list
```

Copy a theme for customization:

```sh
papercrown themes copy clean-srd themes/my-clean-srd
```

Then set `theme_dir: ../themes` and `theme: my-clean-srd` in a recipe.

## Documentation

The GitHub Pages site is built with Paper Crown itself:

```sh
task docs:build
task docs:serve
task docs:clean
```

Docs source lives under `docs/`. Generated output lives under `docs/site/` and
is ignored.

## Development

All local and CI quality gates run through Task.

```sh
task deps
task setup
task lint
task test
task package
task package:verify
task audit:public
task check
```

`task docker:check` runs `task check` inside `Dockerfile.ci`.

Tag pushes matching `v*` run the release workflow, which builds the package,
verifies runtime resources, audits the public tree, and creates a GitHub
Release from `dist/`.

## Dependency Tracking

`dependencies.yaml` is the repo-owned index for non-content dependencies. It
does not duplicate lockfiles: Python runtime and dev packages stay in
`pyproject.toml` and `uv.lock`, external CLIs stay with their package managers,
Windows WeasyPrint native libraries are managed through MSYS2, and bundled
fonts are package resources.

For users, `papercrown doctor` is the normal preflight check for a project. In a
repository checkout, maintainers can run `task deps` to see the current path,
version, managing file/tool, status, and exact install/update command for each
dependency. Run `task deps:install` to install or synchronize the supported
development dependency set.

## Windows PDF Runtime

Paper Crown uses MSYS2 Pango/GLib for WeasyPrint on Windows. Installed users
should run `papercrown doctor` in a project to detect missing or stale native
PDF runtime libraries. In a repository checkout, the maintainer setup path is:

```powershell
task deps:install
task deps
```

The older `GTK3-Runtime Win64` package is unsupported for Paper Crown. If
`C:\Program Files\GTK3-Runtime Win64\bin` appears before MSYS2 in `PATH`, or
GLib resolves from that directory, dependency checks warn because that runtime
can trigger noisy GLib-GIO UWP app-info warnings during PDF builds.

## License

Paper Crown is free software released under the GNU Affero General Public
License v3.0 or later (`AGPL-3.0-or-later`). If you distribute modified
versions, or run a modified version as a network service, you must provide the
corresponding source under the same license. See `LICENSE` and
`THIRD_PARTY_LICENSES.md`.
