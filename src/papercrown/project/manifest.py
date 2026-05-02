"""Manifest builder: BookConfig -> Chapter tree.

Walks a BookConfig's chapters, dispatches each entry to the right kind handler,
and produces a tree of `Chapter` objects ready for the renderer.

A Chapter has:
  * title, slug, eyebrow, art_path
  * spot_art_path and tailpiece_path for sparse in-flow ornaments
  * source_files: list of vault .md files to concatenate when rendering
  * children: nested chapters (e.g. classes-catalog can produce siblings as
    children if wrapper=true; otherwise produces flat top-level siblings)
  * individual_pdf: emit a standalone PDF for this leaf chapter
  * individual_pdf_subdir: subfolder under output/ for the standalone
  * style: CSS section-kind hook (default | setting | class | ...)

The renderer doesn't care HOW a chapter was assembled, just walks the tree.
"""

from __future__ import annotations

import re
from pathlib import Path

from papercrown.art.roles import (
    IMAGE_SUFFIXES,
    PAGE_WEAR_FILENAME_RE,
    classify_art_path,
)
from papercrown.project.catalog import parse_catalog_file
from papercrown.project.manifest_art import (
    art_path as _art_path,
)
from papercrown.project.manifest_art import (
    classify_filler_art_path,
    convention_art_path,
    resolve_art_asset,
)
from papercrown.project.manifest_dump import dump
from papercrown.project.manifest_models import (
    BookPart,
    Chapter,
    ChapterFillerSlot,
    ChapterHeadingFillerMarker,
    FillerArtClassification,
    FillerAsset,
    FillerCatalog,
    FillerSlot,
    GeneratedPart,
    Manifest,
    PageDamageAsset,
    PageDamageCatalog,
    Splash,
    TocPart,
)
from papercrown.project.recipe import (
    WEAR_FAMILIES,
    WEAR_SIZES,
    ArtPlacementSpec,
    BookConfig,
    ContentItemSpec,
    FillerAssetSpec,
    FillerHeadingMarkerSpec,
    FillerMarkersSpec,
    SourceRef,
)
from papercrown.project.slugs import slugify
from papercrown.project.vaults import VaultIndex, WikilinkTarget

# Image extensions accepted for filler art discovered from the art library.
FILLER_IMAGE_SUFFIXES = IMAGE_SUFFIXES
# Image extensions accepted for page-wear overlays.
PAGE_DAMAGE_IMAGE_SUFFIXES = {".png", ".webp"}
# Page-wear filename parser shared with the art role classifier.
PAGE_DAMAGE_FILENAME_RE = PAGE_WEAR_FILENAME_RE

__all__ = [
    "BookPart",
    "Chapter",
    "ChapterFillerSlot",
    "ChapterHeadingFillerMarker",
    "FillerArtClassification",
    "FillerAsset",
    "FillerCatalog",
    "FillerSlot",
    "GeneratedPart",
    "Manifest",
    "ManifestError",
    "PageDamageAsset",
    "PageDamageCatalog",
    "Splash",
    "TocPart",
    "build_manifest",
    "classify_filler_art_path",
    "convention_art_path",
    "dump",
    "resolve_art_asset",
    "slugify",
]

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ManifestError(ValueError):
    """Raised when a recipe cannot be turned into a renderable manifest.

    This covers missing source files, unknown vault references, and chapter
    specs whose fields are incompatible with their declared kind.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_source(
    source: SourceRef,
    recipe: BookConfig,
    vault_index: VaultIndex,
) -> Path:
    """Turn a recipe's `vault:path` reference into an absolute file path."""
    if source.vault is not None:
        vault = recipe.vault_by_name(source.vault)
        if vault is None:
            raise ManifestError(f"unknown vault {source.vault!r} in source {source!s}")
        path = (vault.path / source.path).resolve()
        if not path.exists():
            raise ManifestError(f"source {source!s} not found at {path}")
        return path
    # No vault prefix -- try VaultIndex resolve via path-or-stem
    target = WikilinkTarget.parse(source.path.removesuffix(".md"))
    hit = vault_index.resolve(target)
    if hit is None:
        raise ManifestError(
            f"source {source!s} not found in any vault (no explicit vault prefix)"
        )
    return hit


def _chapter_art_path(
    recipe: BookConfig,
    spec: ContentItemSpec,
    title: str,
) -> Path | None:
    """Resolve explicit or convention-derived chapter divider/header art."""
    if spec.art.divider:
        return _art_path(recipe, spec.art.divider)
    return convention_art_path(
        recipe,
        {"chapter-header", "chapter-divider"},
        slug=_chapter_slug(spec, title),
        prefixes=("header", "chapter-header", "divider", "chapter-divider"),
    )


