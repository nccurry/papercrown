# Builds and Publishing

Builds turn a resolved recipe into caller-owned output. Paper Crown can render
PDFs for review or release, static HTML for the web, and diagnostics that help
you understand what the renderer decided.

## CLI Surface

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

:::: {.rule #cli-surface title="CLI Surface" tags="docs,cli,build"}
### CLI Surface

The CLI keeps author work in four repeatable phases: inspect with `manifest`,
preflight with `doctor`, render with `build`, and check results with `verify`.
::::

If no recipe argument is provided, Paper Crown reads `papercrown.yaml` in the
current directory and uses its `default_recipe`.

## Build Options

```sh
papercrown build book.yaml --scope book --profile print
papercrown build book.yaml --scope sections --jobs auto
papercrown build book.yaml --chapter primer
papercrown build book.yaml --target web
papercrown build book.yaml --profile draft --filler-debug-overlay
```

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

Generated files live under one caller-owned tree:

```text
<output_dir>/Paper Crown/<output_name>/
  pdf/book/
  pdf/sections/
  pdf/individuals/
  web/
  cache/
```

## How to Publish

Static web output is just files. You can upload the generated `web` directory
to any host that serves static assets. PDF output can be reviewed locally,
attached to releases, or copied into a publishing workflow after `verify`
passes.

Use `doctor` before rendering when setting up a new project or moving content
between machines:

```sh
papercrown doctor book.yaml --strict
```

Use `verify` after rendering PDFs:

```sh
papercrown verify book.yaml --scope book --profile print --strict
```

## GitHub Pages

The documentation site is built by Paper Crown and deployed by GitHub Actions.
The source lives under `docs/`; generated HTML lives under `docs/site/` and is
not committed.

Build the site locally:

```sh
task docs:build
```

Serve the generated site:

```sh
task docs:serve
```

Clean generated docs output:

```sh
task docs:clean
```

The Pages workflow runs on pushes to `main` that affect docs, source, bootstrap
scripts, or build configuration. It follows the custom GitHub Pages Actions
flow:

1. Bootstrap dependencies with `./scripts/bootstrap.sh`.
2. Build docs with `task docs:build`.
3. Upload `docs/site/Paper Crown/papercrown-docs/web`.
4. Deploy the uploaded artifact to GitHub Pages.

:::: {.handout #pages-route title="Pages Route" tags="docs,publishing"}
### Pages Route

The Pages artifact is the generated `web` directory for the docs recipe. The
workflow uploads only that static tree, not the recipe source or local caches.
::::

Configure the repository Pages source to use GitHub Actions. The expected
public URL is:

```text
https://nccurry.github.io/papercrown/
```

## Container Image

Paper Crown publishes a reusable runtime image to GitHub Container Registry:

```text
ghcr.io/nccurry/papercrown
```

The image includes the installed `papercrown` CLI, Pandoc, WeasyPrint's native
Linux libraries, and `obsidian-export`. It is designed for projects that want
to build Paper Crown output in CI without installing the toolchain in each job.

Run a project locally through the image:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace ghcr.io/nccurry/papercrown:latest papercrown build --target web
```

Use a version tag such as `ghcr.io/nccurry/papercrown:1.0.0` for repeatable CI.
The `latest` and `main` tags track the default branch; `v*` repository tags
publish matching image tags.

Minimal GitLab Pages job:

```yaml
pages:
  image: ghcr.io/nccurry/papercrown:latest
  script:
    - papercrown build --target web --force
    - mkdir -p public
    - cp -R "output/Paper Crown/my-book/web/." public/
  artifacts:
    paths:
      - public
```

Replace the `cp` source with the web output path produced by the recipe's
`output_dir` and `output_name`.
