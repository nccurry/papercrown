#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"

log() {
  printf '==> %s\n' "$1"
}

is_windows_shell() {
  case "$(uname -s 2>/dev/null || printf unknown)" in
    MINGW*|MSYS*|CYGWIN*) return 0 ;;
    *) return 1 ;;
  esac
}

if is_windows_shell; then
  if command -v task >/dev/null 2>&1; then
    log "Installing Paper Crown dependencies through Task"
    task deps:install
    exit 0
  fi

  if command -v powershell.exe >/dev/null 2>&1; then
    ps_script="$repo_root/scripts/bootstrap.ps1"
    if command -v cygpath >/dev/null 2>&1; then
      ps_script=$(cygpath -w "$ps_script")
    fi
    log "Delegating Windows bootstrap to PowerShell"
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$ps_script"
    exit 0
  fi

  printf '%s\n' "Task is not installed and PowerShell was not found. Run scripts/bootstrap.ps1 from Windows PowerShell." >&2
  exit 1
fi

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

if ! command -v task >/dev/null 2>&1; then
  if ! command -v curl >/dev/null 2>&1; then
    printf '%s\n' "Task is not installed and curl is not available. Install Task, then run: task deps:install" >&2
    exit 1
  fi

  log "Installing Task"
  mkdir -p "$HOME/.local/bin"
  curl -sL https://taskfile.dev/install.sh | sh -s -- -d -b "$HOME/.local/bin"
fi

if ! command -v task >/dev/null 2>&1; then
  printf '%s\n' "Task was installed but was not found on PATH. Add $HOME/.local/bin to PATH, then run: task deps:install" >&2
  exit 1
fi

log "Installing Paper Crown dependencies through Task"
task deps:install
