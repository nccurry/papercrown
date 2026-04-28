#!/usr/bin/env bash
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

export PATH="$HOME/.local/bin:$PATH"

load_versions() {
  if [ ! -f versions.env ]; then
    printf '%s\n' "versions.env is missing." >&2
    exit 1
  fi
  # shellcheck disable=SC1091
  . ./versions.env
}

log() {
  printf '==> %s\n' "$1"
}

need_sudo() {
  if [ "$(id -u)" -eq 0 ]; then
    return 1
  fi
  command -v sudo >/dev/null 2>&1
}

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  elif command -v sudo >/dev/null 2>&1; then
    sudo "$@"
  else
    printf 'Missing sudo; run this command as root: %s\n' "$*" >&2
    exit 1
  fi
}

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    return
  fi
  if ! command -v curl >/dev/null 2>&1; then
    printf '%s\n' "uv is missing and curl is not available." >&2
    exit 1
  fi
  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
}

install_pandoc() {
  if command -v pandoc >/dev/null 2>&1; then
    return
  fi
  log "Installing Pandoc"
  if command -v apt-get >/dev/null 2>&1; then
    run_privileged apt-get update
    run_privileged apt-get install -y pandoc
  elif command -v brew >/dev/null 2>&1; then
    brew install pandoc
  elif command -v dnf >/dev/null 2>&1; then
    run_privileged dnf install -y pandoc
  elif command -v pacman >/dev/null 2>&1; then
    run_privileged pacman -S --needed --noconfirm pandoc
  elif command -v zypper >/dev/null 2>&1; then
    run_privileged zypper install -y pandoc
  else
    printf '%s\n' "Pandoc is missing and no supported package manager was found." >&2
    exit 1
  fi
}

install_obsidian_export() {
  expected="obsidian-export ${OBSIDIAN_EXPORT_VERSION}"
  existing_path=$(command -v obsidian-export 2>/dev/null || true)
  if [ -n "$existing_path" ] &&
    obsidian-export --version 2>/dev/null | grep -q "^${expected}$"; then
    case "$existing_path" in
      *".cargo"*) ;;
      *) return ;;
    esac
  fi
  if ! command -v curl >/dev/null 2>&1; then
    printf '%s\n' "obsidian-export is missing and curl is not available." >&2
    exit 1
  fi
  os=$(uname -s)
  arch=$(uname -m)
  case "$os:$arch" in
    Linux*:x86_64|Linux*:amd64)
      asset="obsidian-export-x86_64-unknown-linux-gnu.tar.xz"
      ;;
    Darwin*:arm64|Darwin*:aarch64)
      asset="obsidian-export-aarch64-apple-darwin.tar.xz"
      ;;
    Darwin*:x86_64|Darwin*:amd64)
      asset="obsidian-export-x86_64-apple-darwin.tar.xz"
      ;;
    *)
      printf 'Unsupported obsidian-export binary platform: %s %s\n' "$os" "$arch" >&2
      exit 1
      ;;
  esac
  url="https://github.com/zoni/obsidian-export/releases/download/v${OBSIDIAN_EXPORT_VERSION}/${asset}"
  tmp_dir=$(mktemp -d)
  trap 'rm -rf "$tmp_dir"' EXIT
  log "Installing obsidian-export ${OBSIDIAN_EXPORT_VERSION}"
  curl --proto '=https' --tlsv1.2 -LsSf "$url" -o "$tmp_dir/$asset"
  curl --proto '=https' --tlsv1.2 -LsSf "$url.sha256" -o "$tmp_dir/$asset.sha256"
  expected_hash=$(awk '{print $1}' "$tmp_dir/$asset.sha256")
  if command -v sha256sum >/dev/null 2>&1; then
    actual_hash=$(sha256sum "$tmp_dir/$asset" | awk '{print $1}')
  else
    actual_hash=$(shasum -a 256 "$tmp_dir/$asset" | awk '{print $1}')
  fi
  if [ "$expected_hash" != "$actual_hash" ]; then
    printf '%s\n' "obsidian-export checksum mismatch." >&2
    exit 1
  fi
  tar -C "$tmp_dir" -xf "$tmp_dir/$asset"
  mkdir -p "$HOME/.local/bin"
  binary=$(find "$tmp_dir" -type f -name obsidian-export -perm -u+x | head -n 1)
  if [ -z "$binary" ]; then
    binary=$(find "$tmp_dir" -type f -name obsidian-export | head -n 1)
  fi
  if [ -z "$binary" ]; then
    printf '%s\n' "obsidian-export binary was not found in release archive." >&2
    exit 1
  fi
  cp "$binary" "$HOME/.local/bin/obsidian-export"
  chmod +x "$HOME/.local/bin/obsidian-export"
  export PATH="$HOME/.local/bin:$PATH"
}

install_pdf_runtime() {
  case "$(uname -s)" in
    Linux*)
      if command -v apt-get >/dev/null 2>&1; then
        log "Installing Linux PDF runtime libraries"
        run_privileged apt-get update
        run_privileged apt-get install -y libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0
      elif command -v dnf >/dev/null 2>&1; then
        log "Installing Linux PDF runtime libraries"
        run_privileged dnf install -y pango harfbuzz
      elif command -v pacman >/dev/null 2>&1; then
        log "Installing Linux PDF runtime libraries"
        run_privileged pacman -S --needed --noconfirm pango harfbuzz
      fi
      ;;
    Darwin*)
      if command -v brew >/dev/null 2>&1; then
        log "Installing macOS PDF runtime libraries"
        brew install pango
      fi
      ;;
  esac
}

load_versions
install_uv
install_pandoc
install_obsidian_export
install_pdf_runtime

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' "uv was installed but was not found on PATH." >&2
  exit 1
fi

log "Syncing Python dependencies"
uv sync --locked --all-groups

log "Verifying dependency state"
uv run --locked papercrown deps check
