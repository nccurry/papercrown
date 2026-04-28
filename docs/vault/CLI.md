# CLI

The installed `papercrown` command is the supported product interface. Install
it once with uv:

```sh
uv tool install papercrown
```

```text
papercrown build [RECIPE]
papercrown manifest [RECIPE]
papercrown art audit [RECIPE]
papercrown art contact-sheet [RECIPE]
papercrown doctor [RECIPE]
papercrown verify [RECIPE]
papercrown deps check
papercrown init [PATH]
papercrown themes list
papercrown themes copy NAME DEST
```

:::: {.rule #cli-surface title="CLI Surface" tags="docs,cli,reference"}
### CLI Surface

The CLI keeps author work in four repeatable phases: inspect with `manifest`,
preflight with `doctor`, render with `build`, and check results with `verify`.
::::

Common build options:

```sh
papercrown build book.yaml --scope book --profile print
papercrown build book.yaml --scope sections --jobs auto
papercrown build book.yaml --chapter primer
papercrown build book.yaml --target web
papercrown build book.yaml --profile draft --filler-debug-overlay
```

Use `doctor` before rendering when setting up a new project or moving content
between machines:

```sh
papercrown doctor book.yaml --strict
```

Use `art audit` after adding or reorganizing art. It checks the
[art contract](Art.md), recipe references, dimensions, and automatic filler
coverage:

```sh
papercrown art audit book.yaml --strict
papercrown art audit book.yaml --format markdown
```

Use `art contact-sheet` when reviewing a whole library visually. It writes a
grouped HTML inventory with thumbnails, dimensions, roles, and per-asset
warnings:

```sh
papercrown art contact-sheet book.yaml --output art-contact-sheet.html
```

Use `verify` after rendering PDFs:

```sh
papercrown verify book.yaml --scope book --profile print --strict
```

## Build Option Map

| Option | Use |
| --- | --- |
| `--target pdf` or `--target web` | Choose PDF output or static HTML |
| `--scope book`, `sections`, or `all` | Choose which PDF artifacts to emit |
| `--profile print`, `digital`, or `draft` | Tune render quality and image handling |
| `--chapter <slug-or-title>` | Build one section while iterating |
| `--jobs auto` | Parallelize independent PDF work |
| `--draft-mode fast` or `visual` | Decide whether draft builds skip or keep art |
| `--page-damage auto`, `off`, `fast`, `full`, or `proof` | Control PDF page-wear overlays |
| `--filler-debug-overlay` | Write a sibling `*.filler-debug.pdf` with measured filler slots and placement decisions |
