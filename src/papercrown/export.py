"""External tool discovery and Obsidian vault export support."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .cache import CACHE_SCHEMA_VERSION, JsonValue, fingerprint_files
from .manifest import Manifest

LogFn = Callable[[str], None]
EXPORT_STRATEGY_VERSION = "referenced-per-file-v1"


@dataclass(frozen=True)
class Tools:
    """Resolved paths to the external commands used by the build pipeline."""

    pandoc: str
    obsidian_export: str
    weasyprint: str


def _find_weasyprint() -> str:
    """Return a usable WeasyPrint executable path or raise ``RuntimeError``."""
    executable_dir = Path(sys.executable).resolve().parent
    for name in ("weasyprint.exe", "weasyprint"):
        candidate = executable_dir / name
        if candidate.is_file():
            return str(candidate)
    path = shutil.which("weasyprint")
    if path:
        return path
    raise RuntimeError("weasyprint not found. Install Paper Crown's dependencies.")


def discover_tools(*, require_weasyprint: bool = True) -> Tools:
    """Find external build tools on the local machine.

    Args:
        require_weasyprint: When true, resolve WeasyPrint for PDF rendering.
            Static web exports only need Pandoc and obsidian-export, so they
            can pass false and receive an empty ``Tools.weasyprint`` value.

    Raises:
        RuntimeError: If a required command cannot be found.
    """
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError(
            "pandoc not on PATH. Install via `winget install JohnMacFarlane.Pandoc`."
        )
    obsidian_export = shutil.which("obsidian-export")
    if not obsidian_export:
        raise RuntimeError(
            "obsidian-export not on PATH. Install via `cargo install obsidian-export`."
        )
    return Tools(
        pandoc=pandoc,
        obsidian_export=obsidian_export,
        weasyprint=_find_weasyprint() if require_weasyprint else "",
    )


def _run_export_command(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run an obsidian-export command with Windows-safe text decoding."""
    env = os.environ.copy()
    if os.name == "nt":
        env.setdefault("GIO_USE_VFS", "local")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def _contains_obsidian_reference(text: str) -> bool:
    """Return whether raw markdown needs obsidian-export link/embed rewriting."""
    return "[[" in text and "]]" in text


def _source_needs_obsidian_export(source_file: Path) -> bool:
    """Return whether a note contains Obsidian syntax we need to rewrite."""
    try:
        text = source_file.read_text(encoding="utf-8")
    except OSError as error:
        message = f"failed to read source note {source_file}: {error}"
        raise RuntimeError(message) from error
    return _contains_obsidian_reference(text)


def _copy_plain_markdown(source_file: Path, dest: Path) -> Path:
    """Copy a source note that does not require Obsidian link resolution."""
    dest.mkdir(parents=True, exist_ok=True)
    exported = dest / source_file.name
    shutil.copy2(source_file, exported)
    return exported.resolve()


def _export_failure_message(
    source_file: Path,
    result: subprocess.CompletedProcess[str],
) -> str:
    """Return a concise, actionable obsidian-export failure message."""
    stderr = result.stderr or ""
    stdout = result.stdout or ""
    lines = (stderr or stdout).splitlines()
    detail = next((line.strip() for line in lines if line.strip()), "unknown error")
    return (
        f"obsidian-export failed for {source_file}: {detail}. "
        "Fix the referenced note or embed before rebuilding."
    )


def export_vault(tools: Tools, vault_root: Path, dest: Path) -> None:
    """Export an entire Obsidian vault into ``dest``.

    Raises:
        RuntimeError: If obsidian-export exits non-zero.
    """
    dest.mkdir(parents=True, exist_ok=True)
    result = _run_export_command([tools.obsidian_export, str(vault_root), str(dest)])
    if result.returncode != 0:
        stderr = result.stderr or ""
        stdout = result.stdout or ""
        first_lines = (stderr or stdout).splitlines()
        first = first_lines[0] if first_lines else "unknown error"
        raise RuntimeError(
            f"obsidian-export on {vault_root.name} failed: {first}\n"
            f"STDERR (tail):\n{stderr[-500:]}"
        )


def export_source_file(
    tools: Tools,
    source_file: Path,
    dest: Path,
    *,
    log: LogFn | None = None,
) -> Path:
    """Export one markdown note and return the exported markdown file.

    Plain Markdown files are copied directly. Notes that contain Obsidian
    wikilinks or embeds are sent through obsidian-export so those references
    are resolved before assembly.
    """
    dest.mkdir(parents=True, exist_ok=True)
    if not _source_needs_obsidian_export(source_file):
        return _copy_plain_markdown(source_file, dest)

    result = _run_export_command([tools.obsidian_export, str(source_file), str(dest)])
    if result.returncode != 0:
        raise RuntimeError(_export_failure_message(source_file, result))

    expected = dest / source_file.name
    if expected.is_file():
        return expected.resolve()
    exported = sorted(dest.rglob("*.md"))
    if exported:
        return exported[0].resolve()
    raise RuntimeError(f"obsidian-export produced no markdown for {source_file}")


