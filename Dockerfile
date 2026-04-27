# syntax=docker/dockerfile:1

FROM rust:1-bookworm AS obsidian-export

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libssl-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN cargo install obsidian-export --locked

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

WORKDIR /src
COPY pyproject.toml uv.lock README.md LICENSE THIRD_PARTY_LICENSES.md ./
COPY src ./src
RUN uv build --wheel --out-dir /dist

FROM python:3.12-slim-bookworm AS runtime

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
    && rm -rf /var/lib/apt/lists/*

COPY --from=obsidian-export /usr/local/cargo/bin/obsidian-export /usr/local/bin/obsidian-export
COPY --from=build /dist/*.whl /tmp/

RUN python -m pip install /tmp/*.whl \
    && rm -f /tmp/*.whl \
    && papercrown --help >/dev/null \
    && pandoc --version >/dev/null \
    && obsidian-export --version >/dev/null

CMD ["papercrown", "--help"]
