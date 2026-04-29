# Recipes

A recipe is the contract between your Markdown vaults and the generated book.
It declares the title, output location, theme, vault roots, ordered contents,
and optional art systems.

:::: {.handout #recipe-contract title="Recipe Contract" tags="docs,recipe"}
### Recipe Contract

Recipes are intentionally explicit. Paths, vault aliases, ordered contents,
themes, book-level pages, covers, and optional art systems live in YAML so
builds are repeatable.
::::

## How to Use It

Start with one vault, one theme, and one chapter. Paths are resolved relative to
the recipe file unless they are absolute.

```yaml
title: Starfall Field Guide
output_dir: output
output_name: starfall-field-guide
theme: clean-srd

vaults:
  rules: vault

contents:
  - kind: toc
  - kind: file
    title: Primer
    source: rules:Primer.md
```

Content paths are not assumed to be inside the package or repository. Vaults,
art directories, theme directories, and output directories can all point at
arbitrary filesystem locations.

Use `papercrown manifest` whenever a recipe changes. The manifest shows exactly
which files, chapters, themes, and art references Paper Crown resolved before
you spend time rendering.

## How to Adapt It

Book-level pages are ordinary content items. Put them before `kind: toc` for
front matter, or after the main chapters for back matter:

```yaml
# vault/Legal & Support.md
# Legal & Support

This book is an independent product.

# book.yaml
contents:
  - kind: file
    style: legal
    title: Legal & Support
    source: rules:Legal & Support.md
  - kind: toc
  - kind: file
    title: Primer
    source: rules:Primer.md
  - kind: generated
    type: appendix-index
    title: Game Object Index
```

Computed pages, such as `appendix-index`, are explicit `kind: generated` items
in the same `contents:` stream.

Art lives under `art_dir` and follows the [art contract](Art.md). The contract
defines canonical folders, filename shapes, automatic filler roles, and the
checks performed by `papercrown art audit`.

Images render without filters or blend modes by default. Use
`image_treatments` only when a role needs an intentional treatment such as
`ink-blend` for decorative line art.

## How It Works

Paper Crown loads the recipe into typed models, resolves each vault alias to a
real folder, then turns the chapter list into a render manifest. The manifest
is the handoff between project configuration and the assembly/render pipeline.

Automatic filler policy usually lives in project defaults in `papercrown.yaml`.
Source Markdown may opt out of a local marker, but project/book configuration
decides which marker families exist, which slots they use, and which filler
shapes are eligible for those slots.

```yaml
fillers:
  enabled: true
  art_dir: papercrown-docs
  slots:
    chapter-end:
      min_space: 0.75in
      max_space: 6.00in
      shapes: [tailpiece, spot, small-wide, plate, page-finish]
  assets:
    - id: bridge-plate
      art: fillers/plate/filler-plate-general-bridge-01.png
      shape: plate
      height: 3.25in
```

If `fillers.markers` is omitted, Paper Crown uses the default marker policy.
Set a marker family such as `terminal`, `source_boundary`, or `subclass` to
`false` to disable it, or use `headings: []` to disable generated heading
markers.

Chapters can disable generated filler markers with `fillers: false`.
Individual items inside a `sequence` can disable the source-boundary marker
after that source with `filler: false`.

Common chapter shapes:

- `file`: one Markdown source becomes one chapter.
- `sequence`: several Markdown sources are assembled in order.
- `folder`, `catalog`, and related kinds support larger structured books.

## Compact Field Reference

| Field | Purpose |
| --- | --- |
| `title`, `subtitle`, `metadata` | Book identity and PDF metadata |
| `output_dir`, `output_name`, `cache_dir` | Caller-owned output and cache locations |
| `vaults`, `vault_overlay` | Named Markdown roots and fallback search order |
| `theme_dir`, `theme`, `theme_options`, `image_treatments` | Bundled/local visual system and opt-in image role treatments |
| `cover` | Optional cover settings; cover art can be inferred from canonical Art filenames |
| `contents` | Ordered book structure using `toc`, `generated`, `file`, `sequence`, `folder`, `catalog`, `classes-catalog`, or `group` |
| `splashes`, `fillers`, `page_damage`, `ornaments` | Optional art and page-furniture systems |

For larger projects, recipes can also share structure with `extends`,
`include_contents`, and `include_vaults`.

Class catalogs can use role-based art patterns:

```yaml
class_art_pattern: classes/dividers/class-{slug}.png
class_spot_art_pattern: classes/spots/spot-class-{slug}.png
```
