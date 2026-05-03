# Builds and Publishing

Builds turn a resolved book config into caller-owned output. Paper Crown can
render PDFs, static HTML, diagnostics, art reports, and dependency checks.

## CLI Surface

```text
papercrown build [BOOK]
papercrown manifest [BOOK]
papercrown doctor [BOOK]
papercrown verify [BOOK]
papercrown art audit [BOOK]
papercrown art contact-sheet [BOOK]
papercrown deps check
papercrown new [PATH]
papercrown init [PATH]
papercrown themes list
papercrown themes copy NAME DEST
```

:::: {.rule #cli-surface title="CLI Surface" tags="docs,cli,build"}
### CLI Surface

The author loop is: inspect with `manifest`, preflight with `doctor`, render
with `build`, then check with `verify`.
::::

If no book argument is provided, Paper Crown uses the `book:` in
`papercrown.yaml` or falls back to `book.yml` in the current directory.

## Build Options

```sh
papercrown build book.yml --scope book --profile print
papercrown build book.yml --scope sections --jobs auto
papercrown build book.yml --chapter primer
papercrown build book.yml --target web
papercrown build book.yml --profile draft --filler-debug-overlay
```

| Option | Use |
| --- | --- |
| `--target pdf`, `web` | Choose PDF output or static HTML |
| `--scope all`, `book`, `sections`, `individuals` | Choose PDF artifacts |
| `--profile print`, `digital`, `draft` | Choose PDF output profile |
| `--chapter <slug-or-title>` | Build one section while iterating |
| `--jobs auto` | Parallelize independent PDF work, capped by Paper Crown |
| `--pagination off`, `report`, `fix` | Control pagination analysis |
| `--draft-mode fast`, `visual` | Decide whether draft builds skip or keep art |
| `--wear auto`, `off`, `fast`, `full`, `proof` | Control PDF page wear |
| `--filler-debug-overlay` | Write a sibling filler decision PDF |

Web target only supports `--scope all` and the default print profile, because
it writes one static site instead of PDF variants.

## Verification

Use `doctor` before rendering:

```sh
papercrown doctor book.yml --strict
```

Use `verify` after rendering PDFs:

```sh
papercrown verify book.yml --scope book --profile print --strict
```

For web-only validation, check local web asset references without asking for
PDFs:

```sh
papercrown verify book.yml --scope book --no-book --web-assets
```

## GitHub Pages

This documentation site is built by Paper Crown and deployed by GitHub Actions.
Source lives under `docs/`; generated HTML lives under `docs/site/` and is not
committed.

```sh
task docs:build
task docs:serve
task docs:clean
```

The Pages workflow:

1. Checks out the repository.
2. Restores package and docs caches.
3. Builds docs with `task docs:build`.
4. Uploads `docs/site/Paper Crown/papercrown-docs/web`.
5. Deploys the uploaded static tree to GitHub Pages.

:::: {.handout #pages-route title="Pages Route" tags="docs,publishing"}
### Pages Route

The Pages artifact is the generated `web` directory for `docs/book.yml`, not the
book source or cache.
::::

## Container Image

Paper Crown publishes a reusable runtime image:

```text
ghcr.io/nccurry/papercrown
```

It includes the CLI, Pandoc, WeasyPrint's Linux runtime libraries, and
`obsidian-export`.

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace ghcr.io/nccurry/papercrown:latest papercrown build --target web
```

Use a version tag for repeatable CI.