def _class_art_path(recipe: BookConfig, slug: str) -> Path | None:
    """Resolve convention-derived class divider art for a class slug."""
    return convention_art_path(
        recipe,
        {"class-divider"},
        slug=slug,
        prefixes=("class", "class-divider"),
    )


def _class_spot_art_path(recipe: BookConfig, slug: str) -> Path | None:
    """Resolve convention-derived class opening spot art for a class slug."""
    return convention_art_path(
        recipe,
        {"class-opening-spot"},
        slug=slug,
        prefixes=("spot-class", "class-spot"),
    )


def _filler_art_root(recipe: BookConfig) -> Path:
    """Return the root used for filler assets."""
    folder = recipe.fillers.folder
    if folder:
        return (recipe.art_dir / folder).resolve()
    return recipe.art_dir.resolve()


def _filler_art_path(recipe: BookConfig, spec: FillerAssetSpec) -> Path | None:
    """Resolve a filler art asset path."""
    root = _filler_art_root(recipe)
    art = (root / spec.art).resolve()
    try:
        art.relative_to(root)
    except ValueError:
        return None
    return art if art.is_file() else None


def _page_damage_art_root(recipe: BookConfig) -> Path:
    """Return the root used for page-wear assets."""
    return (recipe.art_dir / recipe.wear.folder).resolve()


def _page_damage_asset_from_path(
    path: Path,
    *,
    art_root: Path,
) -> PageDamageAsset | None:
    """Build a page-wear asset from a filename convention, if valid."""
    stem = path.stem.lower()
    match = PAGE_DAMAGE_FILENAME_RE.fullmatch(stem)
    if match is None:
        return None
    family = match.group("family")
    size = match.group("size")
    if family not in WEAR_FAMILIES or size not in WEAR_SIZES:
        return None
    try:
        relative = path.relative_to(art_root)
    except ValueError:
        relative = path
    return PageDamageAsset(
        id=slugify(relative.with_suffix("").as_posix().replace("/", "-")),
        art_path=path.resolve(),
        family=family,
        size=size,
    )


def _auto_filler_asset_id(path: Path, *, art_root: Path) -> str:
    try:
        relative = path.relative_to(art_root)
    except ValueError:
        relative = path
    return "auto-" + slugify(relative.with_suffix("").as_posix().replace("/", "-"))


def _auto_filler_assets(
    recipe: BookConfig,
    *,
    seen_ids: set[str],
    seen_paths: set[Path],
) -> list[FillerAsset]:
    """Discover safe, context-gated filler assets from filename conventions."""
    root = _filler_art_root(recipe)
    if not root.is_dir():
        return []

    allow_tailpieces = any(
        "tailpiece" in slot.shapes for slot in recipe.fillers.slots.values()
    )
    assets: list[FillerAsset] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.suffix.lower() not in FILLER_IMAGE_SUFFIXES:
            continue
        resolved = path.resolve()
        if resolved in seen_paths:
            continue
        classification = classify_art_path(
            resolved,
            art_root=root,
        )
        is_tailpiece = (
            allow_tailpieces
            and classification.role == "ornament-tailpiece"
            and classification.shape == "tailpiece"
        )
        if not (classification.auto_placeable or is_tailpiece):
            continue
        if classification.shape is None or classification.height_in is None:
            continue
        asset_id = _auto_filler_asset_id(resolved, art_root=root)
        if asset_id in seen_ids:
            continue
        seen_ids.add(asset_id)
        seen_paths.add(resolved)
        assets.append(
            FillerAsset(
                id=asset_id,
                art_path=resolved,
                shape=classification.shape,
                height_in=classification.height_in,
            )
        )
    return assets


def _per_class_art(recipe: BookConfig, slug: str) -> Path | None:
    """Look for art-library ``<slug>.png`` fallbacks for a generated child."""
    for ext in ("png", "jpg", "jpeg", "webp"):
        candidate = recipe.art_dir / f"{slug}.{ext}"
        if candidate.is_file():
            return candidate
    return None


def _art_path_from_pattern(
    recipe: BookConfig,
    pattern: str | None,
    *,
    slug: str,
    title: str,
) -> Path | None:
    """Resolve an art filename pattern with chapter values."""
    if not pattern:
        return None
    try:
        art_filename = pattern.format(slug=slug, title=title)
    except (KeyError, ValueError):
        return None
    return _art_path(recipe, art_filename)


def _chapter_slug(spec: ContentItemSpec, title: str) -> str:
    """Return an explicit recipe slug or derive one from the chapter title."""
    return spec.slug or slugify(title)


