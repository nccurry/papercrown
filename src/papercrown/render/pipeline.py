"""Rendering pipeline: markdown -> HTML / markdown -> PDF.

Two seams sharing a single `RenderContext`:

  * `render_markdown_to_html(markdown, ctx) -> str`
        Pandoc + Lua filters + custom HTML template -> standalone HTML string.
        Used by snapshot tests so they don't need WeasyPrint installed.

  * `render_markdown_to_pdf(markdown, out_path, ctx) -> Path`
        Same Pandoc HTML stage, then the Python WeasyPrint API. This is the
        production path because it can inspect first-pass layout before
        optional filler-art injection.
"""

from __future__ import annotations

import hashlib
import html as html_lib
import importlib
import os
import re
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from urllib.parse import unquote, urlsplit

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter

from papercrown.media import fillers, page_damage
from papercrown.project.manifest import FillerCatalog, PageDamageCatalog
from papercrown.project.resources import TEXTURES_DIR
from papercrown.render import pagination
from papercrown.render import pandoc as _pandoc
from papercrown.render import pdf as _pdf_tools
from papercrown.render.snapshots import normalize_for_snapshot as normalize_for_snapshot

# Detects Windows absolute paths before URL normalization.
_WINDOWS_ABSOLUTE_URL_RE = re.compile(r"^[A-Za-z]:[\\/]")
# PDF point to inch conversion used for PyMuPDF placement math.
PT_PER_IN = 72.0
# Bottom inset for bottom-band bleed art stamped onto PDF pages.
BOTTOM_BLEED_BOTTOM_INSET_IN = 0.12
_build_pandoc_base_args = _pandoc.build_pandoc_base_args
_run_subprocess = _pandoc.run_subprocess
_save_fitz_pdf = _pdf_tools.save_fitz_pdf
_write_pdf_metadata = _pdf_tools.write_pdf_metadata
if os.name == "nt":
    # GLib's default Windows VFS enumerates UWP file-association handlers and
    # can emit unrelated GLib-GIO warnings. We only fetch local build assets.
    os.environ.setdefault("GIO_USE_VFS", "local")


@cache
def _weasyprint_classes() -> tuple[Any, Any]:
    """Import WeasyPrint lazily so non-PDF paths do not initialize GLib/GIO."""
    from weasyprint import CSS, HTML  # type: ignore[import-untyped]

    return CSS, HTML


@cache
def _weasyprint_font_configuration_class() -> Any:
    """Import WeasyPrint's font registry lazily for @font-face support."""
    from weasyprint.text.fonts import FontConfiguration  # type: ignore[import-untyped]

    return FontConfiguration


def _new_weasyprint_font_config() -> Any:
    """Return a fresh WeasyPrint font configuration for one render pass."""
    return _weasyprint_font_configuration_class()()


@cache
def _weasyprint_default_url_fetcher() -> Any:
    """Return WeasyPrint's URLFetcher lazily for non-local resources."""
    from weasyprint.urls import URLFetcher  # type: ignore[import-untyped]

    return URLFetcher()


@cache
def _weasyprint_url_fetcher_response_class() -> Any:
    """Import WeasyPrint's URL fetch response class lazily."""
    from weasyprint.urls import URLFetcherResponse

    return URLFetcherResponse


def _weasyprint_url_fetcher(url: str, *args: Any, **kwargs: Any) -> Any:
    """Fetch local files as bytes so WeasyPrint doesn't invoke Windows GIO scans."""
    del args, kwargs
    normalized = _normalize_weasyprint_url(url)
    local_path = _local_file_from_url(normalized)
    if local_path is not None and local_path.is_file():
        return _local_file_response(local_path)
    return _weasyprint_default_url_fetcher().fetch(normalized)


# Stable fetcher object passed into WeasyPrint render calls.
_WEASYPRINT_URL_FETCHER = _weasyprint_url_fetcher
# Matches quoted Windows paths before HTML/CSS URL rewriting.
_WINDOWS_QUOTED_URL_RE = re.compile(
    r"(?P<quote>[\"'])(?P<value>[A-Za-z]:[\\/][^\"']*)(?P=quote)"
)
# Matches CSS url(...) values that contain Windows absolute paths.
_WINDOWS_CSS_URL_RE = re.compile(
    r"url\(\s*(?P<quote>[\"']?)(?P<value>[A-Za-z]:[\\/][^)\"']+)(?P=quote)\s*\)"
)

# CSS that clears page backgrounds when a raster underlay supplies paper color.
_PAGE_BACKGROUND_UNDERLAY_CSS = """
@page {
  background-color: transparent;
  background-image: none;
}
@page divider-page {
  background-color: transparent;
  background-image: none;
}
@page digital {
  background-color: transparent;
  background-image: none;
}
@page digital-divider-page {
  background-color: transparent;
  background-image: none;
}
@page cover-page {
  background-color: transparent;
  background-image: none;
}
"""

# CSS overlay used by fast draft builds to suppress expensive page textures.
_FAST_DRAFT_CSS = """
@page {
  background-color: #fbfaf8;
  background-image: none;
  @bottom-center {
    background-image: none;
  }
}
@page divider-page {
  background-color: #fbfaf8;
  background-image: none;
  @bottom-center {
    background-image: none;
  }
}
@page digital {
  background-color: #fbfaf8;
  background-image: none;
  @bottom-center {
    background-image: none;
  }
}
@page digital-divider-page {
  background-color: #fbfaf8;
  background-image: none;
  @bottom-center {
    background-image: none;
  }
}
@page cover-page {
  background-color: #fbfaf8;
  background-image: none;
  @bottom-center {
    background-image: none;
  }
}
"""

