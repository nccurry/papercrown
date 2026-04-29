"""Layout-aware conditional filler art selection.

The filler pass runs after WeasyPrint has laid out normal book HTML once. It
finds zero-height marker slots, measures the remaining page content space, and
chooses deterministic art only when it fits without forcing pagination.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from papercrown.project.manifest import FillerAsset, FillerCatalog

# CSS pixel to inch conversion used for WeasyPrint box measurements.
PX_PER_IN = 96.0
# Clear space reserved above flow filler art.
TOP_SAFETY_IN = 0.12
# Clear space reserved below flow filler art.
BOTTOM_SAFETY_IN = 0.15
# Filler shapes supported by the first auto-placement policy.
V1_SHAPES = {"tailpiece", "spot", "small-wide", "plate", "bottom-band", "page-finish"}
# WeasyPrint page names where filler placement is skipped.
SKIP_PAGE_NAMES = {"cover-page", "divider-page", "digital-divider-page"}
# DOM classes that mark pages where filler placement is skipped.
SKIP_PAGE_CLASSES = {"cover", "toc", "splash-page"}
# Minimum usable gap treated as large enough for prominent filler art.
LARGE_GAP_IN = 2.0
# Minimum usable gap treated as a very large filler opportunity.
HUGE_GAP_IN = 3.0
# Minimum usable gap needed before bottom-band art becomes a good fit.
BOTTOM_BAND_GAP_IN = 3.25
# Minimum usable gap needed before page-finish art becomes a good fit.
PAGE_FINISHER_GAP_IN = 4.75
# Minimum rendered height required for page-finish art candidates.
PAGE_FINISHER_IN = 4.0
# Nominal render height for plate-shaped filler art.
PLATE_IN = 3.25
# Smallest art height worth reporting for medium-gap opportunities.
MIN_MEDIUM_GAP_ART_IN = 0.75
# Minimum gap fill ratio required for medium filler opportunities.
MEDIUM_MIN_FILL_RATIO = 0.45
# Minimum gap fill ratio required for bottom-band opportunities.
BOTTOM_BAND_MIN_FILL_RATIO = 0.50
# Minimum gap fill ratio required for page-finisher opportunities.
PAGE_FINISHER_MIN_FILL_RATIO = 0.60
# Gap threshold where source-boundary slots defer to page finishers.
SOURCE_BOUNDARY_PAGE_FINISHER_SKIP_IN = PAGE_FINISHER_GAP_IN
# Minimum page distance before reusing prominent filler art of the same shape.
PROMINENT_REUSE_PAGE_GAP = {
    "spot": 8,
    "small-wide": 32,
    "plate": 40,
    "bottom-band": 40,
    "page-finish": 56,
}
# Chapter slugs that can receive setting-themed wide filler art.
SETTING_WIDE_CHAPTERS = {"setting-primer", "backgrounds", "for-gms"}
# Chapter slugs that can receive equipment/combat wide filler art.
EQUIPMENT_WIDE_CHAPTERS = {"combat"}
# Slot names that imply frame-context filler art.
FRAME_SLOT_NAMES = {"frame-family-end"}
# Slot names that imply class-context filler art.
CLASS_SLOT_NAMES = {"class-end", "subclass-end"}
# Context aliases mapped to chapter slugs allowed for that art context.
CHAPTER_CONTEXTS = {
    "combat": {"combat"},
    "equipment": {"combat"},
    "gear": {"combat"},
    "languages": {"languages"},
    "language": {"languages"},
    "powers": {"powers"},
    "power": {"powers"},
    "reference": {"quick-reference"},
    "quick": {"quick-reference"},
    "setting": SETTING_WIDE_CHAPTERS,
}
# Context values that are allowed to match any slot or chapter.
GENERAL_FILLER_CONTEXTS = {"general", "generic", "neutral"}
# Normalized synonyms for recipe and filename filler contexts.
CONTEXT_ALIASES = {
    "gear": "equipment",
    "language": "languages",
    "power": "powers",
    "spell": "powers",
    "spells": "powers",
    "quick": "reference",
    "quick-reference": "reference",
    "source-reference": "reference",
}


@dataclass(frozen=True)
class FillerAssetUse:
    """The first selected use of a filler asset in a rendered document."""

    page_number: int
    slot_id: str
    slot_name: str
    chapter_slug: str
    section_title: str | None = None


@dataclass(frozen=True)
class FillerMeasurement:
    """A measured filler slot in a rendered WeasyPrint document."""

    slot_id: str
    slot_name: str
    chapter_slug: str
    page_number: int
    available_in: float
    preferred_asset_id: str | None = None
    section_slug: str | None = None
    section_title: str | None = None
    slot_kind: str | None = None
    context: str | None = None
    slot_y_in: float = 0.0
    content_bottom_in: float = 0.0


@dataclass(frozen=True)
class FillerPlacement:
    """A selected filler asset for one marker slot."""

    slot_id: str
    asset: FillerAsset
    page_number: int = 0
    slot_name: str = ""
    mode: str = "flow"
    render_height_in: float = 0.0
    fill_ratio: float = 1.0
    reused_from: FillerAssetUse | None = None
    chapter_slug: str = ""
    section_title: str | None = None

    def __post_init__(self) -> None:
        """Default old two-argument construction to the asset's nominal height."""
        if self.render_height_in <= 0:
            object.__setattr__(self, "render_height_in", self.asset.height_in)


