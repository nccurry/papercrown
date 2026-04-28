# Recipes

A recipe is the contract between your Markdown vaults and the generated book.
It declares the title, output location, theme, vault roots, and chapter order.

:::: {.handout #recipe-contract title="Recipe Contract" tags="docs,recipe,authoring"}
### Recipe Contract

Recipes are intentionally explicit: paths, vault aliases, chapter order, themes,
front matter, back matter, covers, and optional art systems all live in YAML so
builds are repeatable.
::::

Minimal recipe:

```yaml
title: Starfall Field Guide
output_dir: ../output
output_name: starfall-field-guide
theme: clean-srd
image_treatments:
  ornament: ink-blend

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

Art lives under `art_dir` and follows the [art contract](Art.md). The contract
defines canonical folders, filename shapes, automatic filler roles, and the
checks performed by `papercrown art audit`.

Images render without filters or blend modes by default. Use
`image_treatments` only when a role needs an intentional treatment such as
`ink-blend` for decorative line art. See the [art contract](Art.md) for
supported roles and presets.

Automatic filler policy also lives in the recipe. Source Markdown may opt out
of a local marker, but the recipe decides which marker families exist, which
slots they use, and which filler shapes are eligible for those slots.

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
  markers:
    terminal:
      chapter_slot: chapter-end
      class_slot: class-end
    source_boundary:
      sequence_slot: section-end
    subclass:
      slot: subclass-end
    headings:
      - chapter: frames
        slot: frame-family-end
        heading_level: 1
        slot_kind: frame-family
        skip_first: true
        context: frame
```

If `fillers.markers` is omitted, Paper Crown uses the historical default marker
policy. Set a marker family such as `terminal`, `source_boundary`, or
`subclass` to `false` to disable it, or use `headings: []` to disable generated
heading markers. `fillers.art_dir` is optional; when present, filler asset
paths are resolved under `art_dir / fillers.art_dir`.

Chapters can disable generated filler markers with `fillers: false`. Individual
items inside a `sequence` can disable the source-boundary marker after that
source with `filler: false`.

Common chapter shapes:

- `file`: one Markdown source becomes one chapter.
- `sequence`: several Markdown sources are assembled in order.
- `folder`, `catalog`, and related kinds support larger structured books.

Use `papercrown manifest` to inspect exactly which files and chapters a recipe
resolves before rendering.

## Compact Field Reference

| Field | Purpose |
| --- | --- |
| `title`, `subtitle`, `metadata` | Book identity, PDF metadata, and generated matter inputs |
| `output_dir`, `output_name`, `cache_dir` | Caller-owned output and cache locations |
| `vaults`, `vault_overlay` | Named Markdown roots and fallback search order |
| `theme_dir`, `theme`, `theme_options`, `image_treatments` | Bundled/local visual system and opt-in image role treatments |
| `cover`, `front_matter`, `back_matter` | Book-level pages and generated appendix content |
| `chapters` | Ordered book structure using `file`, `sequence`, `folder`, `catalog`, `classes-catalog`, or `group` |
| `splashes`, `fillers`, `page_damage`, `ornaments` | Optional art and page-furniture systems |

For larger projects, recipes can also share structure with `extends`,
`include_chapters`, and `include_vaults`.

Class catalogs can use role-based art patterns:

```yaml
class_art_pattern: classes/dividers/class-{slug}.png
class_spot_art_pattern: classes/spots/spot-class-{slug}.png
```
