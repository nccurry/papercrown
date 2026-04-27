# Themes

Themes control typography, page furniture, colors, and layout. Paper Crown
ships with several bundled themes, including clean SRD, parchment classic,
modern minimal, and more expressive genre styles.

List bundled themes:

```sh
task themes:list
```

Copy a bundled theme into a project for customization:

```sh
task themes:copy THEME=clean-srd DEST=themes/my-clean-srd
```

Then point a recipe at the custom theme:

```yaml
theme_dir: ../themes
theme: my-clean-srd
```

Theme assets are treated as render inputs. Changing theme CSS, templates, or
resources invalidates the build cache for affected outputs.