# ---------------------------------------------------------------------------
# RenderContext
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PdfRenderSettings:
    """WeasyPrint image/PDF optimization settings for one render profile."""

    optimize_images: bool = True
    dpi: int | None = None
    jpeg_quality: int | None = None
    cache: dict[str, Any] | None = field(default_factory=dict)

    def weasy_options(self) -> dict[str, Any]:
        """Return keyword options passed to WeasyPrint render/write calls."""
        options: dict[str, Any] = {"optimize_images": self.optimize_images}
        if self.dpi is not None:
            options["dpi"] = self.dpi
        if self.jpeg_quality is not None:
            options["jpeg_quality"] = self.jpeg_quality
        if self.cache is not None:
            options["cache"] = self.cache
        return options

    def fingerprint_payload(self) -> dict[str, str | int | bool | None]:
        """Return stable settings metadata for render-cache fingerprints."""
        return {
            "optimize_images": self.optimize_images,
            "dpi": self.dpi,
            "jpeg_quality": self.jpeg_quality,
            "cache": "memory" if self.cache is not None else None,
        }


@dataclass
class RenderContext:
    """Everything the renderer needs that isn't markdown content."""

    pandoc: str  # path to pandoc binary
    weasyprint: str  # path to weasyprint binary
    template: Path  # Pandoc HTML template
    css_files: list[Path]  # ordered stylesheets
    lua_filters: list[Path]  # ordered list
    resource_paths: list[Path]  # for Pandoc --resource-path
    inline_css: list[str] = field(default_factory=list)
    fingerprint_paths: list[Path] = field(default_factory=list)

    chapter_title: str = "Untitled"
    chapter_eyebrow: str = "Chapter"
    chapter_art: Path | None = None
    section_kind: str = "default"

    # Cover (only used when this is the start of a combined book)
    cover_enabled: bool = False
    cover_title: str | None = None
    cover_subtitle: str | None = None
    cover_eyebrow: str | None = None
    cover_footer: str | None = None
    cover_art: Path | None = None

    include_toc: bool = False
    output_profile: str = "print"
    ornament_folio_frame: Path | None = None
    ornament_corner_bracket: Path | None = None
    page_background_underlay: bool = False

    # Whether to emit the template-level chapter-opener block. Set to False
    # for combined-book mode (which uses inline section-divider pages
    # instead) so we don't double up on the first chapter.
    chapter_opener: bool = True

    # Title prefix shown in browser tab / PDF metadata
    title_prefix: str = ""
    book_author: str | None = None
    book_description: str | None = None
    book_keywords: str | None = None
    book_date: str | None = None
    book_publisher: str | None = None
    book_version: str | None = None
    book_license: str | None = None

    # Comma-separated slugs that internal-links.lua may resolve to anchors.
    # When rendering a single chapter PDF, this is just that chapter's slug;
    # for the combined book, every chapter slug.
    valid_anchors: str = ""

    pdf_settings: PdfRenderSettings = field(default_factory=PdfRenderSettings)
    image_profile: str = "print"
    clean_pdf: bool = True
    draft_placeholders: bool = False
    draft_mode: str = ""
    pagination_mode: str = "report"
    page_damage_mode: str = "auto"
    pagination_report_path: Path | None = None
    filler_debug_overlay_path: Path | None = None
    timings: bool = False
    timing_label: str = ""
    timing_log: Callable[[str], None] | None = None
    warning_log: Callable[[str], None] | None = None


# ---------------------------------------------------------------------------
# Stage 1: markdown -> HTML
# ---------------------------------------------------------------------------


def render_markdown_to_html(markdown: str, ctx: RenderContext) -> str:
    """Run Pandoc on `markdown`, return the resulting standalone HTML.

    No WeasyPrint, no PDF. Suitable for snapshot testing.
    """
    with tempfile.TemporaryDirectory(prefix="papercrown-html-") as td:
        td_path = Path(td)
        md_file = td_path / "chapter.md"
        md_file.write_text(markdown, encoding="utf-8")
        out_html = td_path / "chapter.html"

        cmd: list[str] = [
            ctx.pandoc,
            str(md_file),
            "--to=html5",
            *_build_pandoc_base_args(ctx, css=True),
            "-o",
            str(out_html),
        ]
        result = _run_subprocess(cmd)
        if result.returncode != 0:
            raise RuntimeError(
                f"pandoc (html) failed ({result.returncode}):\n"
                f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}"
            )
        html = out_html.read_text(encoding="utf-8")
        return _inject_inline_css(html, ctx.inline_css)


# ---------------------------------------------------------------------------
# Stage 2: markdown -> PDF (via WeasyPrint)
# ---------------------------------------------------------------------------


def render_markdown_to_pdf(
    markdown: str,
    out_pdf: Path,
    ctx: RenderContext,
    *,
    filler_catalog: FillerCatalog | None = None,
    page_damage_catalog: PageDamageCatalog | None = None,
    recipe_title: str | None = None,
    filler_report_path: Path | None = None,
    missing_art_report_path: Path | None = None,
) -> Path:
    """Run Pandoc then WeasyPrint, producing a PDF on disk.

    PDF rendering is owned directly by the Python WeasyPrint API so we can do
    a layout-inspection pass before optional filler-art injection.
    """
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    stage_start = time.perf_counter()
    total_start = stage_start
    ctx.page_background_underlay = (
        page_damage_catalog is not None
        and page_damage_catalog.enabled
        and ctx.page_damage_mode == "full"
    )
    html = render_markdown_to_html(markdown, ctx)
    stage_start = _log_timing(ctx, "pandoc html", stage_start)
    render_html_to_pdf(
        html,
        out_pdf,
        ctx,
        filler_catalog=filler_catalog,
        page_damage_catalog=page_damage_catalog,
        recipe_title=recipe_title or ctx.title_prefix or ctx.chapter_title,
        filler_report_path=filler_report_path,
        missing_art_report_path=missing_art_report_path,
    )
    _log_timing(ctx, "html to pdf", stage_start)
    _log_timing(ctx, "total pdf render", total_start)
    return out_pdf


