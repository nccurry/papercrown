"""Recipe art audit and validation helpers."""

from __future__ import annotations

import hashlib
import html as html_lib
import math
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageChops, UnidentifiedImageError

from papercrown.art.roles import (
    IMAGE_SUFFIXES,
    ArtAssetClassification,
    classify_art_path,
)
from papercrown.project.manifest import Manifest
from papercrown.project.recipe import ChapterSpec, Recipe
from papercrown.system.diagnostics import (
    Diagnostic,
    DiagnosticReport,
    DiagnosticSeverity,
)

# Page paper color used as the baseline for visibility and background matching.
PAPER_RGB = (0xFB, 0xFA, 0xF8)
# Minimum grayscale difference from PAPER_RGB for a pixel to count as visible art.
VISIBLE_DIFF_THRESHOLD = 14
# Minimum alpha for a non-paper pixel to count toward visible-content bounds.
VISIBLE_ALPHA_THRESHOLD = 24
# Minimum alpha for an edge pixel to count toward opaque background checks.
OPAQUE_ALPHA_THRESHOLD = 180
# Maximum average edge color distance from PAPER_RGB before blend roles warn.
BACKGROUND_EDGE_DISTANCE_THRESHOLD = 30.0
# Minimum opaque perimeter fraction required before checking edge color mismatch.
BACKGROUND_EDGE_FRACTION_THRESHOLD = 0.25
# Print resolution target used to derive minimum pixel dimensions from role size.
PRINT_DPI = 300
# Minimum top margin required for bottom-band art so it does not crowd text above.
BOTTOM_BAND_TOP_SAFETY_FRACTION = 0.12
# Filler shapes that live in normal text flow and should not mix with bottom-band.
FLOW_FILLER_SLOT_SHAPES = {"tailpiece", "spot", "small-wide", "plate", "page-finish"}
# Per role minimum visible width, height, and bounding-box area fractions.
SPARSE_ROLE_THRESHOLDS: dict[str, tuple[float, float, float]] = {
    "filler-wide": (0.62, 0.30, 0.10),
    "filler-plate": (0.58, 0.34, 0.14),
    "filler-bottom": (0.48, 0.25, 0.10),
    "page-finish": (0.58, 0.38, 0.18),
}
# Roles whose important visible content should stay clear of trim and gutter edges.
SAFE_ZONE_ROLES = {
    "cover",
    "cover-front",
    "cover-back",
    "spread",
    "splash",
    "page-finish",
}
# Roles that should render sharply without page illustration blend/filter effects.
CRISP_RENDERING_ROLES = {"diagram", "screenshot", "map", "logo", "icon"}
# Roles expected to visually blend into the paper background at their edges.
PAGE_BLEND_ROLES = {
    "class-opening-spot",
    "filler-bottom",
    "filler-plate",
    "page-finish",
    "filler-spot",
    "filler-wide",
    "gear",
    "item",
    "npc",
    "ornament-break",
    "ornament-corner",
    "ornament-folio",
    "ornament-headpiece",
    "ornament-tailpiece",
    "portrait",
    "spot",
}


@dataclass(frozen=True)
class ArtReference:
    """One recipe or manifest reference to an art file."""

    label: str
    path: Path
    expected_roles: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ArtMetadata:
    """Basic image metadata needed by art diagnostics."""

    width: int
    height: int
    has_alpha: bool
    sha256: str
    visible_width_fraction: float = 1.0
    visible_height_fraction: float = 1.0
    visible_area_fraction: float = 1.0
    edge_distance: float = 0.0
    opaque_edge_fraction: float = 0.0
    visible_edge_margin_fraction: float = 1.0
    visible_top_margin_fraction: float = 1.0
    visible_bottom_margin_fraction: float = 1.0


@dataclass(frozen=True)
class AuditedArtAsset:
    """One discovered art asset and its role classification."""

    path: Path
    relative_path: str
    classification: ArtAssetClassification
    metadata: ArtMetadata | None = None


