"""Deterministic page-wear placement and underlay rendering."""

from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, TypeVar

from PIL import Image

from papercrown.project.manifest import PageDamageAsset, PageDamageCatalog

# Generic type variable for deterministic weighted-choice helpers.
_T = TypeVar("_T")

# Physical page width used for page-wear placement.
PAGE_WIDTH_IN = 8.5
# Physical page height used for page-wear placement.
PAGE_HEIGHT_IN = 11.0
# PDF coordinate conversion from inches to points.
PDF_POINTS_PER_IN = 72.0
# Raster resolution used when compositing page-wear underlays.
RASTER_DPI = 144
# Raster page width derived from physical width and underlay DPI.
PAGE_WIDTH_PX = round(PAGE_WIDTH_IN * RASTER_DPI)
# Raster page height derived from physical height and underlay DPI.
PAGE_HEIGHT_PX = round(PAGE_HEIGHT_IN * RASTER_DPI)
# Paper-colored RGBA base for generated underlay textures.
PAPER_COLOR = (251, 250, 248, 255)
# Width ranges used when scaling page-wear assets by named size.
SIZE_WIDTHS_IN = {
    "tiny": (0.15, 0.35),
    "small": (0.35, 0.8),
    "medium": (0.8, 1.8),
    "large": (1.8, 3.5),
}
# Relative probabilities for selecting page-wear size categories.
SIZE_WEIGHTS = (("tiny", 0.40), ("small", 0.37), ("medium", 0.20), ("large", 0.03))
# Relative probabilities for selecting page-wear visual families.
FAMILY_WEIGHTS = {
    "smudge-grime": 4.2,
    "grease-fingerprint": 3.4,
    "tape-residue": 3.0,
    "water-condensation": 2.4,
    "coffee": 1.8,
    "crease-mark": 1.1,
    "nick-scratch": 0.85,
    "clip-puncture": 0.45,
    "scorch-heat": 0.35,
    "printer-misfeed": 0.3,
    "edge-tear": 0.12,
}
# Chance that selected families are placed in the page field instead of edges.
FIELD_FAMILY_CHANCES = {
    "smudge-grime": 0.72,
    "grease-fingerprint": 0.52,
    "tape-residue": 0.46,
    "water-condensation": 0.42,
}
# Families that prefer placement along page edges.
EDGE_FAMILIES = {"edge-tear", "clip-puncture", "edge-dust"}
# Families that can be anchored near page corners.
CORNER_FAMILIES = {"coffee", "grease-fingerprint", "tape-residue"}
# Families that can span mechanically across the page.
MECHANICAL_FAMILIES = {"printer-misfeed", "crease-mark"}
# WeasyPrint page-type names skipped for each recipe skip target.
PAGE_TYPE_BY_SKIP = {
    "cover": {"cover-page"},
    "divider": {"divider-page", "digital-divider-page"},
}
# DOM class names skipped for each recipe skip target.
CLASS_BY_SKIP = {
    "cover": {"cover"},
    "toc": {"toc"},
    "divider": {"section-divider", "chapter-opener"},
    "splash": {"splash-page"},
}


@dataclass(frozen=True)
class PageDamagePlacement:
    """A selected page-wear asset and absolute page position."""

    asset: PageDamageAsset
    page_number: int
    x_in: float
    y_in: float
    width_in: float
    rotation_deg: float
    opacity: float


@dataclass(frozen=True)
class PageDamageImage:
    """A rendered page-wear image plus its PDF-space placement."""

    png: bytes
    x_in: float
    y_in: float
    width_in: float
    height_in: float


