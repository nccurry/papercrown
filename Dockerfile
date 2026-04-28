# syntax=docker/dockerfile:1

ARG UV_BASE_IMAGE=ghcr.io/astral-sh/uv:0.11.8-python3.12-bookworm-slim
ARG PYTHON_RUNTIME_IMAGE=python:3.12-slim-bookworm
ARG OBSIDIAN_EXPORT_VERSION=25.3.0

FROM ${UV_BASE_IMAGE} AS build

WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY_LICENSES.md ./
COPY src ./src
RUN uv build --wheel --out-dir /dist

FROM ${PYTHON_RUNTIME_IMAGE} AS runtime

ARG OBSIDIAN_EXPORT_VERSION

LABEL org.opencontainers.image.title="Paper Crown" \
      org.opencontainers.image.description="Paper Crown CLI with Pandoc, WeasyPrint native libraries, and obsidian-export installed." \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/nccurry/papercrown"

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fontconfig \
        fonts-dejavu-core \
        git \
        libharfbuzz-subset0 \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        pandoc \
        shared-mime-info \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    asset="obsidian-export-x86_64-unknown-linux-gnu.tar.xz"; \
    url="https://github.com/zoni/obsidian-export/releases/download/v${OBSIDIAN_EXPORT_VERSION}/${asset}"; \
    tmp="$(mktemp -d)"; \
    curl --proto '=https' --tlsv1.2 -LsSf "$url" -o "$tmp/$asset"; \
    curl --proto '=https' --tlsv1.2 -LsSf "$url.sha256" -o "$tmp/$asset.sha256"; \
    expected="$(awk '{print $1}' "$tmp/$asset.sha256")"; \
    actual="$(sha256sum "$tmp/$asset" | awk '{print $1}')"; \
    test "$expected" = "$actual"; \
    tar -C "$tmp" -xf "$tmp/$asset"; \
    install -m 0755 "$(find "$tmp" -type f -name obsidian-export | head -n 1)" /usr/local/bin/obsidian-export; \
    rm -rf "$tmp"; \
    obsidian-export --version

COPY --from=build /dist/*.whl /tmp/

RUN python -m pip install /tmp/*.whl \
    && rm -f /tmp/*.whl \
    && papercrown --help >/dev/null \
    && pandoc --version >/dev/null \
    && obsidian-export --version >/dev/null

CMD ["papercrown", "--help"]
