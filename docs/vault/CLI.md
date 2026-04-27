# CLI

The installed `papercrown` command is the supported product interface. Install
it once with uv:

```sh
uv tool install papercrown
```

```text
papercrown build [RECIPE]
papercrown manifest [RECIPE]
papercrown doctor [RECIPE]
papercrown verify [RECIPE]
papercrown deps check
papercrown init [PATH]
papercrown themes list
papercrown themes copy NAME DEST
```

Common build options:

```sh
papercrown build book.yaml --scope book --profile print
papercrown build book.yaml --scope sections --jobs auto
papercrown build book.yaml --chapter primer
papercrown build book.yaml --target web
```

Use `doctor` before rendering when setting up a new project or moving content
between machines:

```sh
papercrown doctor book.yaml --strict
```

Use `verify` after rendering PDFs:

```sh
papercrown verify book.yaml --scope book --profile print --strict
```