def _chapter_from_spec(
    spec: ContentItemSpec,
    recipe: BookConfig,
    title: str,
    *,
    source_files: list[Path] | None = None,
    source_titles: list[str | None] | None = None,
    source_strip_related: list[bool] | None = None,
    source_filler_enabled: list[bool] | None = None,
    source_boundary_filler_slots: list[str] | None = None,
    children: list[Chapter] | None = None,
    slug: str | None = None,
    eyebrow: str | None = None,
    style: str | None = None,
    art_path: Path | None = None,
    use_spec_art: bool = True,
    spot_art_path: Path | None = None,
    replace_opening_art: bool = False,
    individual_pdf: bool = False,
    individual_pdf_subdir: str | None = None,
    divider: bool = False,
) -> Chapter:
    """Create a Chapter with shared recipe-derived defaults."""
    return Chapter(
        title=title,
        slug=slug if slug is not None else _chapter_slug(spec, title),
        eyebrow=eyebrow if eyebrow is not None else spec.eyebrow,
        art_path=(
            art_path if not use_spec_art else _chapter_art_path(recipe, spec, title)
        ),
        spot_art_path=spot_art_path,
        replace_opening_art=replace_opening_art,
        tailpiece_path=_art_path(recipe, spec.art.tailpiece),
        headpiece_path=_art_path(recipe, spec.art.headpiece),
        break_ornament_path=_art_path(recipe, spec.art.break_ornament),
        source_files=list(source_files or []),
        source_titles=list(source_titles or []),
        source_strip_related=list(source_strip_related or []),
        source_filler_enabled=list(source_filler_enabled or []),
        source_boundary_filler_slots=list(source_boundary_filler_slots or []),
        subclass_filler_slots=list(recipe.fillers.markers.subclass.slots),
        fillers_enabled=spec.art.fillers_enabled,
        children=list(children or []),
        individual_pdf=individual_pdf,
        individual_pdf_subdir=individual_pdf_subdir,
        style=style if style is not None else spec.style,
        divider=divider,
        full_page_sections=list(spec.full_page_sections),
        toc_depth=spec.toc_depth,
        art_inserts=list(spec.art.placements),
    )


def _find_chapter(chapters: list[Chapter], name: str) -> Chapter | None:
    """Find a chapter by exact slug or case-insensitive title match."""
    lowered = name.lower()
    for chapter in chapters:
        for candidate in chapter.walk():
            if (
                candidate.slug == lowered
                or candidate.slug == slugify(name)
                or candidate.title.lower() == lowered
            ):
                return candidate
    return None


def _build_splashes(
    specs: list[ArtPlacementSpec],
    recipe: BookConfig,
    chapters: list[Chapter],
    warnings: list[str],
) -> list[Splash]:
    """Resolve dynamic art placements to filesystem paths and chapter slugs."""
    splashes: list[Splash] = []
    has_back_cover = any(spec.target == "back-cover" for spec in specs)
    for index, spec in enumerate(specs):
        chapter_slug: str | None = None
        if spec.chapter:
            chapter = _find_chapter(chapters, spec.chapter)
            if chapter is None:
                raise ManifestError(
                    "art placement "
                    f"{spec.id or index + 1!r} references unknown chapter "
                    f"{spec.chapter!r}"
                )
            chapter_slug = chapter.slug

        art_path = resolve_art_asset(
            recipe,
            art=spec.art,
            role=spec.role,
            context=spec.context,
            subject=spec.subject or (chapter_slug if spec.context is None else None),
        )
        placement_id = spec.id or slugify(
            "-".join(
                part
                for part in (
                    spec.role,
                    spec.context,
                    spec.subject,
                    chapter_slug,
                    spec.target,
                    spec.heading,
                    str(index + 1),
                )
                if part
            )
        )
        if art_path is None:
            label = spec.art or spec.context or spec.subject or spec.role
            warnings.append(
                f"art placement {placement_id!r}: art not found for {label!r}"
            )

        splashes.append(
            Splash(
                id=placement_id,
                art_path=art_path,
                target=spec.target,
                placement=spec.placement,
                chapter_slug=chapter_slug,
                heading_slug=slugify(spec.heading) if spec.heading else None,
            )
        )
    splashes.extend(_build_scoped_art_splashes(chapters, recipe, warnings))
    if not has_back_cover:
        back_cover = convention_art_path(recipe, {"cover-back"})
        if back_cover is not None:
            splashes.append(
                Splash(
                    id="auto-cover-back",
                    art_path=back_cover,
                    target="back-cover",
                    placement="back-cover",
                )
            )
    return splashes


