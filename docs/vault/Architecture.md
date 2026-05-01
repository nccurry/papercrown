# Architecture

Paper Crown is organized around a simple publishing pipeline: collect Markdown
from vaults, resolve a book config into a manifest, apply a theme and art
library, then render PDF and web outputs.

## Product Model

:::: {.art-slot role="splash" placement="bottom-half" art="papercrown-docs/splashes/splash-product-model-codex-route.png"}
::::

| Layer | What you own | What Paper Crown does |
| --- | --- | --- |
| Vault | Markdown notes, images, and Obsidian-style links | Resolves source files and embeds |
| Book Config | Book structure, metadata, themes, art, and outputs | Builds a render manifest |
| Theme | CSS, template, page furniture, and visual identity | Applies consistent print and web layout |
| Build | CLI options for target, scope, profile, and speed | Emits PDFs, HTML, caches, and reports |

## Data Flow

The book config is the center of the system. It gives each vault an alias,
declares chapter order, selects a bundled or local theme, and points at
optional art systems. `papercrown manifest` shows the resolved structure before
rendering so you can check paths, headings, art references, and output names
without waiting for a full PDF build.

Markdown assembly happens before either renderer runs. That means PDF and web
exports share the same source resolution, filters, typed TTRPG blocks, internal
links, generated matter, and book-config-driven art declarations.

## Output Model

Paper Crown can render one assembled book to PDF outputs, static HTML, or both.
PDF builds can emit a combined book, section PDFs, individual chapter PDFs, and
draft diagnostics. Web builds emit a static site that can be copied to GitHub
Pages, GitLab Pages, or any plain file host.

## Package Map

- `papercrown.app`: CLI commands, command actions, console output, and layered
  build configuration.
- `papercrown.build`: command-neutral build options, build requests, and build
  results shared by the CLI, render orchestration, paths, and diagnostics.
- `papercrown.project`: book config models/loading, manifest construction, vault and
  catalog resolution, project scaffolding, bundled resource paths, output paths,
  and themes.
- `papercrown.assembly`: Markdown assembly, heading/source normalization, art
  blocks, filler markers, and TTRPG block preprocessing.
- `papercrown.render`: build orchestration, render jobs, Pandoc/WeasyPrint/PDF
  pipeline code, pagination analysis, static web export, and render snapshots.
- `papercrown.media`: image diagnostics/optimization, image treatments,
  conditional filler placement, and page-wear rendering.
- `papercrown.art`: art role classification and book art audit/reporting.
- `papercrown.system`: diagnostics, cache fingerprints, dependency checks,
  Obsidian export, doctor checks, and post-build verification.

## Placement Rules

New code should live where its main owner lives. A new book config field belongs in
`project`, a new PDF stamping step belongs in `render`, and a new image
preprocessing policy belongs in `media`. Shared dataclasses should stay near
the subsystem that creates them unless several packages already depend on them.

Avoid adding new top-level modules under `papercrown`. The root package is kept
for package initialization and bundled resources; behavior belongs in one of
the subpackages above.
