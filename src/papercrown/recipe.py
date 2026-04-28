"""Recipe loader.

A recipe is a YAML file that declares one book: which vaults to use, what
chapters to include, and how to style the output. Loaded into typed
dataclasses so downstream code can rely on shape and validation.

Recipe shape:

    title: "My Book"
    subtitle: "..."
    cover_eyebrow: "..."
    cover_footer: "..."

    vaults:
      rules: ../my-content-vault

    vault_overlay: [rules]

    output_dir: .                  # optional; generated files go under Paper Crown/
    output_name: my-book           # optional; defaults to a slug of the title
    art_dir: assets/art            # optional; relative to this recipe file

    cover:
      enabled: true
      art: cover.png

    ornaments:
      folio_frame: ornaments/ornament-folio-frame.png

    chapters:
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
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RecipeError(ValueError):
    """Raised when a recipe is malformed or references missing files."""


# ---------------------------------------------------------------------------
# Page damage / wear spec
# ---------------------------------------------------------------------------


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

PAGE_DAMAGE_SIZES = {
    "tiny",
    "small",
    "medium",
    "large",
}

PAGE_DAMAGE_SKIP_TARGETS = {
    "cover",
    "toc",
    "divider",
    "splash",
}

DEFAULT_PAGE_DAMAGE_SKIP = ["cover", "toc", "divider", "splash"]


@dataclass(frozen=True)
class PageDamageSpec:
    """Recipe-level page wear configuration."""

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
    """Recipe policy for terminal chapter filler markers."""

    chapter_slot: str | None = "chapter-end"
    class_slot: str | None = "class-end"

    @classmethod
    def from_raw(cls, raw: object, *, loc: str) -> FillerTerminalMarkersSpec:
        """Parse the optional ``fillers.markers.terminal`` value."""
        if raw is None:
            return cls()
        if raw is False:
            return cls(chapter_slot=None, class_slot=None)
        if not isinstance(raw, Mapping):
            raise RecipeError(f"{loc} must be a mapping or false")
        return cls(
            chapter_slot=_marker_slot_or_none(
                raw.get("chapter_slot", raw.get("chapter")),
                default="chapter-end",
                loc=f"{loc}.chapter_slot",
            ),
            class_slot=_marker_slot_or_none(
                raw.get("class_slot", raw.get("class")),
                default="class-end",
                loc=f"{loc}.class_slot",
            ),
        )


@dataclass(frozen=True)
class FillerSourceBoundaryMarkersSpec:
    """Recipe policy for sequence source-boundary filler markers."""

    sequence_slot: str | None = "section-end"

    @classmethod
    def from_raw(cls, raw: object, *, loc: str) -> FillerSourceBoundaryMarkersSpec:
        """Parse the optional ``fillers.markers.source_boundary`` value."""
        if raw is None:
            return cls()
        if raw is False:
            return cls(sequence_slot=None)
        if isinstance(raw, str):
            return cls(sequence_slot=_required_marker_slot(raw, loc=loc))
        if not isinstance(raw, Mapping):
            raise RecipeError(f"{loc} must be a mapping, string, or false")
        return cls(
            sequence_slot=_marker_slot_or_none(
                raw.get("sequence_slot", raw.get("sequence", raw.get("slot"))),
                default="section-end",
                loc=f"{loc}.sequence_slot",
            )
        )


@dataclass(frozen=True)
class FillerSubclassMarkersSpec:
    """Recipe policy for subclass source-end filler markers."""

    slot: str | None = "subclass-end"

    @classmethod
    def from_raw(cls, raw: object, *, loc: str) -> FillerSubclassMarkersSpec:
        """Parse the optional ``fillers.markers.subclass`` value."""
        if raw is None:
            return cls()
        if raw is False:
            return cls(slot=None)
        if isinstance(raw, str):
            return cls(slot=_required_marker_slot(raw, loc=loc))
        if not isinstance(raw, Mapping):
            raise RecipeError(f"{loc} must be a mapping, string, or false")
        return cls(
            slot=_marker_slot_or_none(
                raw.get("slot"),
                default="subclass-end",
                loc=f"{loc}.slot",
            )
        )


@dataclass(frozen=True)
class FillerHeadingMarkerSpec:
    """Recipe policy for generated section-end filler markers."""

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
            raise RecipeError(f"{loc}.chapter is required")
        slot = _required_marker_slot(raw.get("slot"), loc=f"{loc}.slot")
        heading_level = _positive_int(
            raw.get("heading_level"),
            loc=f"{loc}.heading_level",
        )
        if heading_level > 6:
            raise RecipeError(f"{loc}.heading_level must be between 1 and 6")
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
    """Recipe policy for generated invisible filler marker slots."""

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
            raise RecipeError("fillers.markers must be a mapping when provided")
        headings_raw = raw.get("headings", _default_heading_marker_specs())
        if not isinstance(headings_raw, list):
            raise RecipeError("fillers.markers.headings must be a list")
        headings: list[FillerHeadingMarkerSpec] = []
        for i, item in enumerate(headings_raw):
            if isinstance(item, FillerHeadingMarkerSpec):
                headings.append(item)
                continue
            if not isinstance(item, Mapping):
                raise RecipeError(f"fillers.markers.headings[{i}] must be a mapping")
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
            raise RecipeError(f"{loc}.id is required")
        art = _str_or_none(raw.get("art"))
        if art is None:
            raise RecipeError(f"{loc}.art is required")
        shape = _str_or_none(raw.get("shape"))
        if shape not in FILLER_SHAPES:
            raise RecipeError(f"{loc}.shape must be one of {sorted(FILLER_SHAPES)}")
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
            raise RecipeError(f"{loc}.shapes must be a non-empty list")
        shapes: list[str] = []
        for i, shape_raw in enumerate(shapes_raw):
            shape = _str_or_none(shape_raw)
            if shape not in FILLER_SHAPES:
                raise RecipeError(
                    f"{loc}.shapes[{i}] must be one of {sorted(FILLER_SHAPES)}"
                )
            shapes.append(shape)
        min_space = _inch_value(raw.get("min_space"), loc=f"{loc}.min_space")
        max_space = _inch_value(raw.get("max_space"), loc=f"{loc}.max_space")
        if max_space < min_space:
            raise RecipeError(f"{loc}.max_space must be >= min_space")
        return cls(
            name=name,
            min_space_in=min_space,
            max_space_in=max_space,
            shapes=shapes,
        )


@dataclass(frozen=True)
class FillersSpec:
    """Recipe-level conditional filler art configuration."""

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
            raise RecipeError("fillers.slots must be a mapping when provided")
        slots: dict[str, FillerSlotSpec] = {}
        for name, slot_raw in slots_raw.items():
            slot_name = str(name).strip()
            if not slot_name:
                raise RecipeError("fillers.slots keys must be non-empty")
            if not isinstance(slot_raw, Mapping):
                raise RecipeError(f"fillers.slots.{slot_name} must be a mapping")
            slots[slot_name] = FillerSlotSpec.from_dict(
                slot_name,
                slot_raw,
                loc=f"fillers.slots.{slot_name}",
            )

        assets_raw = raw.get("assets") or []
        if not isinstance(assets_raw, list):
            raise RecipeError("fillers.assets must be a list when provided")
        assets: list[FillerAssetSpec] = []
        for i, asset_raw in enumerate(assets_raw):
            if not isinstance(asset_raw, Mapping):
                raise RecipeError(
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


SPLASH_TARGETS = {
    "front-cover",
    "back-cover",
    "chapter-start",
    "after-heading",
}

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
            raise RecipeError(f"{loc}.id is required")
        art = _str_or_none(raw.get("art"))
        if art is None:
            raise RecipeError(f"{loc}.art is required")
        target = _str_or_none(raw.get("target"))
        if target not in SPLASH_TARGETS:
            raise RecipeError(f"{loc}.target must be one of {sorted(SPLASH_TARGETS)}")
        placement = _str_or_none(raw.get("placement"))
        if placement not in SPLASH_PLACEMENTS:
            raise RecipeError(
                f"{loc}.placement must be one of {sorted(SPLASH_PLACEMENTS)}"
            )

        chapter = _str_or_none(raw.get("chapter"))
        heading = _str_or_none(raw.get("heading"))
        if target in {"chapter-start", "after-heading"} and chapter is None:
            raise RecipeError(f"{loc}.chapter is required for target={target!r}")
        if target == "after-heading" and heading is None:
            raise RecipeError(f"{loc}.heading is required for target='after-heading'")
        if target in {"front-cover", "back-cover"} and chapter is not None:
            raise RecipeError(f"{loc}.chapter is only valid for chapter splashes")
        if target != "after-heading" and heading is not None:
            raise RecipeError(f"{loc}.heading is only valid for target='after-heading'")

        return cls(
            id=splash_id,
            art=art,
            target=target,
            placement=placement,
            chapter=chapter,
            heading=heading,
        )


# ---------------------------------------------------------------------------
# Source reference: vault:relative/path.md
# ---------------------------------------------------------------------------


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
            raise RecipeError("empty source reference")
        m = _SOURCE_RE.match(raw.strip())
        if not m:
            raise RecipeError(f"invalid source reference: {raw!r}")
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
            raise RecipeError(
                f"{loc} must be a source string or mapping, got {type(raw).__name__}"
            )
        source_raw = raw.get("source")
        if not isinstance(source_raw, str) or not source_raw.strip():
            raise RecipeError(f"{loc}.source is required")
        return cls(
            source=SourceRef.parse(source_raw),
            title=_str_or_none(raw.get("title")),
            strip_related=bool(raw.get("strip_related", False)),
            filler_enabled=_bool_value(raw.get("filler", True), loc=f"{loc}.filler"),
        )


# ---------------------------------------------------------------------------
# Chapter spec
# ---------------------------------------------------------------------------


CHAPTER_KINDS = {
    "file",
    "catalog",
    "composite",
    "classes-catalog",
    "folder",
    "group",
    "sequence",
}

# Kinds that don't need (or use) their own `source:` field. `group` is a
# pure structural wrapper around its `children:`. `sequence` uses `sources:`.
_KINDS_WITHOUT_SOURCE = {"group", "sequence"}


@dataclass
class ChapterSpec:
    """One entry in the recipe's `chapters:` list.

    `kind` is structural (how to assemble files into chapter content).
    `style` is semantic (the CSS hook value passed to the template as
    `section-kind` metadata; CSS targets `body.section-<style>`).
    """

    # file | catalog | composite | classes-catalog | folder | group | sequence
    kind: str
    # required for every kind except `group`
    source: SourceRef | None = None
    # optional; some kinds derive it
    title: str | None = None
    # optional explicit PDF/link anchor
    slug: str | None = None
    eyebrow: str | None = None
    # filename in recipe.art_dir
    art: str | None = None
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
    children: list[ChapterSpec] = field(default_factory=list)
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
    ) -> ChapterSpec:
        """Parse and validate one chapter mapping from the recipe YAML."""
        loc = f"chapter[{index}]" if not path else f"{path}.children[{index}]"
        if not isinstance(raw, Mapping):
            raise RecipeError(f"{loc} must be a mapping, got {type(raw).__name__}")
        kind_raw = raw.get("kind")
        if not isinstance(kind_raw, str):
            raise RecipeError(f"{loc}.kind must be a string")
        kind = kind_raw
        if kind not in CHAPTER_KINDS:
            raise RecipeError(
                f"{loc}.kind={kind!r} is not one of {sorted(CHAPTER_KINDS)}"
            )
        source_raw = raw.get("source")
        sources_raw = raw.get("sources")
        source: SourceRef | None = None
        if kind in _KINDS_WITHOUT_SOURCE:
            if source_raw is not None:
                raise RecipeError(
                    f"{loc} kind={kind!r} should not declare `source:` "
                    f"(use `children:` for groups or `sources:` for sequences)"
                )
        else:
            if not isinstance(source_raw, str) or not source_raw.strip():
                raise RecipeError(f"{loc} missing required field: source")
            try:
                source = SourceRef.parse(source_raw)
            except RecipeError as e:
                raise RecipeError(f"{loc}: {e}") from e

        sources: list[SourceItem] = []
        if kind == "sequence":
            if not isinstance(sources_raw, list) or not sources_raw:
                raise RecipeError(
                    f"{loc} kind='sequence' requires a non-empty `sources:` list"
                )
            for i, item in enumerate(sources_raw):
                try:
                    sources.append(SourceItem.from_raw(item, loc=f"{loc}.sources[{i}]"))
                except RecipeError as e:
                    raise RecipeError(str(e)) from e
        elif sources_raw is not None:
            raise RecipeError(
                f"{loc}.sources is only valid for kind='sequence' (got kind={kind!r})"
            )

        # Recursively parse `children:` (only meaningful for `group` kind, but
        # we accept it generically for forward-compatibility).
        if "sort" in raw:
            raise RecipeError(
                f"{loc}.sort is no longer supported; folder ordering is always "
                "alphabetical. Remove the field from your recipe."
            )

        children_raw = raw.get("children") or []
        if not isinstance(children_raw, list):
            raise RecipeError(
                f"{loc}.children must be a list, got {type(children_raw).__name__}"
            )
        if kind == "group" and not children_raw:
            raise RecipeError(
                f"{loc} kind='group' requires a non-empty `children:` list"
            )
        if kind != "group" and children_raw:
            raise RecipeError(
                f"{loc}.children is only valid for kind='group' (got kind={kind!r})"
            )
        children: list[ChapterSpec] = []
        for i, child_raw in enumerate(children_raw):
            if not isinstance(child_raw, Mapping):
                raise RecipeError(
                    f"{loc}.children[{i}] must be a mapping, "
                    f"got {type(child_raw).__name__}"
                )
            children.append(cls.from_dict(child_raw, index=i, path=loc))

        full_page_sections_raw = raw.get("full_page_sections") or []
        if not isinstance(full_page_sections_raw, list) or not all(
            isinstance(x, str) for x in full_page_sections_raw
        ):
            raise RecipeError(
                f"{loc}.full_page_sections must be a list of heading titles/slugs"
            )
        toc_depth = _toc_depth_or_none(raw.get("toc_depth"), loc=loc)

        return cls(
            kind=kind,
            source=source,
            title=_str_or_none(raw.get("title")),
            slug=_slug_or_none(raw.get("slug"), loc=loc),
            eyebrow=_str_or_none(raw.get("eyebrow")),
            art=_str_or_none(raw.get("art")),
            style=str(raw.get("style", "default")),
            wrapper=bool(raw.get("wrapper", False)),
            child_style=str(raw.get("child_style", "default")),
            child_divider=bool(raw.get("child_divider", False)),
            children=children,
            sources=sources,
            full_page_sections=[str(section) for section in full_page_sections_raw],
            headpiece=_str_or_none(raw.get("headpiece")),
            break_ornament=_str_or_none(raw.get("break_ornament")),
            toc_depth=toc_depth,
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


# ---------------------------------------------------------------------------
# Recipe
# ---------------------------------------------------------------------------


DEFAULT_THEME = "pinlight-industrial"

GENERATED_MATTER_TYPES = {
    "title-page",
    "credits",
    "copyright",
    "license",
    "art-credits",
    "changelog",
    "appendix-index",
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


@dataclass(frozen=True)
class MatterSpec:
    """One generated front/back matter page declared by a recipe."""

    type: str
    title: str | None = None

    @classmethod
    def from_raw(cls, raw: object, *, loc: str) -> MatterSpec:
        """Parse one front/back matter item from a string or mapping."""
        if isinstance(raw, str):
            matter_type = raw.strip()
            title = None
        elif isinstance(raw, Mapping):
            matter_type = _str_or_none(raw.get("type")) or ""
            title = _str_or_none(raw.get("title"))
            kind = _str_or_none(raw.get("kind")) or "generated"
            if kind != "generated":
                raise RecipeError(
                    f"{loc}.kind currently supports only 'generated' matter"
                )
        else:
            raise RecipeError(
                f"{loc} must be a generated matter type string or mapping"
            )
        if matter_type not in GENERATED_MATTER_TYPES:
            raise RecipeError(
                f"{loc}.type must be one of {sorted(GENERATED_MATTER_TYPES)}"
            )
        return cls(type=matter_type, title=title)


@dataclass
class VaultSpec:
    """A vault declared in the recipe's `vaults:` mapping."""

    name: str  # alias used in source refs (e.g. "custom")
    path: Path  # absolute path to the vault root