def render_html_to_pdf(
    html: str,
    out_pdf: Path,
    ctx: RenderContext,
    *,
    filler_catalog: FillerCatalog | None = None,
    page_damage_catalog: PageDamageCatalog | None = None,
    recipe_title: str | None = None,
    filler_report_path: Path | None = None,
    missing_art_report_path: Path | None = None,
) -> Path:
    """Render a standalone HTML string to PDF, optionally injecting fillers."""
    stage_start = time.perf_counter()
    html, session = _prepare_weasy_render(html, ctx)
    stage_start = _log_timing(ctx, "weasy setup", stage_start)
    first_doc = _render_weasy_document(html, session)
    stage_start = _log_timing(
        ctx,
        f"weasy layout ({len(first_doc.pages)} pages)",
        stage_start,
    )

    pagination_result = _apply_pagination_fix(html, first_doc, session, ctx)
    html = pagination_result.html
    first_doc = pagination_result.document
    if ctx.pagination_mode == "fix":
        stage_start = _log_timing(ctx, "pagination fix pass", stage_start)

    filler_result = _plan_and_render_fillers(
        html,
        first_doc,
        session,
        ctx,
        catalog=filler_catalog,
        recipe_title=recipe_title,
        filler_report_path=filler_report_path,
        missing_art_report_path=missing_art_report_path,
    )
    final_doc = filler_result.document
    if filler_result.ran:
        stage_start = _log_timing(ctx, "filler planning/injection", stage_start)

    overlay_placements = _bottom_bleed_placements(filler_result.placements)
    damage_catalog = page_damage_catalog
    damage_placements: list[page_damage.PageDamagePlacement] = []
    if damage_catalog is not None and damage_catalog.enabled:
        damage_placements = _plan_page_damage(
            final_doc,
            damage_catalog,
            recipe_title=recipe_title or ctx.chapter_title,
        )
        stage_start = _log_timing(
            ctx,
            f"page damage planning ({len(damage_placements)} placements)",
            stage_start,
        )

    write_result = _write_final_pdf(
        final_doc,
        out_pdf,
        ctx=ctx,
        session=session,
        damage_catalog=damage_catalog,
        damage_placements=damage_placements,
        overlay_placements=overlay_placements,
    )
    stage_start = _log_timing(ctx, write_result.timing_label, stage_start)

    _write_render_reports_metadata_and_debug(
        out_pdf,
        final_doc,
        ctx,
        recipe_title=recipe_title,
        pagination_result=pagination_result,
        pdf_already_cleaned=write_result.pdf_already_cleaned,
        filler_result=filler_result,
        stage_start=stage_start,
    )
    return out_pdf


@dataclass(frozen=True)
class _WeasyRenderSession:
    """Shared WeasyPrint setup for repeated layout passes."""

    base_url: str
    html_class: Any
    font_config: Any
    stylesheets: list[Any]
    weasy_options: dict[str, Any]


@dataclass(frozen=True)
class _PaginationPassResult:
    """Output from the optional pagination fix pass."""

    html: str
    document: Any
    fix_ids: list[str]
    accepted_fix: bool | None
    fix_reason: str | None


@dataclass(frozen=True)
class _FillerPassResult:
    """Output from optional filler planning and injection."""

    document: Any
    placements: list[fillers.FillerPlacement]
    decisions: list[fillers.FillerDecision]
    ran: bool


@dataclass(frozen=True)
class _PdfWriteResult:
    """Outcome metadata for the final PDF write strategy."""

    timing_label: str
    pdf_already_cleaned: bool = False


def _prepare_weasy_render(
    html: str,
    ctx: RenderContext,
) -> tuple[str, _WeasyRenderSession]:
    """Normalize HTML and construct reusable WeasyPrint render inputs."""
    normalized_html = _normalize_local_urls_in_markup(html)
    _, html_class = _weasyprint_classes()
    font_config = _new_weasyprint_font_config()
    return normalized_html, _WeasyRenderSession(
        base_url=ctx.template.parent.resolve().as_uri(),
        html_class=html_class,
        font_config=font_config,
        stylesheets=_render_stylesheets(ctx, font_config=font_config),
        weasy_options=ctx.pdf_settings.weasy_options(),
    )


def _render_weasy_document(html: str, session: _WeasyRenderSession) -> Any:
    """Render one HTML string through the configured WeasyPrint session."""
    return session.html_class(
        string=html,
        base_url=session.base_url,
        url_fetcher=_WEASYPRINT_URL_FETCHER,
    ).render(
        stylesheets=session.stylesheets,
        font_config=session.font_config,
        **session.weasy_options,
    )