def _build_scoped_art_splashes(
    chapters: list[Chapter],
    recipe: BookConfig,
    warnings: list[str],
) -> list[Splash]:
    """Resolve content-item ``art:`` inserts into chapter splash placements."""
    splashes: list[Splash] = []
    for chapter in chapters:
        for candidate in chapter.walk():
            for index, insert in enumerate(candidate.art_inserts):
                art_path = resolve_art_asset(
                    recipe,
                    art=insert.art,
                    role=insert.role,
                    context=insert.context,
                    subject=None if insert.context else candidate.slug,
                )
                splash_id = insert.id or slugify(
                    "-".join(
                        part
                        for part in (
                            candidate.slug,
                            insert.context,
                            insert.target,
                            insert.heading,
                            str(index + 1),
                        )
                        if part
                    )
                )
                if art_path is None:
                    label = insert.art or insert.context or candidate.slug
                    warnings.append(
                        f"art insert {splash_id!r}: art not found for {label!r}"
                    )
                splashes.append(
                    Splash(
                        id=splash_id,
                        art_path=art_path,
                        target=insert.target,
                        placement=insert.placement,
                        chapter_slug=candidate.slug,
                        heading_slug=(
                            slugify(insert.heading) if insert.heading else None
                        ),
                    )
                )
    return splashes


def _build_filler_catalog(recipe: BookConfig, warnings: list[str]) -> FillerCatalog:
    """Resolve recipe filler assets to filesystem paths."""
    spec = recipe.fillers
    if not spec.enabled:
        return FillerCatalog()
    slots = {
        name: FillerSlot(
            name=slot.name,
            min_space_in=slot.min_space_in,
            max_space_in=slot.max_space_in,
            shapes=list(slot.shapes),
        )
        for name, slot in spec.slots.items()
    }
    assets: list[FillerAsset] = []
    seen_ids: set[str] = set()
    seen_paths: set[Path] = set()
    for asset_spec in spec.assets:
        if asset_spec.id in seen_ids:
            warnings.append(f"filler {asset_spec.id!r}: duplicate id ignored")
            continue
        seen_ids.add(asset_spec.id)
        art_path = _filler_art_path(recipe, asset_spec)
        if art_path is None:
            warnings.append(
                f"filler {asset_spec.id!r}: art not found: {asset_spec.art}"
            )
            continue
        seen_paths.add(art_path.resolve())
        assets.append(
            FillerAsset(
                id=asset_spec.id,
                art_path=art_path,
                shape=asset_spec.shape,
                height_in=asset_spec.height_in,
            )
        )
    assets.extend(
        _auto_filler_assets(
            recipe,
            seen_ids=seen_ids,
            seen_paths=seen_paths,
        )
    )
    return FillerCatalog(enabled=True, slots=slots, assets=assets)


def _build_page_damage_catalog(
    recipe: BookConfig,
    warnings: list[str],
) -> PageDamageCatalog:
    """Resolve transparent page-wear assets from the recipe art library."""
    spec = recipe.wear
    if not spec.enabled:
        return PageDamageCatalog()

    root = _page_damage_art_root(recipe)
    if not root.is_dir():
        warnings.append(f"wear: folder not found: {root}")
        return PageDamageCatalog(
            enabled=True,
            seed=spec.seed or recipe.title,
            density=spec.density,
            max_assets_per_page=spec.max_assets_per_page,
            opacity=spec.opacity,
            glaze_opacity=spec.glaze_opacity,
            glaze_texture=spec.glaze_texture,
            skip=list(spec.skip),
        )

    assets: list[PageDamageAsset] = []
    seen_ids: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.suffix.lower() not in PAGE_DAMAGE_IMAGE_SUFFIXES:
            continue
        asset = _page_damage_asset_from_path(path.resolve(), art_root=root)
        if asset is None:
            if path.stem.lower().startswith("wear-"):
                warnings.append(
                    f"wear: ignored asset with invalid name/family/size: {path.name}"
                )
            continue
        if asset.id in seen_ids:
            warnings.append(f"wear {asset.id!r}: duplicate id ignored")
            continue
        seen_ids.add(asset.id)
        assets.append(asset)

    if not assets:
        warnings.append(f"wear: no assets found in {root}")

    return PageDamageCatalog(
        enabled=True,
        seed=spec.seed or recipe.title,
        density=spec.density,
        max_assets_per_page=spec.max_assets_per_page,
        opacity=spec.opacity,
        glaze_opacity=spec.glaze_opacity,
        glaze_texture=spec.glaze_texture,
        skip=list(spec.skip),
        assets=assets,
    )


