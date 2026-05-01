"""BookConfig loader.

A recipe is a YAML file that declares one book: which vaults to use, what
chapters to include, and how to style the output. Loaded into typed
dataclasses so downstream code can rely on shape and validation.

BookConfig shape:

    title: "My Book"
    subtitle: "..."
    cover_eyebrow: "..."
    cover_footer: "..."

    vaults:
      rules: ../my-content-vault

    vault_overlay: [rules]

    output_dir: .                  # optional; generated files go under Paper Crown/
    output_name: my-book           # optional; defaults to a slug of the title
    art_dir: Art                   # optional; relative to the project root

    cover:
      enabled: true
      art: cover.png

    ornaments:
      folio_frame: ornaments/ornament-folio-frame.png

    contents:
      - kind: file
        style: setting
        title: Setting Primer
        slug: setting-primer
        eyebrow: Setting Primer
        art: setting-header.png
        source: rules:Setting Primer.md
      - kind: classes-catalog
        source: rules:Heroes/Classes List.md
        wrapper: false
        child_style: class
        individual_pdfs: true
        individual_pdf_subdir: classes
        art_per_class: true
        class_art_pattern: classes/dividers/class-{slug}.png
        class_spot_art_pattern: classes/spots/spot-class-{slug}.png
        replace_existing_opening_art: true
      - kind: sequence
        title: Combat
        tailpiece: ornaments/ornament-tailpiece-casing.png
        sources:
          - rules:Combat.md
          - title: Combat Structure
            source: rules:System/Rules/Combat Structure.md
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from papercrown.art.roles import ArtRoleSpec
from papercrown.media.image_treatments import (
    IMAGE_TREATMENT_PRESETS,
    IMAGE_TREATMENT_ROLE_SELECTORS,
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class BookConfigError(ValueError):
    """Raised when a recipe is malformed or references missing files."""


# ---------------------------------------------------------------------------
# Page damage / wear spec
# ---------------------------------------------------------------------------


# Page-wear family names accepted in recipe and asset metadata.
PAGE_DAMAGE_FAMILIES = {
    "coffee",
    "edge-tear",
    "nick-scratch",
    "smudge-grime",
    "crease-mark",
    "water-condensation",
    "grease-fingerprint",
    "tape-residue",
    "clip-puncture",
    "scorch-heat",
    "printer-misfeed",
}
# Page-wear size names accepted in recipe and asset metadata.
PAGE_DAMAGE_SIZES = {
    "tiny",
    "small",
    "medium",
    "large",
}
# BookConfig skip targets that suppress page-wear on matching pages.
PAGE_DAMAGE_SKIP_TARGETS = {
    "cover",
    "toc",
    "divider",
    "splash",
}
# Default page-wear exclusions for structural pages.
DEFAULT_PAGE_DAMAGE_SKIP = ["cover", "toc", "divider", "splash"]


@dataclass(frozen=True)
class PageDamageSpec:
    """BookConfig-level page wear configuration."""

    enabled: bool = False
    art_dir: str = "page-wear"
    seed: str | None = None
    density: float = 0.55
    max_assets_per_page: int = 2
    opacity: float = 0.28
    glaze_opacity: float = 0.0
    glaze_texture: str = "surface-warm-paper-tint-cloud.png"
    skip: list[str] = field(default_factory=lambda: list(DEFAULT_PAGE_DAMAGE_SKIP))

    @classmethod
    def from_dict(cls, raw: Mapping[str, object] | None) -> PageDamageSpec:
        """Build page-damage settings from an optional recipe mapping."""
        if not raw:
            return cls()
        density = _float_between(
            raw.get("density", 0.55),
            loc="page_damage.density",
            min_value=0.0,
            max_value=1.0,
        )
        opacity = _float_between(
            raw.get("opacity", 0.28),
            loc="page_damage.opacity",
            min_value=0.0,
            max_value=1.0,
        )
        glaze_opacity = _float_between(
            raw.get("glaze_opacity", 0.0),
            loc="page_damage.glaze_opacity",
            min_value=0.0,
            max_value=1.0,
        )
        max_assets = _positive_int(
            raw.get("max_assets_per_page", 2),
            loc="page_damage.max_assets_per_page",
        )
        skip = _skip_targets(raw.get("skip", DEFAULT_PAGE_DAMAGE_SKIP))
        return cls(
            enabled=bool(raw.get("enabled", False)),
            art_dir=_str_or_none(raw.get("art_dir")) or "page-wear",
            seed=_str_or_none(raw.get("seed")),
            density=density,
            max_assets_per_page=max_assets,
            opacity=opacity,
            glaze_opacity=glaze_opacity,
            glaze_texture=(
                _str_or_none(raw.get("glaze_texture"))
                or "surface-warm-paper-tint-cloud.png"
            ),
            skip=skip,
        )


# ---------------------------------------------------------------------------
# Conditional filler art spec
# ---------------------------------------------------------------------------


# Filler shape names accepted in recipe filler assets and slots.
FILLER_SHAPES = {
    "tailpiece",
    "spot",
    "small-wide",
    "plate",
    "bottom-band",
    "page-finish",
    "corner-left",
    "corner-right",
    "page-wear",
    "full-page",
}


@dataclass(frozen=True)
class FillerTerminalMarkersSpec:
    """BookConfig policy for terminal chapter filler markers."""

    chapter_slots: tuple[str, ...] = ("chapter-end",)
    class_slots: tuple[str, ...] = ("class-end",)

    @classmethod
    def from_raw(cls, raw: object, *, loc: str) -> FillerTerminalMarkersSpec:
        """Parse the optional ``fillers.markers.terminal`` value."""
        if raw is None:
            return cls()
        if raw is False:
            return cls(chapter_slots=(), class_slots=())
        if not isinstance(raw, Mapping):
            raise BookConfigError(f"{loc} must be a mapping or false")
        return cls(
            chapter_slots=_marker_slots_or_none(
                _marker_raw_value(raw, "chapter_slots"),
                default="chapter-end",
                loc=f"{loc}.chapter_slots",
            ),
            class_slots=_marker_slots_or_none(
                _marker_raw_value(raw, "class_slots"),
                default="class-end",
                loc=f"{loc}.class_slots",
            ),
        )


@dataclass(frozen=True)
class FillerSourceBoundaryMarkersSpec:
    """BookConfig policy for sequence source-boundary filler markers."""

    sequence_slots: tuple[str, ...] = ("section-end",)

    @classmethod
    def from_raw(cls, raw: object, *, loc: str) -> FillerSourceBoundaryMarkersSpec:
        """Parse the optional ``fillers.markers.source_boundary`` value."""
        if raw is None:
            return cls()
        if raw is False:
            return cls(sequence_slots=())
        if isinstance(raw, str):
            return cls(sequence_slots=(_required_marker_slot(raw, loc=loc),))
        if not isinstance(raw, Mapping):
            raise BookConfigError(f"{loc} must be a mapping, string, or false")
        return cls(
            sequence_slots=_marker_slots_or_none(
                _marker_raw_value(raw, "sequence_slots"),
                default="section-end",
                loc=f"{loc}.sequence_slots",
            )
        )


@dataclass(frozen=True)
class FillerSubclassMarkersSpec:
    """BookConfig policy for subclass source-end filler markers."""

    slots: tuple[str, ...] = ("subclass-end",)

    @classmethod
    def from_raw(cls, raw: object, *, loc: str) -> FillerSubclassMarkersSpec:
        """Parse the optional ``fillers.markers.subclass`` value."""
        if raw is None:
            return cls()
        if raw is False:
            return cls(slots=())
        if isinstance(raw, str):
            return cls(slots=(_required_marker_slot(raw, loc=loc),))
        if not isinstance(raw, Mapping):
            raise BookConfigError(f"{loc} must be a mapping, string, or false")
        return cls(
            slots=_marker_slots_or_none(
                _marker_raw_value(raw, "slots"),
                default="subclass-end",
                loc=f"{loc}.slots",
            )
        )


@dataclass(frozen=True)
class FillerHeadingMarkerSpec:
    """BookConfig policy for generated section-end filler markers."""

    chapter: str
    slot: str
    heading_level: int
    slot_kind: str
    skip_first: bool = False
    context: str | None = None

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, object],
        *,
        index: int,
    ) -> FillerHeadingMarkerSpec:
        """Parse one ``fillers.markers.headings`` entry."""
        loc = f"fillers.markers.headings[{index}]"
        chapter = _str_or_none(raw.get("chapter"))
        if chapter is None:
            raise BookConfigError(f"{loc}.chapter is required")
        slot = _required_marker_slot(raw.get("slot"), loc=f"{loc}.slot")
        heading_level = _positive_int(
            raw.get("heading_level"),
            loc=f"{loc}.heading_level",
        )
        if heading_level > 6:
            raise BookConfigError(f"{loc}.heading_level must be between 1 and 6")
        return cls(
            chapter=chapter,
            slot=slot,
            heading_level=heading_level,
            slot_kind=(_str_or_none(raw.get("slot_kind")) or slot.removesuffix("-end")),
            skip_first=bool(raw.get("skip_first", False)),
            context=_str_or_none(raw.get("context")),
        )


def _default_heading_marker_specs() -> list[FillerHeadingMarkerSpec]:
    return [
        FillerHeadingMarkerSpec(
            chapter="frames",
            slot="frame-family-end",
            heading_level=1,
            slot_kind="frame-family",
            skip_first=True,
            context="frame",
        ),
        FillerHeadingMarkerSpec(
            chapter="backgrounds",
            slot="background-section-end",
            heading_level=2,
            slot_kind="background-section",
            context="setting",
        ),
    ]


@dataclass(frozen=True)
class FillerMarkersSpec:
    """BookConfig policy for generated invisible filler marker slots."""

    terminal: FillerTerminalMarkersSpec = field(
        default_factory=FillerTerminalMarkersSpec
    )
    source_boundary: FillerSourceBoundaryMarkersSpec = field(
        default_factory=FillerSourceBoundaryMarkersSpec
    )
    subclass: FillerSubclassMarkersSpec = field(
        default_factory=FillerSubclassMarkersSpec
    )
    headings: list[FillerHeadingMarkerSpec] = field(
        default_factory=_default_heading_marker_specs
    )

    @classmethod
    def from_dict(cls, raw: object) -> FillerMarkersSpec:
        """Build marker policy from the optional ``fillers.markers`` mapping."""
        if raw is None:
            return cls()
        if not isinstance(raw, Mapping):
            raise BookConfigError("fillers.markers must be a mapping when provided")
        headings_raw = raw.get("headings", _default_heading_marker_specs())
        if not isinstance(headings_raw, list):
            raise BookConfigError("fillers.markers.headings must be a list")
        headings: list[FillerHeadingMarkerSpec] = []
        for i, item in enumerate(headings_raw):
            if isinstance(item, FillerHeadingMarkerSpec):
                headings.append(item)
                continue
            if not isinstance(item, Mapping):
                raise BookConfigError(
                    f"fillers.markers.headings[{i}] must be a mapping"
                )
            headings.append(FillerHeadingMarkerSpec.from_dict(item, index=i))
        return cls(
            terminal=FillerTerminalMarkersSpec.from_raw(
                raw.get("terminal"),
                loc="fillers.markers.terminal",
            ),
            source_boundary=FillerSourceBoundaryMarkersSpec.from_raw(
                raw.get("source_boundary"),
                loc="fillers.markers.source_boundary",
            ),
            subclass=FillerSubclassMarkersSpec.from_raw(
                raw.get("subclass"),
                loc="fillers.markers.subclass",
            ),
            headings=headings,
        )


@dataclass(frozen=True)
class FillerAssetSpec:
    """One recipe-level filler art asset candidate."""

    id: str
    art: str
    shape: str
    height_in: float

    @classmethod
    def from_dict(cls, raw: Mapping[str, object], *, index: int) -> FillerAssetSpec:
        """Parse and validate one item in ``fillers.assets``."""
        loc = f"fillers.assets[{index}]"
        asset_id = _slug_or_none(raw.get("id"), loc=loc)
        if asset_id is None:
            raise BookConfigError(f"{loc}.id is required")
        art = _str_or_none(raw.get("art"))
        if art is None:
            raise BookConfigError(f"{loc}.art is required")
        shape = _str_or_none(raw.get("shape"))
        if shape not in FILLER_SHAPES:
            raise BookConfigError(f"{loc}.shape must be one of {sorted(FILLER_SHAPES)}")
        return cls(
            id=asset_id,
            art=art,
            shape=shape,
            height_in=_inch_value(raw.get("height"), loc=f"{loc}.height"),
        )


@dataclass(frozen=True)
class FillerSlotSpec:
    """One named conditional filler slot recipe."""

    name: str
    min_space_in: float
    max_space_in: float
    shapes: list[str]

    @classmethod
    def from_dict(
        cls,
        name: str,
        raw: Mapping[str, object],
        *,
        loc: str,
    ) -> FillerSlotSpec:
        """Parse one ``fillers.slots`` mapping value."""
        shapes_raw = raw.get("shapes")
        if not isinstance(shapes_raw, list) or not shapes_raw:
            raise BookConfigError(f"{loc}.shapes must be a non-empty list")
        shapes: list[str] = []
        for i, shape_raw in enumerate(shapes_raw):
            shape = _str_or_none(shape_raw)
            if shape not in FILLER_SHAPES:
                raise BookConfigError(
                    f"{loc}.shapes[{i}] must be one of {sorted(FILLER_SHAPES)}"
                )
            shapes.append(shape)
        min_space = _inch_value(raw.get("min_space"), loc=f"{loc}.min_space")
        max_space = _inch_value(raw.get("max_space"), loc=f"{loc}.max_space")
        if max_space < min_space:
            raise BookConfigError(f"{loc}.max_space must be >= min_space")
        return cls(
            name=name,
            min_space_in=min_space,
            max_space_in=max_space,
            shapes=shapes,
        )


@dataclass(frozen=True)
class FillersSpec:
    """BookConfig-level conditional filler art configuration."""

    enabled: bool = False
    art_dir: str | None = None
    slots: dict[str, FillerSlotSpec] = field(default_factory=dict)
    assets: list[FillerAssetSpec] = field(default_factory=list)
    markers: FillerMarkersSpec = field(default_factory=FillerMarkersSpec)

    @classmethod
    def from_dict(cls, raw: Mapping[str, object] | None) -> FillersSpec:
        """Build filler settings from the recipe's optional mapping."""
        if not raw:
            return cls()
        slots_raw = raw.get("slots") or {}
        if not isinstance(slots_raw, Mapping):
            raise BookConfigError("fillers.slots must be a mapping when provided")
        slots: dict[str, FillerSlotSpec] = {}
        for name, slot_raw in slots_raw.items():
            slot_name = str(name).strip()
            if not slot_name:
                raise BookConfigError("fillers.slots keys must be non-empty")
            if not isinstance(slot_raw, Mapping):
                raise BookConfigError(f"fillers.slots.{slot_name} must be a mapping")
            slots[slot_name] = FillerSlotSpec.from_dict(
                slot_name,
                slot_raw,
                loc=f"fillers.slots.{slot_name}",
            )

        assets_raw = raw.get("assets") or []
        if not isinstance(assets_raw, list):
            raise BookConfigError("fillers.assets must be a list when provided")
        assets: list[FillerAssetSpec] = []
        for i, asset_raw in enumerate(assets_raw):
            if not isinstance(asset_raw, Mapping):
                raise BookConfigError(
                    f"fillers.assets[{i}] must be a mapping, "
                    f"got {type(asset_raw).__name__}"
                )
            assets.append(FillerAssetSpec.from_dict(asset_raw, index=i))

        return cls(
            enabled=bool(raw.get("enabled", False)),
            art_dir=_str_or_none(raw.get("art_dir")),
            slots=slots,
            assets=assets,
            markers=FillerMarkersSpec.from_dict(raw.get("markers")),
        )


