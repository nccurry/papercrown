# Paper Crown Feature Gaps Noted During Docs Anthology Work

These are follow-up product opportunities found while turning the docs into a
Paper Crown showcase. They are not required for the docs theme pass.

## Web and PDF Feature Parity

- `page_damage` is currently a PDF post-processing feature. Web builds do not
  emit equivalent deterministic page-wear overlays from the recipe fields, so
  this docs theme uses local CSS grain and damage assets as a showcase
  workaround. A product implementation should let the web renderer consume the
  same `page_damage` inputs such as `art_dir`, `seed`, `density`,
  `max_assets_per_page`, `opacity`, and `skip`. For unbroken HTML, this should
  likely mean deterministic small stamps distributed over web surfaces, or an
  explicit paged-preview mode; stretching a full-page damage overlay across a
  long scroll does not translate well.
- Recipe `ornaments.folio_frame` and `ornaments.corner_bracket` are PDF-oriented
  today; web builds clear those context values. A future web path could expose
  the same ornament variables so the generated site can demonstrate recipe
  furniture without theme-specific workarounds.
- `ornaments.corner_bracket` is parsed and passed through, but the base CSS has
  no meaningful visible corner-bracket treatment yet.

## Art-System Discoverability

- There is no first-class art inventory command. A future `papercrown art audit`
  or `papercrown manifest --art` mode could list referenced, missing,
  auto-discovered, unused, filler, splash, ornament, and page-wear assets.
- Missing art currently appears as manifest warnings for resolved recipe fields.
  A dedicated art brief or missing-art report for recipes could make placeholder
  planning easier before final assets exist.

## Web Demonstrations of PDF-Only Systems

- Fillers and page damage rely on PDF layout inspection and overlay stamping.
  The static web export can describe those systems, but it cannot show the same
  dynamic behavior live without screenshots, sample PDFs, or a separate preview
  component.
- A docs/demo mode could optionally render static explanatory placeholders for
  PDF-only systems when targeting web.

## Reference Generation

- Recipe fields, generated matter types, chapter kinds, splash targets, filler
  shapes, and page-damage families are defined in Python dataclasses/constants.
  The docs currently explain them by hand. A generated schema/reference page
  would reduce drift.

## Theme Authoring Ergonomics

- Theme packs can override templates and CSS, but there is no starter command
  specifically for theme authoring. A future `papercrown themes init` command
  could scaffold `theme.yaml`, `book.css`, optional `book.html`, and asset
  folders with comments.
