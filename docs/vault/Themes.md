# Themes

Themes control typography, page furniture, colors, and layout. Paper Crown
ships with several bundled themes, including clean SRD, parchment classic,
modern minimal, and more expressive genre styles.

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

## What Themes Can Style

Themes can customize @handout.book-furniture, typed TTRPG blocks, tables,
code, art frames, web layout, print page margins, cover pages, section dividers,
and generated matter.

This documentation uses a local theme pack so each chapter can show a different
genre treatment while sharing one book structure.
