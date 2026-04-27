# Recipes

A recipe is the contract between your Markdown vaults and the generated book.
It declares the title, output location, theme, vault roots, and chapter order.

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

Paths are resolved relative to the recipe file. Vaults, art directories, theme
directories, and output directories do not need to live inside the package or
repository.

## Legal front matter

Use `metadata.license` with generated `front_matter` when a book needs a
visible license, attribution, compatibility, or support notice near the
beginning of the PDF and static web export:

```yaml
metadata:
  license: |
    This book is an independent product.

    It is not official or endorsed by the original publisher.

front_matter:
  - type: license
    title: Legal & Support
```

Generated front matter appears before the table of contents in combined book
outputs. Generated back matter still appears after the assembled chapters.

Common chapter shapes:

- `file`: one Markdown source becomes one chapter.
- `sequence`: several Markdown sources are assembled in order.
- `folder`, `catalog`, and related kinds support larger structured books.

Use `papercrown manifest` to inspect exactly which files and chapters a recipe
resolves before rendering.
