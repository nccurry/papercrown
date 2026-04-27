#!/usr/bin/env bash
set -euo pipefail

push="${CONTAINER_PUSH:-false}"
tags="${CONTAINER_TAGS:-papercrown:latest}"
labels="${CONTAINER_LABELS:-}"

args=(
  --file Dockerfile
  --pull
)

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