def _apply_pagination_fix(
    html: str,
    document: Any,
    session: _WeasyRenderSession,
    ctx: RenderContext,
) -> _PaginationPassResult:
    """Try the optional stranded-heading pagination fix pass."""
    fix_ids: list[str] = []
    accepted_fix: bool | None = None
    fix_reason: str | None = None
    if ctx.pagination_mode != "fix":
        return _PaginationPassResult(
            html=html,
            document=document,
            fix_ids=fix_ids,
            accepted_fix=accepted_fix,
            fix_reason=fix_reason,
        )

    initial_report = pagination.analyze_document(document)
    fix_result = pagination.inject_page_break_fixes(html, initial_report)
    if fix_result.changed:
        fixed_html = _normalize_local_urls_in_markup(fix_result.html)
        candidate_doc = _render_weasy_document(fixed_html, session)
        candidate_report = pagination.analyze_document(candidate_doc)
        page_growth = len(candidate_doc.pages) - len(document.pages)
        if (
            candidate_report.total_badness < initial_report.total_badness
            and page_growth <= 1
        ):
            return _PaginationPassResult(
                html=fixed_html,
                document=candidate_doc,
                fix_ids=fix_result.applied_ids,
                accepted_fix=True,
                fix_reason=(
                    f"badness {initial_report.total_badness} -> "
                    f"{candidate_report.total_badness}"
                ),
            )
        accepted_fix = False
        fix_reason = (
            f"candidate badness {candidate_report.total_badness}; "
            f"page growth {page_growth}"
        )
    elif initial_report.issues:
        accepted_fix = False
        fix_reason = "no eligible stranded heading fixes"
    return _PaginationPassResult(
        html=html,
        document=document,
        fix_ids=fix_ids,
        accepted_fix=accepted_fix,
        fix_reason=fix_reason,
    )


def _plan_and_render_fillers(
    html: str,
    document: Any,
    session: _WeasyRenderSession,
    ctx: RenderContext,
    *,
    catalog: FillerCatalog | None,
    recipe_title: str | None,
    filler_report_path: Path | None,
    missing_art_report_path: Path | None,
) -> _FillerPassResult:
    """Plan filler art and render a candidate filled layout when useful."""
    if catalog is None or not catalog.enabled:
        return _FillerPassResult(
            document=document,
            placements=[],
            decisions=[],
            ran=False,
        )

    placements, decisions = fillers.plan_filler_decisions(
        document,
        catalog,
        recipe_title=recipe_title or ctx.chapter_title,
    )
    for warning in fillers.filler_warnings(placements):
        _log_warning(ctx, warning)
    if filler_report_path is not None:
        fillers.write_filler_report(
            filler_report_path,
            document,
            catalog,
            recipe_title=recipe_title or ctx.chapter_title,
        )
    if missing_art_report_path is not None:
        fillers.write_missing_art_report(
            missing_art_report_path,
            document,
            catalog,
            recipe_title=recipe_title or ctx.chapter_title,
        )

    final_doc = document
    if placements:
        filled_html = fillers.inject_fillers(html, placements)
        filled_html = _normalize_local_urls_in_markup(filled_html)
        candidate_doc = _render_weasy_document(filled_html, session)
        if len(candidate_doc.pages) <= len(document.pages):
            final_doc = candidate_doc
    return _FillerPassResult(
        document=final_doc,
        placements=placements,
        decisions=decisions,
        ran=True,
    )


def _bottom_bleed_placements(
    placements: list[fillers.FillerPlacement],
) -> list[fillers.FillerPlacement]:
    """Return filler placements stamped as bottom-bleed PDF overlays."""
    return [placement for placement in placements if placement.mode == "bottom-bleed"]


def _plan_page_damage(
    document: Any,
    catalog: PageDamageCatalog,
    *,
    recipe_title: str,
) -> list[page_damage.PageDamagePlacement]:
    """Plan page-damage overlays for the selected render strategy."""
    return page_damage.plan_page_damage(
        document,
        catalog,
        recipe_title=recipe_title,
    )


def _write_final_pdf(
    document: Any,
    out_pdf: Path,
    *,
    ctx: RenderContext,
    session: _WeasyRenderSession,
    damage_catalog: PageDamageCatalog | None,
    damage_placements: list[page_damage.PageDamagePlacement],
    overlay_placements: list[fillers.FillerPlacement],
) -> _PdfWriteResult:
    """Choose and run the final PDF write strategy."""
    if damage_catalog is not None and damage_catalog.enabled:
        if ctx.page_damage_mode == "full":
            _write_pdf_with_page_art(
                document,
                out_pdf,
                damage_catalog=damage_catalog,
                damage_placements=damage_placements,
                overlay_placements=overlay_placements,
                base_url=session.base_url,
                ctx=ctx,
            )
            return _PdfWriteResult(timing_label=f"pdf write ({ctx.page_damage_mode})")
        _write_pdf_with_page_damage_fast(
            document,
            out_pdf,
            damage_catalog=damage_catalog,
            damage_placements=damage_placements,
            overlay_placements=overlay_placements,
            base_url=session.base_url,
            ctx=ctx,
        )
        return _PdfWriteResult(
            timing_label=f"pdf write ({ctx.page_damage_mode})",
            pdf_already_cleaned=True,
        )

    if overlay_placements:
        _write_pdf_with_bottom_bleeds(
            document,
            out_pdf,
            overlay_placements,
            session.base_url,
            ctx,
        )
        return _PdfWriteResult(timing_label="pdf write (bottom bleeds)")

    document.write_pdf(out_pdf, **session.weasy_options)
    return _PdfWriteResult(timing_label="pdf write")


def _write_render_reports_metadata_and_debug(
    out_pdf: Path,
    document: Any,
    ctx: RenderContext,
    *,
    recipe_title: str | None,
    pagination_result: _PaginationPassResult,
    pdf_already_cleaned: bool,
    filler_result: _FillerPassResult,
    stage_start: float,
) -> None:
    """Write reports, cleanup, metadata, and debug overlays after PDF output."""
    if ctx.pagination_mode != "off" and ctx.pagination_report_path is not None:
        pagination.write_report(
            ctx.pagination_report_path,
            pagination.analyze_document(document),
            fix_ids=pagination_result.fix_ids,
            accepted_fix=pagination_result.accepted_fix,
            fix_reason=pagination_result.fix_reason,
        )
        stage_start = _log_timing(ctx, "pagination report", stage_start)
    if ctx.clean_pdf and not pdf_already_cleaned:
        _clean_pdf(out_pdf)
        stage_start = _log_timing(ctx, "pdf cleanup", stage_start)
    _write_pdf_metadata(
        out_pdf,
        title=recipe_title or ctx.title_prefix or ctx.chapter_title,
        ctx=ctx,
    )
    _log_timing(ctx, "pdf metadata", stage_start)
    if ctx.filler_debug_overlay_path is not None:
        _write_filler_debug_overlay(
            out_pdf,
            ctx.filler_debug_overlay_path,
            filler_result.decisions,
            filler_result.placements,
        )


