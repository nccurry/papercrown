#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: scripts/ci-image-run.sh '<command>'" >&2
  exit 2
fi

source versions.env

image="${CI_IMAGE}:main"
if docker pull "$image"; then
  echo "Using published CI image: $image"
else
  image="papercrown-ci:candidate"
  echo "Published CI image unavailable; building local candidate: $image" >&2
  docker build \
    --file Dockerfile.ci \
    --build-arg "UV_BASE_IMAGE=${UV_BASE_IMAGE}" \
    --build-arg "TASK_VERSION=${TASK_VERSION}" \
    --build-arg "OBSIDIAN_EXPORT_VERSION=${OBSIDIAN_EXPORT_VERSION}" \
    --tag "$image" \
    .
fi

workspace="${GITHUB_WORKSPACE:-$PWD}"
docker run --rm \
  -e UV_CACHE_DIR=/workspace/.uv-cache \
  -v "${workspace}:/workspace" \
  -w /workspace \
  "$image" \
  bash -lc "git config --global --add safe.directory /workspace && uv sync --locked --all-groups && $1"