def plan_page_damage(
    document: object,
    catalog: PageDamageCatalog,
    *,
    recipe_title: str,
) -> list[PageDamagePlacement]:
    """Return stable page-wear placements for a rendered WeasyPrint document."""
    if not catalog.enabled or not catalog.assets or catalog.density <= 0:
        return []

    placements: list[PageDamagePlacement] = []
    pages = getattr(document, "pages", [])
    seed = f"{catalog.seed}|{recipe_title}"
    for page_index, page in enumerate(pages, start=1):
        if should_skip_page(page, catalog.skip):
            continue
        page_seed = f"{seed}|page:{page_index}"
        if _unit(page_seed, "enabled") > catalog.density:
            continue
        count = 1
        for slot_index in range(1, catalog.max_assets_per_page):
            if _unit(page_seed, "extra", str(slot_index)) <= catalog.density * 0.45:
                count += 1

        used_families: set[str] = set()
        for slot_index in range(count):
            asset = _select_asset(catalog.assets, page_seed, slot_index, used_families)
            if asset is None:
                break
            used_families.add(asset.family)
            placements.append(
                _place_asset(
                    asset,
                    page_number=page_index,
                    seed=f"{page_seed}|slot:{slot_index}",
                    opacity=catalog.opacity,
                )
            )
    return placements


def should_skip_page(page: object, skip: list[str]) -> bool:
    """Return whether a rendered page should not receive random page wear."""
    skip_set = set(skip)
    page_type = _page_type_name(page)
    for target in skip_set:
        if page_type in PAGE_TYPE_BY_SKIP.get(target, set()):
            return True

    classes = _page_classes(page)
    for target in skip_set:
        if classes & CLASS_BY_SKIP.get(target, set()):
            return True
    return False


def page_has_surface_art(page: object) -> bool:
    """Return whether a rendered page contains document art worth glazing."""
    page_box = getattr(page, "_page_box", None)
    if page_box is None:
        return False
    descendants = getattr(page_box, "descendants", None)
    if not callable(descendants):
        return False
    for box in descendants():
        element = getattr(box, "element", None)
        if element is None:
            continue
        tag = str(getattr(element, "tag", "")).lower()
        if tag.endswith("img"):
            return True
    return False


def render_page_underlay_pdf(
    placements: list[PageDamagePlacement],
    *,
    base_url: str,
    url_fetcher: Any,
    paper_grain_path: Path | None,
    page_patina_path: Path | None,
    folio_frame_path: Path | None = None,
    weasy_options: dict[str, Any] | None = None,
) -> bytes:
    """Render one Letter-sized paper page plus optional page-wear images."""
    del base_url, url_fetcher, weasy_options
    canvas = _paper_canvas(
        paper_grain_path=paper_grain_path,
        page_patina_path=page_patina_path,
    )
    _composite_folio_frame(canvas, folio_frame_path)
    for placement in placements:
        _composite_page_damage(canvas, placement)
    return _rgba_page_to_pdf(canvas)


def render_page_damage_overlay_pdf(
    placements: list[PageDamagePlacement],
) -> bytes:
    """Render transparent page-wear overlays for faster PDF stamping."""
    return _rgba_page_to_pdf(_damage_overlay_canvas(placements))


def render_page_damage_overlay_png(
    placements: list[PageDamagePlacement],
) -> bytes:
    """Render transparent page-wear overlays as PNG bytes."""
    return _rgba_page_to_png(_damage_overlay_canvas(placements))


def render_page_damage_image_png(placement: PageDamagePlacement) -> PageDamageImage:
    """Render one page-wear placement as a tightly bounded PNG."""
    image, left, top = _prepared_damage_image(placement)
    return PageDamageImage(
        png=_rgba_image_to_png(image),
        x_in=left / RASTER_DPI,
        y_in=top / RASTER_DPI,
        width_in=image.width / RASTER_DPI,
        height_in=image.height / RASTER_DPI,
    )


def _damage_overlay_canvas(placements: list[PageDamagePlacement]) -> Image.Image:
    """Return a transparent canvas with page-wear placements composited."""
    canvas = Image.new("RGBA", (PAGE_WIDTH_PX, PAGE_HEIGHT_PX), (0, 0, 0, 0))
    for placement in placements:
        _composite_page_damage(canvas, placement)
    return canvas


