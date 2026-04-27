"""Recipe art audit and validation helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from .art_roles import IMAGE_SUFFIXES, ArtAssetClassification, classify_art_path
from .diagnostics import Diagnostic, DiagnosticReport, DiagnosticSeverity
from .manifest import Manifest
from .recipe import ChapterSpec, Recipe


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
    aspect = metadata.width / max(1, metadata.height)
    role = classification.role
    if role in {"filler-wide", "filler-bottom", "filler-page"} and aspect < 1.15:
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
            _reference(recipe, "cover", recipe.cover.art, expected_roles={"cover"})
        )
    if recipe.ornaments.folio_frame:
        refs.append(_reference(recipe, "folio_frame", recipe.ornaments.folio_frame))
    if recipe.ornaments.corner_bracket:
        refs.append(
            _reference(recipe, "corner_bracket", recipe.ornaments.corner_bracket)
        )
    for splash in recipe.splashes:
        refs.append(
            _reference(
                recipe,
                f"splash {splash.id}",
                splash.art,
                expected_roles={"splash"},
            )
        )
    for asset in recipe.fillers.assets:
        expected = _expected_filler_roles(asset.shape)
        refs.append(
            _reference(
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
                    expected_roles=frozenset({"splash"}),
                )
            )
    for chapter in manifest.all_chapters():
        if chapter.art_path is not None:
            refs.append(
                ArtReference(
                    label=f"chapter {chapter.title}",
                    path=chapter.art_path.resolve(),
                    expected_roles=frozenset(
                        {"chapter-header", "chapter-divider", "class-divider", "cover"}
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


def _walk_specs(chapters: list[ChapterSpec]) -> list[ChapterSpec]:
    specs: list[ChapterSpec] = []
    for spec in chapters:
        specs.append(spec)
        specs.extend(_walk_specs(spec.children))
    return specs


def _expected_filler_roles(shape: str) -> set[str]:
    if shape == "spot":
        return {"filler-spot", "spot", "class-opening-spot"}
    if shape == "small-wide":
        return {"filler-wide"}
    if shape == "bottom-band":
        return {"filler-bottom", "filler-page", "faction", "gear", "vista"}
    if shape == "tailpiece":
        return {"ornament-tailpiece"}
    return set()


def _read_metadata(path: Path) -> ArtMetadata | None:
    try:
        with Image.open(path) as image:
            return ArtMetadata(
                width=int(image.size[0]),
                height=int(image.size[1]),
                has_alpha="A" in image.getbands(),
            )
    except (OSError, UnidentifiedImageError):
        return None


def _folder_mismatch(asset: AuditedArtAsset) -> bool:
    expected = asset.classification.expected_folder
    if expected is None:
        return False
    normalized = asset.relative_path.replace("\\", "/").lower()
    expected_prefix = expected.lower().strip("/")
    return not normalized.startswith(f"{expected_prefix}/")


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
    if counts["filler-bottom"] == 0:
        suggestions.append("fillers/bottom/filler-bottom-general-01.png")
    if counts["filler-page"] == 0:
        suggestions.append("fillers/page/filler-page-general-01.png")
    return suggestions
