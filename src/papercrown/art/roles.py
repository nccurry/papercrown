"""Central art role registry and filename classifier."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

# Raster image extensions eligible for art role classification.
IMAGE_SUFFIXES = {".apng", ".avif", ".jpeg", ".jpg", ".png", ".webp"}
# Canonical page-wear filename pattern with family, size, and variant parts.
PAGE_WEAR_FILENAME_RE = re.compile(
    r"^wear-(?P<family>[a-z0-9-]+)-(?P<size>[a-z0-9-]+)-(?P<variant>[a-z0-9-]+)$"
)


@dataclass(frozen=True)
class ArtRoleSpec:
    """The canonical behavior expected for one kind of book art."""

    role: str
    expected_folder: str | None
    nominal_width_in: float | None = None
    nominal_height_in: float | None = None
    shape: str | None = None
    transparent: bool | None = None
    auto_placeable: bool = False


class _ParsedArtName(TypedDict):
    context: str | None
    subject: str | None
    variant: str | None


@dataclass(frozen=True)
class ArtAssetClassification:
    """Filename/path-derived role metadata for one art file."""

    role: str
    context: str | None = None
    subject: str | None = None
    variant: str | None = None
    expected_folder: str | None = None
    nominal_width_in: float | None = None
    nominal_height_in: float | None = None
    transparent: bool | None = None
    auto_placeable: bool = False
    shape: str | None = None
    matched_convention: str = "canonical"

    @property
    def height_in(self) -> float | None:
        """Return the nominal placement height, for filler compatibility."""
        return self.nominal_height_in


# Canonical art roles and their folder, size, transparency, and placement rules.
ROLE_REGISTRY: dict[str, ArtRoleSpec] = {
    "cover-front": ArtRoleSpec("cover-front", "covers", 5.5, 7.113, transparent=False),
    "cover-back": ArtRoleSpec("cover-back", "covers", 5.5, 7.113, transparent=False),
    "cover": ArtRoleSpec("cover", "covers", 5.5, 7.113, transparent=False),
    "chapter-divider": ArtRoleSpec(
        "chapter-divider", "dividers", 6.0, 0.933, transparent=False
    ),
    "chapter-header": ArtRoleSpec(
        "chapter-header", "headers", 6.0, 2.0, transparent=False
    ),
    "class-divider": ArtRoleSpec(
        "class-divider", "classes/dividers", 6.0, 4.0, transparent=False
    ),
    "class-opening-spot": ArtRoleSpec("class-opening-spot", "classes/spots", 2.0, 2.0),
    "frame-divider": ArtRoleSpec("frame-divider", "frames/dividers", 6.0, 3.0),
    "splash": ArtRoleSpec("splash", "splashes", 6.0, 1.8, transparent=False),
    "spread": ArtRoleSpec("spread", "spreads", 12.0, 9.0, transparent=False),
    "ornament-headpiece": ArtRoleSpec(
        "ornament-headpiece", "ornaments/headpieces", 5.333, 0.867
    ),
    "ornament-break": ArtRoleSpec("ornament-break", "ornaments/breaks", 2.0, 0.4),
    "ornament-tailpiece": ArtRoleSpec(
        "ornament-tailpiece",
        "ornaments/tailpieces",
        5.333,
        0.867,
        shape="tailpiece",
    ),
    "ornament-corner": ArtRoleSpec(
        "ornament-corner", "ornaments/corners", 1.0, 1.0, transparent=True
    ),
    "ornament-folio": ArtRoleSpec(
        "ornament-folio", "ornaments/folios", 0.65, 0.65, transparent=True
    ),
    "filler-spot": ArtRoleSpec(
        "filler-spot",
        "fillers/spot",
        1.5,
        1.35,
        shape="spot",
        auto_placeable=True,
    ),
    "filler-wide": ArtRoleSpec(
        "filler-wide",
        "fillers/wide",
        4.0,
        1.25,
        shape="small-wide",
        auto_placeable=True,
    ),
    "filler-plate": ArtRoleSpec(
        "filler-plate",
        "fillers/plate",
        5.0,
        3.6,
        shape="plate",
        auto_placeable=True,
    ),
    "filler-bottom": ArtRoleSpec(
        "filler-bottom",
        "fillers/bottom",
        6.0,
        2.067,
        shape="bottom-band",
        auto_placeable=True,
    ),
    "page-finish": ArtRoleSpec(
        "page-finish",
        "fillers/page-finish",
        6.0,
        5.25,
        shape="page-finish",
        auto_placeable=True,
    ),
    "page-wear": ArtRoleSpec(
        "page-wear", "page-wear", transparent=True, shape="page-wear"
    ),
    "faction": ArtRoleSpec(
        "faction", "content/factions", 6.0, 2.4, shape="bottom-band"
    ),
    "gear": ArtRoleSpec("gear", "content/gear", 6.0, 2.4, shape="bottom-band"),
    "vista": ArtRoleSpec("vista", "content/vistas", 6.0, 2.4, shape="bottom-band"),
    "spot": ArtRoleSpec("spot", None, 2.0, 2.0),
    "portrait": ArtRoleSpec("portrait", "content/portraits", 2.0, 3.0),
    "map": ArtRoleSpec("map", "content/maps", 6.0, 4.0),
    "diagram": ArtRoleSpec("diagram", "content/diagrams", 6.0, 3.5),
    "screenshot": ArtRoleSpec("screenshot", "content/screenshots", 6.0, 3.5),
    "icon": ArtRoleSpec("icon", "icons", 0.5, 0.5, transparent=True),
    "logo": ArtRoleSpec("logo", "logos", 2.0, 1.0, transparent=True),
    "item": ArtRoleSpec("item", "content/items", 2.0, 2.0),
    "npc": ArtRoleSpec("npc", "content/npcs", 2.0, 3.0),
    "location": ArtRoleSpec("location", "content/locations", 6.0, 3.0),
    "handout": ArtRoleSpec("handout", "content/handouts", 6.0, 4.0),
    "excluded": ArtRoleSpec("excluded", None),
    "unclassified": ArtRoleSpec("unclassified", None),
}


def classify_art_path(
    path: Path,
    art_root: Path | None = None,
) -> ArtAssetClassification:
    """Classify an art path according to the Paper Crown art contract."""
    relative = _relative_to_root(path, art_root)
    parts = [part.lower() for part in relative.parts]
    dirs = parts[:-1]
    stem = path.stem.lower()
    name = path.name.lower()

    if _is_excluded(parts, stem):
        return _classification("excluded")
    if "campaign" in dirs:
        return _classification("excluded")

    if stem == "cover-back" or stem.startswith("cover-back-"):
        return _classification("cover-back", **_parse_prefix(stem, ("cover-back",)))
    if stem in {"cover", "cover-front"} or stem.startswith("cover-front-"):
        role = "cover-front" if stem.startswith("cover-front") else "cover"
        convention = "canonical" if role == "cover-front" else "legacy"
        return _classification(
            role,
            matched_convention=convention,
            **_parse_prefix(stem, ("cover-front", "cover")),
        )

    if _in_nested_folder(dirs, "classes", "dividers"):
        return _classification("class-divider", **_parse_prefix(stem, ("class",)))
    if _in_folder(dirs, "classes") and stem.startswith("class-"):
        return _classification("class-divider", **_parse_prefix(stem, ("class",)))

    if (
        _in_folder(dirs, "dividers") and "classes" not in dirs and "frames" not in dirs
    ) or stem == "chapter-divider":
        return _classification(
            "chapter-divider",
            **_parse_prefix(stem, ("divider", "chapter-divider")),
        )
    if stem.startswith("divider-"):
        return _classification(
            "chapter-divider",
            matched_convention="legacy",
            **_parse_prefix(stem, ("divider",)),
        )

    if (
        _in_folder(dirs, "headers")
        or stem.endswith("-header")
        or stem.startswith("header-")
    ):
        return _classification(
            "chapter-header",
            **_parse_prefix(stem, ("header",), suffixes=("-header",)),
        )

    if _in_nested_folder(dirs, "classes", "spots"):
        return _classification(
            "class-opening-spot", **_parse_prefix(stem, ("spot-class",))
        )
    if "class-spots" in dirs or stem.startswith("spot-class-"):
        return _classification(
            "class-opening-spot",
            matched_convention="legacy",
            **_parse_prefix(stem, ("spot-class",)),
        )

    if _in_nested_folder(dirs, "frames", "dividers") or "frame-dividers" in dirs:
        return _classification("frame-divider", **_parse_prefix(stem, ("frame",)))
    if stem.startswith("frame-"):
        return _classification(
            "frame-divider",
            matched_convention="legacy",
            **_parse_prefix(stem, ("frame",)),
        )

    if _in_folder(dirs, "spreads") or stem.startswith("spread-"):
        return _classification("spread", **_parse_prefix(stem, ("spread",)))

    if _in_folder(dirs, "splashes") or stem.startswith(
        ("splash-", "opening-", "closing-")
    ):
        return _classification(
            "splash",
            **_parse_prefix(
                stem,
                (
                    "splash-cover-front",
                    "splash-cover-back",
                    "splash-chapter",
                    "splash-section",
                    "splash",
                    "opening",
                    "closing",
                ),
            ),
        )

    ornament_role = _classify_ornament(dirs, stem)
    if ornament_role is not None:
        role, convention = ornament_role
        return _classification(
            role,
            matched_convention=convention,
            **_parse_prefix(
                stem,
                (
                    "ornament-headpiece",
                    "ornament-break",
                    "ornament-tailpiece",
                    "ornament-corner",
                    "ornament-folio",
                ),
            ),
        )

    filler_role = _classify_filler(dirs, stem)
    if filler_role is not None:
        role, convention = filler_role
        return _classification(
            role,
            matched_convention=convention,
            **_parse_prefix(
                stem,
                (
                    "filler-spot",
                    "filler-wide",
                    "filler-plate",
                    "filler-bottom",
                    "page-finish",
                ),
            ),
        )

    if stem.startswith("wear-"):
        match = PAGE_WEAR_FILENAME_RE.fullmatch(stem)
        if match is not None:
            return _classification(
                "page-wear",
                context=match.group("family"),
                subject=match.group("size"),
                variant=match.group("variant"),
            )
        return _classification("page-wear", subject=stem)

    content_role = _classify_content(dirs, stem, name)
    if content_role is not None:
        role, convention = content_role
        return _classification(
            role,
            matched_convention=convention,
            **_parse_prefix(stem, (role,)),
        )

    return _classification("unclassified")


def _classification(
    role: str,
    *,
    context: str | None = None,
    subject: str | None = None,
    variant: str | None = None,
    matched_convention: str = "canonical",
) -> ArtAssetClassification:
    spec = ROLE_REGISTRY[role]
    return ArtAssetClassification(
        role=role,
        context=context,
        subject=subject,
        variant=variant,
        expected_folder=spec.expected_folder,
        nominal_width_in=spec.nominal_width_in,
        nominal_height_in=spec.nominal_height_in,
        transparent=spec.transparent,
        auto_placeable=spec.auto_placeable,
        shape=spec.shape,
        matched_convention=matched_convention,
    )


def _relative_to_root(path: Path, art_root: Path | None) -> Path:
    if art_root is None:
        return path
    try:
        return path.resolve().relative_to(art_root.resolve())
    except (OSError, ValueError):
        try:
            return path.relative_to(art_root)
        except ValueError:
            return path


def _is_excluded(parts: list[str], stem: str) -> bool:
    excluded_parts = {"unused", "contact-sheets", "__pycache__"}
    if any(part in excluded_parts for part in parts):
        return True
    if "corner" in stem and not stem.startswith("ornament-corner"):
        return True
    return (
        stem in {"manifest", "contact-sheet"}
        or stem.startswith("contact-sheet-")
        or stem.endswith("-contact-sheet")
    )


def _in_folder(dirs: list[str], folder: str) -> bool:
    folder_parts = folder.lower().split("/")
    if not folder_parts:
        return False
    if len(folder_parts) == 1:
        return folder_parts[0] in dirs
    return _contains_sequence(dirs, folder_parts)


def _in_nested_folder(dirs: list[str], parent: str, child: str) -> bool:
    return _contains_sequence(dirs, [parent, child])


def _contains_sequence(items: list[str], sequence: list[str]) -> bool:
    if len(items) < len(sequence):
        return False
    return any(
        items[index : index + len(sequence)] == sequence for index in range(len(items))
    )


def _classify_ornament(dirs: list[str], stem: str) -> tuple[str, str] | None:
    if _in_nested_folder(dirs, "ornaments", "headpieces") or stem.startswith(
        "ornament-headpiece-"
    ):
        return ("ornament-headpiece", "canonical")
    if _in_nested_folder(dirs, "ornaments", "breaks") or stem.startswith(
        "ornament-break-"
    ):
        return ("ornament-break", "canonical")
    if _in_nested_folder(dirs, "ornaments", "tailpieces") or stem.startswith(
        "ornament-tailpiece-"
    ):
        return ("ornament-tailpiece", "canonical")
    if _in_nested_folder(dirs, "ornaments", "corners") or stem.startswith(
        "ornament-corner-"
    ):
        return ("ornament-corner", "canonical")
    if _in_nested_folder(dirs, "ornaments", "folios") or stem.startswith(
        "ornament-folio-"
    ):
        return ("ornament-folio", "canonical")
    if "ornaments" in dirs and stem.startswith("ornament-"):
        return ("ornament-break", "legacy")
    return None


def _classify_filler(dirs: list[str], stem: str) -> tuple[str, str] | None:
    folder_roles = {
        "spot": "filler-spot",
        "wide": "filler-wide",
        "plate": "filler-plate",
        "bottom": "filler-bottom",
        "page-finish": "page-finish",
    }
    if "fillers" in dirs:
        for folder, role in folder_roles.items():
            if folder in dirs and stem.startswith(f"{role}-"):
                return (role, "canonical")
    for role in (
        "filler-spot",
        "filler-wide",
        "filler-plate",
        "filler-bottom",
        "page-finish",
    ):
        if stem.startswith(f"{role}-"):
            return (role, "legacy" if "fillers" in dirs else "canonical")
    return None


def _classify_content(
    dirs: list[str],
    stem: str,
    name: str,
) -> tuple[str, str] | None:
    folder_roles = {
        "factions": "faction",
        "gear": "gear",
        "vistas": "vista",
        "spreads": "spread",
        "spots": "spot",
        "background-spots": "spot",
        "portraits": "portrait",
        "maps": "map",
        "diagrams": "diagram",
        "screenshots": "screenshot",
        "icons": "icon",
        "logos": "logo",
        "items": "item",
        "npcs": "npc",
        "locations": "location",
        "handouts": "handout",
    }
    if "content" in dirs:
        for folder, role in folder_roles.items():
            if folder in dirs:
                return (role, "canonical")
    prefix_roles = {
        "faction": "faction",
        "gear": "gear",
        "vista": "vista",
        "spot": "spot",
        "portrait": "portrait",
        "map": "map",
        "diagram": "diagram",
        "screenshot": "screenshot",
        "icon": "icon",
        "logo": "logo",
        "item": "item",
        "npc": "npc",
        "location": "location",
        "handout": "handout",
        "stamp": "spot",
        "label": "spot",
        "ship": "handout",
        "vehicle": "handout",
    }
    for prefix, role in prefix_roles.items():
        if stem.startswith(f"{prefix}-"):
            return (role, "legacy")
    if name.startswith(("opening-", "closing-")):
        return ("splash", "legacy")
    return None


def _parse_prefix(
    stem: str,
    prefixes: tuple[str, ...],
    *,
    suffixes: tuple[str, ...] = (),
) -> _ParsedArtName:
    for suffix in suffixes:
        if stem.endswith(suffix) and len(stem) > len(suffix):
            return {
                "context": None,
                "subject": stem.removesuffix(suffix),
                "variant": None,
            }
    for prefix in sorted(prefixes, key=len, reverse=True):
        if stem == prefix:
            return {"context": None, "subject": None, "variant": None}
        token_prefix = f"{prefix}-"
        if stem.startswith(token_prefix):
            tokens = stem.removeprefix(token_prefix).split("-")
            return _parse_tokens(tokens)
    return {"context": None, "subject": stem, "variant": None}


def _parse_tokens(tokens: list[str]) -> _ParsedArtName:
    if not tokens:
        return {"context": None, "subject": None, "variant": None}
    variant = tokens[-1] if _looks_like_variant(tokens[-1]) else None
    body = tokens[:-1] if variant is not None else tokens
    context = body[0] if len(body) >= 2 else None
    subject_tokens = body[1:] if context is not None else body
    subject = "-".join(subject_tokens) if subject_tokens else None
    return {"context": context, "subject": subject, "variant": variant}


def _looks_like_variant(token: str) -> bool:
    return token.isdigit() or bool(re.fullmatch(r"v?\d+[a-z]?", token))