def render_page_glaze_pdf(
    *,
    base_url: str,
    url_fetcher: Any,
    texture_path: Path,
    opacity: float,
    weasy_options: dict[str, Any] | None = None,
) -> bytes:
    """Render a transparent surface-grain overlay for the whole page."""
    del base_url, url_fetcher, weasy_options
    safe_opacity = max(0.0, min(1.0, opacity))
    canvas = Image.new("RGBA", (PAGE_WIDTH_PX, PAGE_HEIGHT_PX), (0, 0, 0, 0))
    if safe_opacity > 0:
        texture = _load_rgba(texture_path)
        texture = texture.resize(
            (PAGE_WIDTH_PX, PAGE_HEIGHT_PX),
            Image.Resampling.LANCZOS,
        )
        _apply_opacity(texture, safe_opacity)
        _alpha_composite_clipped(canvas, texture, 0, 0)
    return _rgba_page_to_pdf(canvas)


def render_page_glaze_png(
    *,
    texture_path: Path,
    opacity: float,
) -> bytes:
    """Render a transparent surface-grain overlay as PNG bytes."""
    safe_opacity = max(0.0, min(1.0, opacity))
    canvas = Image.new("RGBA", (PAGE_WIDTH_PX, PAGE_HEIGHT_PX), (0, 0, 0, 0))
    if safe_opacity > 0:
        texture = _load_rgba(texture_path)
        texture = texture.resize(
            (PAGE_WIDTH_PX, PAGE_HEIGHT_PX),
            Image.Resampling.LANCZOS,
        )
        _apply_opacity(texture, safe_opacity)
        _alpha_composite_clipped(canvas, texture, 0, 0)
    return _rgba_page_to_png(canvas)


def _select_asset(
    assets: list[PageDamageAsset],
    seed: str,
    slot_index: int,
    used_families: set[str],
) -> PageDamageAsset | None:
    preferred_size = _weighted_size(seed, slot_index)
    candidates = [
        asset
        for asset in assets
        if asset.size == preferred_size and asset.family not in used_families
    ]
    if not candidates:
        candidates = [asset for asset in assets if asset.family not in used_families]
    if not candidates:
        candidates = list(assets)
    if not candidates:
        return None
    return _weighted_asset_choice(candidates, seed, "asset", str(slot_index))


def _weighted_size(seed: str, slot_index: int) -> str:
    roll = _unit(seed, "size", str(slot_index))
    cumulative = 0.0
    for size, weight in SIZE_WEIGHTS:
        cumulative += weight
        if roll <= cumulative:
            return size
    return SIZE_WEIGHTS[-1][0]


def _place_asset(
    asset: PageDamageAsset,
    *,
    page_number: int,
    seed: str,
    opacity: float,
) -> PageDamagePlacement:
    min_width, max_width = SIZE_WIDTHS_IN[asset.size]
    width = _lerp(min_width, max_width, _unit(seed, "width"))
    if asset.family == "edge-tear":
        width = min(width, _lerp(0.28, 0.9, _unit(seed, "tear-width")))
    if asset.family == "grease-fingerprint":
        width = min(width, _lerp(0.28, 0.68, _unit(seed, "fingerprint-width")))
    if asset.family == "printer-misfeed" and asset.size in {"medium", "large"}:
        width = _lerp(6.4, 8.5, _unit(seed, "printer-width"))

    x, y = _placement_xy(asset, width, seed)
    rotation = _rotation(asset, seed)
    opacity_jitter = _lerp(0.82, 1.08, _unit(seed, "opacity"))
    return PageDamagePlacement(
        asset=asset,
        page_number=page_number,
        x_in=x,
        y_in=y,
        width_in=width,
        rotation_deg=rotation,
        opacity=max(0.0, min(1.0, opacity * opacity_jitter)),
    )


