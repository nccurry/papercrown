# Book Configs

A book config is the contract between your Markdown vaults and the generated book.
It declares the theme, ordered contents, and only the overrides that differ
from Paper Crown's book defaults.

:::: {.handout #book-config-contract title="Book Config Contract" tags="docs,book-config"}
### Book Config Contract

Book configs are convention-first. The common book shape is inferred from the
contents stream, local `themes/`, local `Art/`, and the project root unless
the config says otherwise.
::::

## How to Use It

Start with top-level title fields, a theme, and ordered content. Paths are resolved
relative to the book file unless they are absolute.

```yaml
title: Starfall Field Guide
subtitle: A public sample for Paper Crown
theme: industrial

contents:
  - kind: toc
  - title: Primer
    source: vault/Primer.md
```

With no `vaults:` mapping, Paper Crown treats the book file's directory as a single
content vault. `output_dir` defaults to the book file's directory, `output_name` is
derived from the top-level title text, `art_dir` defaults to `Art/`, and a
matching local `themes/<theme>/` wins over bundled themes. The subtitle is not
included in the default output folder name; set `output_name` only when you
need a release-specific name or two books would otherwise collide.

Use `papercrown manifest` whenever a book config changes. The manifest shows exactly
which files, chapters, themes, and art references Paper Crown resolved before
you spend time rendering.

## How to Adapt It

Book-level pages are ordinary content items. Put them before `kind: toc` for
front matter, or after the main chapters for back matter:

```yaml
# vault/Legal & Support.md
# Legal & Support

This book is an independent product.

# book.yml
contents:
  - style: legal
    title: Legal & Support
    source: rules:Legal & Support.md
  - kind: toc
  - title: Primer
    source: rules:Primer.md
  - kind: generated
    type: appendix-index
    title: Game Object Index
```

Computed pages, such as `appendix-index`, are explicit `kind: generated` items
in the same `contents:` stream.

Art lives under `Art/` by default and follows the [art contract](Art.md). Most
books use three art APIs:

- Markdown images for ordinary inline art: `![](map-station.png)`.
- Markdown `.art-slot` blocks for explicit layout intent near the content.
- Scoped YAML `art:` inserts only when source Markdown should stay untouched.

The art contract defines canonical folders, filename shapes, automatic filler
roles, and the checks performed by `papercrown art audit`.

Most explicit in-flow art belongs in Markdown next to the content it supports:

```markdown
:::: {.art-slot role="splash" context="boarding" placement="bottom-half"}
::::
```

Use scoped YAML `art:` inserts only when the source Markdown should stay
untouched:

```yaml
contents:
  - title: Character Creation
    source: Heroes/Character Creation.md
    art:
      - after_heading: Why are you out here?
        art: splash-section-general-boarding-queue-bottom-01.png
        placement: bottom-half
```

Images render without filters or blend modes by default. Use
`image_treatments` only when a role needs an intentional treatment such as
`ink-blend` for decorative line art.

## How It Works

Paper Crown loads the book config into typed models, resolves each vault alias to a
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

:::: {.art-slot role="splash" placement="bottom-half" art="papercrown-docs/splashes/splash-compact-reference-casefile-ritual.png"}
::::

| Field | Purpose |
| --- | --- |
| `contents` inline title item | Book identity, cover title text, and default output name |
| `theme`, `theme_options`, `image_treatments` | Visual system and opt-in image role treatments |
| `art_roles` | Book-specific art filename roles, nominal sizes, transparency checks, and role CSS |
| `vaults`, `vault_overlay` | Optional named Markdown roots and fallback search order |
| `output_dir`, `output_name`, `cache_dir` | Optional caller-owned output and cache overrides |
| `cover` | Optional cover settings; cover art can be inferred from canonical Art filenames |
| `contents` | Ordered book structure using `inline`, `toc`, `generated`, `file`, `sequence`, `folder`, `catalog`, `classes-catalog`, or `group` |
| `fillers`, `page_damage`, `ornaments` | Optional art and page-furniture systems |

For larger projects, book configs can also share structure with `extends`,
`include_contents`, and `include_vaults`.

Class catalogs can use role-based art patterns:

```yaml
class_art_pattern: classes/dividers/class-{slug}.png
class_spot_art_pattern: classes/spots/spot-class-{slug}.png
```