def _attach_chapter_filler_slots(
    chapters: list[Chapter],
    catalog: FillerCatalog,
    markers: FillerMarkersSpec,
    warnings: list[str],
) -> None:
    """Attach terminal conditional filler slots to chapters with body content."""
    if not catalog.enabled:
        return
    by_path = {asset.art_path.resolve(): asset for asset in catalog.assets}
    by_id = {asset.id: asset for asset in catalog.assets}
    for chapter in chapters:
        for candidate in chapter.walk():
            candidate.filler_slots.clear()
            candidate.heading_filler_markers = []
            if not candidate.fillers_enabled:
                candidate.source_boundary_filler_slots = []
                candidate.subclass_filler_slots = []
                continue
            candidate.heading_filler_markers = _chapter_heading_filler_markers(
                candidate,
                markers.headings,
                catalog,
            )
            candidate.subclass_filler_slots = _valid_marker_slots(
                candidate.subclass_filler_slots,
                catalog,
            )
            if not candidate.source_files:
                continue
            candidate.source_boundary_filler_slots = _valid_marker_slots(
                candidate.source_boundary_filler_slots,
                catalog,
            )
            if _skip_terminal_filler_slot(candidate):
                continue
            slot_names = _terminal_marker_slots(
                candidate,
                markers,
                catalog,
            )
            if not slot_names:
                continue
            preferred_asset = None
            if candidate.tailpiece_path is not None:
                preferred_asset = by_path.get(candidate.tailpiece_path.resolve())
                if preferred_asset is None:
                    preferred_asset = by_id.get(candidate.tailpiece_path.stem)
                if preferred_asset is None:
                    warnings.append(
                        f"chapter {candidate.slug!r}: tailpiece has no matching "
                        "filler asset"
                    )
            for slot_name in slot_names:
                candidate.filler_slots.append(
                    ChapterFillerSlot(
                        id=f"filler-{slot_name}-{candidate.slug}",
                        slot=slot_name,
                        chapter_slug=candidate.slug,
                        preferred_asset_id=(
                            preferred_asset.id if preferred_asset is not None else None
                        ),
                        section_slug=candidate.slug,
                        section_title=candidate.title,
                        slot_kind="terminal",
                        context=_chapter_filler_context(candidate),
                    )
                )


def _valid_marker_slots(slots: list[str], catalog: FillerCatalog) -> list[str]:
    """Return configured marker slots that exist in the filler catalog."""
    return [slot for slot in slots if slot in catalog.slots]


def _terminal_marker_slots(
    chapter: Chapter,
    markers: FillerMarkersSpec,
    catalog: FillerCatalog,
) -> list[str]:
    """Return terminal marker slots for a chapter, preserving class fallback."""
    if chapter.style == "class":
        class_slots = _valid_marker_slots(list(markers.terminal.class_slots), catalog)
        if class_slots:
            return class_slots
        return _valid_marker_slots(list(markers.terminal.chapter_slots), catalog)
    return _valid_marker_slots(list(markers.terminal.chapter_slots), catalog)


def _chapter_heading_filler_markers(
    chapter: Chapter,
    marker_specs: list[FillerHeadingMarkerSpec],
    catalog: FillerCatalog,
) -> list[ChapterHeadingFillerMarker]:
    markers: list[ChapterHeadingFillerMarker] = []
    for spec in marker_specs:
        if spec.slot not in catalog.slots:
            continue
        if not _marker_spec_matches_chapter(spec, chapter):
            continue
        markers.append(
            ChapterHeadingFillerMarker(
                slot=spec.slot,
                heading_level=spec.heading_level,
                slot_kind=spec.slot_kind,
                skip_first=spec.skip_first,
                context=spec.context or _chapter_filler_context(chapter),
            )
        )
    return markers


def _marker_spec_matches_chapter(
    spec: FillerHeadingMarkerSpec,
    chapter: Chapter,
) -> bool:
    target = spec.chapter.lower().strip()
    return target in {
        chapter.slug.lower(),
        chapter.title.lower(),
        slugify(chapter.title),
    }


def _set_fillers_enabled(chapter: Chapter, enabled: bool) -> None:
    chapter.fillers_enabled = enabled
    for child in chapter.children:
        _set_fillers_enabled(child, enabled)


def _skip_terminal_filler_slot(chapter: Chapter) -> bool:
    if not chapter.slug.startswith("original-") or chapter.tailpiece_path is not None:
        return False
    return chapter.style not in {
        "rules",
        "class",
        "powers",
        "equipment",
        "source-reference",
    }


def _chapter_filler_context(chapter: Chapter) -> str:
    if chapter.slug.startswith("original-") or chapter.style == "source-reference":
        return "reference"
    if chapter.style == "powers" or chapter.slug in {
        "powers",
        "spells",
        "spellcasting",
    }:
        return "powers"
    if chapter.style == "equipment" or chapter.slug in {"combat", "gear", "equipment"}:
        return "combat"
    if chapter.style == "quick-reference" or chapter.slug in {
        "quick-reference",
        "reference",
    }:
        return "reference"
    if chapter.style == "class":
        return "class"
    if chapter.style == "ancestries" or chapter.slug == "frames":
        return "frame"
    if chapter.style == "backgrounds":
        return "setting"
    if chapter.slug in {"languages", "language"}:
        return "languages"
    if chapter.slug in {"setting-primer", "backgrounds", "for-gms"}:
        return "setting"
    return "general"


