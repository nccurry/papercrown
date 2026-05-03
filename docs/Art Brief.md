# Paper Crown Docs Art Brief

Internal planning brief for a later art pass. This file is not included in
`docs/book.yml`, so it is not served by GitHub Pages.

## Direction

The docs book is a readable genre anthology. Each chapter keeps practical
documentation first, while the art gives that section a distinct TTRPG mood.

| Chapter | Style | Art Direction |
| --- | --- | --- |
| Overview | Fantasy | Crowned field guide, illuminated map margins, warm parchment |
| Quick Start | Space opera | Launch checklist, cockpit panels, clean bright technical shapes |
| Architecture | Comic book | Bold panels, flow arrows, readable system diagram energy |
| Book Configs | Occult casefile | Contract parchment, ritual indexing, file tabs, restrained mystery |
| Vaults and Markdown | Hexcrawl | Map grid, trails, folders as terrain markers |
| Themes | Zine lab | Cut paper, swatches, paste-up tools, colorful but legible |
| Art | Bestiary gallery | Catalog plates, specimen labels, curated asset shelves |
| Builds and Publishing | Steampunk | Pressworks, gears, brass routes, deployment machinery |
| Developer Guide | Cyberpunk | Console overlays, repo routes, terminal panels, cool neon accents |

## Generation Constraints

- Match Paper Crown role conventions and target folders.
- Prefer crisp subject matter over atmospheric blur.
- Keep important faces, symbols, and text inside safe zones.
- Avoid readable UI/code text unless the asset is explicitly a screenshot.
- Transparent assets must have useful alpha and no baked rectangular paper.
- Chapter title plates should be 1800x1200, crop safely to a 3:2 frame, and
  leave quiet edges for the printed title-page border.
- Web and print splashes must crop well in a wide horizontal frame.

## Missing Or Candidate Assets

| Asset | Role | Target Path | Needed For | Brief | Status |
| --- | --- | --- | --- | --- | --- |
| `map-station.png` | `map` | `papercrown-docs/content/maps/map-station.png` | Example inline map art | Small readable sci-fi station map, black ink plus two accent colors, no tiny labels | Missing |
| `power-header-void-engine.png` | custom art label | `papercrown-docs/content/diagrams/power-header-void-engine.png` | Example fixed art-label image | Wide void-engine header, clean technical frame, high contrast, usable above a rules block | Missing |
| `filler-plate-general-01.png` | `filler-plate` | `papercrown-docs/fillers/plate/filler-plate-general-01.png` | Medium automatic filler | Genre-neutral docs plate with crown, dice, folder, and page icons, transparent background | Missing |
| `filler-bottom-general-01.png` | `filler-bottom` | `papercrown-docs/fillers/bottom/filler-bottom-general-01.png` | Bottom-band automatic filler | Low visual-weight press mark along bottom edge, transparent top fade | Missing |
| `page-finish-general-01.png` | `page-finish` | `papercrown-docs/fillers/page-finish/page-finish-general-01.png` | Large ending filler | Large in-flow closing illustration for blank page endings, no bottom bleed | Missing |

## Existing Asset Inventory