def _placement_xy(
    asset: PageDamageAsset,
    width: float,
    seed: str,
) -> tuple[float, float]:
    height_estimate = width
    field_chance = FIELD_FAMILY_CHANCES.get(asset.family, 0.0)
    if (
        field_chance > 0
        and asset.size in {"small", "medium", "large"}
        and _unit(seed, "field") <= field_chance
    ):
        return _field_position(width, height_estimate, seed)
    if asset.family in EDGE_FAMILIES:
        return _edge_position(width, height_estimate, seed)
    if asset.family in CORNER_FAMILIES and asset.size in {"small", "medium", "large"}:
        return _corner_position(width, height_estimate, seed)
    if asset.family in MECHANICAL_FAMILIES and asset.size in {"medium", "large"}:
        return _band_position(width, height_estimate, seed)
    return _margin_position(width, height_estimate, seed)


def _field_position(width: float, height: float, seed: str) -> tuple[float, float]:
    """Place subtle residue in the readable page field, behind the text."""
    return (
        _lerp(0.9, PAGE_WIDTH_IN - width - 0.9, _unit(seed, "x-field")),
        _lerp(1.15, PAGE_HEIGHT_IN - height - 1.55, _unit(seed, "y-field")),
    )


def _edge_position(width: float, height: float, seed: str) -> tuple[float, float]:
    edge = _choice(["left", "right", "top", "bottom"], seed, "edge")
    if edge == "left":
        return (
            -width * _lerp(0.18, 0.48, _unit(seed, "x-edge")),
            _lerp(0.45, PAGE_HEIGHT_IN - height - 0.45, _unit(seed, "y")),
        )
    if edge == "right":
        return (
            PAGE_WIDTH_IN - width * _lerp(0.52, 0.85, _unit(seed, "x-edge")),
            _lerp(0.45, PAGE_HEIGHT_IN - height - 0.45, _unit(seed, "y")),
        )
    if edge == "top":
        return (
            _lerp(0.25, PAGE_WIDTH_IN - width - 0.25, _unit(seed, "x")),
            -height * _lerp(0.18, 0.45, _unit(seed, "y-edge")),
        )
    return (
        _lerp(0.25, PAGE_WIDTH_IN - width - 0.25, _unit(seed, "x")),
        PAGE_HEIGHT_IN - height * _lerp(0.55, 0.88, _unit(seed, "y-edge")),
    )


def _corner_position(width: float, height: float, seed: str) -> tuple[float, float]:
    corner = _choice(["tl", "tr", "bl", "br"], seed, "corner")
    inset_x = _lerp(0.05, 0.55, _unit(seed, "inset-x"))
    inset_y = _lerp(0.05, 0.7, _unit(seed, "inset-y"))
    if corner == "tl":
        return inset_x, inset_y
    if corner == "tr":
        return PAGE_WIDTH_IN - width - inset_x, inset_y
    if corner == "bl":
        return inset_x, PAGE_HEIGHT_IN - height - inset_y
    return PAGE_WIDTH_IN - width - inset_x, PAGE_HEIGHT_IN - height - inset_y


def _band_position(width: float, height: float, seed: str) -> tuple[float, float]:
    band = _choice(["top", "bottom", "outer"], seed, "band")
    if band == "top":
        return _lerp(0.0, max(0.0, PAGE_WIDTH_IN - width), _unit(seed, "x")), 0.2
    if band == "bottom":
        return (
            _lerp(0.0, max(0.0, PAGE_WIDTH_IN - width), _unit(seed, "x")),
            PAGE_HEIGHT_IN - height - 0.2,
        )
    return _margin_position(width, height, seed)


def _margin_position(width: float, height: float, seed: str) -> tuple[float, float]:
    zone = _choice(["left", "right", "top", "bottom"], seed, "zone")
    if zone == "left":
        return (
            _lerp(0.05, 0.62, _unit(seed, "x")),
            _lerp(0.7, PAGE_HEIGHT_IN - height - 0.7, _unit(seed, "y")),
        )
    if zone == "right":
        return (
            PAGE_WIDTH_IN - width - _lerp(0.05, 0.62, _unit(seed, "x")),
            _lerp(0.7, PAGE_HEIGHT_IN - height - 0.7, _unit(seed, "y")),
        )
    if zone == "top":
        return (
            _lerp(0.7, PAGE_WIDTH_IN - width - 0.7, _unit(seed, "x")),
            _lerp(0.08, 0.62, _unit(seed, "y")),
        )
    return (
        _lerp(0.7, PAGE_WIDTH_IN - width - 0.7, _unit(seed, "x")),
        PAGE_HEIGHT_IN - height - _lerp(0.08, 0.72, _unit(seed, "y")),
    )