# ---------------------------------------------------------------------------
# Splash art spec
# ---------------------------------------------------------------------------


# BookConfig targets that describe when splash art should be placed.
SPLASH_TARGETS = {
    "front-cover",
    "back-cover",
    "chapter-start",
    "after-heading",
}
# Splash placement modes supported by the renderer.
SPLASH_PLACEMENTS = {
    "cover",
    "back-cover",
    "corner-left",
    "corner-right",
    "bottom-half",
}


@dataclass(frozen=True)
class SplashSpec:
    """One large recipe-level splash art placement."""

    id: str
    art: str
    target: str
    placement: str
    chapter: str | None = None
    heading: str | None = None

    @classmethod
    def from_dict(cls, raw: Mapping[str, object], *, index: int) -> SplashSpec:
        """Parse and validate one item in the top-level ``splashes:`` list."""
        loc = f"splashes[{index}]"
        splash_id = _slug_or_none(raw.get("id"), loc=loc)
        if splash_id is None:
            raise BookConfigError(f"{loc}.id is required")
        art = _str_or_none(raw.get("art"))
        if art is None:
            raise BookConfigError(f"{loc}.art is required")
        target = _str_or_none(raw.get("target"))
        if target not in SPLASH_TARGETS:
            raise BookConfigError(
                f"{loc}.target must be one of {sorted(SPLASH_TARGETS)}"
            )
        placement = _str_or_none(raw.get("placement"))
        if placement not in SPLASH_PLACEMENTS:
            raise BookConfigError(
                f"{loc}.placement must be one of {sorted(SPLASH_PLACEMENTS)}"
            )

        chapter = _str_or_none(raw.get("chapter"))
        heading = _str_or_none(raw.get("heading"))
        if target in {"chapter-start", "after-heading"} and chapter is None:
            raise BookConfigError(f"{loc}.chapter is required for target={target!r}")
        if target == "after-heading" and heading is None:
            raise BookConfigError(
                f"{loc}.heading is required for target='after-heading'"
            )
        if target in {"front-cover", "back-cover"} and chapter is not None:
            raise BookConfigError(f"{loc}.chapter is only valid for chapter splashes")
        if target != "after-heading" and heading is not None:
            raise BookConfigError(
                f"{loc}.heading is only valid for target='after-heading'"
            )

        return cls(
            id=splash_id,
            art=art,
            target=target,
            placement=placement,
            chapter=chapter,
            heading=heading,
        )