| Asset | Role | Size | Keep / Review | Notes |
| --- | --- | --- | --- | --- |
| `logos/logo-papercrown-readme.svg` | `logo` | SVG | Keep | README brand asset; not part of docs book art library. |
| `papercrown-docs/contact-sheet-docs-art.png` | excluded | 1180x3290 | Keep | Generated visual inventory; do not serve as book art. |
| `papercrown-docs/covers/cover-front-genre-anthology.png` | `cover-front` | 1650x2134 | Review | Strong anthology signal; audit reports crowded safe zone, so replace if cover text feels cramped. |
| `papercrown-docs/classes/dividers/class-overview-title-plate.jpg` | `class-divider` | 1800x1200 | Keep | New fantasy title-page plate; generated for the book-shaped divider layout. |
| `papercrown-docs/classes/dividers/class-quick-start-title-plate.jpg` | `class-divider` | 1800x1200 | Keep | New space-opera launch title-page plate. |
| `papercrown-docs/classes/dividers/class-architecture-title-plate.jpg` | `class-divider` | 1800x1200 | Keep | New comic-book architecture title-page plate. |
| `papercrown-docs/classes/dividers/class-book-configs-title-plate.jpg` | `class-divider` | 1800x1200 | Keep | New occult casefile title-page plate. |
| `papercrown-docs/classes/dividers/class-vaults-markdown-title-plate.jpg` | `class-divider` | 1800x1200 | Keep | New hexcrawl field-guide title-page plate. |
| `papercrown-docs/classes/dividers/class-themes-title-plate.jpg` | `class-divider` | 1800x1200 | Keep | New zine-lab title-page plate. |
| `papercrown-docs/classes/dividers/class-art-title-plate.jpg` | `class-divider` | 1800x1200 | Keep | New bestiary-gallery title-page plate. |
| `papercrown-docs/classes/dividers/class-builds-publishing-title-plate.jpg` | `class-divider` | 1800x1200 | Keep | New steampunk pressworks title-page plate. |
| `papercrown-docs/classes/dividers/class-developer-guide-title-plate.jpg` | `class-divider` | 1800x1200 | Keep | New cyberpunk developer title-page plate. |
| `papercrown-docs/dividers/divider-overview-docs-crown.png` | `chapter-divider` | 1800x280 | Superseded | Old thin banner kept as source direction; no longer used by the book. |
| `papercrown-docs/dividers/divider-quick-start-launch-checklist.png` | `chapter-divider` | 1800x280 | Superseded | Old thin banner kept as source direction; no longer used by the book. |
| `papercrown-docs/dividers/divider-overview-fantasy-codex.png` | `chapter-divider` | 1800x280 | Superseded | Old thin banner kept as source direction; no longer used by the book. |
| `papercrown-docs/dividers/divider-authoring-occult-casefile.png` | `chapter-divider` | 1800x280 | Superseded | Old thin banner kept as source direction; no longer used by the book. |
| `papercrown-docs/dividers/divider-vaults-markdown-archive.png` | `chapter-divider` | 1800x280 | Superseded | Old thin banner kept as source direction; no longer used by the book. |
| `papercrown-docs/dividers/divider-themes-gallery-spread.png` | `chapter-divider` | 1800x280 | Superseded | Old thin banner kept as source direction; no longer used by the book. |
| `papercrown-docs/dividers/divider-maintaining-industrial-guide.png` | `chapter-divider` | 1800x280 | Superseded | Old thin banner kept as source direction; no longer used by the book. |
| `papercrown-docs/dividers/divider-setup-launch-manual.png` | `chapter-divider` | 1800x280 | Superseded | Old thin banner kept as source direction; no longer used by the book. |
| `papercrown-docs/splashes/splash-core-flow-launch-sequence.png` | `splash` | 1800x540 | Review | Good Quick Start subject; audit reports safe-zone crowding. |
| `papercrown-docs/splashes/splash-product-model-codex-route.png` | `splash` | 1800x540 | Review | Good system route idea; replace if comic-book architecture needs stronger panel language. |
| `papercrown-docs/splashes/splash-compact-reference-casefile-ritual.png` | `splash` | 1800x540 | Review | Good occult casefile subject; audit reports safe-zone crowding. |
| `papercrown-docs/splashes/splash-theme-gallery-spread.png` | `splash` | 1800x540 | Keep | Strong theme-gallery sample. |
| `papercrown-docs/splashes/splash-pages-field-guide-press.png` | `splash` | 1800x540 | Review | Good publishing subject; audit reports safe-zone crowding. |
| `papercrown-docs/splashes/splash-repository-bootstrap-launch-panel.png` | `splash` | 1800x540 | Review | Good developer workflow subject; may need cyberpunk-specific replacement. |
| `papercrown-docs/splashes/splash-core-flow-quest-map.png` | `splash` | 1800x540 | Review | Currently unused; candidate for Overview or Vaults if crop and safe zone are improved. |
| `papercrown-docs/fillers/spot/filler-spot-codex-crown-01.png` | `filler-spot` | 720x720 | Keep | Useful general docs/crown spot. |
| `papercrown-docs/fillers/spot/filler-spot-launch-console-01.png` | `filler-spot` | 720x720 | Keep | Space-opera/cyberpunk console spot. |
| `papercrown-docs/fillers/spot/filler-spot-casefile-orbit-01.png` | `filler-spot` | 720x720 | Keep | Casefile/orbit transitional spot. |
| `papercrown-docs/fillers/spot/filler-spot-field-guide-tag-01.png` | `filler-spot` | 720x720 | Keep | Field-guide/bestiary label spot. |
| `papercrown-docs/fillers/wide/filler-wide-codex-route-01.png` | `filler-wide` | 1400x420 | Keep | Route diagram filler, good for architecture. |
| `papercrown-docs/fillers/wide/filler-wide-launch-panel-01.png` | `filler-wide` | 1400x420 | Keep | Launch panel filler, good for quick start. |
| `papercrown-docs/fillers/wide/filler-wide-casefile-ritual-01.png` | `filler-wide` | 1400x420 | Keep | Occult/casefile filler. |
| `papercrown-docs/ornaments/headpieces/ornament-headpiece-launch.png` | `ornament-headpiece` | 1600x260 | Keep | Space-opera headpiece. |
| `papercrown-docs/ornaments/headpieces/ornament-headpiece-field-guide.png` | `ornament-headpiece` | 1600x260 | Keep | Field-guide/bestiary headpiece. |
| `papercrown-docs/ornaments/headpieces/ornament-headpiece-codex.png` | `ornament-headpiece` | 1600x260 | Keep | Fantasy/comic/codex fallback. |
| `papercrown-docs/ornaments/headpieces/ornament-headpiece-casefile.png` | `ornament-headpiece` | 1600x260 | Keep | Occult casefile headpiece. |
| `papercrown-docs/ornaments/tailpieces/ornament-tailpiece-launch.png` | `ornament-tailpiece` | 1600x260 | Keep | Space-opera closer. |
| `papercrown-docs/ornaments/tailpieces/ornament-tailpiece-field-guide.png` | `ornament-tailpiece` | 1600x260 | Keep | Field-guide/bestiary closer. |
| `papercrown-docs/ornaments/tailpieces/ornament-tailpiece-codex.png` | `ornament-tailpiece` | 1600x260 | Keep | Fantasy/comic/codex closer. |
| `papercrown-docs/ornaments/tailpieces/ornament-tailpiece-casefile.png` | `ornament-tailpiece` | 1600x260 | Keep | Occult casefile closer. |
| `papercrown-docs/page-wear/wear-nick-scratch-tiny-01.png` | `page-wear` | 720x220 | Keep | Transparent scratch texture. |
| `papercrown-docs/page-wear/wear-nick-scratch-small-01.png` | `page-wear` | 920x180 | Keep | Transparent scratch texture. |
| `papercrown-docs/page-wear/wear-nick-scratch-medium-01.png` | `page-wear` | 260x760 | Keep | Transparent scratch texture. |
| `papercrown-docs/page-wear/wear-printer-misfeed-medium-01.png` | `page-wear` | 980x300 | Keep | Transparent printer-misfeed texture. |
| `papercrown-docs/page-wear/wear-smudge-grime-small-01.png` | `page-wear` | 680x260 | Keep | Transparent grime texture. |
| `papercrown-docs/page-wear/wear-smudge-grime-medium-01.png` | `page-wear` | 760x260 | Keep | Transparent grime texture. |

## Acceptance Checklist For Future Art Pass

- `papercrown art audit docs/book.yml --format markdown` reports no missing
  references and no unexpected unclassified assets.
- New filler art appears in the suggested roles and is picked up by auto
  discovery or explicit `art.fillers.assets`.
- `papercrown doctor docs/book.yml --target web` has no `content.image-missing`
  errors.
- `task docs:build` produces readable desktop and mobile layouts with no text
  overlap on dividers, splashes, cover, TOC, or callouts.