@dataclass
class ArtAuditResult:
    """All data emitted by a recipe art audit."""

    art_root: Path
    assets: list[AuditedArtAsset] = field(default_factory=list)
    references: list[ArtReference] = field(default_factory=list)
    diagnostics: DiagnosticReport = field(default_factory=DiagnosticReport)
    suggestions: list[str] = field(default_factory=list)

    @property
    def role_counts(self) -> Counter[str]:
        """Return counts of discovered assets by classified role."""
        return Counter(asset.classification.role for asset in self.assets)

    @property
    def unclassified(self) -> list[AuditedArtAsset]:
        """Return discovered assets that did not match the art contract."""
        return [
            asset
            for asset in self.assets
            if asset.classification.role == "unclassified"
        ]

    def exit_code(self, *, strict: bool) -> int:
        """Return a CLI exit code for this audit."""
        return self.diagnostics.exit_code(strict=strict)


def audit_recipe_art(
    recipe: Recipe,
    manifest: Manifest,
    *,
    include_unclassified: bool = True,
) -> ArtAuditResult:
    """Audit a recipe's art root, references, and image metadata."""
    art_root = recipe.art_dir.resolve()
    result = ArtAuditResult(art_root=art_root)
    result.references.extend(_recipe_art_references(recipe))
    result.references.extend(_manifest_art_references(manifest))
    _add_filler_slot_policy_diagnostics(result, recipe)
    _add_reference_diagnostics(result)
    if art_root.is_dir():
        result.assets.extend(_discover_art_assets(art_root))
        _add_asset_diagnostics(result, include_unclassified=include_unclassified)
    elif result.references or recipe.fillers.enabled or recipe.page_damage.enabled:
        result.diagnostics.add(
            Diagnostic(
                code="art.root-missing",
                severity=DiagnosticSeverity.ERROR,
                message="recipe art_dir does not exist",
                path=art_root,
            )
        )
    result.suggestions.extend(_missing_filler_suggestions(result.role_counts))
    return result


def format_art_audit_text(result: ArtAuditResult) -> str:
    """Render an art audit result as plain text."""
    lines = ["papercrown art audit", f"  art root: {result.art_root}"]
    counts = result.role_counts
    recognized = sum(
        count
        for role, count in counts.items()
        if role not in {"unclassified", "excluded"}
    )
    lines.append(f"  assets: {len(result.assets)} discovered, {recognized} recognized")
    if counts:
        lines.append("  role counts:")
        for role, count in sorted(counts.items()):
            lines.append(f"    {role}: {count}")
    if result.unclassified:
        lines.append(f"  unclassified ({len(result.unclassified)}):")
        for asset in result.unclassified[:20]:
            lines.append(f"    {asset.relative_path}")
        omitted = len(result.unclassified) - 20
        if omitted > 0:
            lines.append(f"    ... {omitted} more")
    if result.references:
        reference_count = len(_dedupe_references(result.references))
        lines.append(f"  references checked: {reference_count}")
    lines.extend(_format_diagnostics(result.diagnostics))
    if result.suggestions:
        lines.append("  suggested missing filler filenames:")
        for suggestion in result.suggestions:
            lines.append(f"    {suggestion}")
    return "\n".join(lines)


def format_art_audit_markdown(result: ArtAuditResult) -> str:
    """Render an art audit result as Markdown."""
    lines = [
        "# Paper Crown Art Audit",
        "",
        f"- Art root: `{result.art_root}`",
        f"- Assets discovered: **{len(result.assets)}**",
        f"- References checked: **{len(_dedupe_references(result.references))}**",
        "",
        "## Role Counts",
        "",
    ]
    for role, count in sorted(result.role_counts.items()):
        lines.append(f"- `{role}`: {count}")
    if result.unclassified:
        lines.extend(["", "## Unclassified", ""])
        for asset in result.unclassified[:50]:
            lines.append(f"- `{asset.relative_path}`")
    if result.diagnostics.diagnostics:
        lines.extend(["", "## Diagnostics", ""])
        for diagnostic in result.diagnostics.diagnostics:
            location = diagnostic.location()
            suffix = f" (`{location}`)" if location else ""
            lines.append(
                f"- **{diagnostic.severity.value}** `{diagnostic.code}`: "
                f"{diagnostic.message}{suffix}"
            )
    if result.suggestions:
        lines.extend(["", "## Suggested Missing Filler Filenames", ""])
        for suggestion in result.suggestions:
            lines.append(f"- `{suggestion}`")
    return "\n".join(lines)