@dataclass(frozen=True)
class ArtInsertSpec:
    """One content-scoped art placement declared on a contents item."""

    id: str | None
    role: str
    art: str | None
    context: str | None
    target: str
    placement: str
    heading: str | None = None

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, object],
        *,
        index: int,
        loc: str,
    ) -> ArtInsertSpec:
        """Parse one item from a content item's ``art:`` insert list."""
        item_loc = f"{loc}.art[{index}]"
        role = _str_or_none(raw.get("role")) or "splash"
        if role != "splash":
            raise BookConfigError(f"{item_loc}.role currently supports only 'splash'")
        placement = _str_or_none(raw.get("placement")) or "bottom-half"
        if placement not in {"corner-left", "corner-right", "bottom-half"}:
            raise BookConfigError(
                f"{item_loc}.placement must be one of "
                "['bottom-half', 'corner-left', 'corner-right']"
            )
        heading = _str_or_none(raw.get("after_heading") or raw.get("heading"))
        target = _str_or_none(raw.get("target"))
        if heading is not None:
            target = "after-heading"
        target = target or "chapter-start"
        if target not in {"chapter-start", "after-heading"}:
            raise BookConfigError(
                f"{item_loc}.target must be 'chapter-start' or 'after-heading'"
            )
        if target == "after-heading" and heading is None:
            raise BookConfigError(
                f"{item_loc}.after_heading is required for target='after-heading'"
            )
        return cls(
            id=_slug_or_none(raw.get("id"), loc=item_loc),
            role=role,
            art=_str_or_none(raw.get("art")),
            context=_str_or_none(raw.get("context")),
            target=target,
            placement=placement,
            heading=heading,
        )


