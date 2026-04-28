# Quick Start

Install the CLI once:

```sh
uv tool install https://github.com/nccurry/papercrown/releases/download/v1.0.0/papercrown-1.0.0-py3-none-any.whl
```

Replace `1.0.0` with the release version you want. Paper Crown release artifacts
live on GitHub Releases, not PyPI.

Create a new Paper Crown project:

```sh
papercrown init my-book
cd my-book
papercrown manifest
papercrown doctor
papercrown build
papercrown verify
```

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
