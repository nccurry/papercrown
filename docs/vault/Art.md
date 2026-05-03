# Art

Paper Crown treats `art.library` as the book's art library. It classifies image
files by role, validates references, and only auto-places roles that are safe
for automatic layout.

:::: {.sidebar #art-library title="Art Library Contract" tags="docs,art"}
### Art Library Contract

Use role-shaped filenames under the art library. Opaque images are best for
covers, splashes, maps, and screenshots; transparent PNGs are best for
ornaments, spots, fillers, and page wear.
::::

## How to Use It

Use the lightest API that matches the intent:

- Markdown images for art that belongs exactly where it appears.
- `contents[].art` for dividers, ornaments, child catalog art, and local filler
  opt-outs.
- Top-level `art.placements` for Paper Crown-managed cover, back-cover,
  chapter-start, and after-heading splash art.
- `art.fillers` and `art.wear` for automatic page finish and paper-wear systems.

Run these when adding or moving art:

```sh
papercrown art audit book.yml
papercrown art audit book.yml --format markdown --strict
papercrown art contact-sheet book.yml --output art-contact-sheet.html
```

## Roles

Common canonical folders:

| Role | Folder | Use |
| --- | --- | --- |
| `cover-front`, `cover-back` | `covers/` | Full cover plates |
| `chapter-divider`, `chapter-header` | `dividers/`, `headers/` | Chapter identity art |
| `splash` | `splashes/` | Large injected section art |
| `ornament-headpiece`, `ornament-tailpiece`, `ornament-break` | `ornaments/` | Reusable page furniture |
| `filler-spot`, `filler-wide`, `filler-plate`, `filler-bottom`, `page-finish` | `fillers/` | Automatic blank-space art |
| `page-wear` | `page-wear/` | Transparent paper damage overlays |
| `map`, `diagram`, `screenshot`, `icon`, `logo` | Content or asset folders | Explicit reference art |

`unused/`, contact sheets, and non-image files are ignored by automatic
discovery.

## Fillers

Filler slots describe blank-space opportunities. Assets can be listed
explicitly or discovered from canonical filler folders.

```yaml
art:
  fillers:
    enabled: true
    slots:
      chapter-end:
        min_space: 0.75in
        max_space: 6.00in
        shapes: [tailpiece, spot, small-wide, plate, page-finish]
```

Use larger roles for larger gaps: `spot` under roughly `2in`, `small-wide` for
short horizontal gaps, `plate` for medium page space, and `page-finish` for
large in-flow endings. `bottom-band` is for true bottom-anchored strip art and
should not be mixed into ordinary in-flow slots.

## Wear and Treatments

Page-wear assets use filenames like `wear-smudge-grime-small-01.png` and must
have alpha. Configure density, opacity, seed, and skip targets under
`art.wear`.

Image pixels render raw by default. Use `art.treatments` only for role-wide
effects:

```yaml
art:
  treatments:
    ornament: ink-blend
    filler: raw
    cover: raw
```

Supported presets include `raw`, `ink-blend`, `print-punch`, `subtle-punch`,
`strong-punch`, and `soft-print`.

## This Docs Book

The full art inventory and future generation prompts live in
`docs/Art Brief.md`. It is intentionally not part of the served book.