# ---------------------------------------------------------------------------
# Source reference: vault:relative/path.md
# ---------------------------------------------------------------------------


# Parses optional vault prefixes from recipe source references.
_SOURCE_RE = re.compile(r"^(?:(?P<vault>[A-Za-z0-9_-]+):)?(?P<path>.+)$")


@dataclass(frozen=True)
class SourceRef:
    """A `vault:path` reference parsed from a recipe.

    `vault` may be None to indicate "search the vault overlay".
    `path` is always the relative path inside the chosen vault, with
    forward slashes normalized.
    """

    vault: str | None
    path: str

    @classmethod
    def parse(cls, raw: str) -> SourceRef:
        """Parse a raw recipe source string into a structured reference."""
        if not raw or not raw.strip():
            raise BookConfigError("empty source reference")
        m = _SOURCE_RE.match(raw.strip())
        if not m:
            raise BookConfigError(f"invalid source reference: {raw!r}")
        vault = m.group("vault")
        path = m.group("path").replace("\\", "/").lstrip("/")
        return cls(vault=vault, path=path)

    def __str__(self) -> str:
        return f"{self.vault}:{self.path}" if self.vault else self.path


# ---------------------------------------------------------------------------
# Cover spec
# ---------------------------------------------------------------------------


@dataclass
class CoverSpec:
    """Optional cover art configuration for a combined book."""

    enabled: bool = False
    art: str | None = None  # filename relative to recipe.art_dir

    @classmethod
    def from_dict(cls, raw: Mapping[str, object] | None) -> CoverSpec:
        """Build a cover spec from the recipe's optional ``cover`` mapping."""
        if not raw:
            return cls()
        return cls(
            enabled=bool(raw.get("enabled", False)),
            art=_str_or_none(raw.get("art")),
        )


# ---------------------------------------------------------------------------
# Ornament spec
# ---------------------------------------------------------------------------


@dataclass
class OrnamentsSpec:
    """Optional page furniture art shared across a recipe."""

    folio_frame: str | None = None  # filename relative to recipe.art_dir
    corner_bracket: str | None = None  # reserved; disabled unless explicitly set

    @classmethod
    def from_dict(cls, raw: Mapping[str, object] | None) -> OrnamentsSpec:
        """Build ornament settings from the recipe's optional mapping."""
        if not raw:
            return cls()
        return cls(
            folio_frame=_str_or_none(raw.get("folio_frame")),
            corner_bracket=_str_or_none(raw.get("corner_bracket")),
        )


# ---------------------------------------------------------------------------
# Source items
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceItem:
    """One ordered source inside a `sequence` chapter.

    A bare string item is treated as `{source: "vault:path"}`. A mapping can
    also provide `title`, which assembly.py will insert as a heading when the
    referenced file does not already start with an H1. This keeps shared source
    pages readable when they are threaded into a reskinned chapter.
    """

    source: SourceRef
    title: str | None = None
    strip_related: bool = False
    filler_enabled: bool = True

    @classmethod
    def from_raw(cls, raw: object, *, loc: str) -> SourceItem:
        """Parse a raw sequence item from a source string or mapping."""
        if isinstance(raw, str):
            return cls(source=SourceRef.parse(raw))
        if not isinstance(raw, Mapping):
            raise BookConfigError(
                f"{loc} must be a source string or mapping, got {type(raw).__name__}"
            )
        source_raw = raw.get("source")
        if not isinstance(source_raw, str) or not source_raw.strip():
            raise BookConfigError(f"{loc}.source is required")
        return cls(
            source=SourceRef.parse(source_raw),
            title=_str_or_none(raw.get("title")),
            strip_related=bool(raw.get("strip_related", False)),
            filler_enabled=_bool_value(raw.get("filler", True), loc=f"{loc}.filler"),
        )


# ---------------------------------------------------------------------------
# Content item spec
# ---------------------------------------------------------------------------


# Structural content kinds accepted in book contents.
CONTENT_ITEM_KINDS = {
    "file",
    "catalog",
    "composite",
    "classes-catalog",
    "folder",
    "group",
    "sequence",
    "toc",
    "generated",
}

# Kinds that don't need (or use) their own `source:` field. `group` is a
# pure structural wrapper around its `children:`. `sequence` uses `sources:`.
_KINDS_WITHOUT_SOURCE = {"group", "sequence", "toc", "generated"}


