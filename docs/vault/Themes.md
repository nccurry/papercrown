# Themes

:::: {.flourish-note .flourish-theme}
Themes control typography, page furniture, colors, component styling, and web
layout. The same Markdown can read as a clean SRD, field manual, zine, occult
casefile, or custom book.
::::

Paper Crown ships with `clean-srd`, `industrial`, `parchment-classic`,
`occult-casefile`, `pulp-adventure`, and `risograph-zine`.

<div class="art-rule art-rule-theme" aria-hidden="true"></div>

:::: {.sidebar #theme-pack title="Theme Pack" tags="docs,theme"}
### Theme Pack

A theme is a directory with `theme.yaml`, declared CSS files, optional assets,
optional art-label CSS, and an optional template.
::::

## How to Use It

List and copy themes:

```sh
papercrown themes list
papercrown themes copy clean-srd themes/my-clean-srd
```

Select the local theme in `book.yml`:

```yaml
theme: my-clean-srd
```

Set `theme_dir` only when themes live somewhere other than the project
`themes/` directory.

## How to Adapt It

Start with tokens when the book only needs a palette or type change. Move into
component CSS when covers, dividers, tables, code, callouts, TTRPG widgets, or
web navigation need their own treatment.

`theme.yaml` declares load order:

```yaml
name: My Clean SRD
css:
  - tokens.css
  - components.css
template: book.html
```

The renderer layers styles in this order:

```text
Paper Crown core CSS modules
selected theme CSS files
book theme_options
role image-treatment CSS
```

Web export writes the stack into `web/styles/book.css`.

## Local Theme Example

This site uses a local `papercrown-docs` theme. Its book config only needs:

```yaml
theme: papercrown-docs
```

Because the theme lives at `docs/themes/papercrown-docs`, Paper Crown finds it
before looking at bundled themes.

Theme options become CSS custom properties:

```yaml
theme_options:
  accent: "#8f2d5d"
  paper: "#fff8e8"
```

Book-specific art labels are CSS files too. A project file such as
`styles/power-header.css` makes filenames beginning with `power-header-` render
with `.power-header` and `.art-role-power-header`.