@dataclass(frozen=True)
class FillerDecision:
    """Selection result for one measured filler slot."""

    measurement: FillerMeasurement
    asset: FillerAsset | None
    reason: str
    render_height_in: float | None = None
    fill_ratio: float | None = None
    reused_from: FillerAssetUse | None = None


@dataclass(frozen=True)
class _Candidate:
    """A fitting candidate with its proposed render size for one gap."""

    asset: FillerAsset
    render_height_in: float
    fill_ratio: float


@dataclass(frozen=True)
class _FillerSelection:
    """Internal selection result with placement metadata."""

    asset: FillerAsset
    render_height_in: float
    fill_ratio: float
    reused_from: FillerAssetUse | None = None


@dataclass(frozen=True)
class MissingFillerOpportunity:
    """A measured slot that needs purpose-built art before it can be filled."""

    context: str
    slot_name: str
    chapter_slug: str
    page_number: int
    available_in: float
    usable_in: float
    recommended_shape: str
    suggested_filename: str
    transparency_note: str
    section_title: str | None = None
    reason: str = ""


def plan_fillers(
    document: object,
    catalog: FillerCatalog,
    *,
    recipe_title: str,
) -> list[FillerPlacement]:
    """Return deterministic filler placements for a rendered WeasyPrint document."""
    if not catalog.enabled:
        return []
    return _plan_filler_decisions(document, catalog, recipe_title=recipe_title)[0]


def measure_slots(document: object) -> list[FillerMeasurement]:
    """Measure every visible-in-layout filler marker in a WeasyPrint document."""
    measurements: list[FillerMeasurement] = []
    pages = getattr(document, "pages", [])
    for page_index, page in enumerate(pages):
        if _should_skip_page(page):
            continue
        seen: set[str] = set()
        page_box = getattr(page, "_page_box", None)
        if page_box is None:
            continue
        for box in page_box.descendants():
            element = getattr(box, "element", None)
            if element is None or "filler-slot" not in _classes(element):
                continue
            slot_id = element.get("id")
            slot_name = element.get("data-slot")
            chapter_slug = element.get("data-chapter")
            if not slot_id or not slot_name or not chapter_slug or slot_id in seen:
                continue
            seen.add(slot_id)
            slot_y = _box_top(box)
            if _has_occupied_content_after(page, slot_y):
                continue
            content_bottom = _page_content_bottom(page)
            occupied_bottom = _lowest_occupied_bottom_before(page, slot_y)
            available_px = max(0.0, content_bottom - max(slot_y, occupied_bottom))
            measurements.append(
                FillerMeasurement(
                    slot_id=slot_id,
                    slot_name=slot_name,
                    chapter_slug=chapter_slug,
                    page_number=page_index + 1,
                    available_in=available_px / PX_PER_IN,
                    preferred_asset_id=element.get("data-preferred-filler"),
                    section_slug=element.get("data-section"),
                    section_title=element.get("data-section-title"),
                    slot_kind=element.get("data-slot-kind"),
                    context=element.get("data-filler-context"),
                    slot_y_in=slot_y / PX_PER_IN,
                    content_bottom_in=content_bottom / PX_PER_IN,
                )
            )
    return measurements


def plan_filler_decisions(
    document: object,
    catalog: FillerCatalog,
    *,
    recipe_title: str,
) -> tuple[list[FillerPlacement], list[FillerDecision]]:
    """Return placements plus per-slot decisions for reports and overlays."""
    if not catalog.enabled:
        return ([], [])
    return _plan_filler_decisions(document, catalog, recipe_title=recipe_title)


def select_filler(
    catalog: FillerCatalog,
    measurement: FillerMeasurement,
    *,
    recipe_title: str,
) -> FillerAsset | None:
    """Choose a deterministic fitting asset for one measured slot."""
    return _select_filler_with_reason(
        catalog,
        measurement,
        recipe_title=recipe_title,
    )[0]