def _log_timing(ctx: RenderContext, stage: str, start: float) -> float:
    """Log an opt-in render timing mark and return the new start time."""
    now = time.perf_counter()
    if ctx.timings and ctx.timing_log is not None:
        label = f" {ctx.timing_label}" if ctx.timing_label else ""
        ctx.timing_log(f"  timing{label} {stage}: {now - start:.2f}s")
    return now


def _log_warning(ctx: RenderContext, message: str) -> None:
    """Log a non-fatal render warning when a build logger is attached."""
    if ctx.warning_log is not None:
        ctx.warning_log(message)


def _render_stylesheets(
    ctx: RenderContext,
    *,
    font_config: Any | None = None,
) -> list[Any]:
    """Return WeasyPrint stylesheets with optional late page-background override."""
    CSS, _ = _weasyprint_classes()
    stylesheets: list[Any] = []
    stylesheets.extend(
        CSS(
            filename=str(path),
            url_fetcher=_WEASYPRINT_URL_FETCHER,
            font_config=font_config,
        )
        for path in ctx.css_files
    )
    stylesheets.extend(
        CSS(
            string=css,
            url_fetcher=_WEASYPRINT_URL_FETCHER,
            font_config=font_config,
        )
        for css in ctx.inline_css
        if css.strip()
    )
    if ctx.page_background_underlay:
        stylesheets.append(
            CSS(
                string=_PAGE_BACKGROUND_UNDERLAY_CSS,
                url_fetcher=_WEASYPRINT_URL_FETCHER,
                font_config=font_config,
            )
        )
    if ctx.ornament_folio_frame is not None and ctx.ornament_folio_frame.is_file():
        stylesheets.append(
            CSS(
                string=_folio_frame_css(ctx.ornament_folio_frame),
                url_fetcher=_WEASYPRINT_URL_FETCHER,
                font_config=font_config,
            )
        )
    if ctx.draft_placeholders:
        stylesheets.append(
            CSS(
                string=_FAST_DRAFT_CSS,
                url_fetcher=_WEASYPRINT_URL_FETCHER,
                font_config=font_config,
            )
        )
    return stylesheets


def _inject_inline_css(html: str, css_blocks: list[str]) -> str:
    """Inject render-context inline CSS into standalone HTML output."""
    css = "\n".join(block.strip() for block in css_blocks if block.strip())
    if not css:
        return html
    style = f"<style>\n{css}\n</style>\n"
    if "</head>" not in html:
        return style + html
    return html.replace("</head>", style + "</head>", 1)


def _clean_pdf(path: Path) -> None:
    """Compatibility wrapper for PDF cleanup using this module's fitz importer."""
    fitz: Any = importlib.import_module("fitz")
    tmp_path = path.with_name(f"{path.stem}.cleaning{path.suffix}")
    if tmp_path.exists():
        tmp_path.unlink()
    doc = fitz.open(path)
    try:
        doc.save(
            tmp_path,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
            use_objstms=1,
        )
    finally:
        doc.close()
    _pdf_tools.replace_pdf(tmp_path, path)


def _write_filler_debug_overlay(
    source_pdf: Path,
    debug_pdf: Path,
    decisions: list[fillers.FillerDecision],
    placements: list[fillers.FillerPlacement],
) -> None:
    """Write a separate PDF annotated with filler measurements and choices."""
    debug_pdf.parent.mkdir(parents=True, exist_ok=True)
    fitz: Any = importlib.import_module("fitz")
    doc = fitz.open(source_pdf)
    placed = {(placement.slot_id, placement.page_number) for placement in placements}
    try:
        for decision in decisions:
            measurement = decision.measurement
            page_index = measurement.page_number - 1
            if page_index < 0 or page_index >= len(doc):
                continue
            page = doc[page_index]
            page_rect = page.rect
            top = max(0.0, measurement.slot_y_in * PT_PER_IN)
            bottom = min(page_rect.height, measurement.content_bottom_in * PT_PER_IN)
            if bottom <= top:
                bottom = min(page_rect.height, top + 0.12 * PT_PER_IN)
            rect = fitz.Rect(
                page_rect.x0 + 0.55 * PT_PER_IN,
                top,
                page_rect.x1 - 0.55 * PT_PER_IN,
                bottom,
            )
            is_placed = (measurement.slot_id, measurement.page_number) in placed
            color = (0.0, 0.45, 0.25) if is_placed else (0.75, 0.32, 0.0)
            page.draw_rect(rect, color=color, width=1.0, overlay=True)
            asset_text = decision.asset.id if decision.asset is not None else "none"
            label = (
                f"{measurement.slot_name} {measurement.slot_id} | "
                f"{decision.reason} | {asset_text} | "
                f"{measurement.available_in:.2f}in"
            )
            page.insert_textbox(
                fitz.Rect(rect.x0, max(0.0, rect.y0 - 18.0), rect.x1, rect.y0),
                label,
                fontsize=6.5,
                color=color,
                overlay=True,
            )
        _save_fitz_pdf(doc, debug_pdf)
    finally:
        doc.close()


def _folio_frame_css(path: Path) -> str:
    """Return late-bound margin-box CSS for the page-number frame image."""
    image_url = path.resolve().as_uri().replace('"', '\\"')
    return f"""
@page {{
  @bottom-center {{
    background-image: url("{image_url}");
  }}
}}
@page digital {{
  @bottom-center {{
    background-image: url("{image_url}");
  }}
}}
"""


