# Themes

Themes control typography, page furniture, colors, and layout. Paper Crown
ships with six bundled themes: clean SRD, parchment classic, Pinlight
industrial, occult casefile, pulp adventure, and risograph zine.

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

The shared book foundation lives in modular CSS files under
`resources/styles/core/`. Paper Crown layers those files before the active
theme's CSS. Web export writes a generated `styles/book.css` bundle into the
output, but theme authors only edit their own theme CSS.

Theme packs usually override tokens and a few components in their own CSS. A
theme declares its source files in `theme.yaml`; Paper Crown loads those files
in order and does not infer filenames. A small theme is often enough:

```yaml
name: My Clean SRD
css:
  - tokens.css
  - components.css
```

```css
/* tokens.css */
:root {
  --paper: #ffffff;
  --ink: #171717;
  --accent: #2563eb;
}
```

```css
/* components.css */
table th {
  background: var(--accent);
}

.callout {
  border-left-color: var(--accent);
}
```

For a very small local theme, one declared file like `theme.css` is also fine.
The important distinction is that source theme files are author-owned inputs;
`styles/book.css` is the generated output bundle.
