"""Layout-aware conditional filler art selection.

The filler pass runs after WeasyPrint has laid out normal book HTML once. It
finds zero-height marker slots, measures the remaining page content space, and
chooses deterministic art only when it fits without forcing pagination.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .manifest import FillerAsset, FillerCatalog

PX_PER_IN = 96.0
TOP_SAFETY_IN = 0.12
BOTTOM_SAFETY_IN = 0.15
V1_SHAPES = {"tailpiece", "spot", "small-wide", "bottom-band"}
SKIP_PAGE_NAMES = {"cover-page", "divider-page", "digital-divider-page"}
SKIP_PAGE_CLASSES = {"cover", "toc", "splash-page"}
LARGE_GAP_IN = 2.0
HUGE_GAP_IN = 3.0
PAGE_FINISHER_IN = 4.0
SETTING_WIDE_CHAPTERS = {"setting-primer", "backgrounds", "for-gms"}
EQUIPMENT_WIDE_CHAPTERS = {"combat"}
FRAME_SLOT_NAMES = {"frame-family-end"}
CLASS_SLOT_NAMES = {"class-end", "subclass-end"}
CHAPTER_CONTEXTS = {
    "combat": {"combat"},
    "gear": {"combat"},
    "languages": {"languages"},
    "language": {"languages"},
    "powers": {"powers"},
    "power": {"powers"},
    "reference": {"quick-reference"},
    "quick": {"quick-reference"},
    "setting": SETTING_WIDE_CHAPTERS,
}
GENERAL_FILLER_CONTEXTS = {"general", "generic", "neutral"}


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


@dataclass(frozen=True)
class FillerPlacement:
    """A selected filler asset for one marker slot."""

    slot_id: str
    asset: FillerAsset
    page_number: int = 0
    slot_name: str = ""
    mode: str = "flow"


@dataclass(frozen=True)
class FillerDecision:
    """Selection result for one measured filler slot."""

    measurement: FillerMeasurement
    asset: FillerAsset | None
    reason: str


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
                )
            )
    return measurements


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
    lines = [
        "# Filler Audit",
        "",
        f"- Enabled: {catalog.enabled}",
        f"- Assets in catalog: {len(catalog.assets)}",
        f"- Measured slots: {len(decisions)}",
        f"- Placements: {len(placements)}",
        "",
        "## Asset Counts",
        "",
    ]
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
            asset_text = (
                f"{selected_asset.id} "
                f"({selected_asset.shape}, {selected_asset.height_in:.2f}in)"
            )
        section = (
            f", section={measurement.section_title}"
            if measurement.section_title
            else ""
        )
        lines.append(
            "- "
            f"p{measurement.page_number} {measurement.slot_id} "
            f"[{measurement.slot_name}{section}] "
            f"available={measurement.available_in:.2f}in -> {asset_text}; {status}"
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
        _missing_art_opportunity(decision)
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
    by_page: dict[int, tuple[tuple[int, float, int], FillerPlacement]] = {}
    decisions: list[FillerDecision] = []
    used_asset_ids: set[str] = set()
    for index, measurement in enumerate(measure_slots(document)):
        asset, reason = _select_filler_with_reason(
            catalog,
            measurement,
            recipe_title=recipe_title,
            used_asset_ids=used_asset_ids,
        )
        decisions.append(FillerDecision(measurement, asset, reason))
        if asset is None:
            continue
        placement = FillerPlacement(
            slot_id=measurement.slot_id,
            asset=asset,
            page_number=measurement.page_number,
            slot_name=measurement.slot_name,
            mode=_placement_mode(asset),
        )
        rank = _placement_rank(measurement, asset, index)
        current = by_page.get(measurement.page_number)
        if current is None or rank < current[0]:
            if current is not None:
                used_asset_ids.discard(current[1].asset.id)
            by_page[measurement.page_number] = (rank, placement)
            used_asset_ids.add(asset.id)
    placements = [by_page[page_number][1] for page_number in sorted(by_page)]
    placed_ids = {placement.slot_id for placement in placements}
    decisions = [
        (
            FillerDecision(
                decision.measurement,
                decision.asset,
                "suppressed by page winner",
            )
            if decision.asset is not None
            and decision.measurement.slot_id not in placed_ids
            else decision
        )
        for decision in decisions
    ]
    return placements, decisions


def _select_filler_with_reason(
    catalog: FillerCatalog,
    measurement: FillerMeasurement,
    *,
    recipe_title: str,
    used_asset_ids: set[str] | None = None,
) -> tuple[FillerAsset | None, str]:
    slot = catalog.slots.get(measurement.slot_name)
    if slot is None:
        return None, "slot not configured"
    if measurement.available_in < slot.min_space_in:
        return None, "insufficient space"

    fit_limit = measurement.available_in - TOP_SAFETY_IN - BOTTOM_SAFETY_IN
    if fit_limit <= 0:
        return None, "insufficient safety margin"
    candidates = [
        asset
        for asset in catalog.assets
        if asset.shape in V1_SHAPES
        and asset.shape in slot.shapes
        and asset.height_in <= slot.max_space_in
        and asset.height_in <= fit_limit
        and _asset_matches_context(asset, measurement)
        and _candidate_is_useful(asset, measurement)
    ]
    if not candidates:
        return None, "no fitting context-matched asset"
    unused_candidates = [
        asset
        for asset in candidates
        if used_asset_ids is None or asset.id not in used_asset_ids
    ]
    if unused_candidates:
        candidates = unused_candidates

    seed = (
        f"{recipe_title}|{measurement.chapter_slug}|"
        f"{measurement.section_slug or ''}|"
        f"{measurement.slot_id}|{measurement.page_number}"
    )
    preferred = _preferred_candidates(candidates, measurement, seed)
    for asset in preferred:
        if asset.id == measurement.preferred_asset_id:
            return asset, "preferred asset"
    return min(preferred, key=lambda asset: _stable_key(seed, asset.id)), "chosen"


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
    shape_class = f"filler-{asset.shape}"
    return (
        f'<div class="filler-art {shape_class}" '
        f'id="{placement.slot_id}-art" '
        f'data-filler-asset="{asset.id}" '
        f'style="height: {asset.height_in:.3f}in;">'
        f'<img class="filler-img" src="{asset.art_path.as_posix()}" alt="" />'
        "</div>"
    )


def _placement_rank(
    measurement: FillerMeasurement,
    asset: FillerAsset,
    index: int,
) -> tuple[int, float, int]:
    slot_rank = 0 if measurement.slot_name == "chapter-end" else 1
    return (slot_rank, -asset.height_in, index)


def _placement_mode(asset: FillerAsset) -> str:
    return "bottom-bleed" if asset.shape == "bottom-band" else "flow"


def _candidate_is_useful(
    asset: FillerAsset,
    measurement: FillerMeasurement,
) -> bool:
    """Reject tiny ornaments when the measured gap needs a real treatment."""
    if measurement.available_in < LARGE_GAP_IN:
        return True
    if asset.shape == "tailpiece":
        return False
    return True


def _is_missing_art_decision(decision: FillerDecision) -> bool:
    if decision.asset is not None:
        return False
    return decision.reason == "no fitting context-matched asset"


def _missing_art_opportunity(
    decision: FillerDecision,
) -> MissingFillerOpportunity | None:
    measurement = decision.measurement
    usable = max(0.0, measurement.available_in - TOP_SAFETY_IN - BOTTOM_SAFETY_IN)
    if usable <= 0:
        return None
    shape, prefix, note = _recommended_missing_shape(usable)
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


def _recommended_missing_shape(usable_in: float) -> tuple[str, str, str]:
    if usable_in < 2.0:
        return (
            "spot/object filler",
            "filler-spot",
            "transparent background, soft edge falloff, no rectangular backing",
        )
    if usable_in < 3.25:
        return (
            "wide transparent filler",
            "filler-wide",
            "transparent background, low visual mass, no hard canvas edge",
        )
    if usable_in < 5.25:
        return (
            "bottom-band filler",
            "filler-bottom",
            "transparent or feathered top edge, safe for bottom-page placement",
        )
    return (
        "page-finisher filler",
        "filler-page",
        "transparent/feathered top edge, composed for mostly empty trailing pages",
    )


def _missing_context(measurement: FillerMeasurement) -> str:
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
    if (
        stem.startswith("filler-spot-")
        or stem.startswith("filler-wide-")
        or stem.startswith("filler-bottom-")
        or stem.startswith("filler-page-")
    ):
        return _named_filler_matches_context(stem, measurement)
    if stem.startswith("faction-"):
        return chapter in SETTING_WIDE_CHAPTERS
    if stem.startswith("gear-"):
        return chapter in EQUIPMENT_WIDE_CHAPTERS
    if stem.startswith("vista-"):
        return chapter in SETTING_WIDE_CHAPTERS
    return True


def _named_filler_matches_context(
    stem: str,
    measurement: FillerMeasurement,
) -> bool:
    """Restrict purpose-named filler art to matching layout contexts."""
    context = _named_filler_context(stem)
    if context is None or context in GENERAL_FILLER_CONTEXTS:
        return True
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
        "filler-bottom-",
        "filler-page-",
    ):
        if stem.startswith(prefix):
            remainder = stem.removeprefix(prefix)
            return remainder.split("-", 1)[0] if remainder else None
    return None


def _preferred_candidates(
    candidates: list[FillerAsset],
    measurement: FillerMeasurement,
    seed: str,
) -> list[FillerAsset]:
    """Pick a tasteful size tier before choosing a concrete deterministic asset."""
    for group in _preferred_groups(measurement, seed):
        grouped = [asset for asset in candidates if _candidate_group(asset) == group]
        if grouped:
            return grouped
    return candidates


def _preferred_groups(measurement: FillerMeasurement, seed: str) -> list[str]:
    available = measurement.available_in
    roll = _stable_unit(seed, "filler-size")
    if available < LARGE_GAP_IN:
        return ["tailpiece", "spot", "small-wide", "bottom-band"]
    if available < 3.25:
        return ["spot", "small-wide", "bottom-band"]
    if available < 5.25:
        if measurement.slot_name in FRAME_SLOT_NAMES:
            return (
                ["small-wide", "spot", "bottom-band", "page-finish"]
                if roll < 0.30
                else ["bottom-band", "small-wide", "spot", "page-finish"]
            )
        return (
            ["small-wide", "spot", "bottom-band", "page-finish"]
            if roll < 0.55
            else ["bottom-band", "small-wide", "spot", "page-finish"]
        )
    if roll < 0.35:
        return ["page-finish", "bottom-band", "small-wide", "spot"]
    if roll < 0.70:
        return ["bottom-band", "page-finish", "small-wide", "spot"]
    return ["small-wide", "spot", "bottom-band", "page-finish"]


def _candidate_group(asset: FillerAsset) -> str:
    if asset.shape == "tailpiece":
        return "tailpiece"
    if asset.shape == "spot":
        return "spot"
    if asset.shape == "small-wide":
        return "small-wide"
    if asset.shape == "bottom-band" and asset.height_in >= PAGE_FINISHER_IN:
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


def _stable_unit(seed: str, salt: str) -> float:
    digest = hashlib.sha256(f"{seed}|{salt}".encode()).hexdigest()
    return int(digest[:12], 16) / float(16**12 - 1)