def _write_pdf_with_page_art(
    document: Any,
    out_pdf: Path,
    *,
    damage_catalog: PageDamageCatalog,
    damage_placements: list[page_damage.PageDamagePlacement],
    overlay_placements: list[fillers.FillerPlacement],
    base_url: str,
    ctx: RenderContext,
) -> None:
    """Write ``document`` with paper/damage underlays and optional overlays."""
    weasy_options = ctx.pdf_settings.weasy_options()
    pdf_bytes = document.write_pdf(**weasy_options)
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    damage_by_page: dict[int, list[page_damage.PageDamagePlacement]] = {}
    for damage_placement in damage_placements:
        damage_by_page.setdefault(damage_placement.page_number, []).append(
            damage_placement
        )
    overlay_by_page: dict[int, list[fillers.FillerPlacement]] = {}
    for overlay_placement in overlay_placements:
        overlay_by_page.setdefault(overlay_placement.page_number, []).append(
            overlay_placement
        )

    paper_grain_path, page_patina_path = _paper_texture_paths(ctx)
    glaze_pdf: bytes | None = None
    glaze_texture_path = _glaze_texture_path(ctx, damage_catalog)
    if damage_catalog.glaze_opacity > 0 and glaze_texture_path.is_file():
        glaze_pdf = page_damage.render_page_glaze_pdf(
            base_url=base_url,
            url_fetcher=_WEASYPRINT_URL_FETCHER,
            texture_path=glaze_texture_path,
            opacity=damage_catalog.glaze_opacity,
            weasy_options=weasy_options,
        )
    blank_underlay_pdfs: dict[bool, bytes] = {}
    for page_index, page in enumerate(writer.pages, start=1):
        page_damage_placements = damage_by_page.get(page_index, [])
        folio_frame_path = (
            ctx.ornament_folio_frame
            if _page_has_page_number(page, page_index)
            else None
        )
        if page_damage_placements:
            underlay_pdf = page_damage.render_page_underlay_pdf(
                page_damage_placements,
                base_url=base_url,
                url_fetcher=_WEASYPRINT_URL_FETCHER,
                paper_grain_path=paper_grain_path,
                page_patina_path=page_patina_path,
                folio_frame_path=folio_frame_path,
                weasy_options=weasy_options,
            )
        else:
            has_folio = folio_frame_path is not None
            if has_folio not in blank_underlay_pdfs:
                blank_underlay_pdfs[has_folio] = page_damage.render_page_underlay_pdf(
                    [],
                    base_url=base_url,
                    url_fetcher=_WEASYPRINT_URL_FETCHER,
                    paper_grain_path=paper_grain_path,
                    page_patina_path=page_patina_path,
                    folio_frame_path=folio_frame_path,
                    weasy_options=weasy_options,
                )
            underlay_pdf = blank_underlay_pdfs[has_folio]
        underlay = PdfReader(BytesIO(underlay_pdf)).pages[0]
        page.merge_page(underlay, over=False)
        for overlay_placement in overlay_by_page.get(page_index, []):
            overlay_pdf = _bottom_bleed_overlay_pdf(
                overlay_placement,
                base_url,
                ctx,
            )
            overlay = PdfReader(BytesIO(overlay_pdf)).pages[0]
            page.merge_page(overlay)
        if glaze_pdf is not None:
            glaze = PdfReader(BytesIO(glaze_pdf)).pages[0]
            page.merge_page(glaze)

    with out_pdf.open("wb") as handle:
        writer.write(handle)


def _write_pdf_with_page_damage_fast(
    document: Any,
    out_pdf: Path,
    *,
    damage_catalog: PageDamageCatalog,
    damage_placements: list[page_damage.PageDamagePlacement],
    overlay_placements: list[fillers.FillerPlacement],
    base_url: str,
    ctx: RenderContext,
) -> None:
    """Write ``document`` and stamp page art with PyMuPDF."""
    del base_url
    fitz: Any = importlib.import_module("fitz")
    stage_start = time.perf_counter()
    pdf_bytes = document.write_pdf(**ctx.pdf_settings.weasy_options())
    base_pdf_path = out_pdf.with_name(f"{out_pdf.stem}.weasy-base{out_pdf.suffix}")
    normalized_pdf_path = out_pdf.with_name(f"{out_pdf.stem}.fitz-base{out_pdf.suffix}")
    if base_pdf_path.exists():
        base_pdf_path.unlink()
    if normalized_pdf_path.exists():
        normalized_pdf_path.unlink()
    base_pdf_path.write_bytes(pdf_bytes)
    stage_start = _log_timing(ctx, "weasy pdf bytes", stage_start)
    base_doc = fitz.open(base_pdf_path)
    try:
        _save_fitz_pdf(base_doc, normalized_pdf_path)
    finally:
        base_doc.close()
    stage_start = _log_timing(ctx, "fitz pdf normalize", stage_start)
    pdf_doc = fitz.open(normalized_pdf_path)
    stage_start = _log_timing(ctx, "fitz pdf open", stage_start)
    try:
        damage_by_page: dict[int, list[page_damage.PageDamagePlacement]] = {}
        for damage_placement in damage_placements:
            damage_by_page.setdefault(damage_placement.page_number, []).append(
                damage_placement
            )
        overlay_by_page: dict[int, list[fillers.FillerPlacement]] = {}
        for overlay_placement in overlay_placements:
            overlay_by_page.setdefault(overlay_placement.page_number, []).append(
                overlay_placement
            )

        glaze_stream: bytes | None = None
        glaze_texture_path = _glaze_texture_path(ctx, damage_catalog)
        if damage_catalog.glaze_opacity > 0 and glaze_texture_path.is_file():
            glaze_stream = page_damage.render_page_glaze_png(
                texture_path=glaze_texture_path,
                opacity=damage_catalog.glaze_opacity,
            )

        for page_number, placements in damage_by_page.items():
            page_index = page_number - 1
            if page_index < 0 or page_index >= len(pdf_doc):
                continue
            page = pdf_doc[page_index]
            for placement in placements:
                _stamp_page_damage_fitz(page, placement, fitz)
        stage_start = _log_timing(ctx, "page damage stamp", stage_start)

        for page_number, page_overlay_placements in overlay_by_page.items():
            page_index = page_number - 1
            if page_index < 0 or page_index >= len(pdf_doc):
                continue
            page = pdf_doc[page_index]
            for overlay_placement in page_overlay_placements:
                _stamp_bottom_bleed_fitz(page, overlay_placement, fitz)
        stage_start = _log_timing(ctx, "bottom bleed stamp", stage_start)

        glaze_xref = 0
        if glaze_stream is not None:
            for page in pdf_doc:
                glaze_xref = page.insert_image(
                    page.rect,
                    stream=glaze_stream,
                    xref=glaze_xref,
                    overlay=True,
                )
        stage_start = _log_timing(ctx, "page glaze stamp", stage_start)
        _save_fitz_pdf(pdf_doc, out_pdf)
        _log_timing(ctx, "fitz pdf save", stage_start)
    finally:
        pdf_doc.close()
        if base_pdf_path.exists():
            base_pdf_path.unlink()
        if normalized_pdf_path.exists():
            normalized_pdf_path.unlink()