# ---------------------------------------------------------------------------
# Kind handlers
# ---------------------------------------------------------------------------


def _build_file_chapter(
    spec: ContentItemSpec,
    recipe: BookConfig,
    vault_index: VaultIndex,
) -> Chapter:
    """Build a chapter from one markdown source file."""
    if spec.source is None:
        raise ManifestError("file chapter requires a source")
    src = _resolve_source(spec.source, recipe, vault_index)
    title = spec.title or src.stem
    return _chapter_from_spec(
        spec,
        recipe,
        title,
        source_files=[src],
        individual_pdf=spec.individual_pdfs,
        individual_pdf_subdir=spec.individual_pdf_subdir,
    )


def _build_catalog_chapter(
    spec: ContentItemSpec,
    recipe: BookConfig,
    vault_index: VaultIndex,
    warnings: list[str],
) -> Chapter:
    """Render a `catalog` as ONE chapter.

    For embed-format catalogs we just pass the catalog file itself through --
    obsidian-export will inline the embeds at export time. For bullet-link
    catalogs we resolve each link via VaultIndex and concatenate the targets
    in order.
    """
    if spec.source is None:
        raise ManifestError("catalog chapter requires a source")
    src = _resolve_source(spec.source, recipe, vault_index)
    parsed = parse_catalog_file(src)
    title = spec.title or src.stem

    chapter = _chapter_from_spec(
        spec,
        recipe,
        title,
        individual_pdf=spec.individual_pdfs,
        individual_pdf_subdir=spec.individual_pdf_subdir,
    )

    if parsed.format in ("embed-compendium", "annotated-embeds", "empty"):
        # The catalog file itself is the source -- obsidian-export inlines embeds.
        chapter.source_files = [src]
        return chapter

    # bullet-links or mixed: follow each link explicitly through VaultIndex.
    # Vault overlay priority takes precedence here -- if `vault_overlay` is
    # [nimble, custom], a `[[Mage]]` link in nimble's catalog will still
    # resolve to custom's Mage when custom has one. This is what makes
    # "thin override vault" possible.
    files: list[Path] = []
    for entry in parsed.entries:
        hit = vault_index.resolve(entry.target)
        if hit is None:
            entry_kind = "embed" if entry.is_embed else "link"
            warnings.append(
                f"catalog {src.name}: unresolved {entry_kind} [[{entry.target.raw}]]",
            )
            continue
        files.append(hit)
    chapter.source_files = files
    return chapter


def _build_composite_chapter(
    spec: ContentItemSpec,
    recipe: BookConfig,
    vault_index: VaultIndex,
) -> Chapter:
    """Render a folder-as-chapter: alphabetical concatenation of all .md files."""
    if spec.source is None:
        raise ManifestError("composite chapter requires a source")
    if spec.source.vault is None:
        raise ManifestError(
            "`composite` chapter requires explicit vault prefix in source: "
            f"{spec.source!s}"
        )
    vault = recipe.vault_by_name(spec.source.vault)
    if vault is None:
        raise ManifestError(f"unknown vault {spec.source.vault!r}")
    folder = (vault.path / spec.source.path).resolve()
    if not folder.is_dir():
        raise ManifestError(f"composite source must be a directory: {folder}")
    files = sorted(folder.rglob("*.md"))
    title = spec.title or folder.name
    return _chapter_from_spec(
        spec,
        recipe,
        title,
        source_files=files,
        individual_pdf=spec.individual_pdfs,
        individual_pdf_subdir=spec.individual_pdf_subdir,
    )


