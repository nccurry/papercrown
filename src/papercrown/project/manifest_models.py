"""Resolved manifest data model."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from papercrown.project.recipe import ArtInsertSpec, BookConfig
from papercrown.project.slugs import slugify
from papercrown.project.vaults import VaultIndex


@dataclass
class Splash:
    """A resolved large splash-art placement."""

    id: str
    art_path: Path | None
    target: str
    placement: str
    chapter_slug: str | None = None
    heading_slug: str | None = None


@dataclass(frozen=True)
class FillerAsset:
    """A resolved conditional filler art asset."""

    id: str
    art_path: Path
    shape: str
    height_in: float


@dataclass(frozen=True)
class FillerSlot:
    """A resolved filler slot definition."""

    name: str
    min_space_in: float
    max_space_in: float
    shapes: list[str]


@dataclass(frozen=True)
class FillerCatalog:
    """Resolved conditional filler art catalog for a recipe."""

    enabled: bool = False
    slots: dict[str, FillerSlot] = field(default_factory=dict)
    assets: list[FillerAsset] = field(default_factory=list)


@dataclass(frozen=True)
class ChapterHeadingFillerMarker:
    """A heading-scoped filler marker policy resolved for one chapter."""

    slot: str
    heading_level: int
    slot_kind: str
    skip_first: bool = False
    context: str | None = None


@dataclass(frozen=True)
class PageDamageAsset:
    """A resolved transparent page-wear asset."""

    id: str
    art_path: Path
    family: str
    size: str


@dataclass(frozen=True)
class PageDamageCatalog:
    """Resolved page-damage catalog for a recipe."""

    enabled: bool = False
    seed: str = "page-damage-v1"
    density: float = 0.55
    max_assets_per_page: int = 2
    opacity: float = 0.28
    glaze_opacity: float = 0.0
    glaze_texture: str = "surface-warm-paper-tint-cloud.png"
    skip: list[str] = field(default_factory=list)
    assets: list[PageDamageAsset] = field(default_factory=list)


@dataclass(frozen=True)
class FillerArtClassification:
    """Filename/path-derived role for an art asset."""

    category: str
    shape: str | None = None
    height_in: float | None = None
    auto_selectable: bool = False


@dataclass(frozen=True)
class ChapterFillerSlot:
    """A concrete marker emitted into assembled chapter markdown."""

    id: str
    slot: str
    chapter_slug: str
    preferred_asset_id: str | None = None
    section_slug: str | None = None
    section_title: str | None = None
    slot_kind: str | None = None
    context: str | None = None


@dataclass
class Chapter:
    """A resolved render unit in the book's chapter tree."""

    title: str
    slug: str
    eyebrow: str | None = None
    art_path: Path | None = None
    spot_art_path: Path | None = None
    replace_opening_art: bool = False
    tailpiece_path: Path | None = None
    headpiece_path: Path | None = None
    break_ornament_path: Path | None = None
    filler_slots: list[ChapterFillerSlot] = field(default_factory=list)
    source_files: list[Path] = field(default_factory=list)
    source_titles: list[str | None] = field(default_factory=list)
    source_strip_related: list[bool] = field(default_factory=list)
    source_filler_enabled: list[bool] = field(default_factory=list)
    source_boundary_filler_slots: list[str] = field(default_factory=list)
    subclass_filler_slots: list[str] = field(default_factory=lambda: ["subclass-end"])
    heading_filler_markers: list[ChapterHeadingFillerMarker] | None = None
    fillers_enabled: bool = True
    children: list[Chapter] = field(default_factory=list)
    individual_pdf: bool = False
    individual_pdf_subdir: str | None = None
    style: str = "default"
    # When True, this chapter (when rendered as a non-top-level descendant in
    # the combined book) gets its OWN full-page section-divider before its
    # content -- the same kind of divider that top-level chapters always get.
    # Top-level chapters always get a divider regardless of this flag.
    divider: bool = False
    # Heading titles/slugs inside this chapter that should start on a fresh
    # page without forcing every same-level section to do so.
    full_page_sections: list[str] = field(default_factory=list)
    # Combined-book table-of-contents depth for this top-level chapter.
    # None means use the assembly default.
    toc_depth: int | None = None
    # Content-scoped art inserts declared on this chapter's recipe item.
    art_inserts: list[ArtInsertSpec] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        """Return whether the chapter has no child chapters."""
        return not self.children

    def walk(self) -> Iterator[Chapter]:
        """Depth-first iterator yielding self then each child recursively."""
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass(frozen=True)
class TocPart:
    """A table-of-contents marker in the ordered book contents."""

    title: str = "Table of Contents"
    slug: str = "table-of-contents"
    depth: int | None = None


@dataclass(frozen=True)
class GeneratedPart:
    """A computed page in the ordered book contents."""

    type: str
    title: str
    slug: str
    style: str = "generated"


BookPart = Chapter | TocPart | GeneratedPart


@dataclass
class Manifest:
    """The resolved recipe, vault index, chapter tree, and warnings."""

    recipe: BookConfig
    vault_index: VaultIndex
    chapters: list[Chapter]  # top-level (siblings)
    contents: list[BookPart] = field(default_factory=list)
    splashes: list[Splash] = field(default_factory=list)
    fillers: FillerCatalog = field(default_factory=FillerCatalog)
    page_damage: PageDamageCatalog = field(default_factory=PageDamageCatalog)
    warnings: list[str] = field(default_factory=list)

    def all_chapters(self) -> list[Chapter]:
        """Return every chapter in depth-first order."""
        out: list[Chapter] = []
        for c in self.chapters:
            out.extend(c.walk())
        return out

    def find_chapter(self, name: str) -> Chapter | None:
        """Find a chapter by exact slug or case-insensitive title match."""
        lowered = name.lower()
        for c in self.all_chapters():
            if (
                c.slug == lowered
                or c.slug == slugify(name)
                or c.title.lower() == lowered
            ):
                return c
        return None