@dataclass
class Recipe:
    """A fully validated recipe ready for manifest construction."""

    title: str
    subtitle: str | None
    cover_eyebrow: str | None
    cover_footer: str | None
    vaults: dict[str, VaultSpec]  # name -> VaultSpec
    vault_overlay: list[str]  # priority order, first = lowest
    cover: CoverSpec
    chapters: list[ChapterSpec]
    recipe_path: Path  # where this recipe was loaded from
    output_dir_override: Path | None = None
    output_name: str | None = None
    cache_dir_override: Path | None = None
    theme: str = DEFAULT_THEME
    theme_dir_override: Path | None = None
    theme_options: dict[str, str] = field(default_factory=dict)
    metadata: BookMetadataSpec = field(default_factory=BookMetadataSpec)
    front_matter: list[MatterSpec] = field(default_factory=list)
    back_matter: list[MatterSpec] = field(default_factory=list)
    art_dir_override: Path | None = None  # optional override for art assets
    ornaments: OrnamentsSpec = field(default_factory=OrnamentsSpec)
    splashes: list[SplashSpec] = field(default_factory=list)
    fillers: FillersSpec = field(default_factory=FillersSpec)
    page_damage: PageDamageSpec = field(default_factory=PageDamageSpec)

    # Convenience
    def vault_priority_paths(self) -> list[Path]:
        """Return vault paths in overlay priority order (first = lowest priority)."""
        return [self.vaults[name].path for name in self.vault_overlay]

    def vault_by_name(self, name: str) -> VaultSpec | None:
        """Return a declared vault by alias, or ``None`` if missing."""
        return self.vaults.get(name)

    @property
    def project_dir(self) -> Path:
        """Resolve the content project root for this recipe."""
        parent = self.recipe_path.parent
        return parent.parent if parent.name == "recipes" else parent

    @property
    def art_dir(self) -> Path:
        """Return the directory used for cover and chapter art assets."""
        return self.art_dir_override or (self.project_dir / "assets" / "art")

    @property
    def output_dir(self) -> Path:
        """Return the caller-owned base directory for generated files."""
        return self.output_dir_override or self.project_dir

    @property
    def generated_name(self) -> str:
        """Return the generated-output directory name for this recipe."""
        return self.output_name or _filename_slug(self.title)

    @property
    def generated_root(self) -> Path:
        """Return the root below which all generated files are written."""
        return self.output_dir / "Paper Crown" / self.generated_name

    @property
    def cache_dir(self) -> Path:
        """Return the cache directory for exports and optimized assets."""
        return self.cache_dir_override or (self.generated_root / "cache")


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _resolve_vault_path(raw: str, recipe_dir: Path) -> Path:
    """Resolve a recipe-relative or absolute filesystem path."""
    p = Path(raw)
    if not p.is_absolute():
        p = (recipe_dir / p).resolve()
    else:
        p = p.resolve()
    return p


