# Container Image

Paper Crown publishes a reusable runtime image to GitHub Container Registry:

```text
ghcr.io/nccurry/papercrown
```

The image includes the installed `papercrown` CLI, Pandoc, WeasyPrint's native
Linux libraries, and `obsidian-export`. It is designed for projects that want to
build Paper Crown output in CI without installing the toolchain in each job.

Run a project locally through the image:

```sh
docker run --rm -v "$PWD:/workspace" -w /workspace ghcr.io/nccurry/papercrown:latest papercrown build --target web
```

Use a version tag such as `ghcr.io/nccurry/papercrown:1.0.0` for repeatable CI.
The `latest` and `main` tags track the default branch; `v*` repository tags
publish matching image tags.

Keep the GHCR package public, or grant package access to downstream projects
that need to pull the image during CI.

Minimal GitLab Pages job:

```yaml
pages:
  image: ghcr.io/nccurry/papercrown:latest
  script:
    - papercrown build --target web --force
    - mkdir -p public
    - cp -R "output/Paper Crown/my-book/web/." public/
  artifacts:
    paths:
      - public
```

Replace the `cp` source with the web output path produced by the recipe's
`output_dir` and `output_name`.
