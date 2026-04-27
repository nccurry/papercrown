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

Art lives under `art_dir` and follows the [art contract](Art.md). The contract
defines canonical folders, filename shapes, automatic filler roles, and the
checks performed by `papercrown art audit`.

Common chapter shapes:

- `file`: one Markdown source becomes one chapter.
- `sequence`: several Markdown sources are assembled in order.
- `folder`, `catalog`, and related kinds support larger structured books.

Use `papercrown manifest` to inspect exactly which files and chapters a recipe
resolves before rendering.

Class catalogs can use role-based art patterns:

```yaml
class_art_pattern: classes/dividers/class-{slug}.png
class_spot_art_pattern: classes/spots/spot-class-{slug}.png
```
