# Art

Paper Crown treats `art_dir` as a named art library. The book owns the files;
Paper Crown classifies them by role, validates the names, and only auto-places
art from roles that are explicitly safe for automatic layout.

Art is book-config-driven for the same reason chapters are: finished books need
repeatable references, predictable naming, and checks that catch missing or
mis-sized assets before a release build.

:::: {.sidebar #art-library title="Art Library Contract" tags="docs,art"}
### Art Library Contract

Keep art under the book config's `art_dir`, use role-shaped filenames, and reserve
transparent PNGs for assets that should float on paper instead of carrying
their own rectangular background. Art can either live in the canonical role
folders below or directly in `art_dir` when filenames are globally unique.
::::

## How to Use It

Put finished images under `Art/` and use the lightest API that expresses your
intent:

- Use ordinary Markdown images for inline art that belongs exactly where it
  appears: `![](map-station.png)`.
- Use Markdown `.art-slot` blocks for explicit art placement near the content
  it supports.
- Use scoped book config `art:` inserts only when the Markdown source should remain
  untouched.

Set `art_dir` only when the art library lives somewhere other than `Art/`. Use
`papercrown art audit book.yml` when adding or moving art.

```markdown
:::: {.art-slot role="splash" placement="bottom-half" art="splash-dock-queue.png"}
::::
```

```yaml
contents:
  - title: Character Creation
    source: Heroes/Character Creation.md
    art:
      - after_heading: Why are you out here?
        art: splash-dock-queue.png
        placement: bottom-half
```

## How to Adapt It

Use opaque images for covers, splashes, dividers, screenshots, maps, and
diagrams that need to carry their own rectangular composition. Use transparent
PNGs for ornaments, spots, page wear, and decorative fillers that should sit on
the paper surface.

## How It Works

The art audit classifies filenames, checks image metadata, verifies book config
references, and reports assets that do not match the role contract. Automatic
filler placement only considers roles that are safe to place without explicit
source Markdown references.

## Canonical Roles

| Role | Folder | Filename shape | Automatic |
| --- | --- | --- | --- |
| `cover-front` | `covers/` | `cover-front-{slug}.png` | No |
| `cover-back` | `covers/` | `cover-back-{slug}.png` | No |
| `chapter-divider` | `dividers/` | `divider-{slug}.png` | No |
| `chapter-header` | `headers/` | `header-{slug}.png` | No |
| `class-divider` | `classes/dividers/` | `class-{slug}.png` | No |
| `class-opening-spot` | `classes/spots/` | `spot-class-{slug}.png` | No |
| `frame-divider` | `frames/dividers/` | `frame-{slug}.png` | No |
| `splash` | `splashes/` | `splash-{context}-{subject}-{variant}.png` | No |
| `spread` | `spreads/` | `spread-{slug}.png` | No |
| `ornament-headpiece` | `ornaments/headpieces/` | `ornament-headpiece-{slug}.png` | No |
| `ornament-break` | `ornaments/breaks/` | `ornament-break-{slug}.png` | No |
| `ornament-tailpiece` | `ornaments/tailpieces/` | `ornament-tailpiece-{slug}.png` | No |
| `ornament-corner` | `ornaments/corners/` | `ornament-corner-{slug}.png` | No |
| `ornament-folio` | `ornaments/folios/` | `ornament-folio-{slug}.png` | No |
| `filler-spot` | `fillers/spot/` | `filler-spot-{context}-{subject}-{variant}.png` | Yes |
| `filler-wide` | `fillers/wide/` | `filler-wide-{context}-{subject}-{variant}.png` | Yes |
| `filler-plate` | `fillers/plate/` | `filler-plate-{context}-{subject}-{variant}.png` | Yes |
| `filler-bottom` | `fillers/bottom/` | `filler-bottom-{context}-{subject}-{variant}.png` | Yes |
| `page-finish` | `fillers/page-finish/` | `page-finish-{context}-{subject}-{variant}.png` | Yes |
| `page-wear` | `page-wear/` | `wear-{family}-{size}-{variant}.png` | Yes |
| `faction` | `content/factions/` | `faction-{slug}.png` | No |
| `gear` | `content/gear/` | `gear-{slug}.png` | No |
| `vista` | `content/vistas/` | `vista-{slug}.png` | No |
| `spot` | `content/spots/` or `content/background-spots/` | `spot-{slug}.png`, `bg-{slug}.png` | No |
| `portrait` | `content/portraits/` | `portrait-{slug}.png` | No |
| `map` | `content/maps/` | `map-{slug}.png` | No |
| `diagram` | `content/diagrams/` | `diagram-{slug}.png` | No |
| `screenshot` | `content/screenshots/` | `screenshot-{slug}.png` | No |
| `icon` | `icons/` | `icon-{slug}.png` | No |
| `logo` | `logos/` | `logo-{slug}.png` | No |
| `item` | `content/items/` | `item-{slug}.png` | No |
| `npc` | `content/npcs/` | `npc-{slug}.png` | No |
| `location` | `content/locations/` | `location-{slug}.png` | No |
| `handout` | `content/handouts/` | `handout-{slug}.png` | No |
| `scene` | project root or campaign art folders | `scene-{slug}.png` | No |

Front and back covers are cover plates, not splashes or torn-picture interior
art. Opaque/full-bleed backgrounds are allowed when the image is composed for
the cover. Interior cinematic art belongs in `splashes/`.

`unused/`, contact sheets, and non-image files are ignored by automatic
discovery. Legacy campaign art folders are ignored by automatic discovery, but
flat `scene-*` filenames can be referenced explicitly by campaign book configs.

## Automatic Placement

The automatic filler pass discovers only roles marked auto-placeable by the
registry: `filler-spot`, `filler-wide`, `filler-plate`, `filler-bottom`, and
`page-finish`. The page-wear pass discovers `page-wear` assets separately.
Explicit book config filler assets can still use `tailpiece`. Filler selection
matches the available blank space to the nominal role size, and renderers do not
upscale small art to fill large spaces. When a gap is large enough, Paper Crown
prefers larger dedicated art and may downscale it to the measured space instead
of reusing a smaller role.

Book config `art_dir` is the root for the whole art library. If `fillers.art_dir`
is set, filler asset paths are resolved under `art_dir / fillers.art_dir`;
auto-discovery and audit still report roles according to the canonical folders
inside that library.

The supported automatic filler shapes are:

- `tailpiece`: tiny ornamental closer.
- `spot`: small centered object or vignette.
- `small-wide`: short landscape filler.
- `plate`: medium/large non-bleed art for roughly half-page gaps.
- `bottom-band`: true bottom-anchored strip art.
- `page-finish`: large in-flow page-ending art.

`page-finish` assets are placed in normal flow, not stamped against the
physical bottom edge. `filler-bottom` assets remain bottom-bleed art and are
stamped with a small bottom safety inset. Slots must explicitly allow
`page-finish` when large page-ending art is desired; `bottom-band` is only for
true bottom-band art in a dedicated bottom-bleed slot.

Do not mix `bottom-band` with in-flow shapes such as `spot`, `small-wide`,
`plate`, or `page-finish` in ordinary chapter/section-end slots. Bottom-band art
should be a wide transparent strip with most visual weight near the lower page
edge and a soft or empty top edge. Generic horizontal illustrations belong in
`fillers/wide/`, `fillers/plate/`, or `fillers/page-finish/`.

The filler size tiers are:

- Under `2.0in`: spot, wide, or tailpiece art can be used.
- `2.0in` to `3.25in`: spot and wide art are preferred, and art should fill at
  least 45% of the usable gap.
- `3.25in` to `4.75in`: plate art is preferred, and art should fill at least
  50% of the usable gap.
- `4.75in` and larger: page-finish art is preferred, and art should fill at
  least 60% of the usable gap.

Slot context is semantic, not just positional. Terminal chapter slots and
source-boundary `section-end` slots can emit contexts such as `reference`,
`combat`, `equipment`, `powers`, `class`, `frame`, `setting`, `languages`, and
`general`. Purpose-named filler files use the `{context}` segment of the
filename to match those slots; `general`, `generic`, and `neutral` remain
fallback contexts.

Use larger art in larger roles:

- Small isolated art goes in `fillers/spot/`.
- Short landscape art goes in `fillers/wide/`.
- Medium and large in-flow art goes in `fillers/plate/`.
- Bottom band art goes in `fillers/bottom/`.
- Large blank-page art goes in `fillers/page-finish/`.
- Transparent paper wear goes in `page-wear/`.

The planner avoids reusing the same filler asset while unused matching art is
available. If a build has to reuse filler art, the draft filler report and build
log include a non-fatal `filler warning` with the later slot and first use.
Draft filler reports also list undersized opportunities when only smaller art
was available for a large gap.

`page-wear` assets must have alpha. Other transparent PNGs are welcome when the
art should float over the page, but opacity is not a naming-contract error for
illustrations that already include their own background.

Paper Crown renders image pixels as authored by default. Book config
`image_treatments` can opt specific roles into a named visual treatment when an
asset set is intentionally designed for it:

```yaml
image_treatments:
  ornament: ink-blend
  filler: raw
  cover: raw
```

Supported treatments are:

- `raw`: no blend, filter, or opacity adjustment.
- `ink-blend`: multiply blending plus a mild contrast lift for simple ink art
  that needs to sit on the paper color.
- `print-punch`, `subtle-punch`, and `strong-punch`: contrast-only boosts.
- `soft-print`: a gentler multiply treatment for intentionally soft art.

Supported role keys include `default`, `inline`, `cover`, `cover-back`,
`chapter`, `divider`, `filler`, `ornament`, `tailpiece`, `headpiece`, `break`,
`splash`, `splash-inline`, `splash-page`, `spot`, `diagram`, `screenshot`,
`map`, `logo`, and `icon`.

Use treatments sparingly. Fix finished illustrations in the source asset when
possible; treatments are best for reusable decorative ink systems. Diagrams,
screenshots, maps, logos, and icons are crisp-rendering roles, so they should
usually remain `raw`.

## Filler Marker Policy

The book config controls where invisible filler measurement markers are
inserted. Markdown headings provide the measured anchor points, but source
Markdown is not the primary control surface for automatic filler policy.
If `fillers.markers` is omitted, Paper Crown synthesizes the historical default
policy: terminal chapter/class markers, sequence source-boundary markers,
subclass markers, frame-family markers, and background-section markers.

```yaml
fillers:
  enabled: true
  slots:
    chapter-end:
      min_space: 0.65in
      max_space: 6.0in
      shapes: [tailpiece, spot, small-wide, plate, page-finish]
  markers:
    terminal:
      chapter_slots: [chapter-end]
      class_slots: [class-end]
    source_boundary:
      sequence_slots: [section-end]
    subclass:
      slots: [subclass-end]
    headings:
      - chapter: frames
        slot: frame-family-end
        heading_level: 1
        slot_kind: frame-family
        skip_first: true
        context: frame
```

Set `terminal`, `source_boundary`, or `subclass` to `false` to disable that
marker family. Set `headings: []` to disable generated heading-section markers.

Chapters can opt out of generated filler markers:

```yaml
contents:
  - kind: file
    title: Legal
    source: rules:Legal.md
    fillers: false
```

Sequence sources can opt out of source-boundary markers after that source:

```yaml
sources:
  - source: rules:Combat.md
    filler: false
```

Use @sidebar.art-library when deciding whether a new asset should be a framed
illustration, a transparent ornament, or an automatically placed filler.

## Class Catalog Art

Class catalogs can name both divider art and opening spot art by slug:

```yaml
class_art_pattern: classes/dividers/class-{slug}.png
class_spot_art_pattern: classes/spots/spot-class-{slug}.png
```

The slug is the normalized class entry slug used by the catalog.

## Audit

Run the art audit against a book config:

```sh
papercrown art audit book.yml
papercrown art audit book.yml --format markdown --strict
papercrown art contact-sheet book.yml --output art-contact-sheet.html
```

The audit prints role counts, recognized and unclassified assets, image metadata
warnings, missing book config references, role mismatches, and suggested filenames
for missing filler opportunities. It also warns about low print resolution,
large aspect-ratio mismatches, missing alpha for transparent roles, visible
content near trim/gutter safety zones, and exact duplicate art.

The contact sheet writes a grouped HTML inventory with thumbnails, dimensions,
roles, and per-asset warnings. Use it to spot inventory gaps such as many combat
fillers but no setting plates.

Draft builds write filler reports and missing-art reports beside draft PDFs.
Use `papercrown build --filler-debug-overlay` to also write a sibling
`*.filler-debug.pdf` with measured filler regions and slot decisions overlaid.

## Common Book Patterns

Rulebooks usually want chapter dividers, class/opening spots, spot/wide fillers,
plates for dense rule sections, diagrams, icons, and occasional full-page
page-finish art.

Campaign books usually want maps, locations, portraits, handouts, spreads,
splashes, plates, faction/gear/vista art, and page-wear if the theme supports
in-world artifacts.

Documentation books usually want screenshots, diagrams, logos, icons, crisp
maps, and fewer automatic decorative fillers.
