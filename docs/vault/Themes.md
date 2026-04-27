# Themes

Themes control typography, page furniture, colors, and layout. Paper Crown
ships with several bundled themes, including clean SRD, parchment classic,
modern minimal, and more expressive genre styles.

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