def write_art_contact_sheet(result: ArtAuditResult, path: Path) -> Path:
    """Write an HTML visual inventory grouped by classified art role."""
    diagnostics_by_path: dict[Path, list[Diagnostic]] = {}
    for diagnostic in result.diagnostics.diagnostics:
        if diagnostic.path is None:
            continue
        diagnostics_by_path.setdefault(diagnostic.path.resolve(), []).append(diagnostic)

    lines = [
        "<!doctype html>",
        '<meta charset="utf-8">',
        "<title>Paper Crown Art Contact Sheet</title>",
        "<style>",
        "body{font-family:system-ui,sans-serif;margin:24px;background:#fbfaf8;color:#222}",
        "h1{font-size:22px} h2{margin-top:28px;border-bottom:1px solid #bbb}",
        ".grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(180px,1fr));gap:14px}",
        ".asset{border:1px solid #ccc;background:white;padding:8px}",
        ".thumb{height:120px;display:flex;align-items:center;justify-content:center;background:#f3f0ea}",
        ".thumb img{max-width:100%;max-height:120px;object-fit:contain}",
        ".name{font-size:12px;word-break:break-word;margin-top:6px}",
        ".meta{font-size:11px;color:#555}",
        ".warn{font-size:11px;color:#8a3b00;margin-top:4px}",
        "</style>",
        "<h1>Paper Crown Art Contact Sheet</h1>",
        f"<p>Art root: <code>{html_lib.escape(str(result.art_root))}</code></p>",
    ]
    assets = [
        asset
        for asset in result.assets
        if asset.classification.role not in {"excluded", "unclassified"}
    ]
    by_role: dict[str, list[AuditedArtAsset]] = {}
    for asset in assets:
        by_role.setdefault(asset.classification.role, []).append(asset)
    for role in sorted(by_role):
        role_assets = by_role[role]
        lines.append(f"<h2>{html_lib.escape(role)} ({len(role_assets)})</h2>")
        lines.append('<div class="grid">')
        for asset in role_assets:
            metadata = asset.metadata
            dimensions = (
                f"{metadata.width}x{metadata.height}px"
                if metadata is not None
                else "unreadable"
            )
            warnings = diagnostics_by_path.get(asset.path.resolve(), [])
            image_src = html_lib.escape(asset.path.as_uri(), quote=True)
            lines.extend(
                [
                    '<div class="asset">',
                    f'<div class="thumb"><img src="{image_src}" alt=""></div>',
                    f'<div class="name">{html_lib.escape(asset.relative_path)}</div>',
                    f'<div class="meta">{dimensions}</div>',
                ]
            )
            for diagnostic in warnings[:4]:
                lines.append(
                    '<div class="warn">'
                    f"{html_lib.escape(diagnostic.code)}: "
                    f"{html_lib.escape(diagnostic.message)}"
                    "</div>"
                )
            lines.append("</div>")
        lines.append("</div>")
    if result.unclassified:
        lines.append(f"<h2>unclassified ({len(result.unclassified)})</h2>")
        lines.append("<ul>")
        for asset in result.unclassified:
            lines.append(f"<li>{html_lib.escape(asset.relative_path)}</li>")
        lines.append("</ul>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _discover_art_assets(art_root: Path) -> list[AuditedArtAsset]:
    assets: list[AuditedArtAsset] = []
    for path in sorted(art_root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        resolved = path.resolve()
        relative = _relative_display(resolved, art_root)
        classification = classify_art_path(resolved, art_root=art_root)
        assets.append(
            AuditedArtAsset(
                path=resolved,
                relative_path=relative,
                classification=classification,
                metadata=_read_metadata(resolved),
            )
        )
    return assets


def _add_asset_diagnostics(
    result: ArtAuditResult,
    *,
    include_unclassified: bool,
) -> None:
    for asset in result.assets:
        classification = asset.classification
        if classification.role == "excluded":
            continue
        if classification.role == "unclassified":
            if include_unclassified:
                result.diagnostics.add(
                    Diagnostic(
                        code="art.unclassified",
                        severity=DiagnosticSeverity.WARNING,
                        message="art file does not match a known role",
                        path=asset.path,
                        hint="move or rename it according to the art contract",
                    )
                )
            continue
        if _folder_mismatch(asset):
            result.diagnostics.add(
                Diagnostic(
                    code="art.folder-mismatch",
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        f"{classification.role} art is outside its expected folder "
                        f"{classification.expected_folder!r}"
                    ),
                    path=asset.path,
                )
            )
        if asset.metadata is None:
            result.diagnostics.add(
                Diagnostic(
                    code="art.unreadable",
                    severity=DiagnosticSeverity.ERROR,
                    message="image could not be read",
                    path=asset.path,
                )
            )
            continue
        _add_metadata_diagnostics(result, asset)
    _add_duplicate_diagnostics(result)


def _add_metadata_diagnostics(result: ArtAuditResult, asset: AuditedArtAsset) -> None:
    metadata = asset.metadata
    if metadata is None:
        return
    classification = asset.classification
    if classification.transparent and not metadata.has_alpha:
        result.diagnostics.add(
            Diagnostic(
                code="art.alpha-missing",
                severity=DiagnosticSeverity.WARNING,
                message=f"{classification.role} art is expected to have alpha",
                path=asset.path,
            )
        )
    if min(metadata.width, metadata.height) < 48:
        result.diagnostics.add(
            Diagnostic(
                code="art.dimensions-small",
                severity=DiagnosticSeverity.WARNING,
                message=f"image is very small ({metadata.width}x{metadata.height})",
                path=asset.path,
            )
        )
    _add_print_size_diagnostic(result, asset)
    aspect = metadata.width / max(1, metadata.height)
    role = classification.role
    if (
        role
        in {
            "filler-wide",
            "filler-plate",
            "filler-bottom",
            "page-finish",
        }
        and aspect < 1.15
    ):
        result.diagnostics.add(
            Diagnostic(
                code="art.aspect-mismatch",
                severity=DiagnosticSeverity.WARNING,
                message=f"{role} art should be landscape/wide",
                path=asset.path,
            )
        )
    if role == "filler-spot" and not 0.45 <= aspect <= 2.2:
        result.diagnostics.add(
            Diagnostic(
                code="art.aspect-mismatch",
                severity=DiagnosticSeverity.WARNING,
                message="filler-spot art should be spot-like",
                path=asset.path,
            )
        )
    _add_role_aspect_diagnostic(result, asset)
    _add_safe_zone_diagnostic(result, asset)
    _add_bottom_band_safety_diagnostic(result, asset)
    _add_crisp_rendering_diagnostic(result, asset)
    _add_visible_content_diagnostic(result, asset)
    _add_background_diagnostic(result, asset)


def _add_print_size_diagnostic(result: ArtAuditResult, asset: AuditedArtAsset) -> None:
    metadata = asset.metadata
    if metadata is None:
        return
    classification = asset.classification
    if (
        classification.nominal_width_in is None
        or classification.nominal_height_in is None
    ):
        return
    min_width = int(round(classification.nominal_width_in * PRINT_DPI))
    min_height = int(round(classification.nominal_height_in * PRINT_DPI))
    if metadata.width >= min_width and metadata.height >= min_height:
        return
    result.diagnostics.add(
        Diagnostic(
            code="art.print-size-low",
            severity=DiagnosticSeverity.WARNING,
            message=(
                f"{classification.role} art is below {PRINT_DPI} DPI target "
                f"for {classification.nominal_width_in:.2f}x"
                f"{classification.nominal_height_in:.2f}in "
                f"({metadata.width}x{metadata.height}px, "
                f"target {min_width}x{min_height}px)"
            ),
            path=asset.path,
        )
    )


def _add_role_aspect_diagnostic(
    result: ArtAuditResult,
    asset: AuditedArtAsset,
) -> None:
    metadata = asset.metadata
    classification = asset.classification
    if metadata is None:
        return
    if (
        classification.nominal_width_in is None
        or classification.nominal_height_in is None
    ):
        return
    role = classification.role
    if role in {
        "filler-spot",
        "filler-wide",
        "filler-plate",
        "filler-bottom",
        "page-finish",
    }:
        return
    target = classification.nominal_width_in / classification.nominal_height_in
    aspect = metadata.width / max(1, metadata.height)
    if 0.65 <= aspect / max(0.01, target) <= 1.55:
        return
    result.diagnostics.add(
        Diagnostic(
            code="art.aspect-mismatch",
            severity=DiagnosticSeverity.WARNING,
            message=f"{role} art aspect ratio is far from its nominal role shape",
            path=asset.path,
        )
    )


def _add_safe_zone_diagnostic(result: ArtAuditResult, asset: AuditedArtAsset) -> None:
    metadata = asset.metadata
    if metadata is None:
        return
    role = asset.classification.role
    if role not in SAFE_ZONE_ROLES:
        return
    if metadata.visible_edge_margin_fraction >= 0.035:
        return
    result.diagnostics.add(
        Diagnostic(
            code="art.safe-zone-crowded",
            severity=DiagnosticSeverity.INFO,
            message=f"{role} art has visible content close to trim or gutter edges",
            path=asset.path,
            hint="keep important faces, text, and symbols inside the safe zone",
        )
    )


def _add_bottom_band_safety_diagnostic(
    result: ArtAuditResult,
    asset: AuditedArtAsset,
) -> None:
    metadata = asset.metadata
    if metadata is None or asset.classification.role != "filler-bottom":
        return
    if metadata.visible_top_margin_fraction >= BOTTOM_BAND_TOP_SAFETY_FRACTION:
        return
    result.diagnostics.add(
        Diagnostic(
            code="art.bottom-band-top-crowded",
            severity=DiagnosticSeverity.WARNING,
            message="filler-bottom art has visible content too close to the top edge",
            path=asset.path,
            hint=(
                "bottom-band art is stamped from the physical page bottom; keep "
                "the top edge transparent or softly faded so it does not crowd text"
            ),
        )
    )


def _add_crisp_rendering_diagnostic(
    result: ArtAuditResult,
    asset: AuditedArtAsset,
) -> None:
    role = asset.classification.role
    if role not in CRISP_RENDERING_ROLES:
        return
    result.diagnostics.add(
        Diagnostic(
            code="art.crisp-rendering-role",
            severity=DiagnosticSeverity.INFO,
            message=(
                f"{role} art should render without illustration blend/filter effects"
            ),
            path=asset.path,
            hint="wrap it with the matching art role class when authoring Markdown",
        )
    )


def _add_visible_content_diagnostic(
    result: ArtAuditResult,
    asset: AuditedArtAsset,
) -> None:
    metadata = asset.metadata
    if metadata is None:
        return
    role = asset.classification.role
    thresholds = SPARSE_ROLE_THRESHOLDS.get(role)
    if thresholds is None:
        return
    min_width, min_height, min_area = thresholds
    if (
        metadata.visible_width_fraction >= min_width
        and metadata.visible_height_fraction >= min_height
        and metadata.visible_area_fraction >= min_area
    ):
        return
    result.diagnostics.add(
        Diagnostic(
            code="art.visible-content-small",
            severity=DiagnosticSeverity.WARNING,
            message=(
                f"{role} art has too little visible content for its role "
                f"({metadata.visible_width_fraction:.0%} wide, "
                f"{metadata.visible_height_fraction:.0%} tall)"
            ),
            path=asset.path,
            hint=(
                "move it to unused/to-remove or replace it with art composed "
                "for this slot"
            ),
        )
    )


def _add_background_diagnostic(
    result: ArtAuditResult,
    asset: AuditedArtAsset,
) -> None:
    metadata = asset.metadata
    if metadata is None:
        return
    role = asset.classification.role
    if role not in PAGE_BLEND_ROLES:
        return
    if metadata.opaque_edge_fraction < BACKGROUND_EDGE_FRACTION_THRESHOLD:
        return
    if metadata.edge_distance <= BACKGROUND_EDGE_DISTANCE_THRESHOLD:
        return
    result.diagnostics.add(
        Diagnostic(
            code="art.background-mismatch",
            severity=DiagnosticSeverity.WARNING,
            message=(
                f"{role} art has opaque edges that do not match the paper background"
            ),
            path=asset.path,
            hint=(
                "use transparency or a paper-colored edge so the art blends "
                "into the page"
            ),
        )
    )


def _add_duplicate_diagnostics(result: ArtAuditResult) -> None:
    by_hash_and_role: dict[tuple[str, str], list[AuditedArtAsset]] = {}
    for asset in result.assets:
        if asset.metadata is None:
            continue
        if asset.classification.role in {"excluded", "unclassified"}:
            continue
        key = (asset.metadata.sha256, asset.classification.role)
        by_hash_and_role.setdefault(key, []).append(asset)
    for duplicate_group in by_hash_and_role.values():
        if len(duplicate_group) < 2:
            continue
        kept = duplicate_group[0]
        for duplicate in duplicate_group[1:]:
            result.diagnostics.add(
                Diagnostic(
                    code="art.duplicate-exact",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"exact duplicate of {kept.relative_path}",
                    path=duplicate.path,
                    hint=(
                        "keep the better or referenced copy and move the "
                        "duplicate to unused/to-remove"
                    ),
                )
            )


def _add_filler_slot_policy_diagnostics(
    result: ArtAuditResult,
    recipe: Recipe,
) -> None:
    if not recipe.fillers.enabled:
        return
    for slot in recipe.fillers.slots.values():
        shapes = set(slot.shapes)
        if "bottom-band" not in shapes:
            continue
        flow_shapes = sorted(shapes & FLOW_FILLER_SLOT_SHAPES)
        if not flow_shapes:
            continue
        result.diagnostics.add(
            Diagnostic(
                code="art.filler-slot-mixed-placement",
                severity=DiagnosticSeverity.WARNING,
                message=(
                    f"filler slot {slot.name!r} mixes bottom-band with flow "
                    f"shape(s): {', '.join(flow_shapes)}"
                ),
                path=recipe.recipe_path,
                hint=(
                    "use bottom-band only in a dedicated bottom-bleed slot; use "
                    "spot, small-wide, plate, or page-finish for ordinary gaps"
                ),
            )
        )


def _add_reference_diagnostics(result: ArtAuditResult) -> None:
    seen: set[Path] = set()
    for reference in _dedupe_references(result.references):
        if reference.path in seen:
            continue
        seen.add(reference.path)
        if not reference.path.is_file():
            result.diagnostics.add(
                Diagnostic(
                    code="art.reference-missing",
                    severity=DiagnosticSeverity.ERROR,
                    message=f"{reference.label} art reference does not exist",
                    path=reference.path,
                )
            )
            continue
        if not reference.expected_roles:
            continue
        classification = classify_art_path(reference.path, art_root=result.art_root)
        if classification.role not in reference.expected_roles:
            result.diagnostics.add(
                Diagnostic(
                    code="art.reference-role",
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        f"{reference.label} expects "
                        f"{', '.join(sorted(reference.expected_roles))} art, "
                        f"but filename classifies as {classification.role}"
                    ),
                    path=reference.path,
                )
            )