def _rotation(asset: PageDamageAsset, seed: str) -> float:
    if asset.family == "printer-misfeed":
        return _lerp(-1.5, 1.5, _unit(seed, "rotation"))
    if asset.family == "crease-mark":
        return _lerp(-18.0, 18.0, _unit(seed, "rotation"))
    if asset.family in EDGE_FAMILIES:
        return _lerp(-4.0, 4.0, _unit(seed, "rotation"))
    return _lerp(-24.0, 24.0, _unit(seed, "rotation"))


def _paper_canvas(
    *,
    paper_grain_path: Path | None,
    page_patina_path: Path | None,
) -> Image.Image:
    """Return a raster paper background matching the former CSS underlay."""
    canvas = Image.new("RGBA", (PAGE_WIDTH_PX, PAGE_HEIGHT_PX), PAPER_COLOR)
    if paper_grain_path is not None and paper_grain_path.is_file():
        grain_size = _in_to_px(1.15)
        grain = _load_rgba(paper_grain_path).resize(
            (grain_size, grain_size),
            Image.Resampling.LANCZOS,
        )
        for x in range(0, PAGE_WIDTH_PX, grain_size):
            for y in range(0, PAGE_HEIGHT_PX, grain_size):
                _alpha_composite_clipped(canvas, grain, x, y)
    if page_patina_path is not None and page_patina_path.is_file():
        patina = _load_rgba(page_patina_path).resize(
            (PAGE_WIDTH_PX, PAGE_HEIGHT_PX),
            Image.Resampling.LANCZOS,
        )
        _alpha_composite_clipped(canvas, patina, 0, 0)
    return canvas


def _composite_folio_frame(canvas: Image.Image, path: Path | None) -> None:
    """Draw the page-number frame into the underlay when available."""
    if path is None or not path.is_file():
        return
    size = _in_to_px(0.640)
    left = round(PAGE_WIDTH_PX / 2 - size / 2)
    top = PAGE_HEIGHT_PX - _in_to_px(0.150) - size
    frame = _load_rgba(path).resize((size, size), Image.Resampling.LANCZOS)
    _apply_opacity(frame, 0.94)
    _alpha_composite_clipped(canvas, frame, left, top)


def _composite_page_damage(
    canvas: Image.Image,
    placement: PageDamagePlacement,
) -> None:
    """Draw one page-wear placement with CSS-equivalent sizing and rotation."""
    image, left, top = _prepared_damage_image(placement)
    _alpha_composite_clipped(canvas, image, left, top)


def _prepared_damage_image(
    placement: PageDamagePlacement,
) -> tuple[Image.Image, int, int]:
    """Return a pre-rotated page-wear image and its top-left pixel position."""
    image = _load_rgba(placement.asset.art_path)
    width_px = _in_to_px(placement.width_in)
    height_px = max(1, round(image.height * (width_px / image.width)))
    image = image.resize((width_px, height_px), Image.Resampling.LANCZOS)
    _apply_opacity(image, placement.opacity)
    rotated = image.rotate(
        -placement.rotation_deg,
        expand=True,
        resample=Image.Resampling.BICUBIC,
    )
    left = _in_to_px(placement.x_in) - round((rotated.width - width_px) / 2)
    top = _in_to_px(placement.y_in) - round((rotated.height - height_px) / 2)
    return rotated, left, top