@dataclass
class ContentItemSpec:
    """One entry in the book's ordered `contents:` list.

    `kind` is structural (how to assemble files into chapter content).
    `style` is semantic (the CSS hook value passed to the template as
    `section-kind` metadata; CSS targets `body.section-<style>`).
    """

    # file | catalog | composite | classes-catalog | folder | group | sequence
    kind: str
    # computed content kind for `kind: generated`
    type: str | None = None
    # required for every kind except `group`
    source: SourceRef | None = None
    # optional; some kinds derive it
    title: str | None = None
    # optional explicit PDF/link anchor
    slug: str | None = None
    eyebrow: str | None = None
    # filename in recipe.art_dir
    art: str | None = None
    # content-scoped art placements
    art_inserts: list[ArtInsertSpec] = field(default_factory=list)
    # CSS hook
    style: str = "default"
    # Wrapper / nesting options (used by classes-catalog AND group)
    # produce a wrapper chapter or flatten
    wrapper: bool = False
    # style applied to per-child chapters
    child_style: str = "default"
    # emit a section-divider page for EACH child
    child_divider: bool = False
    # group-kind sub-chapters
    children: list[ContentItemSpec] = field(default_factory=list)
    # sequence-kind ordered sources
    sources: list[SourceItem] = field(default_factory=list)
    # heading slugs/titles to start on a new page
    full_page_sections: list[str] = field(default_factory=list)
    # optional headpiece rendered near the top of the chapter body
    headpiece: str | None = None
    # optional ornament used to replace thematic breaks in this chapter
    break_ornament: str | None = None
    # combined-book TOC depth for this top-level chapter
    toc_depth: int | None = None
    # `kind: toc` depth cap
    depth: int | None = None
    # classes-catalog options
    # also emit per-leaf standalone PDFs
    individual_pdfs: bool = False
    # subfolder under output/ for individual PDFs
    individual_pdf_subdir: str | None = None
    # auto-pick recipe.art_dir/<slug>.png per child
    art_per_class: bool = False
    # auto-pick divider art for classes-catalog children from a filename pattern
    class_art_pattern: str | None = None
    # auto-pick an opening class spot for classes-catalog children
    class_spot_art_pattern: str | None = None
    # remove a leading hand-authored art spot when class spot art is injected
    replace_existing_opening_art: bool = False
    # optional end-of-chapter ornament; filename relative to recipe.art_dir
    tailpiece: str | None = None
    # disable generated filler markers inside this chapter.
    fillers_enabled: bool = True

    @classmethod
    def from_dict(
        cls,
        raw: Mapping[str, object],
        *,
        index: int,
        path: str = "",
    ) -> ContentItemSpec:
        """Parse and validate one chapter mapping from the recipe YAML."""
        loc = f"contents[{index}]" if not path else f"{path}.children[{index}]"
        if not isinstance(raw, Mapping):
            raise BookConfigError(f"{loc} must be a mapping, got {type(raw).__name__}")
        kind = _chapter_kind(raw, loc=loc)
        generated_type = _chapter_generated_type(kind, raw, loc=loc)
        source = _chapter_source(kind, raw, loc=loc)
        sources = _chapter_sources(kind, raw, loc=loc)
        children = _chapter_children(kind, raw, loc=loc, parser=cls)
        full_page_sections = _chapter_full_page_sections(raw, loc=loc)
        toc_depth, depth = _chapter_toc_depths(kind, raw, loc=loc)
        chapter_art, art_inserts = _chapter_art_fields(raw, loc=loc)

        return cls(
            kind=kind,
            type=generated_type,
            source=source,
            title=_str_or_none(raw.get("title")),
            slug=_slug_or_none(raw.get("slug"), loc=loc),
            eyebrow=_str_or_none(raw.get("eyebrow")),
            art=chapter_art,
            art_inserts=art_inserts,
            style=str(raw.get("style", "default")),
            wrapper=bool(raw.get("wrapper", False)),
            child_style=str(raw.get("child_style", "default")),
            child_divider=bool(raw.get("child_divider", False)),
            children=children,
            sources=sources,
            full_page_sections=full_page_sections,
            headpiece=_str_or_none(raw.get("headpiece")),
            break_ornament=_str_or_none(raw.get("break_ornament")),
            toc_depth=toc_depth,
            depth=depth,
            individual_pdfs=bool(raw.get("individual_pdfs", False)),
            individual_pdf_subdir=_str_or_none(raw.get("individual_pdf_subdir")),
            art_per_class=bool(raw.get("art_per_class", False)),
            class_art_pattern=_str_or_none(raw.get("class_art_pattern")),
            class_spot_art_pattern=_str_or_none(raw.get("class_spot_art_pattern")),
            replace_existing_opening_art=bool(
                raw.get("replace_existing_opening_art", False)
            ),
            tailpiece=_str_or_none(raw.get("tailpiece")),
            fillers_enabled=_bool_value(raw.get("fillers", True), loc=f"{loc}.fillers"),
        )


def _chapter_kind(raw: Mapping[str, object], *, loc: str) -> str:
    """Validate or infer the structural kind for one contents item."""
    kind_raw = raw.get("kind")
    if kind_raw is None:
        kind = _infer_content_kind(raw, loc=loc)
    elif isinstance(kind_raw, str):
        kind = kind_raw
    else:
        raise BookConfigError(f"{loc}.kind must be a string")
    if kind not in CONTENT_ITEM_KINDS:
        raise BookConfigError(
            f"{loc}.kind={kind!r} is not one of {sorted(CONTENT_ITEM_KINDS)}"
        )
    return kind


def _chapter_generated_type(
    kind: str,
    raw: Mapping[str, object],
    *,
    loc: str,
) -> str | None:
    """Validate the optional computed content type."""
    generated_type = _str_or_none(raw.get("type"))
    if kind == "generated" and generated_type not in GENERATED_CONTENT_TYPES:
        raise BookConfigError(
            f"{loc}.type must be one of {sorted(GENERATED_CONTENT_TYPES)}"
        )
    if kind != "generated" and generated_type is not None:
        raise BookConfigError(f"{loc}.type is only valid for kind='generated'")
    return generated_type


