"""Markdown quality checks used by ``papercrown --doctor``."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from papercrown.assembly import markdown as assembly
from papercrown.assembly import ttrpg
from papercrown.media.images import resolve_local_image
from papercrown.project.manifest import Manifest
from papercrown.project.recipe import ChapterSpec, SourceRef
from papercrown.system.diagnostics import Diagnostic, DiagnosticSeverity

# Matches Markdown ATX heading openers for heading-shape linting.
_HEADING_RE = re.compile(r"^(?P<hashes>#{1,6})(?:\s+|$)")
# Matches explicit trailing heading IDs that should remain stable.
_HEADING_ID_RE = re.compile(r"\{[^}]*#(?P<id>[A-Za-z0-9_-]+)[^}]*\}\s*$")
# Matches inline Markdown image references after assembly.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)")
# Text markers that commonly indicate mojibaked recipe source paths.
_MOJIBAKE_MARKERS = ("Γ", "Ç", "�", "Â", "â€")


def lint_manifest_content(
    manifest: Manifest,
    *,
    export_map: dict[Path, Path] | None = None,
) -> list[Diagnostic]:
    """Run non-rendering content checks for a resolved manifest.

    The check operates on the same assembled markdown that Pandoc receives, so
    warnings and errors reflect the final book rather than raw Obsidian source
    syntax that obsidian-export intentionally rewrites.
    """
    diagnostics: list[Diagnostic] = []
    diagnostics.extend(_lint_recipe_source_audit(manifest))
    diagnostics.extend(_lint_source_files(manifest))
    markdown = assembly.assemble_combined_book_markdown(
        manifest.chapters,
        export_map=export_map,
        vault_index=manifest.vault_index,
        include_toc=False,
        include_art=True,
        include_source_markers=True,
    )
    prepared = ttrpg.prepare_book_markdown(
        markdown,
        manifest.recipe,
        include_generated_matter=True,
    )
    diagnostics.extend(prepared.diagnostics)
    markdown = assembly.add_manual_toc(prepared.markdown, manifest.chapters)
    diagnostics.extend(_lint_no_raw_wikilinks(markdown))
    diagnostics.extend(
        _lint_markdown_images(
            markdown,
            search_roots=_content_search_roots(manifest),
        )
    )
    diagnostics.extend(_lint_heading_shape(markdown))
    return diagnostics


def _lint_recipe_source_audit(manifest: Manifest) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    diagnostics.extend(_lint_recipe_source_mojibake(manifest))
    diagnostics.extend(_lint_exact_custom_duplicates(manifest))
    diagnostics.extend(_lint_bypassed_custom_overrides(manifest))
    return diagnostics


def _lint_recipe_source_mojibake(manifest: Manifest) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for source, label, _ in _iter_recipe_sources(manifest.recipe.chapters):
        raw = str(source)
        if not any(marker in raw for marker in _MOJIBAKE_MARKERS):
            continue
        diagnostics.append(
            Diagnostic(
                code="recipe.source-mojibake",
                severity=DiagnosticSeverity.WARNING,
                message=f"recipe source reference looks mojibaked: {raw}",
                path=manifest.recipe.recipe_path,
                hint=f"clean up the filename or source path for {label}",
            )
        )
    return diagnostics


def _lint_exact_custom_duplicates(manifest: Manifest) -> list[Diagnostic]:
    custom_root = _vault_root(manifest, "custom")
    nimble_root = _vault_root(manifest, "nimble")
    if custom_root is None or nimble_root is None:
        return []

    diagnostics: list[Diagnostic] = []
    for custom_file in sorted(custom_root.rglob("*.md")):
        rel = custom_file.relative_to(custom_root)
        original_file = nimble_root / rel
        if not original_file.is_file():
            continue
        try:
            if custom_file.read_bytes() != original_file.read_bytes():
                continue
        except OSError:
            continue
        diagnostics.append(
            Diagnostic(
                code="content.custom-duplicate-exact",
                severity=DiagnosticSeverity.WARNING,
                message=("custom file is byte-identical to the matching original file"),
                path=custom_file,
                hint="delete the custom duplicate or change the recipe to use original",
            )
        )
    return diagnostics


def _lint_bypassed_custom_overrides(manifest: Manifest) -> list[Diagnostic]:
    custom_root = _vault_root(manifest, "custom")
    nimble_root = _vault_root(manifest, "nimble")
    if custom_root is None or nimble_root is None:
        return []

    diagnostics: list[Diagnostic] = []
    for source, label, in_source_reference in _iter_recipe_sources(
        manifest.recipe.chapters
    ):
        if in_source_reference or source.vault != "nimble":
            continue
        custom_file = custom_root / source.path
        original_file = nimble_root / source.path
        if not custom_file.is_file() or not original_file.is_file():
            continue
        try:
            if custom_file.read_bytes() == original_file.read_bytes():
                continue
        except OSError:
            continue
        diagnostics.append(
            Diagnostic(
                code="content.custom-override-bypassed",
                severity=DiagnosticSeverity.WARNING,
                message=(
                    f"{label} uses original text even though changed custom "
                    "content exists"
                ),
                path=manifest.recipe.recipe_path,
                hint=(
                    f"use custom:{source.path} or move this source into a "
                    "reference section"
                ),
            )
        )
    return diagnostics


def _iter_recipe_sources(
    specs: list[ChapterSpec],
    *,
    in_source_reference: bool = False,
) -> Iterator[tuple[SourceRef, str, bool]]:
    for spec in specs:
        label = spec.title or spec.kind
        is_reference = in_source_reference or spec.style == "source-reference"
        if spec.source is not None:
            yield spec.source, label, is_reference
        for item in spec.sources:
            item_label = item.title or label
            yield item.source, item_label, is_reference
        yield from _iter_recipe_sources(
            spec.children,
            in_source_reference=is_reference,
        )


def _vault_root(manifest: Manifest, name: str) -> Path | None:
    vault = manifest.recipe.vault_by_name(name)
    if vault is None:
        return None
    return vault.path


def _lint_source_files(manifest: Manifest) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for chapter in manifest.all_chapters():
        for source in chapter.source_files:
            if not source.is_file():
                diagnostics.append(
                    Diagnostic(
                        code="content.source-missing",
                        severity=DiagnosticSeverity.ERROR,
                        message=f"source file for {chapter.title!r} is missing",
                        path=source,
                    )
                )
                continue
            if source.stat().st_size == 0:
                diagnostics.append(
                    Diagnostic(
                        code="content.source-empty",
                        severity=DiagnosticSeverity.WARNING,
                        message=f"source file for {chapter.title!r} is empty",
                        path=source,
                    )
                )
    return diagnostics


def _lint_no_raw_wikilinks(markdown: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for line_no, line in enumerate(markdown.splitlines(), start=1):
        if "[[" not in line and "]]" not in line:
            continue
        diagnostics.append(
            Diagnostic(
                code="content.raw-wikilink",
                severity=DiagnosticSeverity.ERROR,
                message="assembled markdown still contains an Obsidian wikilink",
                line=line_no,
                hint="check obsidian-export output or add the missing note to a vault",
            )
        )
    return diagnostics


def _lint_markdown_images(
    markdown: str,
    *,
    search_roots: list[Path],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for line_no, line in enumerate(markdown.splitlines(), start=1):
        for match in _MARKDOWN_IMAGE_RE.finditer(line):
            target = _unwrap_target(match.group("target"))
            if match.group("alt") == "":
                diagnostics.append(
                    Diagnostic(
                        code="content.image-alt-empty",
                        severity=DiagnosticSeverity.INFO,
                        message="markdown image has empty alt text",
                        line=line_no,
                    )
                )
            source = resolve_local_image(target, search_roots=search_roots)
            if source is None and not _is_external_or_pandoc_resource(target):
                diagnostics.append(
                    Diagnostic(
                        code="content.image-missing",
                        severity=DiagnosticSeverity.ERROR,
                        message=f"local image reference cannot be resolved: {target}",
                        line=line_no,
                    )
                )
    return diagnostics


def _lint_heading_shape(markdown: str) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    previous_level = 0
    seen_ids: dict[str, int] = {}
    in_code = False
    for line_no, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        match = _HEADING_RE.match(line)
        if match is None:
            continue
        level = len(match.group("hashes"))
        if previous_level and level > previous_level + 1:
            diagnostics.append(
                Diagnostic(
                    code="content.heading-jump",
                    severity=DiagnosticSeverity.INFO,
                    message=f"heading jumps from h{previous_level} to h{level}",
                    line=line_no,
                )
            )
        previous_level = level
        id_match = _HEADING_ID_RE.search(line)
        if id_match is None:
            continue
        heading_id = id_match.group("id")
        first_line = seen_ids.get(heading_id)
        if first_line is not None:
            diagnostics.append(
                Diagnostic(
                    code="content.heading-id-duplicate",
                    severity=DiagnosticSeverity.ERROR,
                    message=(
                        f"duplicate heading id {heading_id!r}; first seen on "
                        f"line {first_line}"
                    ),
                    line=line_no,
                )
            )
        else:
            seen_ids[heading_id] = line_no
    return diagnostics


def _content_search_roots(manifest: Manifest) -> list[Path]:
    roots = [manifest.recipe.art_dir]
    roots.extend(vault.root for vault in manifest.vault_index.vaults)
    roots.extend(
        source.parent
        for chapter in manifest.all_chapters()
        for source in chapter.source_files
    )
    return list(dict.fromkeys(root.resolve() for root in roots if root.exists()))


def _unwrap_target(target: str) -> str:
    stripped = target.strip()
    if stripped.startswith("<") and stripped.endswith(">"):
        return stripped[1:-1]
    return stripped


def _is_external_or_pandoc_resource(target: str) -> bool:
    lowered = target.lower()
    return (
        lowered.startswith("#")
        or lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("data:")
        or lowered.startswith("file:")
        or Path(target).is_absolute()
    )