def load_recipe(path: str | Path) -> Recipe:
    """Load and validate a recipe YAML file.

    Raises RecipeError with a clear message on any structural or referential
    problem (missing required fields, unknown chapter kinds, vault paths that
    don't exist, vault_overlay names not in `vaults`, recipe include cycles,
    etc). Recipes may use ``extends``, ``include_chapters``, and
    ``include_vaults`` to share reusable book structure.
    """
    recipe_path = Path(path).resolve()
    if not recipe_path.is_file():
        raise RecipeError(f"recipe file not found: {recipe_path}")

    raw = _load_recipe_mapping(recipe_path, stack=())

    # Required: title
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise RecipeError("recipe missing required field: title (non-empty string)")

    # Required: vaults (at least one)
    vaults_raw = raw.get("vaults")
    if not isinstance(vaults_raw, Mapping) or not vaults_raw:
        raise RecipeError(
            "recipe missing required field: vaults (mapping of name -> path)"
        )

    recipe_dir = recipe_path.parent
    vaults: dict[str, VaultSpec] = {}
    for name, vp in vaults_raw.items():
        if not isinstance(name, str) or not re.match(r"^[A-Za-z0-9_-]+$", name):
            raise RecipeError(
                f"invalid vault alias {name!r}: must be alphanumeric/underscore/dash"
            )
        resolved = _resolve_vault_path(str(vp), recipe_dir)
        if not resolved.is_dir():
            raise RecipeError(f"vault {name!r} path does not exist: {resolved}")
        vaults[name] = VaultSpec(name=name, path=resolved)

    # Optional: vault_overlay (defaults to declared insertion order)
    overlay_raw = raw.get("vault_overlay")
    if overlay_raw is None:
        vault_overlay = list(vaults.keys())
    else:
        if not isinstance(overlay_raw, list) or not all(
            isinstance(x, str) for x in overlay_raw
        ):
            raise RecipeError("vault_overlay must be a list of vault alias strings")
        for name in overlay_raw:
            if name not in vaults:
                raise RecipeError(
                    f"vault_overlay references unknown vault {name!r}; "
                    f"declared vaults: {sorted(vaults)}"
                )
        # Allow partial overlay; missing vaults still work via explicit prefix.
        vault_overlay = [str(name) for name in overlay_raw]

    art_dir_override = None
    art_dir_raw = _str_or_none(raw.get("art_dir"))
    if art_dir_raw:
        art_dir_override = _resolve_vault_path(art_dir_raw, recipe_dir)
        if not art_dir_override.is_dir():
            raise RecipeError(f"art_dir path does not exist: {art_dir_override}")

    output_dir_override = None
    output_dir_raw = _str_or_none(raw.get("output_dir"))
    if output_dir_raw:
        output_dir_override = _resolve_vault_path(output_dir_raw, recipe_dir)

    output_name = _str_or_none(raw.get("output_name"))
    if output_name is not None:
        output_name = _filename_slug(output_name)

    cache_dir_override = None
    cache_dir_raw = _str_or_none(raw.get("cache_dir"))
    if cache_dir_raw:
        cache_dir_override = _resolve_vault_path(cache_dir_raw, recipe_dir)

    theme = _slug_or_none(raw.get("theme"), loc="theme") or DEFAULT_THEME
    theme_dir_override = None
    theme_dir_raw = _str_or_none(raw.get("theme_dir"))
    if theme_dir_raw:
        theme_dir_override = _resolve_vault_path(theme_dir_raw, recipe_dir)
        if not theme_dir_override.is_dir():
            raise RecipeError(f"theme_dir path does not exist: {theme_dir_override}")

    metadata_raw = raw.get("metadata")
    if metadata_raw is not None and not isinstance(metadata_raw, Mapping):
        raise RecipeError("metadata must be a mapping when provided")
    theme_options = _theme_options_mapping(raw.get("theme_options"))
    front_matter = _matter_list(raw.get("front_matter"), field_name="front_matter")
    back_matter = _matter_list(raw.get("back_matter"), field_name="back_matter")

    # Required: chapters (non-empty)
    cover_raw = raw.get("cover")
    if cover_raw is not None and not isinstance(cover_raw, Mapping):
        raise RecipeError("cover must be a mapping when provided")
    ornaments_raw = raw.get("ornaments")
    if ornaments_raw is not None and not isinstance(ornaments_raw, Mapping):
        raise RecipeError("ornaments must be a mapping when provided")
    fillers_raw = raw.get("fillers")
    if fillers_raw is not None and not isinstance(fillers_raw, Mapping):
        raise RecipeError("fillers must be a mapping when provided")
    page_damage_raw = raw.get("page_damage")
    if page_damage_raw is not None and not isinstance(page_damage_raw, Mapping):
        raise RecipeError("page_damage must be a mapping when provided")

    splashes_raw = raw.get("splashes") or []
    if not isinstance(splashes_raw, list):
        raise RecipeError("splashes must be a list when provided")
    splashes: list[SplashSpec] = []
    for i, splash_raw in enumerate(splashes_raw):
        if not isinstance(splash_raw, Mapping):
            raise RecipeError(
                f"splashes[{i}] must be a mapping, got {type(splash_raw).__name__}"
            )
        splashes.append(SplashSpec.from_dict(splash_raw, index=i))

    chapters_raw = raw.get("chapters")
    if not isinstance(chapters_raw, list) or not chapters_raw:
        raise RecipeError("recipe missing required field: chapters (non-empty list)")
    chapters: list[ChapterSpec] = []
    for i, chapter_raw in enumerate(chapters_raw):
        if not isinstance(chapter_raw, Mapping):
            raise RecipeError(
                f"chapter[{i}] must be a mapping, got {type(chapter_raw).__name__}"
            )
        chapters.append(ChapterSpec.from_dict(chapter_raw, index=i))

    # Validate every chapter source's vault prefix (if explicit) refers to a
    # known vault. Walks recursively into group `children` too.
    def _validate_sources(chs: list[ChapterSpec], crumb: str) -> None:
        for i, ch in enumerate(chs):
            here = f"{crumb}[{i}]"
            if (
                ch.source is not None
                and ch.source.vault is not None
                and ch.source.vault not in vaults
            ):
                raise RecipeError(
                    f"{here} source {ch.source!s} references unknown vault "
                    f"{ch.source.vault!r}; declared vaults: {sorted(vaults)}"
                )
            for j, item in enumerate(ch.sources):
                if item.source.vault is not None and item.source.vault not in vaults:
                    raise RecipeError(
                        f"{here}.sources[{j}] source {item.source!s} "
                        "references unknown vault "
                        f"{item.source.vault!r}; declared vaults: {sorted(vaults)}"
                    )
            _validate_sources(ch.children, f"{here}.children")

    _validate_sources(chapters, "chapter")

    return Recipe(
        title=title.strip(),
        subtitle=_str_or_none(raw.get("subtitle")),
        cover_eyebrow=_str_or_none(raw.get("cover_eyebrow")),
        cover_footer=_str_or_none(raw.get("cover_footer")),
        vaults=vaults,
        vault_overlay=vault_overlay,
        output_dir_override=output_dir_override,
        output_name=output_name,
        cache_dir_override=cache_dir_override,
        theme=theme,
        theme_dir_override=theme_dir_override,
        theme_options=theme_options,
        metadata=BookMetadataSpec.from_dict(metadata_raw),
        front_matter=front_matter,
        back_matter=back_matter,
        art_dir_override=art_dir_override,
        ornaments=OrnamentsSpec.from_dict(ornaments_raw),
        cover=CoverSpec.from_dict(cover_raw),
        splashes=splashes,
        fillers=FillersSpec.from_dict(fillers_raw),
        page_damage=PageDamageSpec.from_dict(page_damage_raw),
        chapters=chapters,
        recipe_path=recipe_path,
    )


