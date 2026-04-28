# Architecture

Paper Crown is organized around the build pipeline: project configuration is
loaded, Markdown is assembled, media is prepared, and renderers write PDF or web
outputs.

## Package Map

- `papercrown.app`: CLI commands, build configuration, option enums, and project
  scaffolding.
- `papercrown.project`: recipe models/loading, manifest construction, vault and
  catalog resolution, bundled resource paths, output paths, and themes.
- `papercrown.assembly`: Markdown assembly, heading/source normalization, art
  blocks, filler markers, and TTRPG block preprocessing.
- `papercrown.render`: build orchestration, render jobs, Pandoc/WeasyPrint/PDF
  pipeline code, pagination analysis, static web export, and render snapshots.
- `papercrown.media`: image diagnostics/optimization, image treatments,
  conditional filler placement, and page-wear rendering.
- `papercrown.art`: art role classification and recipe art audit/reporting.
- `papercrown.system`: diagnostics, cache fingerprints, dependency checks,
  Obsidian export, doctor checks, and post-build verification.

## Placement Rules

New code should live where its main owner lives. For example, a new recipe field
belongs in `project`, a new PDF stamping step belongs in `render`, and a new
image preprocessing policy belongs in `media`. Shared dataclasses should stay
near the subsystem that creates them unless several packages already depend on
them.

Avoid adding new top-level modules under `papercrown`. The root package is kept
for package initialization and bundled resources; behavior belongs in one of the
subpackages above.