def _chapter_source(
    kind: str,
    raw: Mapping[str, object],
    *,
    loc: str,
) -> SourceRef | None:
    """Validate a chapter's single source field, when its kind uses one."""
    source_raw = raw.get("source")
    if kind in _KINDS_WITHOUT_SOURCE:
        if source_raw is not None:
            raise BookConfigError(
                f"{loc} kind={kind!r} should not declare `source:` "
                f"(use `children:` for groups or `sources:` for sequences)"
            )
        return None
    if not isinstance(source_raw, str) or not source_raw.strip():
        raise BookConfigError(f"{loc} missing required field: source")
    try:
        return SourceRef.parse(source_raw)
    except BookConfigError as e:
        raise BookConfigError(f"{loc}: {e}") from e


def _chapter_sources(
    kind: str,
    raw: Mapping[str, object],
    *,
    loc: str,
) -> list[SourceItem]:
    """Validate the ordered source list used by sequence chapters."""
    sources_raw = raw.get("sources")
    if kind != "sequence":
        if sources_raw is not None:
            raise BookConfigError(
                f"{loc}.sources is only valid for kind='sequence' (got kind={kind!r})"
            )
        return []
    if not isinstance(sources_raw, list) or not sources_raw:
        raise BookConfigError(
            f"{loc} kind='sequence' requires a non-empty `sources:` list"
        )
    sources: list[SourceItem] = []
    for i, item in enumerate(sources_raw):
        try:
            sources.append(SourceItem.from_raw(item, loc=f"{loc}.sources[{i}]"))
        except BookConfigError as e:
            raise BookConfigError(str(e)) from e
    return sources


def _chapter_children(
    kind: str,
    raw: Mapping[str, object],
    *,
    loc: str,
    parser: type[ContentItemSpec],
) -> list[ContentItemSpec]:
    """Validate and recursively parse group children."""
    if "sort" in raw:
        raise BookConfigError(
            f"{loc}.sort is no longer supported; folder ordering is always "
            "alphabetical. Remove the field from your recipe."
        )

    children_raw = raw.get("children") or []
    if not isinstance(children_raw, list):
        raise BookConfigError(
            f"{loc}.children must be a list, got {type(children_raw).__name__}"
        )
    if kind == "group" and not children_raw:
        raise BookConfigError(
            f"{loc} kind='group' requires a non-empty `children:` list"
        )
    if kind != "group" and children_raw:
        raise BookConfigError(
            f"{loc}.children is only valid for kind='group' (got kind={kind!r})"
        )

    children: list[ContentItemSpec] = []
    for i, child_raw in enumerate(children_raw):
        if not isinstance(child_raw, Mapping):
            raise BookConfigError(
                f"{loc}.children[{i}] must be a mapping, got {type(child_raw).__name__}"
            )
        children.append(parser.from_dict(child_raw, index=i, path=loc))
    return children


def _chapter_full_page_sections(
    raw: Mapping[str, object],
    *,
    loc: str,
) -> list[str]:
    """Validate explicit full-page heading breaks."""
    sections_raw = raw.get("full_page_sections") or []
    if not isinstance(sections_raw, list) or not all(
        isinstance(x, str) for x in sections_raw
    ):
        raise BookConfigError(
            f"{loc}.full_page_sections must be a list of heading titles/slugs"
        )
    return [str(section) for section in sections_raw]


def _chapter_toc_depths(
    kind: str,
    raw: Mapping[str, object],
    *,
    loc: str,
) -> tuple[int | None, int | None]:
    """Validate combined-book and generated TOC depth settings."""
    toc_depth = _toc_depth_or_none(raw.get("toc_depth"), loc=loc)
    depth = _toc_depth_or_none(raw.get("depth"), loc=loc)
    if depth is not None and kind != "toc":
        raise BookConfigError(f"{loc}.depth is only valid for kind='toc'")
    return toc_depth, depth


def _chapter_art_fields(
    raw: Mapping[str, object],
    *,
    loc: str,
) -> tuple[str | None, list[ArtInsertSpec]]:
    """Split divider art and content-scoped art inserts."""
    art_raw = raw.get("art")
    if not isinstance(art_raw, list):
        return _str_or_none(art_raw) if art_raw is not None else None, []

    art_inserts: list[ArtInsertSpec] = []
    for i, art_item in enumerate(art_raw):
        if not isinstance(art_item, Mapping):
            raise BookConfigError(
                f"{loc}.art[{i}] must be a mapping, got {type(art_item).__name__}"
            )
        art_inserts.append(ArtInsertSpec.from_dict(art_item, index=i, loc=loc))
    return None, art_inserts


# ---------------------------------------------------------------------------
# BookConfig
# ---------------------------------------------------------------------------


# Theme used when a book config does not specify one.
DEFAULT_THEME = "industrial"

# Computed content page types accepted in book contents.
GENERATED_CONTENT_TYPES = {
    "art-credits",
    "appendix-index",
    "changelog",
    "copyright",
    "credits",
    "license",
    "title-page",
}


@dataclass(frozen=True)
class BookMetadataSpec:
    """Optional book metadata used for generated matter and PDF metadata."""

    authors: list[str] = field(default_factory=list)
    editor: str | None = None
    version: str | None = None
    date: str | None = None
    publisher: str | None = None
    license: str | None = None
    description: str | None = None
    keywords: list[str] = field(default_factory=list)
    credits: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Mapping[str, object] | None) -> BookMetadataSpec:
        """Build metadata settings from the optional recipe mapping."""
        if not raw:
            return cls()
        return cls(
            authors=_string_list_or_one(raw.get("authors", raw.get("author"))),
            editor=_str_or_none(raw.get("editor")),
            version=_str_or_none(raw.get("version")),
            date=_str_or_none(raw.get("date")),
            publisher=_str_or_none(raw.get("publisher")),
            license=_str_or_none(raw.get("license")),
            description=_str_or_none(raw.get("description")),
            keywords=_string_list_or_one(raw.get("keywords")),
            credits=_credits_mapping(raw.get("credits")),
        )


@dataclass
class VaultSpec:
    """A vault declared in the recipe's `vaults:` mapping."""

    name: str  # alias used in source refs (e.g. "custom")
    path: Path  # absolute path to the vault root