def _load_recipe_mapping(path: Path, *, stack: tuple[Path, ...]) -> dict[str, object]:
    """Load a recipe or inherited recipe layer into an expanded mapping."""
    recipe_path = path.resolve()
    if recipe_path in stack:
        cycle = " -> ".join(p.name for p in (*stack, recipe_path))
        raise RecipeError(f"recipe extends/include cycle detected: {cycle}")

    try:
        raw_obj = yaml.safe_load(recipe_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RecipeError(f"invalid YAML in {recipe_path}: {e}") from e
    except OSError as e:
        raise RecipeError(f"could not read recipe {recipe_path}: {e}") from e

    if raw_obj is None:
        raise RecipeError(f"recipe is empty: {recipe_path}")
    if not isinstance(raw_obj, Mapping):
        raise RecipeError(
            f"recipe root must be a mapping, got {type(raw_obj).__name__}"
        )

    raw = {str(key): value for key, value in raw_obj.items()}
    recipe_dir = recipe_path.parent
    next_stack = (*stack, recipe_path)

    base: dict[str, object] = {}
    extends_raw = raw.get("extends")
    if extends_raw is not None:
        if not isinstance(extends_raw, str) or not extends_raw.strip():
            raise RecipeError("extends must be a non-empty path string")
        base = _load_recipe_mapping(
            _resolve_include_path(extends_raw, recipe_dir),
            stack=next_stack,
        )

    local = dict(raw)
    local.pop("extends", None)
    chapter_includes = local.pop("include_chapters", None)
    vault_includes = local.pop("include_vaults", None)
    _normalize_recipe_filesystem_paths(local, recipe_dir)

    if vault_includes is not None:
        _merge_vault_includes(local, vault_includes, recipe_dir, stack=next_stack)
    if chapter_includes is not None:
        _merge_chapter_includes(local, chapter_includes, recipe_dir, stack=next_stack)

    return _deep_merge(base, local)


def _resolve_include_path(raw: str, base_dir: Path) -> Path:
    """Resolve an include or extends path relative to the declaring file."""
    path = Path(raw)
    if not path.is_absolute():
        path = base_dir / path
    resolved = path.resolve()
    if not resolved.is_file():
        raise RecipeError(f"included recipe file not found: {resolved}")
    return resolved


def _normalize_recipe_filesystem_paths(
    raw: dict[str, object], recipe_dir: Path
) -> None:
    """Rewrite recipe-relative filesystem paths as absolute strings in place."""
    vaults_raw = raw.get("vaults")
    if isinstance(vaults_raw, Mapping):
        raw["vaults"] = {
            str(name): str(_resolve_vault_path(str(path), recipe_dir))
            for name, path in vaults_raw.items()
        }
    art_dir_raw = raw.get("art_dir")
    if isinstance(art_dir_raw, str) and art_dir_raw.strip():
        raw["art_dir"] = str(_resolve_vault_path(art_dir_raw, recipe_dir))
    output_dir_raw = raw.get("output_dir")
    if isinstance(output_dir_raw, str) and output_dir_raw.strip():
        raw["output_dir"] = str(_resolve_vault_path(output_dir_raw, recipe_dir))
    cache_dir_raw = raw.get("cache_dir")
    if isinstance(cache_dir_raw, str) and cache_dir_raw.strip():
        raw["cache_dir"] = str(_resolve_vault_path(cache_dir_raw, recipe_dir))
    theme_dir_raw = raw.get("theme_dir")
    if isinstance(theme_dir_raw, str) and theme_dir_raw.strip():
        raw["theme_dir"] = str(_resolve_vault_path(theme_dir_raw, recipe_dir))


def _merge_vault_includes(
    raw: dict[str, object],
    includes: object,
    recipe_dir: Path,
    *,
    stack: tuple[Path, ...],
) -> None:
    """Merge vault declarations from include files into ``raw``."""
    include_paths = _include_path_list(includes, field_name="include_vaults")
    included_vaults: dict[str, object] = {}
    included_overlay: list[str] = []
    for include in include_paths:
        include_path = _resolve_include_path(include, recipe_dir)
        fragment = _read_yaml_mapping(include_path, stack=stack)
        vaults_raw = fragment.get("vaults", fragment)
        if not isinstance(vaults_raw, Mapping):
            raise RecipeError(f"{include_path.name}: vault include must be a mapping")
        for name, value in vaults_raw.items():
            included_vaults[str(name)] = str(
                _resolve_vault_path(str(value), include_path.parent)
            )
        overlay_raw = fragment.get("vault_overlay")
        if isinstance(overlay_raw, list) and all(
            isinstance(item, str) for item in overlay_raw
        ):
            included_overlay.extend(str(item) for item in overlay_raw)

    local_vaults = raw.get("vaults")
    merged_vaults = dict(included_vaults)
    if isinstance(local_vaults, Mapping):
        merged_vaults.update({str(key): value for key, value in local_vaults.items()})
    raw["vaults"] = merged_vaults
    if "vault_overlay" not in raw and included_overlay:
        raw["vault_overlay"] = _dedupe(included_overlay + list(merged_vaults))


def _merge_chapter_includes(
    raw: dict[str, object],
    includes: object,
    recipe_dir: Path,
    *,
    stack: tuple[Path, ...],
) -> None:
    """Prepend chapter fragments from include files to ``raw`` chapters."""
    include_paths = _include_path_list(includes, field_name="include_chapters")
    included_chapters: list[object] = []
    for include in include_paths:
        include_path = _resolve_include_path(include, recipe_dir)
        fragment = _read_yaml_mapping_or_list(include_path, stack=stack)
        if isinstance(fragment, list):
            included_chapters.extend(deepcopy(fragment))
            continue
        chapters_raw = fragment.get("chapters")
        if not isinstance(chapters_raw, list):
            raise RecipeError(
                f"{include_path.name}: chapter include must be a list or "
                "a mapping with chapters"
            )
        included_chapters.extend(deepcopy(chapters_raw))

    local_chapters_raw = raw.get("chapters")
    if local_chapters_raw is None:
        local_chapters: list[object] = []
    elif isinstance(local_chapters_raw, list):
        local_chapters = list(local_chapters_raw)
    else:
        raise RecipeError("chapters must be a list when include_chapters is used")
    raw["chapters"] = included_chapters + local_chapters


def _read_yaml_mapping(path: Path, *, stack: tuple[Path, ...]) -> dict[str, object]:
    """Read an include file that must contain a mapping."""
    obj = _read_yaml_mapping_or_list(path, stack=stack)
    if not isinstance(obj, Mapping):
        raise RecipeError(f"{path.name}: expected a mapping")
    return {str(key): value for key, value in obj.items()}


def _read_yaml_mapping_or_list(
    path: Path,
    *,
    stack: tuple[Path, ...],
) -> Mapping[object, object] | list[object]:
    """Read an include file that may contain a mapping or list."""
    resolved = path.resolve()
    if resolved in stack:
        cycle = " -> ".join(p.name for p in (*stack, resolved))
        raise RecipeError(f"recipe extends/include cycle detected: {cycle}")
    try:
        obj = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise RecipeError(f"invalid YAML in {resolved}: {e}") from e
    except OSError as e:
        raise RecipeError(f"could not read include {resolved}: {e}") from e
    if isinstance(obj, Mapping) or isinstance(obj, list):
        return obj
    raise RecipeError(f"{resolved.name}: expected a mapping or list include")


def _include_path_list(raw: object, *, field_name: str) -> list[str]:
    """Normalize one include path or a list of include paths."""
    if isinstance(raw, str) and raw.strip():
        return [raw]
    if isinstance(raw, list) and all(isinstance(item, str) for item in raw):
        return [str(item) for item in raw]
    raise RecipeError(f"{field_name} must be a path string or list of path strings")


def _deep_merge(
    base: dict[str, object], override: dict[str, object]
) -> dict[str, object]:
    """Deep-merge two recipe mappings with list/scalar replacement semantics."""
    merged = deepcopy(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge(
                {str(k): v for k, v in existing.items()},
                {str(k): v for k, v in value.items()},
            )
        else:
            merged[key] = deepcopy(value)
    return merged


def _dedupe(values: list[str]) -> list[str]:
    """Return values with duplicates removed while preserving order."""
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _filename_slug(value: str) -> str:
    """Return a filesystem-friendly lowercase slug for generated folders."""
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip().lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "book"


def _str_or_none(value: object) -> str | None:
    """Return a stripped string for truthy values, otherwise ``None``."""
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _bool_value(value: object, *, loc: str) -> bool:
    """Validate a boolean recipe value."""
    if not isinstance(value, bool):
        raise RecipeError(f"{loc} must be true or false")
    return value


def _required_marker_slot(value: object, *, loc: str) -> str:
    """Validate one filler marker slot name."""
    slot = _str_or_none(value)
    if slot is None:
        raise RecipeError(f"{loc} is required")
    if not re.match(r"^[A-Za-z0-9_-]+$", slot):
        raise RecipeError(
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


def _string_list_or_one(value: object) -> list[str]:
    """Normalize a string or list of strings into a stripped list."""
    if value is None:
        return []
    if isinstance(value, str):
        item = value.strip()
        return [item] if item else []
    if not isinstance(value, list):
        raise RecipeError("expected a string or list of strings")
    items: list[str] = []
    for raw in value:
        if not isinstance(raw, str):
            raise RecipeError("expected a string or list of strings")
        item = raw.strip()
        if item:
            items.append(item)
    return items


def _credits_mapping(value: object) -> dict[str, list[str]]:
    """Validate and normalize metadata credits into role -> names."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RecipeError("metadata.credits must be a mapping")
    credits: dict[str, list[str]] = {}
    for raw_role, raw_names in value.items():
        role = str(raw_role).strip()
        if not role:
            raise RecipeError("metadata.credits keys must be non-empty")
        credits[role] = _string_list_or_one(raw_names)
    return credits


def _theme_options_mapping(value: object) -> dict[str, str]:
    """Validate theme option overrides."""
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise RecipeError("theme_options must be a mapping")
    options: dict[str, str] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key).strip()
        if not key:
            raise RecipeError("theme_options keys must be non-empty")
        if raw_value is None:
            continue
        options[key] = str(raw_value).strip()
    return options


def _matter_list(value: object, *, field_name: str) -> list[MatterSpec]:
    """Validate a front_matter/back_matter list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise RecipeError(f"{field_name} must be a list when provided")
    return [
        MatterSpec.from_raw(raw_item, loc=f"{field_name}[{i}]")
        for i, raw_item in enumerate(value)
    ]


def _slug_or_none(value: object, *, loc: str) -> str | None:
    """Validate and return an optional explicit chapter slug."""
    slug = _str_or_none(value)
    if slug is None:
        return None
    if not re.match(r"^[A-Za-z0-9_-]+$", slug):
        raise RecipeError(
            f"{loc}.slug must contain only letters, numbers, underscores, and hyphens"
        )
    return slug


def _inch_value(value: object, *, loc: str) -> float:
    """Parse a positive CSS inch value such as ``0.65in``."""
    raw = _str_or_none(value)
    if raw is None:
        raise RecipeError(f"{loc} is required")
    match = re.fullmatch(r"(?P<num>\d+(?:\.\d+)?)in", raw)
    if match is None:
        raise RecipeError(f"{loc} must be a positive inch value like '0.65in'")
    parsed = float(match.group("num"))
    if parsed <= 0:
        raise RecipeError(f"{loc} must be greater than 0")
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
        raise RecipeError(f"{loc} must be a number from {min_value} to {max_value}")
    parsed = float(value)
    if parsed < min_value or parsed > max_value:
        raise RecipeError(f"{loc} must be from {min_value} to {max_value}")
    return parsed


def _positive_int(value: object, *, loc: str) -> int:
    """Parse a positive integer recipe value."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecipeError(f"{loc} must be a positive integer")
    if value <= 0:
        raise RecipeError(f"{loc} must be a positive integer")
    return int(value)


def _skip_targets(value: object) -> list[str]:
    """Validate page-damage skip target names."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RecipeError("page_damage.skip must be a list of strings")
    skip: list[str] = []
    for item in value:
        target = item.strip()
        if target not in PAGE_DAMAGE_SKIP_TARGETS:
            raise RecipeError(
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
        raise RecipeError(f"{loc}.toc_depth must be an integer from 1 to 4")
    if value < 1 or value > 4:
        raise RecipeError(f"{loc}.toc_depth must be between 1 and 4")
    return value
