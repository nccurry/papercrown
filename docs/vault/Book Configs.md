# Book Configs

`book.yml` is the book contract. It names the book, selects content, chooses a
theme, declares art, and decides where generated files are written.

:::: {.handout #book-config-contract title="Book Config Contract" tags="docs,book-config"}
### Book Config Contract

Keep authoring shape in `book.yml`; keep repeatable command defaults in
`papercrown.yaml`.
::::

## How to Use It

Minimal books only need a title and contents:

```yaml
title: Starfall Field Guide
subtitle: A public sample for Paper Crown
theme: industrial

contents:
  - kind: toc
  - title: Primer
    source: vault/Primer.md
```

With no `vaults:` mapping, the book file's directory is treated as one vault.
`output_dir` defaults to the book directory, `output_name` defaults to the
slugged top-level `title`, `art.library` defaults to `Art/`, and a local
`themes/<theme>/` directory wins over bundled themes.

Use `papercrown manifest` after changing a book config. It is the fastest way
to confirm source files, chapter slugs, output paths, art references, and theme
resolution.

## Project Defaults

Put build defaults in `papercrown.yaml`:

```yaml
book: book.yml

build:
  target: pdf
  scope: book
  profile: print
  jobs: auto
  pagination: report
  wear: auto
```

CLI options override project defaults for one run. Book-local `build:` blocks
are no longer supported.

## Contents

Content items are ordered. Most books use `toc`, `file`, `sequence`, `group`,
and `generated`:

```yaml
contents:
  - kind: generated
    type: title-page
    title: Title Page
  - kind: toc
    depth: 3
  - kind: file
    title: Primer
    source: rules:Primer.md
  - kind: sequence
    title: Playing the Game
    sources:
      - rules:Core Rules.md
      - source: rules:Examples.md
        title: Examples
        filler: false
```

Other supported shapes are `folder`, `catalog`, `composite`,
`classes-catalog`, and nested `group` entries. Use them when they match the
book structure; otherwise a small list of `file` and `sequence` entries is
easier to maintain.

## Art

Most explicit in-flow art belongs in Markdown:

Use normal Markdown image syntax, with optional Pandoc classes such as
`{.wide}` when the theme provides a matching treatment.

Use book-config placements when Paper Crown should inject the art:

```yaml
art:
  placements:
    - id: character-creation-opening
      image: splashes/splash-section-general-boarding-queue-01.png
      target: after-heading
      chapter: character-creation
      heading: Why are you out here?
      placement: bottom-half
```

Use `art.treatments` only when a whole role needs an intentional visual
treatment, such as `ink-blend` for reusable line ornaments.

## Compact Field Reference

| Field | Purpose |
| --- | --- |
| `title`, `subtitle`, `cover_eyebrow`, `cover_footer` | Book identity and cover text |
| `metadata` | Authors, version, license, description, keywords, and credits |
| `contents` | Ordered book structure and generated pages |
| `vaults`, `vault_overlay` | Named Markdown roots and fallback search order |
| `theme`, `theme_dir`, `theme_options` | Bundled or local theme selection and CSS variables |
| `art` | Library, cover, placements, fillers, wear, ornaments, and treatments |
| `output_dir`, `output_name`, `cache_dir` | Generated output and cache locations |
| `extends`, `include_contents`, `include_vaults` | Shared recipe fragments for larger projects |

## Includes

Use includes when several books share vault declarations or front/back matter:

```yaml
extends: shared/base-book.yml
include_vaults: shared/vaults.yml
include_contents:
  - shared/legal.yml
  - shared/license.yml
```

Local fields override inherited fields. Included contents are prepended to the
local `contents:` list.
