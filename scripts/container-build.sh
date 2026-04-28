#!/usr/bin/env bash
set -euo pipefail

push="${CONTAINER_PUSH:-false}"
tags="${CONTAINER_TAGS:-papercrown:latest}"
labels="${CONTAINER_LABELS:-}"

if [[ -f versions.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source versions.env
  set +a
fi

args=(
  --file Dockerfile
  --pull
  --build-arg "UV_BASE_IMAGE=${UV_BASE_IMAGE:-ghcr.io/astral-sh/uv:0.11.8-python3.12-trixie-slim}"
  --build-arg "PYTHON_RUNTIME_IMAGE=${PYTHON_RUNTIME_IMAGE:-python:3.12-slim-bookworm}"
  --build-arg "OBSIDIAN_EXPORT_VERSION=${OBSIDIAN_EXPORT_VERSION:-25.3.0}"
)

if [[ -n "${DOCKER_CACHE_FROM:-}" ]]; then
  args+=(--cache-from "$DOCKER_CACHE_FROM")
fi

if [[ -n "${DOCKER_CACHE_TO:-}" ]]; then
  args+=(--cache-to "$DOCKER_CACHE_TO")
fi

while IFS= read -r tag; do
  if [[ -n "$tag" ]]; then
    args+=(--tag "$tag")
  fi
done <<< "$tags"

while IFS= read -r label; do
  if [[ -n "$label" ]]; then
    args+=(--label "$label")
  fi
done <<< "$labels"

if [[ "$push" == "true" ]]; then
  args+=(--push)
else
  args+=(--load)
fi

docker buildx build "${args[@]}" .
