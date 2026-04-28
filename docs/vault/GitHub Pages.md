# GitHub Pages

The documentation site is built by Paper Crown and deployed by GitHub Actions.
The source lives under `docs/`; generated HTML lives under `docs/site/` and is
not committed.

Build the site locally:

```sh
task docs:build
```

Serve the generated site:

```sh
task docs:serve
```

Clean generated docs output:

```sh
task docs:clean
```

The Pages workflow runs on pushes to `main` that affect docs, source, bootstrap
scripts, or build configuration. It follows the custom GitHub Pages Actions
flow:

1. Bootstrap dependencies with `./scripts/bootstrap.sh`.
2. Build docs with `task docs:build`.
3. Upload `docs/site/Paper Crown/papercrown-docs/web`.
4. Deploy the uploaded artifact to GitHub Pages.

:::: {.handout #pages-route title="Pages Route" tags="docs,maintenance,publishing"}
### Pages Route

The Pages artifact is the generated `web` directory for the docs recipe. The
workflow uploads only that static tree, not the recipe source or local caches.
::::

Configure the repository Pages source to use GitHub Actions. The expected
public URL is:

```text
https://nccurry.github.io/papercrown/
```

If a local docs build works but Pages does not update, compare the workflow
artifact path against @handout.pages-route first.
