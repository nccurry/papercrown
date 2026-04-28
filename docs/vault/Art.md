# Art Contract

Paper Crown treats `art_dir` as a named art library. The book owns the files;
Paper Crown classifies them by role, validates the names, and only auto-places
art from roles that are explicitly safe for automatic layout.

Use `papercrown art audit book.yaml` when adding or moving art.

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
| `filler-page` | `fillers/page/` | `filler-page-{context}-{subject}-{variant}.png` | Yes |
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

Front and back covers are cover plates, not splashes or torn-picture interior
art. Opaque/full-bleed backgrounds are allowed when the image is composed for
the cover. Interior cinematic art belongs in `splashes/`.

`unused/`, `campaign/`, contact sheets, and non-image files are ignored by
automatic discovery.

## Automatic Placement

The automatic filler pass discovers only roles marked auto-placeable by the
registry: `filler-spot`, `filler-wide`, `filler-bottom`, and `filler-page`.
It also discovers `filler-plate` for medium/large in-flow gaps. The page-wear
pass discovers `page-wear` assets separately. Explicit recipe filler assets can
still use `tailpiece`. Filler selection matches the available blank space to the
nominal role size, and renderers do not upscale small art to fill large spaces.
When a gap is large enough, Paper Crown prefers larger dedicated art and may
downscale it to the measured space instead of reusing a smaller role.

The supported automatic filler shapes are:

- `tailpiece`: tiny ornamental closer.
- `spot`: small centered object or vignette.
- `small-wide`: short landscape filler.
- `plate`: medium/large non-bleed art for roughly half-page gaps.
- `bottom-band`: true bottom-anchored strip art.
- `page-finish`: large in-flow page-ending art.

`filler-page` assets are `page-finish` art. They are placed in normal flow, not
stamped against the physical bottom edge. Older recipes that allow
`bottom-band` still accept `page-finish` assets so existing books keep working.
`filler-bottom` assets remain bottom-bleed art and are stamped with a small
bottom safety inset.

The filler size tiers are:

- Under `2.0in`: spot, wide, or tailpiece art can be used.
- `2.0in` to `3.25in`: spot and wide art are preferred, and art should fill at
  least 45% of the usable gap.
- `3.25in` to `4.75in`: plate art is preferred, and art should fill at least
  50% of the usable gap.
- `4.75in` and larger: page-filler art is preferred, and art should fill at
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
- Large blank-page art goes in `fillers/page/`.
- Transparent paper wear goes in `page-wear/`.

The planner avoids reusing the same filler asset while unused matching art is
available. If a build has to reuse filler art, the draft filler report and build
log include a non-fatal `filler warning` with the later slot and first use.
Draft filler reports also list undersized opportunities when only smaller art
was available for a large gap.

`page-wear` assets must have alpha. Other transparent PNGs are welcome when the
art should float over the page, but opacity is not a naming-contract error for
illustrations that already include their own background.

Diagrams, screenshots, maps, logos, and icons are crisp-rendering roles. Wrap
them in their matching Markdown class, such as `.art-diagram` or
`.art-screenshot`, so they do not inherit illustration blend/filter treatment.

## Filler Marker Policy

The recipe controls where invisible filler measurement markers are inserted.
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
      shapes: [tailpiece, spot, small-wide, plate, bottom-band, page-finish]
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

Set `terminal`, `source_boundary`, or `subclass` to `false` to disable that
marker family. Set `headings: []` to disable generated heading-section markers.

Chapters can opt out of generated filler markers:

```yaml
chapters:
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

## Class Catalog Art

Class catalogs can name both divider art and opening spot art by slug:

```yaml
class_art_pattern: classes/dividers/class-{slug}.png
class_spot_art_pattern: classes/spots/spot-class-{slug}.png
```

The slug is the normalized class entry slug used by the catalog.

## Audit

Run the art audit against a recipe:

```sh
papercrown art audit book.yaml
papercrown art audit book.yaml --format markdown --strict
papercrown art contact-sheet book.yaml --output art-contact-sheet.html
```

The audit prints role counts, recognized and unclassified assets, image metadata
warnings, missing recipe references, role mismatches, and suggested filenames
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