def _build_classes_catalog_chapters(
    spec: ContentItemSpec,
    recipe: BookConfig,
    vault_index: VaultIndex,
    warnings: list[str],
) -> list[Chapter]:
    """Build per-class chapters from a Classes List catalog.

    The catalog must be in `bullet-links` format with `# ClassName` headings
    grouping the per-class file lists. Each group becomes one Chapter with
    source_files = [resolved file for each bullet].

    With `wrapper: false` (default), returns a flat list of sibling chapters.
    With `wrapper: true`, returns a single wrapper Chapter containing all
    per-class chapters as children.
    """
    if spec.source is None:
        raise ManifestError("classes-catalog chapter requires a source")
    src = _resolve_source(spec.source, recipe, vault_index)
    parsed = parse_catalog_file(src)
    if parsed.format not in ("bullet-links", "mixed"):
        raise ManifestError(
            f"`classes-catalog` requires a bullet-links catalog at {src.name}, "
            f"got format={parsed.format!r}"
        )

    children: list[Chapter] = []
    for group in parsed.groups:
        if not group.entries:
            continue
        class_name = group.name.strip()
        # Strip "(Original)" suffix if present, e.g. "Bonded (Mage)" -> "Bonded"
        clean_name = re.sub(r"\s*\([^)]*\)\s*$", "", class_name).strip() or class_name
        slug = slugify(clean_name)
        files: list[Path] = []
        for entry in group.entries:
            # Vault overlay priority resolves links: highest-priority vault wins
            hit = vault_index.resolve(entry.target)
            if hit is None:
                warnings.append(
                    f"classes-catalog {src.name} [{class_name}]: "
                    f"unresolved [[{entry.target.raw}]]"
                )
                continue
            files.append(hit)
        if not files:
            warnings.append(
                f"classes-catalog: skipping {class_name!r} (no resolved files)"
            )
            continue
        art = _art_path_from_pattern(
            recipe,
            spec.art.children.divider_pattern,
            slug=slug,
            title=clean_name,
        )
        if art is None and spec.art.children.per_child:
            art = _per_class_art(recipe, slug)
        if art is None:
            art = _class_art_path(recipe, slug)
        if spec.art.children.divider_pattern and art is None:
            warnings.append(
                f"classes-catalog {src.name} [{class_name}]: "
                f"class divider art not found for slug {slug!r}"
            )
        spot_art = _art_path_from_pattern(
            recipe,
            spec.art.children.opening_spot_pattern,
            slug=slug,
            title=clean_name,
        )
        if spot_art is None:
            spot_art = _class_spot_art_path(recipe, slug)
        if spec.art.children.opening_spot_pattern and spot_art is None:
            warnings.append(
                f"classes-catalog {src.name} [{class_name}]: "
                f"class spot art not found for slug {slug!r}"
            )
        ch = _chapter_from_spec(
            spec,
            recipe,
            clean_name,
            slug=slug,
            eyebrow="Class",
            art_path=art,
            use_spec_art=False,
            spot_art_path=spot_art,
            replace_opening_art=spec.art.children.replace_opening_art,
            source_files=files,
            style=spec.child_style,
            individual_pdf=spec.individual_pdfs,
            individual_pdf_subdir=spec.individual_pdf_subdir,
            divider=spec.child_divider,
        )
        children.append(ch)

    if not spec.wrapper:
        if spec.title:
            warnings.append(
                f"classes-catalog: title {spec.title!r} ignored because wrapper=false"
            )
        return children

    wrapper_title = spec.title or "Classes"
    wrapper = _chapter_from_spec(
        spec,
        recipe,
        wrapper_title,
        children=children,
    )
    return [wrapper]


def _build_group_chapter(
    spec: ContentItemSpec,
    recipe: BookConfig,
    vault_index: VaultIndex,
    warnings: list[str],
) -> Chapter:
    """Build a `group` chapter wrapper with no body of its own.

    Group children are declared inline via `children:` and are dispatched
    through the same kind handlers as top-level chapters. This makes groups
    compose with files, catalogs, composites, class catalogs, folders, and
    nested groups.
    """
    wrapper_title = spec.title or "Group"
    wrapper = _chapter_from_spec(spec, recipe, wrapper_title)

    for child_spec in spec.children:
        child_chapters = _dispatch_chapter(child_spec, recipe, vault_index, warnings)
        for ch in child_chapters:
            # Inherit child styling defaults from the group when the child
            # left them alone, and propagate the `child_divider` toggle.
            if child_spec.style == "default" and spec.child_style != "default":
                ch.style = spec.child_style
            if spec.child_divider:
                ch.divider = True
            if not wrapper.fillers_enabled:
                _set_fillers_enabled(ch, False)
            wrapper.children.append(ch)

    return wrapper


def _build_sequence_chapter(
    spec: ContentItemSpec,
    recipe: BookConfig,
    vault_index: VaultIndex,
) -> Chapter:
    """Build a mixed-source chapter from an explicit ordered source list."""
    files: list[Path] = []
    source_titles: list[str | None] = []
    source_strip_related: list[bool] = []
    source_filler_enabled: list[bool] = []
    for item in spec.sources:
        files.append(_resolve_source(item.source, recipe, vault_index))
        source_titles.append(item.title)
        source_strip_related.append(item.strip_related)
        source_filler_enabled.append(item.filler_enabled)

    title = spec.title or (source_titles[0] if source_titles else None) or files[0].stem
    return _chapter_from_spec(
        spec,
        recipe,
        title,
        source_files=files,
        source_titles=source_titles,
        source_strip_related=source_strip_related,
        source_filler_enabled=source_filler_enabled,
        source_boundary_filler_slots=list(
            recipe.fillers.markers.source_boundary.sequence_slots
        ),
        individual_pdf=spec.individual_pdfs,
        individual_pdf_subdir=spec.individual_pdf_subdir,
    )


