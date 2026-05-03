# Overview

:::: {.flourish-note .flourish-crown}
Paper Crown turns Markdown vaults into polished tabletop RPG books. The same
source can become print-ready PDFs, split section PDFs, or a static web site
ready for GitHub Pages.
::::

This documentation is also a Paper Crown book. Its chapters, dividers, callouts,
art, table of contents, and static HTML are produced by the framework it
documents.

:::: {.sidebar #docs-as-book title="Docs As A Book" tags="docs,overview"}
### Docs As A Book

Read the site as a guide and as a working sample: `docs/book.yml` assembles the
vault, `docs/themes/papercrown-docs` styles it, and `docs/assets` supplies the
art library.
::::

Paper Crown has five pieces:

| Piece | You provide | Paper Crown does |
| --- | --- | --- |
| Vault | Markdown, images, and links | Resolves source files and embeds |
| Book config | Title, contents, theme, art, and output names | Builds a manifest |
| Project config | Build defaults in `papercrown.yaml` | Applies repeatable CLI defaults |
| Theme | CSS, templates, fonts, and assets | Shapes print and web output |
| Build | A CLI command | Writes PDFs, static HTML, caches, and reports |

Start with [[Quick Start]], then use [[Book Configs]], [[Vaults and Markdown]],
[[Themes]], and [[Art]] when you need one layer in more detail.

<div class="art-rule art-rule-crown" aria-hidden="true"></div>
