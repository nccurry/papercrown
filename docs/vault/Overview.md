# Overview

Paper Crown builds polished tabletop RPG PDFs and static web exports from
Markdown content that can live anywhere on disk. A recipe names one or more
content vaults, chooses a bundled or local theme, and declares the chapters to
assemble.

This documentation is also a Paper Crown book. Its public web site is rendered
from the same recipe system that can produce print-ready PDFs, section PDFs,
individual chapter PDFs, and static HTML.

The project has two audiences:

- Authors install Paper Crown with
  `uv tool install https://github.com/nccurry/papercrown/releases/download/v1.0.0/papercrown-1.0.0-py3-none-any.whl`,
  then use the `papercrown` command to initialize projects, check recipes, and
  build books. Release artifacts live on GitHub Releases, not PyPI.
- Maintainers use `task` for every repository workflow, including bootstrap,
  dependency installation, tests, packaging, docs, and releases.

The same renderer powers PDFs and this documentation site. The GitHub Pages
site is built with `papercrown build --target web`, which keeps the public docs
close to the product behavior.

## Feature Showcase

:::: {.rule #recipe-driven-books title="Recipe-driven Books" tags="docs,recipe,feature"}
### Recipe-driven Books

A recipe is the source of truth for title metadata, output paths, vault roots,
theme selection, cover behavior, chapter order, generated matter, and optional
art systems.
::::

:::: {.sidebar #multi-format-rendering title="Multi-format Rendering" tags="docs,build,feature"}
### Multi-format Rendering

Paper Crown can render one assembled book to PDF outputs or a static web export.
The web docs use the same Markdown assembly, theme, filters, and typed TTRPG
block pass as the PDF path.
::::

:::: {.handout #book-furniture title="Book Furniture" tags="docs,theme,feature"}
### Book Furniture

Themes can style covers, table of contents pages, section dividers, running
headers, stat blocks, callouts, art frames, quick references, and generated
appendix matter.
::::

The rest of this guide returns to these features through
@rule.recipe-driven-books, @sidebar.multi-format-rendering, and
@handout.book-furniture.

## Product Model

| Layer | What you own | What Paper Crown does |
| --- | --- | --- |
| Vault | Markdown notes, images, and Obsidian-style links | Resolves source files and embeds |
| Recipe | Book structure, metadata, themes, and outputs | Builds a render manifest |
| Theme | CSS, template, page furniture, and visual identity | Applies consistent print and web layout |
| Build | CLI options for target, scope, profile, and speed | Emits PDFs, HTML, caches, and reports |

## Core Flow

1. Install once with
   `uv tool install https://github.com/nccurry/papercrown/releases/download/v1.0.0/papercrown-1.0.0-py3-none-any.whl`.
2. Write Markdown in a vault.
3. Describe output in a recipe YAML file.
4. Run `papercrown manifest` to inspect the resolved book.
5. Run `papercrown doctor` to catch missing tools, paths, and content issues.
6. Run `papercrown build` for PDFs or `papercrown build --target web` for a
   static HTML export.

Generated output is always caller-owned and goes under:

```text
<output_dir>/Paper Crown/<output_name>/
  pdf/
  web/
  cache/
```

## Reading Path

Start with Quick Start if you want a working command quickly. Use Setup for
installation and repository bootstrap details. Jump to Authoring when you are
ready to shape a book. Use Maintaining Paper Crown when you are working from
the repository or publishing the docs site.