@dataclass
class BookConfig:
    """A fully validated recipe ready for manifest construction."""

    title: str
    subtitle: str | None
    cover_eyebrow: str | None
    cover_footer: str | None
    vaults: dict[str, VaultSpec]  # name -> VaultSpec
    vault_overlay: list[str]  # priority order, first = lowest
    cover: CoverSpec
    contents: list[ContentItemSpec]
    recipe_path: Path  # where this recipe was loaded from
    output_dir_override: Path | None = None
    output_name: str | None = None
    cache_dir_override: Path | None = None
    theme: str = DEFAULT_THEME
    theme_dir_override: Path | None = None
    theme_options: dict[str, str] = field(default_factory=dict)
    image_treatments: dict[str, str] = field(default_factory=dict)
    metadata: BookMetadataSpec = field(default_factory=BookMetadataSpec)
    art_dir_override: Path | None = None  # optional override for art assets
    art_roles: dict[str, ArtRoleSpec] = field(default_factory=dict)
    ornaments: OrnamentsSpec = field(default_factory=OrnamentsSpec)
    splashes: list[SplashSpec] = field(default_factory=list)
    fillers: FillersSpec = field(default_factory=FillersSpec)
    page_damage: PageDamageSpec = field(default_factory=PageDamageSpec)

    def vault_priority_paths(self) -> list[Path]:
        """Return vault paths in overlay priority order (first = lowest priority)."""
        return [self.vaults[name].path for name in self.vault_overlay]

    def vault_by_name(self, name: str) -> VaultSpec | None:
        """Return a declared vault by alias, or ``None`` if missing."""
        return self.vaults.get(name)

    @property
    def project_dir(self) -> Path:
        """Resolve the project root for this book config."""
        return self.recipe_path.parent.resolve()

    @property
    def art_dir(self) -> Path:
        """Return the directory used for cover and chapter art assets."""
        return self.art_dir_override or (self.project_dir / "Art")

    @property
    def output_dir(self) -> Path:
        """Return the caller-owned base directory for generated files."""
        return self.output_dir_override or self.project_dir

    @property
    def generated_name(self) -> str:
        """Return the generated-output directory name for this recipe."""
        if self.output_name:
            return self.output_name
        return _filename_slug(self.title)

    @property
    def generated_root(self) -> Path:
        """Return the root below which all generated files are written."""
        return self.output_dir / "Paper Crown" / self.generated_name

    @property
    def cache_dir(self) -> Path:
        """Return the cache directory for exports and optimized assets."""
        return self.cache_dir_override or (self.generated_root / "cache")


def _filename_slug(value: str) -> str:
    """Return a filesystem-friendly lowercase slug for generated folders."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "book"


def _infer_content_kind(raw: Mapping[str, object], *, loc: str) -> str:
    """Infer a contents item kind from its shape when ``kind`` is omitted."""
    if "sources" in raw:
        return "sequence"
    if "children" in raw:
        return "group"
    if "type" in raw:
        return "generated"
    if "source" in raw:
        return "file"
    raise BookConfigError(f"{loc}.kind must be a string")


def _str_or_none(value: object) -> str | None:
    """Return a stripped string for truthy values, otherwise ``None``."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _bool_value(value: object, *, loc: str) -> bool:
    """Validate a boolean recipe value."""
    if not isinstance(value, bool):
        raise BookConfigError(f"{loc} must be true or false")
    return value


def _required_marker_slot(value: object, *, loc: str) -> str:
    """Validate one filler marker slot name."""
    slot = _str_or_none(value)
    if slot is None:
        raise BookConfigError(f"{loc} is required")
    if not re.match(r"^[A-Za-z0-9_-]+$", slot):
        raise BookConfigError(
            f"{loc} must contain only letters, numbers, underscores, and hyphens"
        )
    return slot


def _marker_slot_or_none(
    value: object,
    *,
    default: str,
    loc: str,
) -> str | None:
    """Parse an optional marker slot where false disables the marker."""
    if value is None:
        return default
    if value is False:
        return None
    return _required_marker_slot(value, loc=loc)


def _marker_raw_value(raw: Mapping[str, object], *keys: str) -> object:
    """Return the first present marker config value from a mapping."""
    for key in keys:
        if key in raw:
            return raw[key]
    return None


def _marker_slots_or_none(
    value: object,
    *,
    default: str,
    loc: str,
) -> tuple[str, ...]:
    """Parse optional marker slot names where false disables the marker."""
    if value is None:
        return (default,)
    if value is False:
        return ()
    if isinstance(value, list):
        slots: list[str] = []
        for i, item in enumerate(value):
            if item is False:
                raise BookConfigError(f"{loc}[{i}] must be a marker slot name")
            slots.append(_required_marker_slot(item, loc=f"{loc}[{i}]"))
        return tuple(slots)
    return (_required_marker_slot(value, loc=loc),)


def _string_list_or_one(value: object) -> list[str]:
    """Normalize a string or list of strings into a stripped list."""
    if value is None:
        return []
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if not isinstance(value, list):
        raise BookConfigError("expected a string or list of strings")
    items: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise BookConfigError("expected a string or list of strings")
        item = raw.strip()
        if item:
            items.append(item)
    return items


def _credits_mapping(value: object) -> dict[str, list[str]]:
    """Validate and normalize metadata credits into role -> names."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BookConfigError("metadata.credits must be a mapping")
    credits: dict[str, list[str]] = {}
    for raw_role, raw_names in value.items():
        role = str(raw_role).strip()
        if not role:
            raise BookConfigError("metadata.credits keys must be non-empty")
        credits[role] = _string_list_or_one(raw_names)
    return credits


def _theme_options_mapping(value: object) -> dict[str, str]:
    """Validate theme option overrides."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BookConfigError("theme_options must be a mapping")
    options: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            raise BookConfigError("theme_options keys must be non-empty")
        if raw_value is None:
            continue
        options[key] = str(raw_value).strip()
    return options