def filler_warnings(placements: list[FillerPlacement]) -> list[str]:
    """Return non-fatal warnings for notable filler placement decisions."""
    warnings: list[str] = []
    for placement in placements:
        if placement.reused_from is None:
            continue
        first = placement.reused_from
        warnings.append(
            "filler warning: reused "
            f"{placement.asset.id} on p{placement.page_number} "
            f"{placement.slot_id}; first used on p{first.page_number} "
            f"{first.slot_id}"
        )
    return warnings


def write_filler_report(
    path: Path,
    document: object,
    catalog: FillerCatalog,
    *,
    recipe_title: str,
) -> None:
    """Write a markdown report describing measured filler decisions."""
    placements, decisions = _plan_filler_decisions(
        document,
        catalog,
        recipe_title=recipe_title,
    )
    placed_slots = {
        (placement.slot_id, placement.page_number) for placement in placements
    }
    warnings = filler_warnings(placements)
    lines = [
        "# Filler Audit",
        "",
        f"- Enabled: {catalog.enabled}",
        f"- Assets in catalog: {len(catalog.assets)}",
        f"- Measured slots: {len(decisions)}",
        f"- Placements: {len(placements)}",
        "",
    ]
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
        lines.append("")
    lines.extend(["## Asset Counts", ""])
    shape_counts: dict[str, int] = {}
    for asset in catalog.assets:
        shape_counts[asset.shape] = shape_counts.get(asset.shape, 0) + 1
    if shape_counts:
        for shape, count in sorted(shape_counts.items()):
            lines.append(f"- {shape}: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Slots", ""])
    if not decisions:
        lines.append("- none measured")
    for decision in decisions:
        measurement = decision.measurement
        selected_asset = decision.asset
        status = (
            "placed"
            if (measurement.slot_id, measurement.page_number) in placed_slots
            else decision.reason
        )
        if selected_asset is None:
            asset_text = "none"
        else:
            render_height = (
                decision.render_height_in
                if decision.render_height_in is not None
                else selected_asset.height_in
            )
            fill_ratio = decision.fill_ratio if decision.fill_ratio is not None else 1.0
            asset_text = (
                f"{selected_asset.id} "
                f"({selected_asset.shape}, nominal={selected_asset.height_in:.2f}in, "
                f"render={render_height:.2f}in, fill={fill_ratio:.0%})"
            )
        reuse_text = ""
        if decision.reused_from is not None:
            first = decision.reused_from
            reuse_text = f"; reused from p{first.page_number} {first.slot_id}"
        section = (
            f", section={measurement.section_title}"
            if measurement.section_title
            else ""
        )
        context = f", context={measurement.context}" if measurement.context else ""
        lines.append(
            "- "
            f"p{measurement.page_number} {measurement.slot_id} "
            f"[{measurement.slot_name}{section}{context}] "
            f"available={measurement.available_in:.2f}in -> "
            f"{asset_text}; {status}{reuse_text}"
        )
    undersized = [
        opportunity
        for opportunity in (
            _missing_art_opportunity(decision, catalog)
            for decision in decisions
            if decision.reason == "no size-matched context asset"
        )
        if opportunity is not None
    ]
    if undersized:
        lines.extend(["", "## Undersized Opportunities", ""])
        for opportunity in undersized:
            lines.append(
                "- "
                f"p{opportunity.page_number} {opportunity.slot_name} "
                f"{opportunity.chapter_slug}: "
                f"available={opportunity.available_in:.2f}in, "
                f"usable={opportunity.usable_in:.2f}in; "
                f"recommended={opportunity.recommended_shape}; "
                f"suggested `{opportunity.suggested_filename}`"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_missing_art_report(
    path: Path,
    document: object,
    catalog: FillerCatalog,
    *,
    recipe_title: str,
) -> None:
    """Write a concise handoff report for unfilled filler opportunities."""
    _, decisions = _plan_filler_decisions(
        document,
        catalog,
        recipe_title=recipe_title,
    )
    raw_opportunities = [
        _missing_art_opportunity(decision, catalog)
        for decision in decisions
        if _is_missing_art_decision(decision)
    ]
    opportunities: list[MissingFillerOpportunity] = [
        opportunity for opportunity in raw_opportunities if opportunity is not None
    ]

    lines = [
        "# Missing Filler Art",
        "",
        f"- Recipe: {recipe_title}",
        f"- Unfilled art-worthy slots: {len(opportunities)}",
        "",
    ]
    if not opportunities:
        lines.append("No missing filler art opportunities were measured.")
    else:
        lines.extend(
            [
                "Generate transparent PNGs into the configured filler art "
                "directory using the suggested filename prefixes below.",
                "",
            ]
        )
        for opportunity in sorted(
            opportunities,
            key=lambda item: (
                item.context,
                item.slot_name,
                item.chapter_slug,
                -item.available_in,
                item.page_number,
            ),
        ):
            section = (
                f" / {opportunity.section_title}"
                if opportunity.section_title
                and opportunity.section_title != opportunity.chapter_slug
                else ""
            )
            lines.append(
                "- "
                f"{opportunity.context} / {opportunity.slot_name}: "
                f"p{opportunity.page_number} {opportunity.chapter_slug}{section}; "
                f"available={opportunity.available_in:.2f}in, "
                f"usable={opportunity.usable_in:.2f}in; "
                f"recommended={opportunity.recommended_shape}; "
                f"suggested `{opportunity.suggested_filename}`; "
                f"{opportunity.transparency_note}"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _plan_filler_decisions(
    document: object,
    catalog: FillerCatalog,
    *,
    recipe_title: str,
) -> tuple[list[FillerPlacement], list[FillerDecision]]:
    by_page_mode: dict[tuple[int, str], tuple[tuple[int, float, int], FillerPlacement]]
    by_page_mode = {}
    decisions: list[FillerDecision] = []
    used_assets: dict[str, FillerAssetUse] = {}
    for index, measurement in enumerate(measure_slots(document)):
        selection, reason = _select_filler_selection(
            catalog,
            measurement,
            recipe_title=recipe_title,
            used_asset_ids=used_assets,
        )
        asset = selection.asset if selection is not None else None
        decisions.append(
            FillerDecision(
                measurement,
                asset,
                reason,
                selection.render_height_in if selection is not None else None,
                selection.fill_ratio if selection is not None else None,
                selection.reused_from if selection is not None else None,
            )
        )
        if selection is None:
            continue
        placement = FillerPlacement(
            slot_id=measurement.slot_id,
            asset=selection.asset,
            page_number=measurement.page_number,
            slot_name=measurement.slot_name,
            mode=_placement_mode(selection.asset),
            render_height_in=selection.render_height_in,
            fill_ratio=selection.fill_ratio,
            reused_from=selection.reused_from,
            chapter_slug=measurement.chapter_slug,
            section_title=measurement.section_title,
        )
        rank = _placement_rank(measurement, placement, index)
        key = (measurement.page_number, placement.mode)
        current = by_page_mode.get(key)
        if current is None or rank < current[0]:
            by_page_mode[key] = (rank, placement)
            used_assets = _placement_use_map(
                [item[1] for item in by_page_mode.values()]
            )
    placements = _finalize_placement_reuse(
        [by_page_mode[key][1] for key in sorted(by_page_mode)]
    )
    placement_by_slot = {
        (placement.slot_id, placement.page_number): placement
        for placement in placements
    }
    revised_decisions: list[FillerDecision] = []
    for decision in decisions:
        key = (decision.measurement.slot_id, decision.measurement.page_number)
        placed = placement_by_slot.get(key)
        if decision.asset is not None and placed is None:
            revised_decisions.append(
                FillerDecision(
                    decision.measurement,
                    decision.asset,
                    "suppressed by page winner",
                    decision.render_height_in,
                    decision.fill_ratio,
                    decision.reused_from,
                )
            )
            continue
        if placed is not None:
            revised_decisions.append(
                FillerDecision(
                    decision.measurement,
                    decision.asset,
                    decision.reason,
                    placed.render_height_in,
                    placed.fill_ratio,
                    placed.reused_from,
                )
            )
            continue
        revised_decisions.append(decision)
    decisions = revised_decisions
    return placements, decisions


def _select_filler_with_reason(
    catalog: FillerCatalog,
    measurement: FillerMeasurement,
    *,
    recipe_title: str,
    used_asset_ids: dict[str, FillerAssetUse] | set[str] | None = None,
) -> tuple[FillerAsset | None, str]:
    selection, reason = _select_filler_selection(
        catalog,
        measurement,
        recipe_title=recipe_title,
        used_asset_ids=used_asset_ids,
    )
    return (selection.asset if selection is not None else None), reason


def _select_filler_selection(
    catalog: FillerCatalog,
    measurement: FillerMeasurement,
    *,
    recipe_title: str,
    used_asset_ids: dict[str, FillerAssetUse] | set[str] | None = None,
) -> tuple[_FillerSelection | None, str]:
    slot = catalog.slots.get(measurement.slot_name)
    if slot is None:
        return None, "slot not configured"
    if measurement.available_in < slot.min_space_in:
        return None, "insufficient space"

    fit_limit = measurement.available_in - TOP_SAFETY_IN - BOTTOM_SAFETY_IN
    usable_in = min(fit_limit, slot.max_space_in)
    if usable_in <= 0 or usable_in < slot.min_space_in:
        return None, "insufficient safety margin"
    if not _slot_has_enough_intervening_content(measurement, usable_in):
        return None, "not enough intervening content"
    fitting_candidates = [
        asset
        for asset in catalog.assets
        if asset.shape in V1_SHAPES
        and _slot_accepts_shape(slot.shapes, asset.shape)
        and asset.height_in <= slot.max_space_in
        and _asset_matches_context(asset, measurement)
    ]
    candidates = [
        _Candidate(
            asset=asset,
            render_height_in=_candidate_render_height_in(asset, usable_in),
            fill_ratio=_candidate_fill_ratio(asset, usable_in),
        )
        for asset in fitting_candidates
        if _candidate_matches_gap_size(asset, usable_in)
    ]
    if not candidates:
        if fitting_candidates:
            return None, "no size-matched context asset"
        return None, "no fitting context-matched asset"
    candidates = _prefer_semantic_context(candidates, measurement)
    unused_candidates = [
        candidate
        for candidate in candidates
        if not _asset_has_prior_use(used_asset_ids, candidate.asset.id)
    ]
    if unused_candidates:
        candidates = unused_candidates
    else:
        reusable_candidates = [
            candidate
            for candidate in candidates
            if _candidate_reuse_allowed(candidate, measurement, used_asset_ids)
        ]
        if not reusable_candidates:
            return None, "matching filler already used recently"
        candidates = reusable_candidates

    seed = (
        f"{recipe_title}|{measurement.chapter_slug}|"
        f"{measurement.section_slug or ''}|"
        f"{measurement.slot_id}|{measurement.page_number}"
    )
    preferred = _preferred_candidates(candidates, usable_in)
    for candidate in preferred:
        if candidate.asset.id == measurement.preferred_asset_id:
            return (
                _selection_for_candidate(candidate, used_asset_ids),
                "preferred asset",
            )
    chosen = min(
        preferred,
        key=lambda candidate: (
            -candidate.render_height_in,
            _stable_key(seed, candidate.asset.id),
        ),
    )
    return _selection_for_candidate(chosen, used_asset_ids), "chosen"


def inject_fillers(html: str, placements: list[FillerPlacement]) -> str:
    """Replace empty marker divs in ``html`` with selected filler blocks."""
    out = html
    for placement in placements:
        if placement.mode != "flow":
            continue
        pattern = re.compile(
            r"<div\b(?=[^>]*\bid=\""
            + re.escape(placement.slot_id)
            + r"\")(?=[^>]*\bclass=\"[^\"]*\bfiller-slot\b[^\"]*\")[^>]*>"
            r"\s*</div>",
            re.DOTALL,
        )
        out = pattern.sub(_render_filler_block(placement), out, count=1)
    return out


def _render_filler_block(placement: FillerPlacement) -> str:
    asset = placement.asset
    shape_class = f"filler-shape-{asset.shape}"
    return (
        f'<div class="filler-art {shape_class}" '
        f'id="{placement.slot_id}-art" '
        f'data-filler-asset="{asset.id}" '
        f'style="height: {placement.render_height_in:.3f}in;">'
        f'<img class="filler-img" src="{asset.art_path.as_posix()}" alt="" />'
        "</div>"
    )


def _placement_rank(
    measurement: FillerMeasurement,
    placement: FillerPlacement,
    index: int,
) -> tuple[int, float, int]:
    slot_rank = 0 if measurement.slot_name == "chapter-end" else 1
    return (slot_rank, -placement.render_height_in, index)


def _placement_mode(asset: FillerAsset) -> str:
    return "bottom-bleed" if asset.shape == "bottom-band" else "flow"


def _slot_has_enough_intervening_content(
    measurement: FillerMeasurement,
    usable_in: float,
) -> bool:
    """Avoid oversized art after tiny source-boundary sections."""
    if measurement.slot_kind != "source-boundary":
        return True
    if _missing_context(measurement) == "reference":
        return False
    return usable_in < SOURCE_BOUNDARY_PAGE_FINISHER_SKIP_IN


def _slot_accepts_shape(slot_shapes: list[str], asset_shape: str) -> bool:
    """Return whether a slot explicitly allows a shape."""
    return asset_shape in slot_shapes


def _placement_use_map(
    placements: list[FillerPlacement],
) -> dict[str, FillerAssetUse]:
    """Return first-use metadata for the current page-winning placements."""
    uses: dict[str, FillerAssetUse] = {}
    for placement in sorted(placements, key=lambda item: item.page_number):
        uses.setdefault(
            placement.asset.id,
            FillerAssetUse(
                page_number=placement.page_number,
                slot_id=placement.slot_id,
                slot_name=placement.slot_name,
                chapter_slug=placement.chapter_slug,
                section_title=placement.section_title,
            ),
        )
    return uses


def _finalize_placement_reuse(
    placements: list[FillerPlacement],
) -> list[FillerPlacement]:
    """Set reuse metadata from the final, page-winning placements only."""
    uses: dict[str, FillerAssetUse] = {}
    finalized: list[FillerPlacement] = []
    for placement in sorted(placements, key=lambda item: item.page_number):
        first_use = uses.get(placement.asset.id)
        finalized.append(replace(placement, reused_from=first_use))
        uses.setdefault(
            placement.asset.id,
            FillerAssetUse(
                page_number=placement.page_number,
                slot_id=placement.slot_id,
                slot_name=placement.slot_name,
                chapter_slug=placement.chapter_slug,
                section_title=placement.section_title,
            ),
        )
    return finalized


def _asset_has_prior_use(
    used_asset_ids: dict[str, FillerAssetUse] | set[str] | None,
    asset_id: str,
) -> bool:
    return used_asset_ids is not None and asset_id in used_asset_ids


def _prior_asset_use(
    used_asset_ids: dict[str, FillerAssetUse] | set[str] | None,
    asset_id: str,
) -> FillerAssetUse | None:
    if isinstance(used_asset_ids, dict):
        return used_asset_ids.get(asset_id)
    return None


def _candidate_reuse_allowed(
    candidate: _Candidate,
    measurement: FillerMeasurement,
    used_asset_ids: dict[str, FillerAssetUse] | set[str] | None,
) -> bool:
    prior = _prior_asset_use(used_asset_ids, candidate.asset.id)
    if prior is None:
        return True
    group = _candidate_group(candidate.asset)
    if group == "tailpiece":
        return True
    if _missing_context(measurement) == "reference":
        return False
    minimum_gap = PROMINENT_REUSE_PAGE_GAP.get(group, 24)
    return measurement.page_number - prior.page_number >= minimum_gap


def _selection_for_candidate(
    candidate: _Candidate,
    used_asset_ids: dict[str, FillerAssetUse] | set[str] | None,
) -> _FillerSelection:
    return _FillerSelection(
        asset=candidate.asset,
        render_height_in=candidate.render_height_in,
        fill_ratio=candidate.fill_ratio,
        reused_from=_prior_asset_use(used_asset_ids, candidate.asset.id),
    )


def _candidate_render_height_in(asset: FillerAsset, usable_in: float) -> float:
    """Return the selected display height without upscaling the asset."""
    return min(asset.height_in, usable_in)


def _candidate_fill_ratio(asset: FillerAsset, usable_in: float) -> float:
    if usable_in <= 0:
        return 0.0
    return _candidate_render_height_in(asset, usable_in) / usable_in


def _candidate_matches_gap_size(asset: FillerAsset, usable_in: float) -> bool:
    """Keep filler art in the gap size tier it was composed to occupy."""
    group = _candidate_group(asset)
    if (
        group == "page-finish"
        and _candidate_render_height_in(asset, usable_in) < PAGE_FINISHER_IN
    ):
        return False
    if _candidate_fill_ratio(asset, usable_in) < _minimum_fill_ratio(usable_in):
        return False
    if usable_in >= PAGE_FINISHER_GAP_IN:
        return group in {"page-finish", "plate", "bottom-band"}
    if usable_in >= BOTTOM_BAND_GAP_IN:
        return group in {"plate", "bottom-band", "page-finish"}
    if usable_in >= LARGE_GAP_IN:
        return group in {"spot", "small-wide", "plate", "bottom-band", "page-finish"}
    return group in {
        "tailpiece",
        "spot",
        "small-wide",
        "plate",
        "bottom-band",
        "page-finish",
    }


def _minimum_fill_ratio(usable_in: float) -> float:
    if usable_in >= PAGE_FINISHER_GAP_IN:
        return PAGE_FINISHER_MIN_FILL_RATIO
    if usable_in >= BOTTOM_BAND_GAP_IN:
        return BOTTOM_BAND_MIN_FILL_RATIO
    if usable_in >= LARGE_GAP_IN:
        return MEDIUM_MIN_FILL_RATIO
    return 0.0


def _is_missing_art_decision(decision: FillerDecision) -> bool:
    if decision.asset is not None:
        return False
    return decision.reason in {
        "no fitting context-matched asset",
        "no size-matched context asset",
    }


def _missing_art_opportunity(
    decision: FillerDecision,
    catalog: FillerCatalog,
) -> MissingFillerOpportunity | None:
    measurement = decision.measurement
    usable = max(0.0, measurement.available_in - TOP_SAFETY_IN - BOTTOM_SAFETY_IN)
    if usable <= 0:
        return None
    shape, prefix, note = _recommended_missing_shape(measurement, catalog, usable)
    context = _missing_context(measurement)
    subject = _slug_part(
        measurement.section_slug or measurement.chapter_slug or measurement.slot_id
    )
    suggested_filename = f"{prefix}-{context}-{subject}-01.png"
    return MissingFillerOpportunity(
        context=context,
        slot_name=measurement.slot_name,
        chapter_slug=measurement.chapter_slug,
        page_number=measurement.page_number,
        available_in=measurement.available_in,
        usable_in=usable,
        recommended_shape=shape,
        suggested_filename=suggested_filename,
        transparency_note=note,
        section_title=measurement.section_title,
        reason=decision.reason,
    )


def _recommended_missing_shape(
    measurement: FillerMeasurement,
    catalog: FillerCatalog,
    usable_in: float,
) -> tuple[str, str, str]:
    slot = catalog.slots.get(measurement.slot_name)
    if slot is not None and slot.shapes == ["bottom-band"]:
        return (
            "bottom-band art",
            "filler-bottom",
            "transparent or softly fading top edge, stamped from the page bottom",
        )
    if usable_in < 2.0:
        return (
            "spot/object filler",
            "filler-spot",
            "transparent background, soft edge falloff, no rectangular backing",
        )
    if usable_in < BOTTOM_BAND_GAP_IN:
        return (
            "wide transparent filler",
            "filler-wide",
            "transparent background, low visual mass, no hard canvas edge",
        )
    if usable_in < PAGE_FINISHER_GAP_IN:
        return (
            "plate filler",
            "filler-plate",
            "transparent or softly feathered edges, composed for a half-page gap",
        )
    return (
        "page-finish art",
        "page-finish",
        "transparent/feathered top edge, composed for mostly empty trailing pages",
    )


def _missing_context(measurement: FillerMeasurement) -> str:
    explicit = _normalize_context(measurement.context)
    if explicit is not None:
        return explicit
    slot_name = measurement.slot_name
    chapter = measurement.chapter_slug.lower()
    if slot_name in FRAME_SLOT_NAMES or chapter == "frames":
        return "frame"
    if slot_name in CLASS_SLOT_NAMES:
        return "class"
    if chapter in {"combat", "gear", "equipment"}:
        return "combat"
    if chapter in {"powers", "spells", "spellcasting"}:
        return "powers"
    if chapter in {"languages", "language"}:
        return "languages"
    if chapter in {"quick-reference", "reference"} or chapter.startswith("original-"):
        return "reference"
    if chapter in SETTING_WIDE_CHAPTERS:
        return "setting"
    return "general"


def _slug_part(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.lower().strip())
    return slug.strip("-") or "slot"


def _asset_matches_context(
    asset: FillerAsset,
    measurement: FillerMeasurement,
) -> bool:
    """Keep heuristic wide art in chapters where the filename context fits."""
    stem = asset.art_path.stem.lower()
    chapter = measurement.chapter_slug.lower()
    requested_context = _normalize_context(measurement.context)
    if (
        stem.startswith("filler-spot-")
        or stem.startswith("filler-wide-")
        or stem.startswith("filler-plate-")
        or stem.startswith("filler-bottom-")
        or stem.startswith("page-finish-")
    ):
        return _named_filler_matches_context(stem, measurement)
    if stem.startswith("faction-"):
        return (
            requested_context in {None, "setting"} and chapter in SETTING_WIDE_CHAPTERS
        )
    if stem.startswith("gear-"):
        return (
            requested_context in {None, "combat", "equipment"}
            and chapter in EQUIPMENT_WIDE_CHAPTERS
        )
    if stem.startswith("vista-"):
        return (
            requested_context in {None, "setting"} and chapter in SETTING_WIDE_CHAPTERS
        )
    return True


def _named_filler_matches_context(
    stem: str,
    measurement: FillerMeasurement,
) -> bool:
    """Restrict purpose-named filler art to matching layout contexts."""
    context = _normalize_context(_named_filler_context(stem))
    if context is None or context in GENERAL_FILLER_CONTEXTS:
        return True
    requested_context = _normalize_context(measurement.context)
    if requested_context is not None:
        return context == requested_context
    if context == "frame":
        return measurement.slot_name in FRAME_SLOT_NAMES
    if context == "class":
        return measurement.slot_name in CLASS_SLOT_NAMES
    chapter = measurement.chapter_slug.lower()
    allowed_chapters = CHAPTER_CONTEXTS.get(context)
    if allowed_chapters is not None:
        return chapter in allowed_chapters
    return True


def _named_filler_context(stem: str) -> str | None:
    for prefix in (
        "filler-spot-",
        "filler-wide-",
        "filler-plate-",
        "filler-bottom-",
        "page-finish-",
    ):
        if stem.startswith(prefix):
            remainder = stem.removeprefix(prefix)
            return remainder.split("-", 1)[0] if remainder else None
    return None


def _prefer_semantic_context(
    candidates: list[_Candidate],
    measurement: FillerMeasurement,
) -> list[_Candidate]:
    requested_context = _normalize_context(measurement.context)
    if requested_context is None:
        return candidates
    exact = [
        candidate
        for candidate in candidates
        if _normalize_context(_asset_filler_context(candidate.asset))
        == requested_context
    ]
    return exact or candidates


def _asset_filler_context(asset: FillerAsset) -> str | None:
    stem = asset.art_path.stem.lower()
    return _named_filler_context(stem)


def _normalize_context(context: str | None) -> str | None:
    if context is None:
        return None
    normalized = context.lower().strip()
    if not normalized:
        return None
    return CONTEXT_ALIASES.get(normalized, normalized)


def _preferred_candidates(
    candidates: list[_Candidate],
    usable_in: float,
) -> list[_Candidate]:
    """Pick a tasteful size tier before choosing a concrete deterministic asset."""
    for group in _preferred_groups(usable_in):
        grouped = [
            candidate
            for candidate in candidates
            if _candidate_group(candidate.asset) == group
        ]
        if grouped:
            return grouped
    return candidates


def _preferred_groups(usable_in: float) -> list[str]:
    if usable_in < LARGE_GAP_IN:
        return ["tailpiece", "spot", "small-wide", "plate", "bottom-band"]
    if usable_in < BOTTOM_BAND_GAP_IN:
        return ["spot", "small-wide", "plate", "bottom-band", "page-finish"]
    if usable_in < PAGE_FINISHER_GAP_IN:
        return ["plate", "bottom-band", "page-finish", "small-wide", "spot"]
    return ["page-finish", "plate", "bottom-band", "small-wide", "spot"]


def _candidate_group(asset: FillerAsset) -> str:
    if asset.shape == "tailpiece":
        return "tailpiece"
    if asset.shape == "spot":
        return "spot"
    if asset.shape == "small-wide":
        return "small-wide"
    if asset.shape == "plate":
        return "plate"
    if asset.shape == "page-finish":
        return "page-finish"
    return "bottom-band"


def _should_skip_page(page: object) -> bool:
    page_box = getattr(page, "_page_box", None)
    if page_box is None:
        return True
    page_type = getattr(page_box, "page_type", None)
    if getattr(page_type, "name", "") in SKIP_PAGE_NAMES:
        return True
    for box in page_box.descendants():
        element = getattr(box, "element", None)
        if element is not None and _classes(element) & SKIP_PAGE_CLASSES:
            return True
    return False


def _lowest_occupied_bottom_before(page: object, slot_y: float) -> float:
    page_box = getattr(page, "_page_box", None)
    if page_box is None:
        return 0.0
    lowest = _page_content_top(page)
    for box in page_box.descendants():
        element = getattr(box, "element", None)
        if element is None:
            continue
        if "filler-slot" in _classes(element):
            continue
        if getattr(box, "element_tag", None) in {"html", "body"}:
            continue
        bottom = _box_bottom(box)
        if bottom <= slot_y + 0.5:
            lowest = max(lowest, bottom)
    return lowest


def _has_occupied_content_after(page: object, slot_y: float) -> bool:
    page_box = getattr(page, "_page_box", None)
    if page_box is None:
        return False
    for box in page_box.descendants():
        element = getattr(box, "element", None)
        if element is None:
            continue
        if "filler-slot" in _classes(element):
            continue
        if getattr(box, "element_tag", None) in {"html", "body"}:
            continue
        top = _box_top(box)
        bottom = _box_bottom(box)
        if bottom <= top + 0.5:
            continue
        if top >= slot_y - 0.5 and bottom > slot_y + 0.5:
            return True
    return False


def _classes(element: Any) -> set[str]:
    raw = element.get("class") or ""
    return set(str(raw).split())


def _box_top(box: object) -> float:
    return float(getattr(box, "position_y", 0.0))


def _box_bottom(box: object) -> float:
    margin_height = getattr(box, "margin_height", None)
    height = margin_height() if callable(margin_height) else getattr(box, "height", 0.0)
    return _box_top(box) + float(height or 0.0)


def _page_content_top(page: object) -> float:
    page_box = getattr(page, "_page_box", None)
    if page_box is None:
        return 0.0
    return float(getattr(page_box, "margin_top", 0.0))


def _page_content_bottom(page: object) -> float:
    page_box = getattr(page, "_page_box", None)
    if page_box is None:
        return 0.0
    return float(getattr(page_box, "margin_top", 0.0)) + float(
        getattr(page_box, "height", 0.0)
    )


def _stable_key(seed: str, asset_id: str) -> str:
    return hashlib.sha256(f"{seed}|{asset_id}".encode()).hexdigest()
