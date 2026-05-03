# Quick Start

Install the CLI from a GitHub release wheel:

```sh
uv tool install https://github.com/nccurry/papercrown/releases/download/v1.0.0/papercrown-1.0.0-py3-none-any.whl
```

Replace `1.0.0` with the release you want. If your shell cannot find
`papercrown`, run `uv tool update-shell` and open a new terminal.

<div class="art-rule art-rule-launch" aria-hidden="true"></div>

Create and build a starter book:

```sh
papercrown new my-book --book-type rules
cd my-book
papercrown manifest
papercrown doctor
papercrown build --scope book --profile draft
papercrown verify --scope book --profile draft
```

`papercrown init` is the same scaffold command as `papercrown new`.

## Core Flow

1. Write Markdown in the project vault.
2. Describe the book in `book.yml`.
3. Put repeatable build defaults in `papercrown.yaml`.
4. Run `papercrown manifest` to inspect the resolved book.
5. Run `papercrown doctor` to catch missing tools, files, and image references.
6. Run `papercrown build` for PDFs, or `papercrown build --target web` for HTML.
7. Run `papercrown verify` before publishing.

:::: {.rule #first-build-loop title="First Build Loop" tags="docs,build,quickstart"}
### First Build Loop

Use `manifest` before rendering, `doctor` before waiting on output, `build` to
write the artifact, and `verify` as the release check.
::::

:::: {.flourish-note .flourish-launch}
When no book path is passed, Paper Crown uses `papercrown.yaml` if it names a
`book:`, otherwise it looks for `book.yml` in the current directory.
::::

## Example Project

From a repository checkout, build the public sample:

```sh
papercrown manifest examples/starfall/book.yml
papercrown build examples/starfall/book.yml
papercrown build examples/starfall/book.yml --target web
```

Generated output is caller-owned:

```text
<output_dir>/Paper Crown/<output_name>/
  pdf/book/
  pdf/sections/
  pdf/individuals/
  web/
  cache/
```

By default, `output_dir` is the project root and `output_name` is the slugged
book title. Set them when source files, generated files, and publishing folders
need to stay separate.