def _stamp_page_damage_fitz(
    page: Any,
    placement: page_damage.PageDamagePlacement,
    fitz: Any,
) -> None:
    """Stamp one page-wear image directly onto a PyMuPDF page."""
    rendered = page_damage.render_page_damage_image_png(placement)
    rect = fitz.Rect(
        rendered.x_in * 72.0,
        rendered.y_in * 72.0,
        (rendered.x_in + rendered.width_in) * 72.0,
        (rendered.y_in + rendered.height_in) * 72.0,
    )
    page.insert_image(rect, stream=rendered.png, overlay=True)


def _stamp_bottom_bleed_fitz(
    page: Any,
    placement: fillers.FillerPlacement,
    fitz: Any,
) -> None:
    """Stamp one bottom-bleed filler directly onto a PyMuPDF page."""
    asset = placement.asset
    render_height_in = _placement_render_height_in(placement)
    band_height = max(render_height_in + 0.25, 1.0) * PT_PER_IN
    bottom_inset = BOTTOM_BLEED_BOTTOM_INSET_IN * PT_PER_IN
    max_image_height = (
        max(0.1, render_height_in - BOTTOM_BLEED_BOTTOM_INSET_IN) * PT_PER_IN
    )
    page_rect = page.rect
    mask_rect = fitz.Rect(
        page_rect.x0,
        page_rect.y1 - band_height,
        page_rect.x1,
        page_rect.y1,
    )
    image_width, image_height = _bottom_bleed_display_size_pt(
        asset.art_path,
        max_width_pt=page_rect.width,
        max_height_pt=max_image_height,
    )
    image_x0 = page_rect.x0 + (page_rect.width - image_width) / 2.0
    image_y1 = page_rect.y1 - bottom_inset
    image_rect = fitz.Rect(
        image_x0,
        image_y1 - image_height,
        image_x0 + image_width,
        image_y1,
    )
    page.draw_rect(mask_rect, color=None, fill=(0.984, 0.980, 0.973), overlay=True)
    page.insert_image(
        image_rect,
        filename=str(asset.art_path),
        keep_proportion=True,
        overlay=True,
    )


def _bottom_bleed_display_size_pt(
    path: Path,
    *,
    max_width_pt: float,
    max_height_pt: float,
) -> tuple[float, float]:
    """Return capped image dimensions without upscaling or distorting art."""
    try:
        with Image.open(path) as image:
            width_px, height_px = image.size
    except (OSError, UnidentifiedImageError):
        return max_width_pt, max_height_pt
    if width_px <= 0 or height_px <= 0:
        return max_width_pt, max_height_pt
    natural_width_pt = (width_px / fillers.PX_PER_IN) * PT_PER_IN
    natural_height_pt = (height_px / fillers.PX_PER_IN) * PT_PER_IN
    scale = min(
        1.0,
        max_width_pt / natural_width_pt,
        max_height_pt / natural_height_pt,
    )
    return natural_width_pt * scale, natural_height_pt * scale


def _page_has_page_number(page: Any, page_number: int) -> bool:
    """Return whether ``page`` appears to render its page number as text."""
    try:
        text = page.extract_text() or ""
    except Exception:  # pragma: no cover - pypdf extraction is best-effort.
        return True
    target = str(page_number)
    return any(line.strip() == target for line in text.splitlines())


def _paper_texture_paths(_ctx: RenderContext) -> tuple[Path | None, Path | None]:
    """Return bundled paper texture paths for the PDF underlay pass."""
    # Surface texture now comes from the top glaze so the page can be swapped
    # between cleaner options without inheriting the older scratchy patina art.
    return (None, None)


def _glaze_texture_path(ctx: RenderContext, catalog: PageDamageCatalog) -> Path:
    """Return the bundled texture used by the top surface glaze."""
    return TEXTURES_DIR / catalog.glaze_texture


