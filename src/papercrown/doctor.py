"""Preflight diagnostics for recipes, tools, content, and assets."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError

from .art_audit import audit_recipe_art
from .build import missing_fonts
from .content_lint import lint_manifest_content
from .dependencies import native_pdf_runtime_diagnostics
from .diagnostics import Diagnostic, DiagnosticReport, DiagnosticSeverity
from .export import Tools, discover_tools, ensure_exports_fresh
from .images import diagnose_image
from .manifest import Manifest, classify_filler_art_path
from .options import BuildTarget
from .recipe import PAGE_DAMAGE_FAMILIES, PAGE_DAMAGE_SIZES, ChapterSpec, Recipe

LogFn = Callable[[str], None]
_TRANSPARENT_FILLER_SHAPES = {"spot", "small-wide", "plate", "bottom-band"}
_EXPECTED_FILLER_CATEGORIES = {
    "spot": {"filler-spot"},
    "small-wide": {"filler-wide"},
    "plate": {"filler-plate"},
    "bottom-band": {"filler-bottom"},
    "page-finish": {"page-finish"},
    "tailpiece": {"tailpiece"},
}
_OPAQUE_ALPHA = 245
_MIN_VISIBLE_ALPHA = 0
_VISIBLE_ALPHA = 16


@dataclass(frozen=True)
class _AlphaStats:
    """Small alpha/boundary summary for transparent PNG asset QA."""

    width: int
    height: int
    has_alpha: bool
    min_alpha: int
    max_alpha: int
    corner_max_alpha: int
    edge_opaque_ratio: float


def run_doctor(
    recipe: Recipe,
    manifest: Manifest,
    *,
    target: BuildTarget,
    strict: bool,
    log: LogFn | None = None,
) -> DiagnosticReport:
    """Run non-rendering preflight checks and return a diagnostic report.

    Doctor validates external tools, fonts, recipe art references, image
    readability, and assembled content quality. When tools are present it uses
    obsidian-export before content linting so final rendered markdown is checked
    instead of raw Obsidian syntax.
    """
    report = DiagnosticReport()
    _add_manifest_warnings(report, manifest)
    _add_font_diagnostics(report)
    if target is BuildTarget.PDF:
        report.extend(native_pdf_runtime_diagnostics())
    _add_recipe_art_diagnostics(report, recipe)
    report.extend(audit_recipe_art(recipe, manifest).diagnostics.diagnostics)
    _add_manifest_image_diagnostics(report, manifest)
    _add_filler_asset_diagnostics(report, manifest)
    _add_page_wear_asset_diagnostics(report, manifest)

    tools = _discover_tools(report, target=target)
    if tools is None:
        return report

    export_map: dict[Path, Path] = {}
    try:
        if log is not None:
            log("Doctor: exporting referenced vault content...")
        export_map = ensure_exports_fresh(tools, manifest, log=log)
    except RuntimeError as error:
        report.add(
            Diagnostic(
                code="tools.obsidian-export",
                severity=DiagnosticSeverity.ERROR,
                message=str(error).splitlines()[0],
                hint="run the same papercrown build command for full output",
            )
        )

    if export_map:
        report.extend(lint_manifest_content(manifest, export_map=export_map))
    elif not report.errors:
        report.extend(lint_manifest_content(manifest))

    if log is not None:
        log(report.format_text(strict=strict))
    return report


def _discover_tools(report: DiagnosticReport, *, target: BuildTarget) -> Tools | None:
    try:
        return discover_tools(require_weasyprint=target is BuildTarget.PDF)
    except RuntimeError as error:
        report.add(
            Diagnostic(
                code="tools.missing",
                severity=DiagnosticSeverity.ERROR,
                message=str(error),
            )
        )
        return None


def _add_manifest_warnings(report: DiagnosticReport, manifest: Manifest) -> None:
    for warning in manifest.warnings:
        report.add(
            Diagnostic(
                code="manifest.warning",
                severity=DiagnosticSeverity.WARNING,
                message=warning,
            )
        )


def _add_font_diagnostics(report: DiagnosticReport) -> None:
    missing = missing_fonts()
    if not missing:
        return
    report.add(
        Diagnostic(
            code="fonts.missing",
            severity=DiagnosticSeverity.WARNING,
            message=f"{len(missing)} bundled font file(s) are missing",
            hint="reinstall Paper Crown so packaged fonts are present",
        )
    )


def _add_recipe_art_diagnostics(report: DiagnosticReport, recipe: Recipe) -> None:
    for label, art_path in _recipe_art_references(recipe):
        if art_path.is_file():
            continue
        report.add(
            Diagnostic(
                code="recipe.art-missing",
                severity=DiagnosticSeverity.ERROR,
                message=f"{label} art reference does not exist",
                path=art_path,
            )
        )


def _add_manifest_image_diagnostics(
    report: DiagnosticReport,
    manifest: Manifest,
) -> None:
    images: set[Path] = set()
    if manifest.recipe.cover.enabled and manifest.recipe.cover.art:
        images.add((manifest.recipe.art_dir / manifest.recipe.cover.art).resolve())
    for chapter in manifest.all_chapters():
        for candidate in (
            chapter.art_path,
            chapter.spot_art_path,
            chapter.tailpiece_path,
        ):
            if candidate is not None:
                images.add(candidate.resolve())
    for splash in manifest.splashes:
        if splash.art_path is not None:
            images.add(splash.art_path.resolve())
    for image in sorted(images, key=lambda path: str(path)):
        report.extend(diagnose_image(image, code_prefix="image"))


def _add_filler_asset_diagnostics(
    report: DiagnosticReport,
    manifest: Manifest,
) -> None:
    if not manifest.fillers.enabled:
        return
    art_root = manifest.recipe.art_dir.resolve()
    for asset in manifest.fillers.assets:
        report.extend(diagnose_image(asset.art_path, code_prefix="filler-image"))
        classification = classify_filler_art_path(asset.art_path, art_root=art_root)
        expected = _EXPECTED_FILLER_CATEGORIES.get(asset.shape)
        if expected is not None and classification.category not in expected:
            report.add(
                Diagnostic(
                    code="filler.role-prefix",
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        f"filler asset {asset.id!r} uses shape {asset.shape!r} "
                        "but its filename is not in the expected role convention"
                    ),
                    path=asset.art_path,
                    hint=(
                        "use filler-spot-*, filler-wide-*, filler-plate-*, "
                        "filler-bottom-*, page-finish-*, or ornament-tailpiece-*"
                    ),
                )
            )
        if asset.shape in _TRANSPARENT_FILLER_SHAPES:
            _add_transparent_png_diagnostics(
                report,
                asset.art_path,
                code_prefix="filler",
                label=f"filler asset {asset.id!r}",
            )


def _add_page_wear_asset_diagnostics(
    report: DiagnosticReport,
    manifest: Manifest,
) -> None:
    if not manifest.page_damage.enabled:
        return
    for asset in manifest.page_damage.assets:
        report.extend(diagnose_image(asset.art_path, code_prefix="page-wear-image"))
        if asset.family not in PAGE_DAMAGE_FAMILIES:
            report.add(
                Diagnostic(
                    code="page-wear.family",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"unknown page-wear family {asset.family!r}",
                    path=asset.art_path,
                )
            )
        if asset.size not in PAGE_DAMAGE_SIZES:
            report.add(
                Diagnostic(
                    code="page-wear.size",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"unknown page-wear size {asset.size!r}",
                    path=asset.art_path,
                )
            )
        _add_transparent_png_diagnostics(
            report,
            asset.art_path,
            code_prefix="page-wear",
            label=f"page-wear asset {asset.id!r}",
        )


def _add_transparent_png_diagnostics(
    report: DiagnosticReport,
    path: Path,
    *,
    code_prefix: str,
    label: str,
) -> None:
    if path.suffix.lower() != ".png":
        report.add(
            Diagnostic(
                code=f"{code_prefix}.format",
                severity=DiagnosticSeverity.WARNING,
                message=f"{label} should be a transparent PNG",
                path=path,
            )
        )
        return
    stats = _alpha_stats(path)
    if stats is None:
        return
    if min(stats.width, stats.height) < 96:
        report.add(
            Diagnostic(
                code=f"{code_prefix}.dimensions",
                severity=DiagnosticSeverity.WARNING,
                message=(
                    f"{label} has very small dimensions ({stats.width}x{stats.height})"
                ),
                path=path,
            )
        )
    if not stats.has_alpha:
        report.add(
            Diagnostic(
                code=f"{code_prefix}.alpha-missing",
                severity=DiagnosticSeverity.WARNING,
                message=f"{label} has no alpha channel",
                path=path,
            )
        )
        return
    if stats.max_alpha <= _MIN_VISIBLE_ALPHA:
        report.add(
            Diagnostic(
                code=f"{code_prefix}.alpha-empty",
                severity=DiagnosticSeverity.WARNING,
                message=f"{label} is effectively invisible",
                path=path,
            )
        )
    if stats.min_alpha >= _OPAQUE_ALPHA:
        report.add(
            Diagnostic(
                code=f"{code_prefix}.alpha-opaque",
                severity=DiagnosticSeverity.WARNING,
                message=f"{label} has an opaque rectangular backing",
                path=path,
            )
        )
    if stats.corner_max_alpha > _VISIBLE_ALPHA or stats.edge_opaque_ratio > 0.20:
        report.add(
            Diagnostic(
                code=f"{code_prefix}.opaque-boundary",
                severity=DiagnosticSeverity.WARNING,
                message=f"{label} has visible pixels on the canvas boundary",
                path=path,
                hint="leave transparent/feathered outer edges so art blends into paper",
            )
        )


def _alpha_stats(path: Path) -> _AlphaStats | None:
    try:
        with Image.open(path) as image:
            width, height = image.size
            if "A" not in image.getbands():
                return _AlphaStats(
                    width=width,
                    height=height,
                    has_alpha=False,
                    min_alpha=255,
                    max_alpha=255,
                    corner_max_alpha=255,
                    edge_opaque_ratio=1.0,
                )
            alpha = image.getchannel("A")
            extrema = alpha.getextrema() or (0, 0)
            edge_pixels: list[int] = []
            for x in range(width):
                edge_pixels.append(_alpha_value(alpha.getpixel((x, 0))))
                edge_pixels.append(_alpha_value(alpha.getpixel((x, height - 1))))
            for y in range(height):
                edge_pixels.append(_alpha_value(alpha.getpixel((0, y))))
                edge_pixels.append(_alpha_value(alpha.getpixel((width - 1, y))))
            corners = [
                _alpha_value(alpha.getpixel((0, 0))),
                _alpha_value(alpha.getpixel((width - 1, 0))),
                _alpha_value(alpha.getpixel((0, height - 1))),
                _alpha_value(alpha.getpixel((width - 1, height - 1))),
            ]
            opaque_edges = sum(1 for value in edge_pixels if value >= _OPAQUE_ALPHA)
            return _AlphaStats(
                width=width,
                height=height,
                has_alpha=True,
                min_alpha=_alpha_value(extrema[0]),
                max_alpha=_alpha_value(extrema[1]),
                corner_max_alpha=max(corners),
                edge_opaque_ratio=opaque_edges / max(1, len(edge_pixels)),
            )
    except (OSError, UnidentifiedImageError):
        return None


def _alpha_value(value: Any) -> int:
    """Normalize Pillow alpha extrema/pixels into an integer."""
    if isinstance(value, tuple):
        return int(value[0]) if value else 0
    return int(value or 0)


def _recipe_art_references(recipe: Recipe) -> Iterator[tuple[str, Path]]:
    if recipe.cover.enabled and recipe.cover.art:
        yield "cover", (recipe.art_dir / recipe.cover.art).resolve()
    if recipe.ornaments.folio_frame:
        yield "folio_frame", (recipe.art_dir / recipe.ornaments.folio_frame).resolve()
    if recipe.ornaments.corner_bracket:
        yield (
            "corner_bracket",
            (recipe.art_dir / recipe.ornaments.corner_bracket).resolve(),
        )
    for spec in _walk_specs(recipe.chapters):
        if spec.art:
            yield (
                f"chapter {spec.title or spec.kind}",
                (recipe.art_dir / spec.art).resolve(),
            )
        if spec.tailpiece:
            yield (
                f"chapter {spec.title or spec.kind} tailpiece",
                (recipe.art_dir / spec.tailpiece).resolve(),
            )


def _walk_specs(chapters: list[ChapterSpec]) -> Iterator[ChapterSpec]:
    for spec in chapters:
        yield spec
        yield from _walk_specs(spec.children)
