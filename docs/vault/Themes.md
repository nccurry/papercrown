# Themes

Themes control typography, page furniture, colors, and layout. Paper Crown
ships with six bundled themes: clean SRD, parchment classic, Pinlight
industrial, occult casefile, pulp adventure, and risograph zine.

:::: {.sidebar #theme-pack title="Theme Pack" tags="docs,theme,authoring"}
### Theme Pack

A theme is a directory with `theme.yaml`, one or more CSS files, optional
template overrides, and optional assets. Local themes let a book define its own
visual language without changing Paper Crown itself.
::::

List bundled themes:

```sh
papercrown themes list
```

Copy a bundled theme into a project for customization:

```sh
papercrown themes copy clean-srd themes/my-clean-srd
```

Then point a recipe at the custom theme:

```yaml
theme_dir: ../themes
theme: my-clean-srd
```

Theme assets are treated as render inputs. Changing theme CSS, templates, or
resources invalidates the build cache for affected outputs.

## CSS Anatomy

Paper Crown's shared book foundation lives in ordered modules under
`resources/styles/core/`. Those core modules provide fonts, page rules,
document typography, art placement, TTRPG components, book structure,
generated matter, and web/print fixes.

At render time, Paper Crown layers styles in this order:

```text
Paper Crown core CSS modules
selected theme CSS files
recipe theme_options
```

Web export writes that stack into a generated `styles/book.css` bundle in the
output folder. Theme authors edit their own declared theme files, not the
generated bundle.

Theme packs usually override tokens and a few components in their own CSS. The
theme declares its source files in `theme.yaml`; Paper Crown loads those files
in order and does not infer filenames. For a very small local theme, one
declared file like `theme.css` is also fine.

## Local Theme Example

This documentation is rendered with its own local theme. The recipe selects a
theme directory instead of using a bundled theme:

```yaml
theme_dir: ../themes
theme: papercrown-docs
```

The local theme declares its CSS files in order:

```yaml
name: Paper Crown Docs Anthology
css:
  - tokens.css
  - components.css
  - polish.css
template: book.html
```

Yes: those docs CSS files override the Paper Crown defaults. The first file
sets broad tokens:

```css
:root {
  --paper: #fbf6e9;
  --ink: #201914;
  --accent: #9a3f2b;
  --accent-deep: #5f2b68;
}
```

The component layer handles the docs-specific book treatment, and the later
polish file adds narrow adjustments without turning the theme into one giant
stylesheet. That is the intended pattern for custom themes: start with tokens,
then add component overrides where the book needs its own voice.

## What Themes Can Style

Themes can customize @handout.book-furniture, typed TTRPG blocks, tables,
code, art frames, web layout, print page margins, cover pages, section dividers,
and generated matter.

This documentation uses a local theme pack so each chapter can show a different
genre treatment while sharing one book structure.
