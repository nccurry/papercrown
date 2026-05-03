# Architecture

Paper Crown is a small publishing pipeline: resolve vault content, turn a book
config into a manifest, assemble Markdown, apply theme and art rules, then
render PDF or web output.

## Product Model

| Layer | Owner | Contract |
| --- | --- | --- |
| `papercrown.yaml` | Project | Build defaults such as target, scope, profile, jobs, pagination, wear, and timings |
| `book.yml` | Book | Title, metadata, vaults, contents, theme, art, output names, and generated pages |
| Vaults | Author | Markdown files, images, Obsidian links, and normal editor-friendly source |
| Theme | Designer | CSS files, optional template, optional art labels, and theme assets |
| Manifest | Paper Crown | The resolved chapter tree, art paths, fillers, wear catalog, and warnings |

## Data Flow

`papercrown manifest` is the first useful readout. It shows the book file,
vault overlay, output root, chapters, styles, sources, and art before rendering.

After that, both PDF and web builds share the same assembled Markdown. Internal
links, Obsidian exports, TTRPG widgets, generated pages, dividers, splashes,
fillers, and image treatments are resolved before a target-specific renderer
writes files.

## Output Model

PDF builds can emit a combined book, section PDFs, individual PDFs, or draft
diagnostics. Web builds emit one static tree under `web/`; it can be copied
directly to GitHub Pages, GitLab Pages, or any static host.

## Package Map

- `papercrown.app`: CLI, command actions, output, and layered build config.
- `papercrown.project`: book loading, manifest construction, vaults, themes,
  scaffolding, paths, and bundled resources.
- `papercrown.assembly`: Markdown assembly, headings, art blocks, source
  normalization, filler markers, and TTRPG preprocessing.
- `papercrown.render`: build orchestration, Pandoc, WeasyPrint, PDFs,
  pagination, static web export, and snapshots.
- `papercrown.media`: images, treatments, filler layout, and page wear.
- `papercrown.art`: art roles, filename classification, audits, and contact
  sheets.
- `papercrown.system`: diagnostics, dependency checks, cache fingerprints,
  export helpers, doctor checks, and verification.