def _referenced_sources(manifest: Manifest) -> set[Path]:
    """Return every source file referenced by the manifest chapter tree."""
    return {
        source.resolve()
        for chapter in manifest.all_chapters()
        for source in chapter.source_files
    }


def _sources_by_vault(
    manifest: Manifest,
    referenced: set[Path],
) -> dict[Path, list[Path]]:
    """Group referenced source files by the vault they live under."""
    vault_sources: dict[Path, list[Path]] = {}
    for source in referenced:
        for vault in manifest.vault_index.vaults:
            try:
                source.relative_to(vault.root)
            except ValueError:
                continue
            vault_sources.setdefault(vault.root, []).append(source)
            break
    return vault_sources


def ensure_exports_fresh(
    tools: Tools,
    manifest: Manifest,
    *,
    log: LogFn | None = None,
    force: bool = False,
) -> dict[Path, Path]:
    """Export referenced vault content and return source-to-exported paths.

    Exports are cached by source-file content, vault roots, and the
    obsidian-export command identity. Only source files referenced by the
    recipe manifest are exported, so unrelated broken notes elsewhere in a
    vault cannot poison a book build.
    """
    cache_dir = manifest.recipe.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    exports_root = cache_dir / "exports"
    referenced = _referenced_sources(manifest)
    fingerprint = _export_fingerprint(tools, manifest, referenced)
    if not force:
        cached = _read_export_cache(cache_dir, fingerprint)
        if cached is not None:
            if log is not None:
                log(f"  obsidian-export: cached ({len(cached)} exported files)")
            return cached

    if exports_root.exists():
        shutil.rmtree(exports_root, ignore_errors=True)
    exports_root.mkdir(parents=True, exist_ok=True)

    vault_sources = _sources_by_vault(manifest, referenced)
    mapping: dict[Path, Path] = {}

    for index, vault in enumerate(manifest.vault_index.vaults):
        sources = sorted(set(vault_sources.get(vault.root, [])), key=lambda p: str(p))
        if not sources:
            if log is not None:
                log(f"  skip: {vault.name} ({vault.root.name}) -- no referenced files")
            continue

        needed = len(sources)
        dest = exports_root / f"vault-{index}-{vault.name}"
        if log is not None:
            log(
                f"  obsidian-export: {vault.name} -> "
                f"{_display_path(dest)}  ({needed} referenced, per-file)"
            )
        for file_index, source in enumerate(sources):
            exported = export_source_file(
                tools,
                source,
                dest / f"file-{file_index}",
                log=log,
            )
            mapping[source.resolve()] = exported

    _write_export_cache(cache_dir, fingerprint, mapping)
    return mapping


def _export_fingerprint(
    tools: Tools,
    manifest: Manifest,
    referenced: set[Path],
) -> str:
    """Return the cache key for the current export inputs."""
    extra: dict[str, JsonValue] = {
        "obsidian_export": tools.obsidian_export,
        "obsidian_export_version": _tool_version(tools.obsidian_export),
        "export_strategy": EXPORT_STRATEGY_VERSION,
        "vaults": [
            {"name": vault.name, "root": str(vault.root)}
            for vault in manifest.vault_index.vaults
        ],
        "overlay": list(manifest.recipe.vault_overlay),
    }
    return fingerprint_files(referenced, extra=extra)


def _tool_version(command: str) -> str:
    """Return a best-effort external tool version string."""
    if not command:
        return ""
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    first_line = (result.stdout or result.stderr or "").splitlines()
    return first_line[0] if first_line else ""


def _read_export_cache(cache_dir: Path, fingerprint: str) -> dict[Path, Path] | None:
    """Return a cached export map when the fingerprint and files still match."""
    state_path = cache_dir / "export-state.json"
    if not state_path.is_file():
        return None
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if (
        raw.get("schema") != CACHE_SCHEMA_VERSION
        or raw.get("fingerprint") != fingerprint
    ):
        return None
    mapping_raw = raw.get("mapping")
    if not isinstance(mapping_raw, list):
        return None
    mapping: dict[Path, Path] = {}
    for item in mapping_raw:
        if not isinstance(item, dict):
            return None
        source_raw = item.get("source")
        exported_raw = item.get("exported")
        if not isinstance(source_raw, str) or not isinstance(exported_raw, str):
            return None
        exported = Path(exported_raw)
        if not exported.is_file():
            return None
        mapping[Path(source_raw).resolve()] = exported.resolve()
    return mapping


def _write_export_cache(
    cache_dir: Path,
    fingerprint: str,
    mapping: dict[Path, Path],
) -> None:
    """Persist the export cache state for a future build."""
    state_path = cache_dir / "export-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, JsonValue] = {
        "schema": CACHE_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "mapping": [
            {"source": str(source.resolve()), "exported": str(exported.resolve())}
            for source, exported in sorted(
                mapping.items(),
                key=lambda item: str(item[0]),
            )
        ],
    }
    state_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _display_path(path: Path) -> str:
    """Return a cwd-relative path when possible for concise logs."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)