def _recipe_art_references(recipe: Recipe) -> list[ArtReference]:
    refs: list[ArtReference] = []
    if recipe.cover.enabled and recipe.cover.art:
        refs.append(
            _reference(
                recipe,
                "cover",
                recipe.cover.art,
                expected_roles={"cover-front"},
            )
        )
    if recipe.ornaments.folio_frame:
        refs.append(_reference(recipe, "folio_frame", recipe.ornaments.folio_frame))
    if recipe.ornaments.corner_bracket:
        refs.append(
            _reference(recipe, "corner_bracket", recipe.ornaments.corner_bracket)
        )
    for splash in recipe.splashes:
        expected_roles = _expected_splash_roles(splash.target)
        refs.append(
            _reference(
                recipe,
                f"splash {splash.id}",
                splash.art,
                expected_roles=expected_roles,
            )
        )
    for asset in recipe.fillers.assets:
        expected = _expected_filler_roles(asset.shape)
        refs.append(
            _filler_reference(
                recipe,
                f"filler {asset.id}",
                asset.art,
                expected_roles=expected,
            )
        )
    for spec in _walk_specs(recipe.chapters):
        label = spec.title or spec.kind
        if spec.art:
            refs.append(
                _reference(
                    recipe,
                    f"chapter {label}",
                    spec.art,
                    expected_roles={
                        "chapter-header",
                        "chapter-divider",
                        "class-divider",
                        "cover",
                    },
                )
            )
        if spec.headpiece:
            refs.append(
                _reference(
                    recipe,
                    f"chapter {label} headpiece",
                    spec.headpiece,
                    expected_roles={"ornament-headpiece"},
                )
            )
        if spec.break_ornament:
            refs.append(
                _reference(
                    recipe,
                    f"chapter {label} break ornament",
                    spec.break_ornament,
                    expected_roles={"ornament-break"},
                )
            )
        if spec.tailpiece:
            refs.append(
                _reference(
                    recipe,
                    f"chapter {label} tailpiece",
                    spec.tailpiece,
                    expected_roles={"ornament-tailpiece"},
                )
            )
    return refs


