"""Build planning and rendering orchestration for recipe-driven PDFs."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from papercrown.assembly import markdown as assembly
from papercrown.assembly import ttrpg
from papercrown.build.options import (
    BuildScope,
    BuildTarget,
    DraftMode,
    OutputProfile,
    PageDamageMode,
    PaginationMode,
)
from papercrown.build.requests import BuildRequest, BuildResult
from papercrown.media import images
from papercrown.media import page_damage as page_damage_module
from papercrown.project import paths, themes
from papercrown.project.manifest import (
    Chapter,
    FillerAsset,
    FillerCatalog,
    Manifest,
    PageDamageAsset,
    PageDamageCatalog,
    Splash,
    convention_art_path,
    slugify,
)
from papercrown.project.recipe import BookConfig
from papercrown.project.resources import (
    ASSETS_DIR,
    CORE_CSS_FILES,
    FONTS_DIR,
    LUA_FILTERS,
    TEXTURES_DIR,
)
from papercrown.render import jobs as _build_jobs
from papercrown.render import pipeline
from papercrown.render import web as _build_web
from papercrown.render.jobs import PdfRenderJob as PdfRenderJob
from papercrown.system.cache import ArtifactCache, JsonValue, fingerprint_files
from papercrown.system.diagnostics import DiagnosticSeverity
from papercrown.system.export import Tools, ensure_exports_fresh

_BuildTimer = _build_jobs.BuildTimer
_RenderJobHooks = _build_jobs.RenderJobHooks
_configure_job_timings = _build_jobs.configure_job_timings
_run_prepared_jobs = _build_jobs.run_prepared_jobs
_run_render_job_cached = _build_jobs.run_render_job_cached

LogFn = Callable[[str], None]
# Bundled fonts required by the core styles and packaged runtime.
REQUIRED_FONTS: tuple[str, ...] = (
    "Rajdhani-Regular.ttf",
    "Rajdhani-SemiBold.ttf",
    "Rajdhani-Bold.ttf",
    "ShareTechMono-Regular.ttf",
    "IBMPlexSerif-Regular.ttf",
    "IBMPlexSerif-Italic.ttf",
    "IBMPlexSerif-Bold.ttf",
    "IBMPlexSerif-BoldItalic.ttf",
)


@dataclass(frozen=True)
class _PdfJobOptions:
    """Internal render options shared by chapter and combined-book jobs."""

    profile: OutputProfile
    include_art: bool = True
    draft_mode: DraftMode = DraftMode.FAST
    pagination_mode: PaginationMode = PaginationMode.REPORT
    page_damage_mode: PageDamageMode = PageDamageMode.AUTO
    clean_pdf: bool = True
    image_session: images.ImageOptimizationSession | None = None
    filler_debug_overlay: bool = False


def missing_fonts() -> list[str]:
    """Return the bundled font filenames that are not present on disk."""
    return [name for name in REQUIRED_FONTS if not (FONTS_DIR / name).is_file()]


def _is_fast_draft(profile: OutputProfile, draft_mode: DraftMode) -> bool:
    """Return whether this build should use lightweight draft behavior."""
    return profile is OutputProfile.DRAFT and draft_mode is DraftMode.FAST


def _image_profile_for(profile: OutputProfile, draft_mode: DraftMode) -> str:
    """Return the image optimization profile for a render request."""
    if profile is OutputProfile.DRAFT and draft_mode is DraftMode.VISUAL:
        return "draft-visual"
    return profile.value


def _effective_page_damage_mode(request: BuildRequest) -> PageDamageMode:
    """Return the concrete page-damage mode for a build request."""
    if request.page_damage_mode is not PageDamageMode.AUTO:
        return request.page_damage_mode
    if _is_fast_draft(request.profile, request.draft_mode):
        return PageDamageMode.OFF
    return PageDamageMode.FAST


def _image_cache_root(recipe: BookConfig) -> Path:
    """Return the recipe image cache root, with a fallback for lightweight tests."""
    cache_dir = getattr(recipe, "cache_dir", Path.cwd() / ".papercrown-cache")
    return cache_dir / "images"


def make_base_context(
    tools: Tools,
    recipe: BookConfig,
    *,
    profile: OutputProfile,
    include_art: bool = True,
    draft_mode: DraftMode = DraftMode.FAST,
    pagination_mode: PaginationMode = PaginationMode.REPORT,
    page_damage_mode: PageDamageMode = PageDamageMode.AUTO,
    clean_pdf: bool = True,
    image_session: images.ImageOptimizationSession | None = None,
) -> pipeline.RenderContext:
    """Create a render context shared by chapter and combined-book builds."""
    image_profile = _image_profile_for(profile, draft_mode)
    art_dir = recipe.art_dir
    cache_dir = getattr(recipe, "cache_dir", Path.cwd() / ".papercrown-cache")
    vault_priority_paths: list[Path] = getattr(
        recipe,
        "vault_priority_paths",
        lambda: [],
    )()
    theme = themes.load_theme(recipe)
    resource_paths = [
        cache_dir / "exports",
        ASSETS_DIR,
        art_dir,
        FONTS_DIR,
        *vault_priority_paths,
        *theme.resource_paths,
    ]
    deduped_resource_paths = list(dict.fromkeys(p.resolve() for p in resource_paths))
    inline_css = [theme.inline_css] if theme.inline_css else []
    ctx = pipeline.RenderContext(
        pandoc=tools.pandoc,
        weasyprint=tools.weasyprint,
        template=theme.template,
        css_files=[*CORE_CSS_FILES, *theme.css_files],
        inline_css=inline_css,
        lua_filters=list(LUA_FILTERS),
        resource_paths=deduped_resource_paths,
        fingerprint_paths=list(theme.fingerprint_paths),
        output_profile=profile.value,
        title_prefix=recipe.title,
    )
    image_settings = images.image_profile_settings(image_profile)
    ctx.pdf_settings = pipeline.PdfRenderSettings(
        optimize_images=True,
        dpi=image_settings.target_dpi,
        jpeg_quality=image_settings.jpeg_quality,
    )
    ctx.image_profile = image_profile
    ctx.clean_pdf = clean_pdf and not _is_fast_draft(profile, draft_mode)
    ctx.draft_placeholders = _is_fast_draft(profile, draft_mode)
    ctx.draft_mode = draft_mode.value if profile is OutputProfile.DRAFT else ""
    ctx.pagination_mode = pagination_mode.value
    ctx.page_damage_mode = page_damage_mode.value
    if include_art and not _is_fast_draft(profile, draft_mode):
        ctx.ornament_folio_frame = _optimized_box_image(
            _recipe_ornament_path(recipe, "folio_frame"),
            profile=image_profile,
            max_width_in=0.64,
            max_height_in=0.64,
            cache_root=cache_dir / "images",
            image_session=image_session,
        )
        ctx.ornament_corner_bracket = _optimized_box_image(
            _recipe_ornament_path(recipe, "corner_bracket"),
            profile=image_profile,
            max_width_in=1.0,
            max_height_in=1.0,
            cache_root=cache_dir / "images",
            image_session=image_session,
        )
    return ctx


def slugs_for_anchors(chapters: list[Chapter]) -> str:
    """Return valid in-document anchor slugs for the internal-links Lua filter."""
    seen: set[str] = set()
    for chapter in chapters:
        for descendant in chapter.walk():
            if descendant.slug:
                seen.add(descendant.slug)
            seen.add(slugify(descendant.title))
            for source in descendant.source_files:
                seen.add(slugify(source.stem))
    return ",".join(sorted(slug for slug in seen if slug))


def context_for_chapter(
    tools: Tools,
    recipe: BookConfig,
    chapter: Chapter,
    *,
    profile: OutputProfile,
    include_art: bool = True,
    draft_mode: DraftMode = DraftMode.FAST,
    pagination_mode: PaginationMode = PaginationMode.REPORT,
    page_damage_mode: PageDamageMode = PageDamageMode.AUTO,
    clean_pdf: bool = True,
    image_session: images.ImageOptimizationSession | None = None,
) -> pipeline.RenderContext:
    """Create a render context for a standalone chapter PDF."""
    ctx = make_base_context(
        tools,
        recipe,
        profile=profile,
        include_art=include_art,
        draft_mode=draft_mode,
        pagination_mode=pagination_mode,
        page_damage_mode=page_damage_mode,
        clean_pdf=clean_pdf,
        image_session=image_session,
    )
    ctx.chapter_title = chapter.title
    ctx.chapter_eyebrow = chapter.eyebrow or "Chapter"
    if include_art and not _is_fast_draft(profile, draft_mode):
        ctx.chapter_art = _optimized_optional_image(
            chapter.art_path,
            profile=_image_profile_for(profile, draft_mode),
            cache_root=_image_cache_root(recipe),
            image_session=image_session,
        )
    ctx.section_kind = chapter.style or "default"
    if chapter.style == "quick-reference":
        ctx.chapter_opener = False
        ctx.chapter_art = None
    ctx.valid_anchors = slugs_for_anchors([chapter])
    return ctx


def context_for_book(
    tools: Tools,
    recipe: BookConfig,
    manifest: Manifest,
    *,
    profile: OutputProfile,
    include_art: bool = True,
    draft_mode: DraftMode = DraftMode.FAST,
    pagination_mode: PaginationMode = PaginationMode.REPORT,
    page_damage_mode: PageDamageMode = PageDamageMode.AUTO,
    clean_pdf: bool = True,
    image_session: images.ImageOptimizationSession | None = None,
) -> pipeline.RenderContext:
    """Create a render context for a combined book PDF."""
    ctx = make_base_context(
        tools,
        recipe,
        profile=profile,
        include_art=include_art,
        draft_mode=draft_mode,
        pagination_mode=pagination_mode,
        page_damage_mode=page_damage_mode,
        clean_pdf=clean_pdf,
        image_session=image_session,
    )
    _populate_book_context(
        ctx,
        recipe,
        manifest,
        include_cover_art=include_art,
        profile=profile,
        draft_mode=draft_mode,
        image_session=image_session,
    )
    return ctx


def context_for_web(
    tools: Tools,
    recipe: BookConfig,
    manifest: Manifest,
    *,
    include_art: bool = True,
    image_session: images.ImageOptimizationSession | None = None,
) -> pipeline.RenderContext:
    """Create a render context for the combined static web export."""
    ctx = make_base_context(
        tools,
        recipe,
        profile=OutputProfile.PRINT,
        include_art=include_art,
        image_session=image_session,
    )
    ctx.output_profile = "web"
    ctx.css_files = [Path("styles/book.css")]
    ctx.ornament_folio_frame = None
    ctx.ornament_corner_bracket = None
    _populate_book_context(
        ctx,
        recipe,
        manifest,
        include_cover_art=include_art,
        image_session=image_session,
    )
    return ctx


def _populate_book_context(
    ctx: pipeline.RenderContext,
    recipe: BookConfig,
    manifest: Manifest,
    *,
    include_cover_art: bool,
    profile: OutputProfile = OutputProfile.PRINT,
    draft_mode: DraftMode = DraftMode.FAST,
    image_session: images.ImageOptimizationSession | None = None,
) -> None:
    """Populate combined-book metadata on a render context in place."""
    ctx.chapter_title = recipe.title
    ctx.chapter_eyebrow = recipe.cover_eyebrow or "Book"
    ctx.section_kind = "book"
    ctx.include_toc = False
    ctx.chapter_opener = False
    ctx.valid_anchors = slugs_for_anchors(manifest.chapters)
    metadata = getattr(recipe, "metadata", None)
    if metadata is not None and metadata.authors:
        ctx.book_author = ", ".join(metadata.authors)
    ctx.book_description = getattr(metadata, "description", None)
    keywords = getattr(metadata, "keywords", [])
    if keywords:
        ctx.book_keywords = ", ".join(keywords)
    ctx.book_date = getattr(metadata, "date", None)
    ctx.book_publisher = getattr(metadata, "publisher", None)
    ctx.book_version = getattr(metadata, "version", None)
    ctx.book_license = getattr(metadata, "license", None)
    if recipe.cover.enabled:
        ctx.cover_enabled = True
        ctx.cover_title = recipe.title
        ctx.cover_subtitle = recipe.subtitle
        ctx.cover_eyebrow = recipe.cover_eyebrow
        ctx.cover_footer = recipe.cover_footer
        if include_cover_art and not _is_fast_draft(profile, draft_mode):
            cover_art = _recipe_cover_art_path(recipe)
            if cover_art is not None:
                ctx.cover_art = _optimized_optional_image(
                    cover_art,
                    profile=_image_profile_for(profile, draft_mode),
                    cache_root=_image_cache_root(recipe),
                    image_session=image_session,
                )
        front_splash = _splash_for_target(manifest, "front-cover")
        if (
            include_cover_art
            and not _is_fast_draft(profile, draft_mode)
            and front_splash is not None
            and front_splash.art_path
        ):
            ctx.cover_art = _optimized_optional_image(
                front_splash.art_path,
                profile=_image_profile_for(profile, draft_mode),
                cache_root=_image_cache_root(recipe),
                image_session=image_session,
            )


def _splash_for_target(manifest: Manifest, target: str) -> Splash | None:
    """Return the first resolved splash for a top-level target."""
    splashes = manifest.splashes if hasattr(manifest, "splashes") else []
    for splash in splashes:
        if splash.target == target and splash.art_path is not None:
            return splash
    return None


def _splashes_for_chapter(manifest: Manifest, chapter: Chapter) -> list[Splash]:
    """Return resolved splash placements scoped to ``chapter``."""
    return [
        splash
        for splash in manifest.splashes
        if splash.chapter_slug == chapter.slug and splash.art_path is not None
    ]


def _recipe_ornament_path(recipe: BookConfig, name: str) -> Path | None:
    """Resolve an optional recipe-level ornament path."""
    ornaments = getattr(recipe, "ornaments", None)
    raw = getattr(ornaments, name, None)
    if isinstance(raw, str) and raw.strip():
        path = (recipe.art_dir / raw).resolve()
        return path if path.is_file() else None
    if name == "folio_frame":
        return convention_art_path(recipe, {"ornament-folio"})
    return None


def _recipe_cover_art_path(recipe: BookConfig) -> Path | None:
    """Resolve explicit or convention-derived front cover art."""
    if recipe.cover.art:
        cover_art = (recipe.art_dir / recipe.cover.art).resolve()
        return cover_art if cover_art.is_file() else None
    return convention_art_path(recipe, {"cover-front", "cover"})


def _prepare_ttrpg_markdown(
    markdown: str,
    recipe: BookConfig,
    *,
    include_generated_matter: bool,
) -> str:
    """Apply typed-block normalization and fail on invalid cross-references."""
    prepared = _prepare_ttrpg_markdown_result(markdown, recipe)
    return prepared.markdown


def _prepare_book_markdown_with_manual_toc(
    markdown: str,
    recipe: BookConfig,
    chapters: list[Chapter],
    *,
    toc_max_depth: int | None = None,
) -> str:
    """Prepare book markdown and replace explicit generated/TOC markers."""
    prepared = _prepare_ttrpg_markdown_result(markdown, recipe)
    markdown = _replace_generated_content_markers(
        prepared.markdown,
        recipe,
        prepared.registry,
    )
    return assembly.replace_manual_toc_markers(
        markdown,
        chapters,
        default_max_depth=toc_max_depth,
    )


def _replace_generated_content_markers(
    markdown: str,
    recipe: BookConfig,
    registry: ttrpg.ObjectRegistry,
) -> str:
    """Replace ordered-content generated page markers."""
    out: list[str] = []
    for line in markdown.splitlines():
        match = assembly.GENERATED_MARKER_RE.match(line)
        if match is None:
            out.append(line)
            continue
        out.append(
            ttrpg.render_generated_content(
                match.group("kind").strip(),
                match.group("title").strip(),
                recipe=recipe,
                registry=registry,
                style=match.group("style").strip() or "generated",
            )
        )
    return "\n".join(out)


def _prepare_ttrpg_markdown_result(
    markdown: str,
    recipe: BookConfig,
) -> ttrpg.PreparedMarkdown:
    """Apply typed-block normalization and return the prepared result."""
    prepared = ttrpg.prepare_book_markdown(
        markdown,
        recipe,
        include_generated_matter=False,
    )
    errors = [
        diagnostic
        for diagnostic in prepared.diagnostics
        if diagnostic.severity is DiagnosticSeverity.ERROR
    ]
    if errors:
        details = "\n".join(
            f"  {diagnostic.code}: {diagnostic.message}"
            + (f" (line {diagnostic.line})" if diagnostic.line is not None else "")
            for diagnostic in errors[:10]
        )
        raise RuntimeError("typed TTRPG validation failed:\n" + details)
    return prepared


def _prepare_chapter_pdf_job(
    tools: Tools,
    recipe: BookConfig,
    chapter: Chapter,
    export_map: dict[Path, Path],
    *,
    options: _PdfJobOptions,
    manifest: Manifest | None = None,
) -> PdfRenderJob:
    """Prepare one chapter render without writing the PDF."""
    profile = options.profile
    include_art = options.include_art
    draft_mode = options.draft_mode
    pagination_mode = options.pagination_mode
    page_damage_mode = options.page_damage_mode
    clean_pdf = options.clean_pdf
    image_session = options.image_session
    filler_debug_overlay = options.filler_debug_overlay
    render_art = include_art and not _is_fast_draft(profile, draft_mode)
    render_fillers = render_art and manifest is not None and manifest.fillers.enabled
    markdown = assembly.assemble_chapter_markdown(
        chapter,
        export_map=export_map,
        vault_index=manifest.vault_index if manifest is not None else None,
        splashes=(
            _splashes_for_chapter(manifest, chapter)
            if manifest is not None and render_art
            else None
        ),
        include_splashes=render_art,
        include_fillers=render_fillers,
        include_source_markers=True,
    )
    markdown = _prepare_ttrpg_markdown(
        markdown,
        recipe,
        include_generated_matter=False,
    )
    markdown = _rewrite_render_images(
        markdown,
        recipe,
        manifest,
        profile=profile,
        draft_mode=draft_mode,
        image_session=image_session,
    )
    out = paths.chapter_pdf_path(recipe, chapter, profile=profile)
    ctx = context_for_chapter(
        tools,
        recipe,
        chapter,
        profile=profile,
        include_art=include_art,
        draft_mode=draft_mode,
        pagination_mode=pagination_mode,
        page_damage_mode=page_damage_mode,
        clean_pdf=clean_pdf,
        image_session=image_session,
    )
    ctx.pagination_report_path = _pagination_report_path(out, pagination_mode)
    if filler_debug_overlay:
        ctx.filler_debug_overlay_path = _filler_debug_overlay_path(out)
    return PdfRenderJob(
        label=chapter.title,
        markdown=markdown,
        out=out,
        ctx=ctx,
        input_paths=_chapter_input_paths(chapter, recipe=recipe, manifest=manifest),
        filler_catalog=_render_filler_catalog(
            manifest.fillers if manifest is not None and render_art else None,
            profile=_image_profile_for(profile, draft_mode),
            cache_root=_image_cache_root(recipe),
            image_session=image_session,
        ),
        page_damage_catalog=_render_page_damage_catalog(
            (
                manifest.page_damage
                if manifest is not None
                and render_art
                and page_damage_mode is not PageDamageMode.OFF
                else None
            ),
            profile=_image_profile_for(profile, draft_mode),
            cache_root=_image_cache_root(recipe),
            image_session=image_session,
            proof=page_damage_mode is PageDamageMode.PROOF,
            visual_draft=(
                profile is OutputProfile.DRAFT and draft_mode is DraftMode.VISUAL
            ),
        ),
        recipe_title=recipe.title,
    )


def build_chapter_pdf(
    tools: Tools,
    recipe: BookConfig,
    chapter: Chapter,
    export_map: dict[Path, Path],
    *,
    profile: OutputProfile,
    manifest: Manifest | None = None,
    cache: ArtifactCache | None = None,
    force: bool = False,
    skipped: list[Path] | None = None,
    log: LogFn | None = None,
    include_art: bool = True,
    draft_mode: DraftMode = DraftMode.FAST,
    pagination_mode: PaginationMode = PaginationMode.REPORT,
    page_damage_mode: PageDamageMode = PageDamageMode.AUTO,
    clean_pdf: bool = True,
    timings: bool = False,
    image_session: images.ImageOptimizationSession | None = None,
    filler_debug_overlay: bool = False,
) -> Path:
    """Render one chapter to a PDF and return the output path."""
    job = _prepare_chapter_pdf_job(
        tools,
        recipe,
        chapter,
        export_map,
        manifest=manifest,
        options=_PdfJobOptions(
            profile=profile,
            include_art=include_art,
            draft_mode=draft_mode,
            pagination_mode=pagination_mode,
            page_damage_mode=page_damage_mode,
            clean_pdf=clean_pdf,
            image_session=image_session,
            filler_debug_overlay=filler_debug_overlay,
        ),
    )
    _configure_job_timings([job], enabled=timings, log=log)
    did_skip = _run_render_job_cached(
        job,
        cache=cache,
        force=force,
        log=log,
        hooks=_render_job_hooks(),
    )
    if did_skip and skipped is not None:
        skipped.append(job.out)
    return job.out


def _prepare_combined_book_job(
    tools: Tools,
    recipe: BookConfig,
    manifest: Manifest,
    export_map: dict[Path, Path],
    *,
    options: _PdfJobOptions,
) -> PdfRenderJob:
    """Prepare the combined book render without writing the PDF."""
    profile = options.profile
    include_art = options.include_art
    draft_mode = options.draft_mode
    pagination_mode = options.pagination_mode
    page_damage_mode = options.page_damage_mode
    clean_pdf = options.clean_pdf
    image_session = options.image_session
    filler_debug_overlay = options.filler_debug_overlay
    render_art = include_art and not _is_fast_draft(profile, draft_mode)
    render_fillers = render_art and manifest.fillers.enabled
    back_cover_pages = (
        assembly.render_back_cover_splashes(manifest.splashes) if render_art else ""
    )
    markdown = assembly.assemble_book_contents_markdown(
        manifest.contents,
        export_map=export_map,
        vault_index=manifest.vault_index,
        include_art=render_art,
        include_fillers=render_fillers,
        splashes=manifest.splashes,
        include_source_markers=True,
        include_back_cover_splashes=False,
        recipe=recipe,
    )
    markdown = _prepare_book_markdown_with_manual_toc(
        markdown,
        recipe,
        manifest.chapters,
    )
    if back_cover_pages:
        markdown = f"{markdown.rstrip()}\n\n{back_cover_pages}\n"
    markdown = _rewrite_render_images(
        markdown,
        recipe,
        manifest,
        profile=profile,
        draft_mode=draft_mode,
        image_session=image_session,
    )
    out = paths.combined_book_path(recipe, profile=profile)
    ctx = context_for_book(
        tools,
        recipe,
        manifest,
        profile=profile,
        include_art=include_art,
        draft_mode=draft_mode,
        pagination_mode=pagination_mode,
        page_damage_mode=page_damage_mode,
        clean_pdf=clean_pdf,
        image_session=image_session,
    )
    ctx.pagination_report_path = _pagination_report_path(out, pagination_mode)
    if filler_debug_overlay:
        ctx.filler_debug_overlay_path = _filler_debug_overlay_path(out)
    return PdfRenderJob(
        label=recipe.title,
        markdown=markdown,
        out=out,
        ctx=ctx,
        input_paths=_book_input_paths(recipe, manifest),
        filler_catalog=_render_filler_catalog(
            manifest.fillers if render_art else None,
            profile=_image_profile_for(profile, draft_mode),
            cache_root=_image_cache_root(recipe),
            image_session=image_session,
        ),
        page_damage_catalog=_render_page_damage_catalog(
            (
                manifest.page_damage
                if render_art and page_damage_mode is not PageDamageMode.OFF
                else None
            ),
            profile=_image_profile_for(profile, draft_mode),
            cache_root=_image_cache_root(recipe),
            image_session=image_session,
            proof=page_damage_mode is PageDamageMode.PROOF,
            visual_draft=(
                profile is OutputProfile.DRAFT and draft_mode is DraftMode.VISUAL
            ),
        ),
        recipe_title=recipe.title,
    )


def build_web_book(
    tools: Tools,
    recipe: BookConfig,
    manifest: Manifest,
    export_map: dict[Path, Path],
    *,
    include_art: bool = True,
    log: LogFn | None = None,
    image_session: images.ImageOptimizationSession | None = None,
) -> Path:
    """Render a single-file static HTML book with local CSS, fonts, and images."""
    if log is not None:
        log("Building static web book...")
    out = paths.web_book_path(recipe)
    web_root = out.parent
    _build_web.reset_web_output(web_root)
    _build_web.copy_web_static_assets(web_root, recipe=recipe)

    back_cover_pages = (
        assembly.render_back_cover_splashes(manifest.splashes) if include_art else ""
    )
    markdown = assembly.assemble_book_contents_markdown(
        manifest.contents,
        export_map=export_map,
        vault_index=manifest.vault_index,
        include_art=include_art,
        include_fillers=False,
        include_tailpiece_art=True,
        splashes=manifest.splashes,
        include_source_markers=True,
        include_back_cover_splashes=False,
        recipe=recipe,
    )
    markdown = _prepare_book_markdown_with_manual_toc(
        markdown,
        recipe,
        manifest.chapters,
        toc_max_depth=2,
    )
    if back_cover_pages:
        markdown = f"{markdown.rstrip()}\n\n{back_cover_pages}\n"
    markdown = _rewrite_render_images(
        markdown,
        recipe,
        manifest,
        profile="web",
        image_session=image_session,
    )
    ctx = context_for_web(
        tools,
        recipe,
        manifest,
        include_art=include_art,
        image_session=image_session,
    )
    html = pipeline.render_markdown_to_html(markdown, ctx)
    html = _build_web.rewrite_web_asset_refs(
        html,
        web_root=web_root,
        search_roots=_build_web.web_asset_search_roots(recipe),
    )
    html = _build_web.enhance_web_image_tags(html, web_root=web_root)
    out.write_text(html, encoding="utf-8")
    return out


def _append_single_chapter(
    produced: list[Path],
    tools: Tools,
    request: BuildRequest,
    export_map: dict[Path, Path],
    *,
    log: LogFn | None,
    cache: ArtifactCache | None,
    force: bool,
    skipped: list[Path],
    image_session: images.ImageOptimizationSession | None,
) -> bool:
    """Build a requested single chapter and return whether it was found."""
    if request.single_chapter is None:
        return False
    chapter = request.manifest.find_chapter(request.single_chapter)
    if chapter is None:
        return False
    if log is not None:
        log(f"Building single: {chapter.title}")
    produced.append(
        build_chapter_pdf(
            tools,
            request.recipe,
            chapter,
            export_map,
            profile=request.profile,
            manifest=request.manifest,
            cache=cache,
            force=force,
            skipped=skipped,
            log=log,
            include_art=request.include_art,
            draft_mode=request.draft_mode,
            pagination_mode=request.pagination_mode,
            page_damage_mode=_effective_page_damage_mode(request),
            clean_pdf=request.clean_pdf,
            timings=request.timings,
            image_session=image_session,
        )
    )
    return True


def clean_stale_pdf_outputs(
    recipe: BookConfig,
    manifest: Manifest,
    *,
    log: LogFn | None = None,
) -> list[Path]:
    """Remove old generated PDFs that no longer match the recipe manifest.

    Renames such as `For DMs` -> `For GMs` leave ignored files behind in
    ``output/``. Only clean during full PDF builds, and keep expected outputs
    for every profile so print/digital books can coexist.
    """
    root = paths.output_root(recipe)
    if not root.exists():
        return []

    expected = _expected_pdf_outputs_all_profiles(recipe, manifest)
    removed: list[Path] = []
    for pdf in sorted(root.rglob("*.pdf"), key=lambda path: path.as_posix()):
        if pdf.resolve() in expected:
            continue
        try:
            pdf.unlink()
        except OSError:
            continue
        removed.append(pdf)
        if log is not None:
            log(f"Removed stale output: {_display_path(pdf)}")
    return removed


def _expected_pdf_outputs_all_profiles(
    recipe: BookConfig,
    manifest: Manifest,
) -> set[Path]:
    expected: set[Path] = set()
    for profile in OutputProfile:
        for chapter in manifest.chapters:
            if chapter.source_files:
                expected.add(
                    paths.chapter_pdf_path(recipe, chapter, profile=profile).resolve()
                )
        for chapter in manifest.all_chapters():
            if chapter.individual_pdf:
                expected.add(
                    paths.chapter_pdf_path(recipe, chapter, profile=profile).resolve()
                )
        expected.add(paths.combined_book_path(recipe, profile=profile).resolve())
    return expected


def build_outputs(
    tools: Tools,
    request: BuildRequest,
    *,
    log: LogFn | None = None,
) -> BuildResult:
    """Run the export step and render the artifacts requested by ``request``."""
    timer = _BuildTimer(enabled=request.timings, log=log)
    image_session = images.ImageOptimizationSession()
    if log is not None:
        log("Exporting vaults (obsidian-export)...")
    export_map = ensure_exports_fresh(
        tools,
        request.manifest,
        log=log,
        force=request.force,
    )
    timer.mark("obsidian export")

    produced: list[Path] = []
    skipped: list[Path] = []
    if request.target is BuildTarget.WEB:
        produced.append(
            build_web_book(
                tools,
                request.recipe,
                request.manifest,
                export_map,
                log=log,
                include_art=request.include_art,
                image_session=image_session,
            )
        )
        timer.mark("web render")
        return BuildResult(produced=produced, skipped=skipped, export_map=export_map)

    render_cache = ArtifactCache.load(request.recipe.cache_dir / "render-state.json")
    timer.mark("render cache load")
    effective_page_damage_mode = _effective_page_damage_mode(request)
    pdf_job_options = _PdfJobOptions(
        profile=request.profile,
        include_art=request.include_art,
        draft_mode=request.draft_mode,
        pagination_mode=request.pagination_mode,
        page_damage_mode=effective_page_damage_mode,
        clean_pdf=request.clean_pdf,
        image_session=image_session,
        filler_debug_overlay=request.filler_debug_overlay,
    )

    if request.scope is BuildScope.ALL:
        clean_stale_pdf_outputs(request.recipe, request.manifest, log=log)
        timer.mark("stale output cleanup")

    if request.single_chapter:
        found = _append_single_chapter(
            produced,
            tools,
            request,
            export_map,
            log=log,
            cache=render_cache,
            force=request.force,
            skipped=skipped,
            image_session=image_session,
        )
        if not found:
            render_cache.save()
            return _build_result(produced, skipped, export_map)
        timer.mark("single render")
        render_cache.save()
        timer.mark("render cache save")
        return _build_result(produced, skipped, export_map)

    jobs: list[PdfRenderJob] = []
    if request.scope in {BuildScope.ALL, BuildScope.SECTIONS}:
        for chapter in request.manifest.chapters:
            if not chapter.source_files:
                continue
            if log is not None:
                log(f"Building section: {chapter.title}")
            jobs.append(
                _prepare_chapter_pdf_job(
                    tools,
                    request.recipe,
                    chapter,
                    export_map,
                    manifest=request.manifest,
                    options=pdf_job_options,
                )
            )

    if request.scope in {BuildScope.ALL, BuildScope.INDIVIDUALS}:
        already = {path.resolve() for path in produced + skipped}
        already |= {job.out.resolve() for job in jobs}
        for chapter in request.manifest.all_chapters():
            if not chapter.individual_pdf:
                continue
            target = paths.chapter_pdf_path(
                request.recipe,
                chapter,
                profile=request.profile,
            ).resolve()
            if target in already:
                continue
            if log is not None:
                log(f"Building individual: {chapter.title}")
            jobs.append(
                _prepare_chapter_pdf_job(
                    tools,
                    request.recipe,
                    chapter,
                    export_map,
                    manifest=request.manifest,
                    options=pdf_job_options,
                )
            )

    if request.scope in {BuildScope.ALL, BuildScope.BOOK}:
        if log is not None:
            log("Building combined book...")
        jobs.append(
            _prepare_combined_book_job(
                tools,
                request.recipe,
                request.manifest,
                export_map,
                options=pdf_job_options,
            )
        )

    if jobs:
        _configure_job_timings(jobs, enabled=request.timings, log=log)
        job_produced, job_skipped = _run_prepared_jobs(
            jobs,
            cache=render_cache,
            force=request.force,
            max_workers=request.jobs,
            log=log,
            hooks=_render_job_hooks(),
        )
        produced.extend(job_produced)
        skipped.extend(job_skipped)
        timer.mark(f"parallel render jobs ({len(jobs)})")

    if request.scope in {BuildScope.ALL, BuildScope.BOOK}:
        timer.mark("book render")

    render_cache.save()
    timer.mark("render cache save")
    return _build_result(produced, skipped, export_map)


def _build_result(
    produced: list[Path],
    skipped: list[Path],
    export_map: dict[Path, Path],
) -> BuildResult:
    """Return a result with cached artifacts removed from produced outputs."""
    skipped_resolved = {path.resolve() for path in skipped}
    written = [path for path in produced if path.resolve() not in skipped_resolved]
    return BuildResult(produced=written, skipped=skipped, export_map=export_map)


def _optimized_optional_image(
    path: Path | None,
    *,
    profile: OutputProfile | str,
    cache_root: Path,
    image_session: images.ImageOptimizationSession | None = None,
) -> Path | None:
    """Return an optimized image path when ``path`` is present."""
    if path is None:
        return None
    return images.optimize_image(
        path,
        profile=profile,
        cache_root=cache_root,
        session=image_session,
    )


def _optimized_box_image(
    path: Path | None,
    *,
    profile: OutputProfile | str,
    max_width_in: float,
    max_height_in: float | None = None,
    cache_root: Path,
    image_session: images.ImageOptimizationSession | None = None,
) -> Path | None:
    """Return an optimized image capped to a known rendered box."""
    if path is None:
        return None
    return images.optimize_image_for_box(
        path,
        profile=profile,
        max_width_in=max_width_in,
        max_height_in=max_height_in,
        cache_root=cache_root,
        session=image_session,
    )


def _render_filler_catalog(
    catalog: FillerCatalog | None,
    *,
    profile: OutputProfile | str,
    cache_root: Path,
    image_session: images.ImageOptimizationSession | None = None,
) -> FillerCatalog | None:
    """Return a filler catalog whose asset paths match the render profile."""
    if catalog is None:
        return None
    return FillerCatalog(
        enabled=catalog.enabled,
        slots=catalog.slots,
        assets=[
            FillerAsset(
                id=asset.id,
                art_path=_optimized_filler_image(
                    asset,
                    profile=profile,
                    cache_root=cache_root,
                    image_session=image_session,
                ),
                shape=asset.shape,
                height_in=asset.height_in,
            )
            for asset in catalog.assets
        ],
    )


def _render_page_damage_catalog(
    catalog: PageDamageCatalog | None,
    *,
    profile: OutputProfile | str,
    cache_root: Path,
    proof: bool = False,
    visual_draft: bool = False,
    image_session: images.ImageOptimizationSession | None = None,
) -> PageDamageCatalog | None:
    """Return page-damage assets optimized for the render profile."""
    if catalog is None:
        return None
    profile_name = profile.value if isinstance(profile, OutputProfile) else profile
    density = catalog.density
    max_assets_per_page = catalog.max_assets_per_page
    opacity = catalog.opacity
    glaze_opacity = catalog.glaze_opacity
    if proof or visual_draft or profile_name == OutputProfile.DRAFT.value:
        density = 1.0
        max_assets_per_page = max(max_assets_per_page, 4)
        opacity = 1.0
        glaze_opacity = 1.0
    return PageDamageCatalog(
        enabled=catalog.enabled,
        seed=catalog.seed,
        density=density,
        max_assets_per_page=max_assets_per_page,
        opacity=opacity,
        glaze_opacity=glaze_opacity,
        glaze_texture=catalog.glaze_texture,
        skip=list(catalog.skip),
        assets=[
            PageDamageAsset(
                id=asset.id,
                art_path=_optimized_page_damage_image(
                    asset,
                    profile=profile,
                    cache_root=cache_root,
                    image_session=image_session,
                ),
                family=asset.family,
                size=asset.size,
            )
            for asset in catalog.assets
        ],
    )


def _rewrite_render_images(
    markdown: str,
    recipe: BookConfig,
    manifest: Manifest | None,
    *,
    profile: OutputProfile | str,
    draft_mode: DraftMode = DraftMode.FAST,
    image_session: images.ImageOptimizationSession | None = None,
) -> str:
    """Rewrite inline images for cached optimized assets when appropriate."""
    search_roots = _render_image_search_roots(recipe, manifest)
    if isinstance(profile, OutputProfile) and _is_fast_draft(profile, draft_mode):
        return images.replace_markdown_image_refs_with_placeholders(
            markdown,
            search_roots=search_roots,
        )
    image_profile = (
        _image_profile_for(profile, draft_mode)
        if isinstance(profile, OutputProfile)
        else profile
    )
    return images.rewrite_markdown_image_refs(
        markdown,
        search_roots=search_roots,
        profile=image_profile,
        cache_root=_image_cache_root(recipe),
        session=image_session,
    )


# Largest CSS placement width for each filler shape during image optimization.
_FILLER_MAX_WIDTH_IN = {
    "tailpiece": 2.1,
    "spot": 3.0,
    "small-wide": 4.6,
    "bottom-band": 8.5,
}


def _optimized_filler_image(
    asset: FillerAsset,
    *,
    profile: OutputProfile | str,
    cache_root: Path,
    image_session: images.ImageOptimizationSession | None = None,
) -> Path:
    """Return a filler asset optimized to its largest CSS placement."""
    max_width_in = _FILLER_MAX_WIDTH_IN.get(asset.shape, 8.5)
    return images.optimize_image_for_box(
        asset.art_path,
        profile=profile,
        max_width_in=max_width_in,
        max_height_in=asset.height_in,
        cache_root=cache_root,
        session=image_session,
    )


def _optimized_page_damage_image(
    asset: PageDamageAsset,
    *,
    profile: OutputProfile | str,
    cache_root: Path,
    image_session: images.ImageOptimizationSession | None = None,
) -> Path:
    """Return a page-wear asset optimized to its placement size family."""
    _min_width, max_width_in = page_damage_module.SIZE_WIDTHS_IN.get(
        asset.size,
        (0.35, 1.0),
    )
    if asset.family == "printer-misfeed" and asset.size in {"medium", "large"}:
        max_width_in = page_damage_module.PAGE_WIDTH_IN
    if asset.family == "edge-tear":
        max_width_in = min(max_width_in, 0.9)
    if asset.family == "grease-fingerprint":
        max_width_in = min(max_width_in, 0.68)
    return images.optimize_image_for_box(
        asset.art_path,
        profile=profile,
        max_width_in=max_width_in,
        max_height_in=max_width_in,
        cache_root=cache_root,
        session=image_session,
    )


def _render_image_search_roots(
    recipe: BookConfig,
    manifest: Manifest | None,
) -> list[Path]:
    """Return roots searched while rewriting render-time image references."""
    theme = themes.load_theme(recipe)
    roots = [
        recipe.cache_dir / "exports",
        recipe.art_dir,
        ASSETS_DIR,
        *theme.resource_paths,
    ]
    if manifest is not None:
        roots.extend(vault.root for vault in manifest.vault_index.vaults)
        roots.extend(
            source.parent
            for chapter in manifest.all_chapters()
            for source in chapter.source_files
        )
    return list(dict.fromkeys(root.resolve() for root in roots if root.exists()))


def _render_job_hooks() -> _RenderJobHooks:
    """Return cache/executor callbacks for prepared PDF jobs."""
    return _RenderJobHooks(
        render=_render_job,
        fingerprint=_render_job_fingerprint,
        display_path=_display_path,
    )


def _render_job(job: PdfRenderJob) -> None:
    """Render a prepared job to disk."""
    job.ctx.page_background_underlay = (
        job.page_damage_catalog is not None
        and job.page_damage_catalog.enabled
        and job.ctx.page_damage_mode == PageDamageMode.FULL.value
    )
    pipeline.render_markdown_to_pdf(
        job.markdown,
        job.out,
        job.ctx,
        filler_catalog=job.filler_catalog,
        page_damage_catalog=job.page_damage_catalog,
        recipe_title=job.recipe_title,
        filler_report_path=_filler_report_path(job.out, job.ctx, job.filler_catalog),
        missing_art_report_path=_missing_art_report_path(
            job.out,
            job.ctx,
            job.filler_catalog,
        ),
    )


def _render_job_fingerprint(job: PdfRenderJob) -> str:
    """Return the render cache fingerprint for a prepared job."""
    job.ctx.page_background_underlay = (
        job.page_damage_catalog is not None
        and job.page_damage_catalog.enabled
        and job.ctx.page_damage_mode == PageDamageMode.FULL.value
    )
    return _render_fingerprint(job.markdown, job.ctx, input_paths=job.input_paths)


def _pagination_report_path(out: Path, mode: PaginationMode) -> Path | None:
    """Return the pagination report path for enabled modes."""
    if mode is PaginationMode.OFF:
        return None
    return out.with_suffix(".pagination-report.md")


def _filler_report_path(
    out: Path,
    ctx: pipeline.RenderContext,
    catalog: FillerCatalog | None,
) -> Path | None:
    """Return the optional audit path for draft filler decisions."""
    if ctx.output_profile != OutputProfile.DRAFT.value:
        return None
    if catalog is None or not catalog.enabled:
        return None
    return out.with_suffix(".filler-report.md")


def _missing_art_report_path(
    out: Path,
    ctx: pipeline.RenderContext,
    catalog: FillerCatalog | None,
) -> Path | None:
    """Return the optional draft handoff path for unfilled art slots."""
    if ctx.output_profile != OutputProfile.DRAFT.value:
        return None
    if catalog is None or not catalog.enabled:
        return None
    return out.with_suffix(".missing-art.md")


def _filler_debug_overlay_path(out: Path) -> Path:
    """Return the sibling debug PDF path for filler overlay diagnostics."""
    return out.with_name(f"{out.stem}.filler-debug{out.suffix}")


def _render_fingerprint(
    markdown: str,
    ctx: pipeline.RenderContext,
    *,
    input_paths: list[Path],
) -> str:
    """Return a cache key for the exact render inputs."""
    markdown_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    paths_for_hash = [
        ctx.template,
        *ctx.css_files,
        *ctx.lua_filters,
        *ctx.fingerprint_paths,
        *input_paths,
        *sorted(FONTS_DIR.glob("*"), key=lambda path: path.name),
        *_renderer_source_paths(),
    ]
    extra: dict[str, JsonValue] = {
        "markdown_sha256": markdown_hash,
        "pandoc": ctx.pandoc,
        "weasyprint": ctx.weasyprint,
        "output_profile": ctx.output_profile,
        "section_kind": ctx.section_kind,
        "chapter_title": ctx.chapter_title,
        "page_background_underlay": ctx.page_background_underlay,
        "inline_css": list(ctx.inline_css),
        "book_author": ctx.book_author,
        "book_description": ctx.book_description,
        "book_keywords": ctx.book_keywords,
        "book_date": ctx.book_date,
        "book_publisher": ctx.book_publisher,
        "book_version": ctx.book_version,
        "book_license": ctx.book_license,
        "image_optimization": cast(
            JsonValue,
            images.image_optimization_fingerprint(ctx.image_profile),
        ),
        "pdf_render_settings": cast(
            JsonValue,
            ctx.pdf_settings.fingerprint_payload(),
        ),
        "clean_pdf": ctx.clean_pdf,
        "draft_mode": ctx.draft_mode,
        "draft_placeholders": ctx.draft_placeholders,
        "pagination_mode": ctx.pagination_mode,
        "page_damage_mode": ctx.page_damage_mode,
        "filler_debug_overlay": ctx.filler_debug_overlay_path is not None,
    }
    return fingerprint_files(paths_for_hash, extra=extra)


def _renderer_source_paths() -> list[Path]:
    """Return Python renderer sources that can affect PDF output."""
    package_root = Path(__file__).resolve().parents[1]
    roots = [
        package_root / "render",
        package_root / "media",
        package_root / "assembly",
        package_root / "project",
    ]
    return sorted(
        {
            path
            for root in roots
            for path in root.glob("*.py")
            if path.name != "__init__.py"
        },
        key=lambda path: path.relative_to(package_root).as_posix(),
    )


def _chapter_input_paths(
    chapter: Chapter,
    *,
    recipe: BookConfig,
    manifest: Manifest | None,
) -> list[Path]:
    """Return files that affect one chapter PDF besides assembled markdown."""
    paths_for_hash = list(chapter.source_files)
    for candidate in (
        chapter.art_path,
        chapter.spot_art_path,
        chapter.tailpiece_path,
        chapter.headpiece_path,
        chapter.break_ornament_path,
    ):
        if candidate is not None:
            paths_for_hash.append(candidate)
    paths_for_hash.extend(_shared_image_paths(recipe, manifest))
    return paths_for_hash


def _book_input_paths(recipe: BookConfig, manifest: Manifest) -> list[Path]:
    """Return files that affect the combined book PDF besides markdown text."""
    paths_for_hash: list[Path] = []
    for chapter in manifest.all_chapters():
        paths_for_hash.extend(
            _chapter_input_paths(chapter, recipe=recipe, manifest=None)
        )
    paths_for_hash.extend(_shared_image_paths(recipe, manifest))
    return paths_for_hash


def _shared_image_paths(recipe: BookConfig, manifest: Manifest | None) -> list[Path]:
    """Return recipe-level image files that can affect output rendering."""
    paths_for_hash: list[Path] = []
    paths_for_hash.append(recipe.recipe_path)
    if recipe.cover.enabled:
        cover_art = _recipe_cover_art_path(recipe)
        if cover_art is not None:
            paths_for_hash.append(cover_art.resolve())
    for name in ("folio_frame", "corner_bracket"):
        ornament_path = _recipe_ornament_path(recipe, name)
        if ornament_path is not None:
            paths_for_hash.append(ornament_path.resolve())
    if manifest is not None:
        for chapter in manifest.all_chapters():
            for candidate in (
                chapter.art_path,
                chapter.spot_art_path,
                chapter.tailpiece_path,
                chapter.headpiece_path,
                chapter.break_ornament_path,
            ):
                if candidate is not None:
                    paths_for_hash.append(candidate)
        for splash in manifest.splashes:
            if splash.art_path is not None:
                paths_for_hash.append(splash.art_path)
        for filler_asset in manifest.fillers.assets:
            paths_for_hash.append(filler_asset.art_path)
        for damage_asset in manifest.page_damage.assets:
            paths_for_hash.append(damage_asset.art_path)
    if recipe.page_damage.enabled:
        paths_for_hash.extend(
            texture_path
            for texture_path in TEXTURES_DIR.glob("*.png")
            if texture_path.is_file()
        )
    return paths_for_hash


def _display_path(path: Path) -> str:
    """Return a project-relative path when possible for log output."""
    cwd = Path.cwd().resolve()
    try:
        return str(path.resolve().relative_to(cwd))
    except ValueError:
        return str(path)