def _image_treatments_mapping(value: object) -> dict[str, str]:
    """Validate recipe image role -> treatment preset overrides."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BookConfigError("image_treatments must be a mapping")
    treatments: dict[str, str] = {}
    for raw_role, raw_treatment in value.items():
        role = str(raw_role).strip()
        if not role:
            raise BookConfigError("image_treatments keys must be non-empty")
        if role not in IMAGE_TREATMENT_ROLE_SELECTORS:
            choices = ", ".join(sorted(IMAGE_TREATMENT_ROLE_SELECTORS))
            raise BookConfigError(
                f"image_treatments role {role!r} is not supported; "
                f"choose one of: {choices}"
            )
        treatment = str(raw_treatment).strip()
        if not treatment:
            raise BookConfigError(f"image_treatments.{role} must be non-empty")
        if treatment == "none":
            treatment = "raw"
        if treatment not in IMAGE_TREATMENT_PRESETS:
            choices = ", ".join(sorted(IMAGE_TREATMENT_PRESETS))
            raise BookConfigError(
                f"image_treatments.{role} preset {treatment!r} is not supported; "
                f"choose one of: {choices}"
            )
        treatments[role] = treatment
    return treatments


def _art_roles_mapping(value: object) -> dict[str, ArtRoleSpec]:
    """Validate project-declared art role classifiers."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise BookConfigError("art_roles must be a mapping")
    roles: dict[str, ArtRoleSpec] = {}
    for raw_role, raw_spec in value.items():
        role = _slug_or_none(raw_role, loc="art_roles") or ""
        if not role:
            raise BookConfigError("art_roles keys must be non-empty")
        if role in roles:
            raise BookConfigError(f"art_roles.{role} is duplicated")
        if not isinstance(raw_spec, Mapping):
            raise BookConfigError(f"art_roles.{role} must be a mapping")
        shape = _str_or_none(raw_spec.get("shape"))
        if shape is not None and shape not in FILLER_SHAPES:
            raise BookConfigError(
                f"art_roles.{role}.shape must be one of {sorted(FILLER_SHAPES)}"
            )
        roles[role] = ArtRoleSpec(
            role=role,
            expected_folder=(
                _str_or_none(raw_spec.get("folder"))
                or _str_or_none(raw_spec.get("expected_folder"))
            ),
            nominal_width_in=_optional_inch_value(
                raw_spec.get("width"),
                loc=f"art_roles.{role}.width",
            ),
            nominal_height_in=_optional_inch_value(
                raw_spec.get("height"),
                loc=f"art_roles.{role}.height",
            ),
            shape=shape,
            transparent=_optional_bool(
                raw_spec.get("transparent"),
                loc=f"art_roles.{role}.transparent",
            ),
            auto_placeable=bool(raw_spec.get("auto_placeable", False)),
            prefixes=_role_prefixes(raw_spec.get("prefixes", raw_spec.get("prefix"))),
        )
    return roles


def _optional_inch_value(value: object, *, loc: str) -> float | None:
    """Parse an optional role size from ``1.5`` or ``1.5in``."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise BookConfigError(f"{loc} must be a positive number or inch string")
    if isinstance(value, int | float):
        parsed = float(value)
        if parsed <= 0:
            raise BookConfigError(f"{loc} must be greater than 0")
        return parsed
    return _inch_value(value, loc=loc)


def _optional_bool(value: object, *, loc: str) -> bool | None:
    """Validate an optional boolean."""
    if value is None:
        return None
    if not isinstance(value, bool):
        raise BookConfigError(f"{loc} must be true or false")
    return value


def _role_prefixes(value: object) -> tuple[str, ...]:
    """Normalize project art role prefixes."""
    if value is None:
        return ()
    raw_prefixes: list[object]
    if isinstance(value, str):
        raw_prefixes = [value]
    elif isinstance(value, list):
        raw_prefixes = value
    else:
        raise BookConfigError("art_roles prefixes must be a string or list")
    prefixes: list[str] = []
    for i, item in enumerate(raw_prefixes):
        prefix = _slug_or_none(item, loc=f"art_roles.prefixes[{i}]")
        if prefix is not None:
            prefixes.append(prefix)
    return tuple(prefixes)


def _slug_or_none(value: object, *, loc: str) -> str | None:
    """Validate and return an optional explicit chapter slug."""
    slug = _str_or_none(value)
    if slug is None:
        return None
    if not re.match(r"^[A-Za-z0-9_-]+$", slug):
        raise BookConfigError(
            f"{loc}.slug must contain only letters, numbers, underscores, and hyphens"
        )
    return slug


def _inch_value(value: object, *, loc: str) -> float:
    """Parse a positive CSS inch value such as ``0.65in``."""
    raw = _str_or_none(value)
    if raw is None:
        raise BookConfigError(f"{loc} is required")
    match = re.fullmatch(r"(?P<num>\d+(?:\.\d+)?)in", raw)
    if match is None:
        raise BookConfigError(f"{loc} must be a positive inch value like '0.65in'")
    parsed = float(match.group("num"))
    if parsed <= 0:
        raise BookConfigError(f"{loc} must be greater than 0")
    return parsed


def _float_between(
    value: object,
    *,
    loc: str,
    min_value: float,
    max_value: float,
) -> float:
    """Parse a numeric value constrained to an inclusive range."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise BookConfigError(f"{loc} must be a number from {min_value} to {max_value}")
    parsed = float(value)
    if parsed < min_value or parsed > max_value:
        raise BookConfigError(f"{loc} must be from {min_value} to {max_value}")
    return parsed


def _positive_int(value: object, *, loc: str) -> int:
    """Parse a positive integer recipe value."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise BookConfigError(f"{loc} must be a positive integer")
    if value <= 0:
        raise BookConfigError(f"{loc} must be a positive integer")
    return int(value)


def _skip_targets(value: object) -> list[str]:
    """Validate page-damage skip target names."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BookConfigError("page_damage.skip must be a list of strings")
    skip: list[str] = []
    for item in value:
        target = item.strip()
        if target not in PAGE_DAMAGE_SKIP_TARGETS:
            raise BookConfigError(
                "page_damage.skip entries must be one of "
                f"{sorted(PAGE_DAMAGE_SKIP_TARGETS)}"
            )
        if target not in skip:
            skip.append(target)
    return skip


def _toc_depth_or_none(value: object, *, loc: str) -> int | None:
    """Validate and return an optional manual TOC depth cap."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise BookConfigError(f"{loc}.toc_depth must be an integer from 1 to 4")
    if value < 1 or value > 4:
        raise BookConfigError(f"{loc}.toc_depth must be between 1 and 4")
    return value