def _manifest_art_references(manifest: Manifest) -> list[ArtReference]:
    refs: list[ArtReference] = []
    for splash in manifest.splashes:
        if splash.art_path is not None:
            refs.append(
                ArtReference(
                    label=f"splash {splash.id}",
                    path=splash.art_path.resolve(),
                    expected_roles=frozenset(_expected_splash_roles(splash.target)),
                )
            )
    for chapter in manifest.all_chapters():
        if chapter.art_path is not None:
            refs.append(
                ArtReference(
                    label=f"chapter {chapter.title}",
                    path=chapter.art_path.resolve(),
                    expected_roles=frozenset(
                        {
                            "chapter-header",
                            "chapter-divider",
                            "class-divider",
                            "cover-front",
                        }
                    ),
                )
            )
        if chapter.spot_art_path is not None:
            refs.append(
                ArtReference(
                    label=f"chapter {chapter.title} class spot",
                    path=chapter.spot_art_path.resolve(),
                    expected_roles=frozenset({"class-opening-spot", "spot"}),
                )
            )
        if chapter.headpiece_path is not None:
            refs.append(
                ArtReference(
                    label=f"chapter {chapter.title} headpiece",
                    path=chapter.headpiece_path.resolve(),
                    expected_roles=frozenset({"ornament-headpiece"}),
                )
            )
        if chapter.break_ornament_path is not None:
            refs.append(
                ArtReference(
                    label=f"chapter {chapter.title} break ornament",
                    path=chapter.break_ornament_path.resolve(),
                    expected_roles=frozenset({"ornament-break"}),
                )
            )
        if chapter.tailpiece_path is not None:
            refs.append(
                ArtReference(
                    label=f"chapter {chapter.title} tailpiece",
                    path=chapter.tailpiece_path.resolve(),
                    expected_roles=frozenset({"ornament-tailpiece"}),
                )
            )
    for asset in manifest.fillers.assets:
        refs.append(
            ArtReference(
                label=f"filler {asset.id}",
                path=asset.art_path.resolve(),
                expected_roles=frozenset(_expected_filler_roles(asset.shape)),
            )
        )
    for page_asset in manifest.page_damage.assets:
        refs.append(
            ArtReference(
                label=f"page-wear {page_asset.id}",
                path=page_asset.art_path.resolve(),
                expected_roles=frozenset({"page-wear"}),
            )
        )
    return refs


