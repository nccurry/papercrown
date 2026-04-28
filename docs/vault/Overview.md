# Overview

Paper Crown builds polished tabletop RPG PDFs and static web exports from
Markdown content that can live anywhere on disk. A recipe names one or more
content vaults, chooses a bundled or local theme, and declares the chapters to
assemble.

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