def _alpha_composite_clipped(
    canvas: Image.Image,
    image: Image.Image,
    left: int,
    top: int,
) -> None:
    """Alpha-composite an image even when it extends beyond the page bounds."""
    dest_left = max(0, left)
    dest_top = max(0, top)
    dest_right = min(canvas.width, left + image.width)
    dest_bottom = min(canvas.height, top + image.height)
    if dest_right <= dest_left or dest_bottom <= dest_top:
        return

    src_left = dest_left - left
    src_top = dest_top - top
    src_right = src_left + (dest_right - dest_left)
    src_bottom = src_top + (dest_bottom - dest_top)
    cropped = image.crop((src_left, src_top, src_right, src_bottom))
    canvas.alpha_composite(cropped, (dest_left, dest_top))


def _load_rgba(path: Path) -> Image.Image:
    """Load an image as an independent RGBA Pillow image."""
    with Image.open(path) as image:
        return image.convert("RGBA")


def _apply_opacity(image: Image.Image, opacity: float) -> None:
    """Multiply an RGBA image's alpha channel in place."""
    alpha = image.getchannel("A")
    factor = max(0.0, min(1.0, opacity))
    image.putalpha(alpha.point(lambda value: round(value * factor)))


def _rgba_page_to_pdf(image: Image.Image) -> bytes:
    """Wrap a Letter-sized RGBA raster page in a PDF."""
    buffer = BytesIO(_rgba_page_to_png(image))
    fitz: Any = importlib.import_module("fitz")
    document = fitz.open()
    try:
        page = document.new_page(
            width=PAGE_WIDTH_IN * PDF_POINTS_PER_IN,
            height=PAGE_HEIGHT_IN * PDF_POINTS_PER_IN,
        )
        page.insert_image(page.rect, stream=buffer.getvalue())
        return bytes(document.write())
    finally:
        document.close()


def _rgba_page_to_png(image: Image.Image) -> bytes:
    """Return a PNG encoding of an RGBA page-sized canvas."""
    return _rgba_image_to_png(image, optimize=True)


def _rgba_image_to_png(image: Image.Image, *, optimize: bool = False) -> bytes:
    """Return a PNG encoding of an RGBA image."""
    buffer = BytesIO()
    image.save(buffer, format="PNG", optimize=optimize, compress_level=6)
    return buffer.getvalue()


def _in_to_px(value: float) -> int:
    return round(value * RASTER_DPI)


def _page_type_name(page: object) -> str:
    page_box = getattr(page, "_page_box", None)
    page_type = getattr(page_box, "page_type", None)
    return str(getattr(page_type, "name", "") or "")


def _page_classes(page: object) -> set[str]:
    page_box = getattr(page, "_page_box", None)
    if page_box is None:
        return set()
    classes: set[str] = set()
    descendants = getattr(page_box, "descendants", None)
    if not callable(descendants):
        return classes
    for box in descendants():
        element = getattr(box, "element", None)
        if element is None:
            continue
        classes |= _classes(element)
    return classes


def _classes(element: Any) -> set[str]:
    raw = element.get("class") or ""
    return set(str(raw).split())


def _weighted_asset_choice(
    items: list[PageDamageAsset],
    *parts: str,
) -> PageDamageAsset:
    total = sum(_asset_weight(item) for item in items)
    if total <= 0:
        return _choice(items, *parts)
    roll = _unit(*parts) * total
    cumulative = 0.0
    for item in items:
        cumulative += _asset_weight(item)
        if roll <= cumulative:
            return item
    return items[-1]


def _asset_weight(asset: PageDamageAsset) -> float:
    weight = FAMILY_WEIGHTS.get(asset.family, 1.0)
    if asset.family == "edge-tear" and asset.size in {"medium", "large"}:
        weight *= 0.18
    return weight


def _choice(items: list[_T], *parts: str) -> _T:
    index = int(_unit(*parts) * len(items))
    return items[min(index, len(items) - 1)]


def _unit(*parts: str) -> float:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:12], 16) / float(0xFFFFFFFFFFFF)


def _lerp(start: float, end: float, amount: float) -> float:
    if end < start:
        end = start
    return start + (end - start) * amount