def _expected_splash_roles(target: str) -> set[str]:
    if target == "front-cover":
        return {"cover-front"}
    if target == "back-cover":
        return {"cover-back"}
    return {"splash"}


def _reference(
    recipe: Recipe,
    label: str,
    art: str,
    *,
    expected_roles: set[str] | None = None,
) -> ArtReference:
    return ArtReference(
        label=label,
        path=(recipe.art_dir / art).resolve(),
        expected_roles=frozenset(expected_roles or set()),
    )


def _filler_reference(
    recipe: Recipe,
    label: str,
    art: str,
    *,
    expected_roles: set[str] | None = None,
) -> ArtReference:
    root = recipe.art_dir
    if recipe.fillers.art_dir:
        root = root / recipe.fillers.art_dir
    return ArtReference(
        label=label,
        path=(root / art).resolve(),
        expected_roles=frozenset(expected_roles or set()),
    )


def _walk_specs(chapters: list[ChapterSpec]) -> list[ChapterSpec]:
    specs: list[ChapterSpec] = []
    for spec in chapters:
        specs.append(spec)
        specs.extend(_walk_specs(spec.children))
    return specs


def _expected_filler_roles(shape: str) -> set[str]:
    if shape == "spot":
        return {"filler-spot"}
    if shape == "small-wide":
        return {"filler-wide"}
    if shape == "plate":
        return {"filler-plate"}
    if shape == "bottom-band":
        return {"filler-bottom"}
    if shape == "page-finish":
        return {"page-finish"}
    if shape == "tailpiece":
        return {"ornament-tailpiece"}
    return set()