def _write_pdf_with_bottom_bleeds(
    document: Any,
    out_pdf: Path,
    placements: list[fillers.FillerPlacement],
    base_url: str,
    ctx: RenderContext,
) -> None:
    """Write ``document`` and stamp bottom-bleed art over selected pages."""
    weasy_options = ctx.pdf_settings.weasy_options()
    pdf_bytes = document.write_pdf(**weasy_options)
    reader = PdfReader(BytesIO(pdf_bytes))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    by_page: dict[int, list[fillers.FillerPlacement]] = {}
    for placement in placements:
        by_page.setdefault(placement.page_number, []).append(placement)

    for page_index, page in enumerate(writer.pages, start=1):
        for placement in by_page.get(page_index, []):
            overlay_pdf = _bottom_bleed_overlay_pdf(placement, base_url, ctx)
            overlay = PdfReader(BytesIO(overlay_pdf)).pages[0]
            page.merge_page(overlay)

    with out_pdf.open("wb") as handle:
        writer.write(handle)


def _bottom_bleed_overlay_pdf(
    placement: fillers.FillerPlacement,
    base_url: str,
    ctx: RenderContext,
) -> bytes:
    """Render one transparent full-page PDF overlay for bottom-bleed art."""
    _, HTML = _weasyprint_classes()
    asset = placement.asset
    render_height_in = _placement_render_height_in(placement)
    band_height = max(render_height_in + 0.25, 1.0)
    image_max_height = max(0.1, render_height_in - BOTTOM_BLEED_BOTTOM_INSET_IN)
    image_src = html_lib.escape(asset.art_path.resolve().as_uri(), quote=True)
    overlay_html = f"""
    <!doctype html>
    <style>
      @page {{ size: Letter; margin: 0; }}
      html, body {{
        margin: 0;
        width: 8.5in;
        height: 11in;
        background: transparent;
      }}
      .footer-mask {{
        position: absolute;
        left: 0;
        bottom: 0;
        width: 8.5in;
        height: {band_height:.3f}in;
        background: #fbfaf8;
      }}
      img {{
        position: absolute;
        left: 50%;
        bottom: {BOTTOM_BLEED_BOTTOM_INSET_IN:.3f}in;
        max-width: 8.5in;
        max-height: {image_max_height:.3f}in;
        width: auto;
        height: auto;
        transform: translateX(-50%);
        display: block;
      }}
    </style>
    <div class="footer-mask"></div>
    <img src="{image_src}" alt="" />
    """
    return cast(
        bytes,
        HTML(
            string=overlay_html,
            base_url=base_url,
            url_fetcher=_WEASYPRINT_URL_FETCHER,
        ).write_pdf(**ctx.pdf_settings.weasy_options()),
    )


def _placement_render_height_in(placement: fillers.FillerPlacement) -> float:
    """Return a placement's selected image height with legacy fallback."""
    return placement.render_height_in or placement.asset.height_in


def _normalize_weasyprint_url(url: str) -> str:
    """Convert Windows absolute paths to file URIs before WeasyPrint fetches them."""
    unquoted = unquote(url)
    path_part, suffix = _split_resource_suffix(unquoted)
    if _WINDOWS_ABSOLUTE_URL_RE.match(path_part):
        return Path(path_part).resolve().as_uri() + suffix
    return url


def _normalize_local_urls_in_markup(markup: str) -> str:
    """Convert raw Windows asset paths before WeasyPrint parses the document."""

    def replace_quoted(match: re.Match[str]) -> str:
        quote = match.group("quote")
        return f"{quote}{_normalize_weasyprint_url(match.group('value'))}{quote}"

    def replace_css_url(match: re.Match[str]) -> str:
        quote = match.group("quote") or '"'
        return f"url({quote}{_normalize_weasyprint_url(match.group('value'))}{quote})"

    markup = _WINDOWS_QUOTED_URL_RE.sub(replace_quoted, markup)
    return _WINDOWS_CSS_URL_RE.sub(replace_css_url, markup)


def _local_file_from_url(url: str) -> Path | None:
    """Return a local filesystem path for file URLs and Windows absolute paths."""
    path_part, _suffix = _split_resource_suffix(unquote(url))
    if _WINDOWS_ABSOLUTE_URL_RE.match(path_part):
        return Path(path_part)

    parsed = urlsplit(url)
    if parsed.scheme != "file":
        return None
    path = unquote(parsed.path)
    if os.name == "nt" and re.match(r"^/[A-Za-z]:/", path):
        path = path[1:]
    return Path(path)


def _local_file_response(path: Path) -> Any:
    """Build a WeasyPrint fetch response for a local file without a file URL."""
    url_response = _weasyprint_url_fetcher_response_class()
    token = f"{path.resolve().as_posix()}:{path.stat().st_mtime_ns}"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    return url_response(
        f"memory://papercrown-local/{digest}/{path.name}",
        body=path.read_bytes(),
        headers={"Content-Type": _mime_type_for_path(path)},
    )


def _mime_type_for_path(path: Path) -> str:
    """Return a deterministic MIME type without consulting OS file associations."""
    match path.suffix.lower():
        case ".css":
            return "text/css"
        case ".gif":
            return "image/gif"
        case ".html" | ".htm":
            return "text/html"
        case ".jpeg" | ".jpg":
            return "image/jpeg"
        case ".otf":
            return "font/otf"
        case ".png":
            return "image/png"
        case ".svg":
            return "image/svg+xml"
        case ".ttf":
            return "font/ttf"
        case ".webp":
            return "image/webp"
        case ".woff":
            return "font/woff"
        case ".woff2":
            return "font/woff2"
        case _:
            return "application/octet-stream"


def _split_resource_suffix(value: str) -> tuple[str, str]:
    """Split a URL-ish local path from its query/fragment suffix."""
    suffix_at = len(value)
    for marker in ("?", "#"):
        idx = value.find(marker)
        if idx != -1:
            suffix_at = min(suffix_at, idx)
    return value[:suffix_at], value[suffix_at:]