def _build_folder_chapter(
    spec: ContentItemSpec,
    recipe: BookConfig,
    vault_index: VaultIndex,
) -> Chapter:
    """All `.md` in a folder, sorted alphabetically."""
    if spec.source is None:
        raise ManifestError("folder chapter requires a source")
    if spec.source.vault is None:
        raise ManifestError(
            "`folder` chapter requires explicit vault prefix in source: "
            f"{spec.source!s}"
        )
    vault = recipe.vault_by_name(spec.source.vault)
    if vault is None:
        raise ManifestError(f"unknown vault {spec.source.vault!r}")
    folder = (vault.path / spec.source.path).resolve()
    if not folder.is_dir():
        raise ManifestError(f"folder source must be a directory: {folder}")
    files = sorted(folder.glob("*.md"))
    title = spec.title or folder.name
    return _chapter_from_spec(
        spec,
        recipe,
        title,
        source_files=files,
        individual_pdf=spec.individual_pdfs,
        individual_pdf_subdir=spec.individual_pdf_subdir,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _dispatch_chapter(
    spec: ContentItemSpec,
    recipe: BookConfig,
    vault_index: VaultIndex,
    warnings: list[str],
) -> list[Chapter]:
    """Run the kind handler for one chapter spec.

    Most chapter kinds yield exactly one `Chapter`; `classes-catalog` with
    `wrapper=false` yields several sibling chapters.
    """
    if spec.kind == "file":
        return [_build_file_chapter(spec, recipe, vault_index)]
    if spec.kind == "catalog":
        return [_build_catalog_chapter(spec, recipe, vault_index, warnings)]
    if spec.kind == "composite":
        return [_build_composite_chapter(spec, recipe, vault_index)]
    if spec.kind == "classes-catalog":
        return _build_classes_catalog_chapters(spec, recipe, vault_index, warnings)
    if spec.kind == "folder":
        return [_build_folder_chapter(spec, recipe, vault_index)]
    if spec.kind == "group":
        return [_build_group_chapter(spec, recipe, vault_index, warnings)]
    if spec.kind == "sequence":
        return [_build_sequence_chapter(spec, recipe, vault_index)]
    raise ManifestError(f"unknown chapter kind: {spec.kind!r}")


def _content_part(
    spec: ContentItemSpec,
    recipe: BookConfig,
    vault_index: VaultIndex,
    warnings: list[str],
) -> tuple[list[BookPart], list[Chapter]]:
    """Resolve one ordered content spec into render parts and chapter entries."""
    if spec.kind == "toc":
        title = spec.title or "Table of Contents"
        return ([TocPart(title=title, slug=slugify(title), depth=spec.depth)], [])
    if spec.kind == "generated":
        if spec.type is None:
            raise ManifestError("generated content requires a type")
        title = spec.title or _default_generated_title(spec.type)
        return (
            [
                GeneratedPart(
                    type=spec.type,
                    title=title,
                    slug=spec.slug or slugify(title),
                    style=spec.style,
                )
            ],
            [],
        )
    chapters = _dispatch_chapter(spec, recipe, vault_index, warnings)
    return (list(chapters), chapters)


def _default_generated_title(kind: str) -> str:
    return {
        "art-credits": "Art Credits",
        "appendix-index": "Index",
        "changelog": "Changelog",
        "copyright": "Copyright",
        "credits": "Credits",
        "license": "License",
        "title-page": "Title Page",
    }.get(kind, kind.replace("-", " ").title())


def build_manifest(recipe: BookConfig) -> Manifest:
    """Walk the recipe and produce a Manifest with a populated Chapter tree."""
    # Build VaultIndex in priority order from recipe.vault_overlay
    vault_specs = [(name, recipe.vaults[name].path) for name in recipe.vault_overlay]
    vault_index = VaultIndex.from_recipe_paths(vault_specs)

    warnings: list[str] = []
    chapters: list[Chapter] = []
    contents: list[BookPart] = []
    for spec in recipe.contents:
        parts, part_chapters = _content_part(spec, recipe, vault_index, warnings)
        contents.extend(parts)
        chapters.extend(part_chapters)
    splashes = _build_splashes(recipe.art_placements, recipe, chapters, warnings)
    fillers = _build_filler_catalog(recipe, warnings)
    page_damage = _build_page_damage_catalog(recipe, warnings)
    _attach_chapter_filler_slots(chapters, fillers, recipe.fillers.markers, warnings)

    return Manifest(
        recipe=recipe,
        vault_index=vault_index,
        chapters=chapters,
        contents=contents,
        splashes=splashes,
        fillers=fillers,
        page_damage=page_damage,
        warnings=warnings,
    )