def _read_metadata(path: Path) -> ArtMetadata | None:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as image:
            rgba = image.convert("RGBA")
            (
                visible_width,
                visible_height,
                visible_area,
                edge_margin,
                top_margin,
                bottom_margin,
            ) = _visible_content_metrics(rgba)
            edge_distance, opaque_edge_fraction = _edge_background_metrics(rgba)
            return ArtMetadata(
                width=int(image.size[0]),
                height=int(image.size[1]),
                has_alpha="A" in image.getbands(),
                sha256=digest,
                visible_width_fraction=visible_width,
                visible_height_fraction=visible_height,
                visible_area_fraction=visible_area,
                edge_distance=edge_distance,
                opaque_edge_fraction=opaque_edge_fraction,
                visible_edge_margin_fraction=edge_margin,
                visible_top_margin_fraction=top_margin,
                visible_bottom_margin_fraction=bottom_margin,
            )
    except (OSError, UnidentifiedImageError):
        return None


def _visible_content_metrics(
    image: Image.Image,
) -> tuple[float, float, float, float, float, float]:
    width, height = image.size
    rgb = image.convert("RGB")
    paper = Image.new("RGB", image.size, PAPER_RGB)
    diff = (
        ImageChops.difference(rgb, paper)
        .convert("L")
        .point(lambda value: 255 if value > VISIBLE_DIFF_THRESHOLD else 0)
    )
    alpha_mask = image.getchannel("A").point(
        lambda alpha: 255 if alpha > VISIBLE_ALPHA_THRESHOLD else 0
    )
    visible = ImageChops.multiply(diff, alpha_mask)
    bbox = visible.getbbox()
    if bbox is None:
        return (0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    x0, y0, x1, y1 = bbox
    visible_width = x1 - x0
    visible_height = y1 - y0
    edge_margin = min(x0, y0, width - x1, height - y1) / max(1, min(width, height))
    top_margin = y0 / max(1, height)
    bottom_margin = (height - y1) / max(1, height)
    return (
        visible_width / max(1, width),
        visible_height / max(1, height),
        (visible_width * visible_height) / max(1, width * height),
        edge_margin,
        top_margin,
        bottom_margin,
    )


def _edge_background_metrics(image: Image.Image) -> tuple[float, float]:
    width, height = image.size
    edge_pixels: list[tuple[int, int, int]] = []
    edge_count = max(1, (2 * width) + (2 * height))
    crops = [
        image.crop((0, 0, width, 1)),
        image.crop((0, height - 1, width, height)),
        image.crop((0, 0, 1, height)),
        image.crop((width - 1, 0, width, height)),
    ]
    for crop in crops:
        data = crop.tobytes()
        for offset in range(0, len(data), 4):
            red, green, blue, alpha = data[offset : offset + 4]
            if alpha > OPAQUE_ALPHA_THRESHOLD:
                edge_pixels.append((red, green, blue))
    if not edge_pixels:
        return (0.0, 0.0)
    mean = tuple(
        sum(pixel[channel] for pixel in edge_pixels) / len(edge_pixels)
        for channel in range(3)
    )
    distance = math.sqrt(
        sum((mean[channel] - PAPER_RGB[channel]) ** 2 for channel in range(3))
    )
    return (distance, len(edge_pixels) / edge_count)


def _folder_mismatch(asset: AuditedArtAsset) -> bool:
    expected = asset.classification.expected_folder
    if expected is None:
        return False
    parts = asset.relative_path.replace("\\", "/").lower().split("/")
    dirs = parts[:-1]
    expected_parts = expected.lower().strip("/").split("/")
    return not _contains_part_sequence(dirs, expected_parts)


def _contains_part_sequence(parts: list[str], sequence: list[str]) -> bool:
    if not sequence:
        return True
    if len(parts) < len(sequence):
        return False
    return any(
        parts[index : index + len(sequence)] == sequence
        for index in range(len(parts) - len(sequence) + 1)
    )


def _relative_display(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe_references(references: list[ArtReference]) -> list[ArtReference]:
    deduped: dict[tuple[Path, str], ArtReference] = {}
    for reference in references:
        key = (reference.path.resolve(), ",".join(sorted(reference.expected_roles)))
        deduped.setdefault(key, reference)
    return list(deduped.values())


def _format_diagnostics(report: DiagnosticReport) -> list[str]:
    if not report.diagnostics:
        return ["  diagnostics: OK"]
    return [
        f"  diagnostics: {len(report.errors)} error(s), "
        f"{len(report.warnings)} warning(s), {len(report.infos)} info"
    ]


def _missing_filler_suggestions(counts: Counter[str]) -> list[str]:
    suggestions: list[str] = []
    if counts["filler-spot"] == 0:
        suggestions.append("fillers/spot/filler-spot-general-01.png")
    if counts["filler-wide"] == 0:
        suggestions.append("fillers/wide/filler-wide-general-01.png")
    if counts["filler-plate"] == 0:
        suggestions.append("fillers/plate/filler-plate-general-01.png")
    if counts["filler-bottom"] == 0:
        suggestions.append("fillers/bottom/filler-bottom-general-01.png")
    if counts["page-finish"] == 0:
        suggestions.append("fillers/page-finish/page-finish-general-01.png")
    return suggestions
