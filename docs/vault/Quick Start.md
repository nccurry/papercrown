# Quick Start

Install the CLI once:

```sh
uv tool install papercrown
```

Create a new Paper Crown project:

```sh
papercrown init my-book
cd my-book
papercrown manifest
papercrown doctor
papercrown build
papercrown verify
```

> [!tip] First useful loop
> Run the commands in this order the first time through. `manifest` explains
> the resolved book shape before rendering, and `doctor` catches missing tools
> before a PDF build has to fail noisily.

:::: {.rule #first-build-loop title="First Build Loop" tags="docs,build,quickstart"}
### First Build Loop

Use `manifest` to inspect what Paper Crown will build, `doctor` to validate the
machine and content, `build` to render outputs, and `verify` to check PDFs
after rendering.
::::

**Manifest:** Inspect the recipe, vault roots, chapter order, theme, and art references.
**Doctor:** Validate the machine, content, recipe paths, images, and external render tools.
**Build:** Render PDF or web output into the configured caller-owned output folder.
**Verify:** Check generated PDFs after rendering, especially before publishing or release.

Paper Crown reads `papercrown.yaml` in the current directory when no recipe path
is provided. That project file usually points to the default recipe.

You can also run the public example from this repository:

```sh
papercrown manifest examples/starfall/recipes/starfall-field-guide.yaml
papercrown build examples/starfall/recipes/starfall-field-guide.yaml
```

For a static web export, use:

```sh
papercrown build examples/starfall/recipes/starfall-field-guide.yaml --target web
```

The docs site is built the same way, using @rule.first-build-loop with
`--target web`.
