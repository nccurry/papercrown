# Art Contract

Paper Crown treats `art_dir` as a named art library. The book owns the files;
Paper Crown classifies them by role, validates the names, and only auto-places
art from roles that are explicitly safe for automatic layout.

Use `papercrown art audit book.yaml` when adding or moving art.

## Canonical Roles

| Role | Folder | Filename shape | Automatic |
| --- | --- | --- | --- |
| `cover` | `covers/` | `cover-front-{slug}.png`, `cover-back-{slug}.png` | No |
| `chapter-divider` | `dividers/` | `divider-{slug}.png` | No |
| `chapter-header` | `headers/` | `header-{slug}.png` | No |
| `class-divider` | `classes/dividers/` | `class-{slug}.png` | No |
| `class-opening-spot` | `classes/spots/` | `spot-class-{slug}.png` | No |
| `frame-divider` | `frames/dividers/` | `frame-{slug}.png` | No |
| `splash` | `splashes/` | `splash-{context}-{subject}-{variant}.png` | No |
| `ornament-headpiece` | `ornaments/headpieces/` | `ornament-headpiece-{slug}.png` | No |
| `ornament-break` | `ornaments/breaks/` | `ornament-break-{slug}.png` | No |
| `ornament-tailpiece` | `ornaments/tailpieces/` | `ornament-tailpiece-{slug}.png` | No |
| `filler-spot` | `fillers/spot/` | `filler-spot-{context}-{subject}-{variant}.png` | Yes |
| `filler-wide` | `fillers/wide/` | `filler-wide-{context}-{subject}-{variant}.png` | Yes |
| `filler-bottom` | `fillers/bottom/` | `filler-bottom-{context}-{subject}-{variant}.png` | Yes |
| `filler-page` | `fillers/page/` | `filler-page-{context}-{subject}-{variant}.png` | Yes |
| `page-wear` | `page-wear/` | `wear-{family}-{size}-{variant}.png` | Yes |
| `faction` | `content/factions/` | `faction-{slug}.png` | No |
| `gear` | `content/gear/` | `gear-{slug}.png` | No |
| `vista` | `content/vistas/` | `vista-{slug}.png` | No |
| `spot` | `content/spots/` or `content/background-spots/` | `spot-{slug}.png`, `bg-{slug}.png` | No |
| `portrait` | `content/portraits/` | `portrait-{slug}.png` | No |
| `map` | `content/maps/` | `map-{slug}.png` | No |
| `item` | `content/items/` | `item-{slug}.png` | No |
| `npc` | `content/npcs/` | `npc-{slug}.png` | No |
| `location` | `content/locations/` | `location-{slug}.png` | No |
| `handout` | `content/handouts/` | `handout-{slug}.png` | No |

`unused/`, `campaign/`, contact sheets, and non-image files are ignored by
automatic discovery.

## Automatic Placement

The automatic filler pass discovers only roles marked auto-placeable by the
registry: `filler-spot`, `filler-wide`, `filler-bottom`, and `filler-page`.
The page-wear pass discovers `page-wear` assets separately. Explicit recipe
filler assets can still use `tailpiece`. Filler selection matches the available
blank space to the nominal role size, and renderers do not upscale small art to
fill large spaces.

Use larger art in larger roles:

- Small isolated art goes in `fillers/spot/`.
- Short landscape art goes in `fillers/wide/`.
- Bottom band art goes in `fillers/bottom/`.
- Large blank-page art goes in `fillers/page/`.
- Transparent paper wear goes in `page-wear/`.

`page-wear` assets must have alpha. Other transparent PNGs are welcome when the
art should float over the page, but opacity is not a naming-contract error for
illustrations that already include their own background.

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
```

The audit prints role counts, recognized and unclassified assets, image metadata
warnings, missing recipe references, role mismatches, and suggested filenames
for missing filler opportunities.
