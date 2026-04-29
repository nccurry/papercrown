# Quick Start

Install the CLI once:

```sh
uv tool install https://github.com/nccurry/papercrown/releases/download/v1.0.0/papercrown-1.0.0-py3-none-any.whl
```

Replace `1.0.0` with the release version you want. Paper Crown release
artifacts live on GitHub Releases, not PyPI. If your shell cannot find
`papercrown` after installation, run `uv tool update-shell` and open a new
terminal.

<div class="art-rule art-rule-launch" aria-hidden="true"></div>

Create a new Paper Crown project:

```sh
papercrown init my-book
cd my-book
papercrown manifest
papercrown doctor
papercrown build
papercrown verify
```

## Core Flow

1. Write Markdown in a vault.
2. Describe the book in a recipe YAML file.
3. Run `papercrown manifest` to inspect the resolved book.
4. Run `papercrown doctor` to catch missing tools, paths, and content issues.
5. Run `papercrown build` for PDFs, or add `--target web` for static HTML.
6. Run `papercrown verify` before publishing PDFs.

:::: {.rule #first-build-loop title="First Build Loop" tags="docs,build,quickstart"}
### First Build Loop

Use `manifest` to inspect what Paper Crown will build, `doctor` to validate the
machine and content, `build` to render outputs, and `verify` to check PDFs
after rendering.
::::

:::: {.flourish-note .flourish-launch}
Paper Crown reads `papercrown.yaml` in the current directory when no recipe path
is provided. That project file usually points to the default recipe.
::::

## Example Project

You can also run the bundled public example from a repository checkout:

```sh
papercrown manifest examples/starfall/recipes/starfall-field-guide.yaml
papercrown build examples/starfall/recipes/starfall-field-guide.yaml
```

For a static web export, use:

```sh
papercrown build examples/starfall/recipes/starfall-field-guide.yaml --target web
```

Generated output is always caller-owned and goes under:

```text
<output_dir>/Paper Crown/<output_name>/
  pdf/
  web/
  cache/
```

`output_dir` and `output_name` are recipe fields. They may point outside the
project folder when you want source, generated files, and publishing artifacts
to stay separate.
