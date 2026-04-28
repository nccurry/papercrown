# Paper Crown Docs Anthology Art Brief

This folder now contains a first generated art pass for the docs anthology.
Use this brief for future refinement or replacement passes. Keep source artwork
under `docs/assets/papercrown-docs/` and avoid text inside images so
localization, accessibility, and headings remain controlled by Markdown and CSS.

## Shared Direction

- Format: PNG or WebP for raster art; transparent PNG for ornaments and page
  wear.
- Tone: premium tabletop RPG book, not software marketing.
- Line quality: print-friendly, readable at letter-page sizes, with clean
  silhouettes.
- Palette: each chapter may have its own genre palette, but all assets should
  still feel like one anthology.
- Safety: no logos from third-party RPGs, no UI screenshots with private data,
  no embedded text except abstract glyphs or interface-like marks.

## Required Assets

| Filename | Use | Suggested Size | Direction |
| --- | --- | --- | --- |
| `covers/cover-front-genre-anthology.png` | Cover | 1650x2134 | A paper crown above four open books: fantasy codex, starship manual, occult dossier, pulp field guide |
| `dividers/divider-overview-fantasy-codex.png` | Overview divider | 1800x280 | Extra-wide illuminated manuscript table with vellum pages, brass tools, and a subtle crown motif |
| `dividers/divider-setup-launch-manual.png` | Setup divider | 1800x280 | Extra-wide starship launch console, checklist cards, and command-panel lights without readable text |
| `dividers/divider-authoring-occult-casefile.png` | Authoring divider | 1800x280 | Extra-wide recipe cards, marked strings, candles, ink, and abstract casefile talismans |
| `dividers/divider-maintaining-industrial-guide.png` | Maintaining divider | 1800x280 | Extra-wide pulp workbench with gauges, stamps, folders, and press-room tools |
| `splashes/splash-core-flow-quest-map.png` | Overview splash | 1800x540 | A route from vault to recipe to build output, expressed as a wide fantasy map |
| `splashes/splash-theme-gallery-spread.png` | Authoring splash | 1800x540 | Several genre books open on a table, each with a different layout language in a wide spread |

## Ornaments

| Filename | Use | Direction |
| --- | --- | --- |
| `ornaments/headpieces/ornament-headpiece-codex.png` | Overview headpiece | Illuminated manuscript art band |
| `ornaments/tailpieces/ornament-tailpiece-codex.png` | Overview tailpiece | Illuminated manuscript art band |
| `ornaments/headpieces/ornament-headpiece-launch.png` | Setup headpiece | Launch-bay control-panel art band |
| `ornaments/tailpieces/ornament-tailpiece-launch.png` | Setup tailpiece | Launch-bay control-panel art band |
| `ornaments/headpieces/ornament-headpiece-casefile.png` | Authoring headpiece | Occult casefile art band |
| `ornaments/tailpieces/ornament-tailpiece-casefile.png` | Authoring tailpiece | Occult casefile art band |
| `ornaments/headpieces/ornament-headpiece-field-guide.png` | Maintaining headpiece | Pulp industrial art band |
| `ornaments/tailpieces/ornament-tailpiece-field-guide.png` | Maintaining tailpiece | Pulp industrial art band |
| `ornament-folio-frame.png` | PDF folio frame | Small neutral page-number frame |
| `ornament-corner-bracket.png` | Future corner bracket | Transparent corner ornament once product support is expanded |

## Inline Spots

| Filename | Use | Direction |
| --- | --- | --- |
| `spot-cli-console.png` | CLI section | Terminal-like device in a genre-neutral style |
| `spot-recipe-scroll.png` | Recipe section | YAML page as a fantasy contract, no readable text |
| `spot-theme-mask.png` | Theme section | Theater masks or book covers representing theme changes |
| `spot-pages-airship.png` | GitHub Pages section | Delivery craft carrying a static web bundle |

## Optional PDF Showcase Assets

These should follow Paper Crown filename conventions so they can later be opted
into recipe-level systems.

| Pattern | Use |
| --- | --- |
| `filler-spot-*.png` | Small conditional filler art |
| `filler-wide-*.png` | Narrow horizontal filler art |
| `filler-bottom-*.png` | Bottom-band filler art |
| `page-wear/wear-nick-scratch-*.png` | Transparent scratch and scuff marks |
| `page-wear/wear-smudge-grime-*.png` | Transparent smudges |
| `page-wear/wear-printer-misfeed-*.png` | Transparent dragged smear bands |

## Integration Notes

The generated assets are referenced by `docs/recipes/papercrown-docs.yaml`.
After replacing or adding art, run:

```sh
uv run papercrown manifest docs/recipes/papercrown-docs.yaml
task docs:build
uv run papercrown build docs/recipes/papercrown-docs.yaml --scope book --profile digital
uv run papercrown verify docs/recipes/papercrown-docs.yaml --scope book --profile digital --strict
```
