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
import subprocess
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

from . import fillers, page_damage, pagination
from .manifest import FillerCatalog, PageDamageCatalog
from .resources import TEXTURES_DIR

_WINDOWS_ABSOLUTE_URL_RE = re.compile(r"^[A-Za-z]:[\\/]")
PT_PER_IN = 72.0
BOTTOM_BLEED_BOTTOM_INSET_IN = 0.12
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


_WEASYPRINT_URL_FETCHER = _weasyprint_url_fetcher
_WINDOWS_QUOTED_URL_RE = re.compile(
    r"(?P<quote>[\"'])(?P<value>[A-Za-z]:[\\/][^\"']*)(?P=quote)"
)
_WINDOWS_CSS_URL_RE = re.compile(
    r"url\(\s*(?P<quote>[\"']?)(?P<value>[A-Za-z]:[\\/][^)\"']+)(?P=quote)\s*\)"
)

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


def _build_pandoc_metadata(ctx: RenderContext) -> list[str]:
    args: list[str] = [
        "--metadata",
        f"pagetitle={ctx.chapter_title}",
        "--metadata",
        f"chapter-title={ctx.chapter_title}",
        "--metadata",
        f"chapter-eyebrow={ctx.chapter_eyebrow}",
        "--metadata",
        f"section-kind={ctx.section_kind}",
    ]
    if ctx.chapter_opener:
        args += ["--metadata", "chapter-opener=true"]
    if ctx.title_prefix:
        args += ["--metadata", f"title-prefix={ctx.title_prefix}"]
    for key, value in (
        ("book-author", ctx.book_author),
        ("book-description", ctx.book_description),
        ("book-keywords", ctx.book_keywords),
        ("book-date", ctx.book_date),
        ("book-publisher", ctx.book_publisher),
        ("book-version", ctx.book_version),
        ("book-license", ctx.book_license),
    ):
        if value:
            args += ["--metadata", f"{key}={value}"]
    if ctx.valid_anchors:
        args += ["--metadata", f"valid-anchors={ctx.valid_anchors}"]
    if ctx.chapter_art and ctx.chapter_art.is_file():
        # Use `--variable`, NOT `--metadata`, for path-typed template
        # values. Pandoc YAML-parses `--metadata` values, and a Windows
        # path like `C:/Users/...` matches YAML's mapping syntax (`C:`
        # looks like a key with `/Users/...` as the value), which corrupts
        # the path before the template substitution and produces nonsense
        # like `withBinaryFile: invalid argument`. `--variable` values are
        # treated as opaque strings, which is what we want for paths. The
        # template references `$chapter-art$` either way -- variables and
        # metadata share that namespace at template-render time.
        args += ["--variable", f"chapter-art={ctx.chapter_art.as_posix()}"]
    args += ["--metadata", f"output-profile={ctx.output_profile}"]
    if ctx.output_profile == "digital":
        args += ["--metadata", "digital=true"]
    if ctx.draft_placeholders:
        args += ["--variable", "draft-placeholders=true"]
    if ctx.ornament_folio_frame and ctx.ornament_folio_frame.is_file():
        args += [
            "--variable",
            f"ornament-folio-frame={ctx.ornament_folio_frame.as_posix()}",
        ]
    if ctx.ornament_corner_bracket and ctx.ornament_corner_bracket.is_file():
        args += [
            "--variable",
            f"ornament-corner-bracket={ctx.ornament_corner_bracket.as_posix()}",
        ]
    if ctx.page_background_underlay:
        args += ["--variable", "page-background-underlay=true"]
    if ctx.cover_enabled:
        args += [
            "--metadata",
            "cover=true",
            "--metadata",
            f"cover-title={ctx.cover_title or ctx.chapter_title}",
            "--metadata",
            f"cover-eyebrow={ctx.cover_eyebrow or 'A Player Book'}",
        ]
        if ctx.cover_subtitle:
            args += ["--metadata", f"cover-subtitle={ctx.cover_subtitle}"]
        if ctx.cover_footer:
            args += ["--metadata", f"cover-footer={ctx.cover_footer}"]
        if ctx.cover_art and ctx.cover_art.is_file():
            # Variable, not metadata -- see chapter-art comment.
            args += ["--variable", f"cover-art={ctx.cover_art.as_posix()}"]
    return args


def _build_pandoc_base_args(ctx: RenderContext, *, css: bool) -> list[str]:
    # Disable yaml_metadata_block: combined-book markdown has many `---`
    # horizontal rules paired with `*italic*` lines, which Pandoc otherwise
    # misparses as a YAML alias inside metadata. Our content has no real
    # YAML frontmatter (assembly.py strips any), so we don't need it.
    #
    # Disable multiline_tables / simple_tables / grid_tables: a chapter body
    # with TWO `---` thematic breaks and bold-text paragraphs between them
    # gets pattern-matched as a multiline table whose body silently absorbs
    # the surrounding `:::::` chapter-wrap closing fence -- which then nests
    # every subsequent chapter inside the previous one (Bonded, Mycologist,
    # and Songweaver were vanishing this way). We only use pipe_tables for
    # real tables, so the others are pure foot-gun.
    args: list[str] = [
        "--from=markdown+pipe_tables+backtick_code_blocks+fenced_divs+bracketed_spans+implicit_figures-yaml_metadata_block-multiline_tables-simple_tables-grid_tables",
        "--standalone",
        # Forward-slash absolute path -- see chapter-art comment for why we
        # avoid both `file:///` URIs and backslash Windows paths.
        f"--template={ctx.template.as_posix()}",
    ]
    if css:
        args.extend(f"--css={path.as_posix()}" for path in ctx.css_files)
    if ctx.resource_paths:
        # Pandoc uses the platform path separator (`;` on Windows, `:` on
        # POSIX) for `--resource-path`. Each path itself uses forward
        # slashes so Pandoc's path parser doesn't trip on `\U` etc.
        args.append(
            "--resource-path="
            f"{os.pathsep.join(p.as_posix() for p in ctx.resource_paths)}"
        )
    for lf in ctx.lua_filters:
        args.append(f"--lua-filter={lf.as_posix()}")
    if ctx.include_toc:
        # depth=4 surfaces chapters, sub-chapters, and a couple more nested
        # levels (e.g. classes -> archetypes -> features). Core CSS
        # progressively indents each nested level so the hierarchy reads.
        args += ["--toc", "--toc-depth=4"]
    args += _build_pandoc_metadata(ctx)
    return args


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
    base_url = ctx.template.parent.resolve().as_uri()
    html = _normalize_local_urls_in_markup(html)
    _, HTML = _weasyprint_classes()
    font_config = _new_weasyprint_font_config()
    stylesheets = _render_stylesheets(ctx, font_config=font_config)
    weasy_options = ctx.pdf_settings.weasy_options()
    stage_start = _log_timing(ctx, "weasy setup", stage_start)
    first_doc = HTML(
        string=html,
        base_url=base_url,
        url_fetcher=_WEASYPRINT_URL_FETCHER,
    ).render(stylesheets=stylesheets, font_config=font_config, **weasy_options)
    stage_start = _log_timing(
        ctx,
        f"weasy layout ({len(first_doc.pages)} pages)",
        stage_start,
    )
    pagination_fix_ids: list[str] = []
    accepted_fix: bool | None = None
    fix_reason: str | None = None
    if ctx.pagination_mode == "fix":
        initial_report = pagination.analyze_document(first_doc)
        fix_result = pagination.inject_page_break_fixes(html, initial_report)
        if fix_result.changed:
            fixed_html = _normalize_local_urls_in_markup(fix_result.html)
            candidate_doc = HTML(
                string=fixed_html,
                base_url=base_url,
                url_fetcher=_WEASYPRINT_URL_FETCHER,
            ).render(
                stylesheets=stylesheets,
                font_config=font_config,
                **weasy_options,
            )
            candidate_report = pagination.analyze_document(candidate_doc)
            page_growth = len(candidate_doc.pages) - len(first_doc.pages)
            if (
                candidate_report.total_badness < initial_report.total_badness
                and page_growth <= 1
            ):
                html = fixed_html
                first_doc = candidate_doc
                pagination_fix_ids = fix_result.applied_ids
                accepted_fix = True
                fix_reason = (
                    f"badness {initial_report.total_badness} -> "
                    f"{candidate_report.total_badness}"
                )
            else:
                accepted_fix = False
                fix_reason = (
                    f"candidate badness {candidate_report.total_badness}; "
                    f"page growth {page_growth}"
                )
        elif initial_report.issues:
            accepted_fix = False
            fix_reason = "no eligible stranded heading fixes"
        stage_start = _log_timing(ctx, "pagination fix pass", stage_start)
    final_doc = first_doc
    placements: list[fillers.FillerPlacement] = []
    filler_decisions: list[fillers.FillerDecision] = []
    catalog = filler_catalog
    if catalog is not None and catalog.enabled:
        placements, filler_decisions = fillers.plan_filler_decisions(
            first_doc,
            catalog,
            recipe_title=recipe_title or ctx.chapter_title,
        )
        for warning in fillers.filler_warnings(placements):
            _log_warning(ctx, warning)
        if filler_report_path is not None:
            fillers.write_filler_report(
                filler_report_path,
                first_doc,
                catalog,
                recipe_title=recipe_title or ctx.chapter_title,
            )
        if missing_art_report_path is not None:
            fillers.write_missing_art_report(
                missing_art_report_path,
                first_doc,
                catalog,
                recipe_title=recipe_title or ctx.chapter_title,
            )
        if placements:
            filled_html = fillers.inject_fillers(html, placements)
            filled_html = _normalize_local_urls_in_markup(filled_html)
            candidate_doc = HTML(
                string=filled_html,
                base_url=base_url,
                url_fetcher=_WEASYPRINT_URL_FETCHER,
            ).render(
                stylesheets=stylesheets,
                font_config=font_config,
                **weasy_options,
            )
            if len(candidate_doc.pages) <= len(first_doc.pages):
                final_doc = candidate_doc
        stage_start = _log_timing(ctx, "filler planning/injection", stage_start)
    overlay_placements = [
        placement for placement in placements if placement.mode == "bottom-bleed"
    ]
    damage_catalog = page_damage_catalog
    damage_placements: list[page_damage.PageDamagePlacement] = []
    pdf_already_cleaned = False
    if damage_catalog is not None and damage_catalog.enabled:
        damage_placements = page_damage.plan_page_damage(
            final_doc,
            damage_catalog,
            recipe_title=recipe_title or ctx.chapter_title,
        )
        stage_start = _log_timing(
            ctx,
            f"page damage planning ({len(damage_placements)} placements)",
            stage_start,
        )
        if ctx.page_damage_mode == "full":
            _write_pdf_with_page_art(
                final_doc,
                out_pdf,
                damage_catalog=damage_catalog,
                damage_placements=damage_placements,
                overlay_placements=overlay_placements,
                base_url=base_url,
                ctx=ctx,
            )
        else:
            _write_pdf_with_page_damage_fast(
                final_doc,
                out_pdf,
                damage_catalog=damage_catalog,
                damage_placements=damage_placements,
                overlay_placements=overlay_placements,
                base_url=base_url,
                ctx=ctx,
            )
            pdf_already_cleaned = True
        stage_start = _log_timing(
            ctx,
            f"pdf write ({ctx.page_damage_mode})",
            stage_start,
        )
    elif overlay_placements:
        _write_pdf_with_bottom_bleeds(
            final_doc,
            out_pdf,
            overlay_placements,
            base_url,
            ctx,
        )
        stage_start = _log_timing(ctx, "pdf write (bottom bleeds)", stage_start)
    else:
        final_doc.write_pdf(out_pdf, **weasy_options)
        stage_start = _log_timing(ctx, "pdf write", stage_start)
    if ctx.pagination_mode != "off" and ctx.pagination_report_path is not None:
        pagination.write_report(
            ctx.pagination_report_path,
            pagination.analyze_document(final_doc),
            fix_ids=pagination_fix_ids,
            accepted_fix=accepted_fix,
            fix_reason=fix_reason,
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
            filler_decisions,
            placements,
        )
    return out_pdf


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


def _write_pdf_metadata(out_pdf: Path, *, title: str, ctx: RenderContext) -> None:
    """Write standard PDF document metadata after cleanup passes."""
    metadata = {
        "/Title": title,
        "/Creator": "papercrown",
    }
    optional = {
        "/Author": ctx.book_author,
        "/Subject": ctx.book_description,
        "/Keywords": ctx.book_keywords,
        "/Publisher": ctx.book_publisher,
        "/Version": ctx.book_version,
        "/License": ctx.book_license,
        "/Date": ctx.book_date,
    }
    metadata.update({key: value for key, value in optional.items() if value})
    reader = PdfReader(str(out_pdf))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.add_metadata(metadata)
    with out_pdf.open("wb") as handle:
        writer.write(handle)


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


def _save_fitz_pdf(document: Any, out_pdf: Path) -> None:
    """Save a PyMuPDF document with the same cleanup settings used elsewhere."""
    tmp_path = out_pdf.with_name(f"{out_pdf.stem}.fitz-saving{out_pdf.suffix}")
    if tmp_path.exists():
        tmp_path.unlink()
    document.save(
        tmp_path,
        garbage=4,
        deflate=True,
        deflate_images=False,
        deflate_fonts=True,
        clean=True,
        use_objstms=1,
    )
    _replace_pdf(tmp_path, out_pdf)


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


def _clean_pdf(path: Path) -> None:
    """Rewrite the PDF to drop unused resources after page merges."""
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
    _replace_pdf(tmp_path, path)


def _replace_pdf(source: Path, target: Path) -> None:
    """Replace a PDF, retrying briefly for Windows handle release lag."""
    for attempt in range(8):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.25)


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


def _run_subprocess(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing stdout/stderr as text.

    Forces utf-8 with replacement so non-cp1252 bytes in tool output (smart
    quotes, em-dashes, etc.) can't crash the reader thread on Windows and
    leave `result.stderr = None`.
    """
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# ---------------------------------------------------------------------------
# Snapshot normalization
# ---------------------------------------------------------------------------


_TOKEN_PAPERCROWN = "<<papercrown>>"
_TOKEN_FIXTURE = "<<fixture>>"
_TOKEN_TMP = "<<tmp>>"


def normalize_for_snapshot(
    html: str,
    *,
    papercrown_root: Path | None = None,
    fixture_root: Path | None = None,
) -> str:
    """Strip absolute paths from HTML before snapshot comparison.

    Two forms get normalized:

      1. `file://` URIs -- old Pandoc behavior; we still see them in some
         versions and in tests that synthesize them.
      2. Plain absolute paths -- current Pandoc behavior on Windows after
         we switched away from `Path.as_uri()` (some Pandoc builds mangle
         file:// URIs containing URL-escaped spaces, leaving literal `%20`
         in the output filename).

    Mappings:
      - paths inside `papercrown_root`  -> <<papercrown>>/relative/path
      - paths inside `fixture_root` -> <<fixture>>/relative/path
      - generic absolute / file:// paths -> <<tmp>>/<basename>
    """
    from urllib.parse import unquote, urlsplit

    out = html

    def _normalize_path(raw: str) -> str:
        # `raw` is a (possibly url-encoded) absolute path with no scheme.
        # Decode percent escapes so spaces and punctuation compare naturally.
        # actual filesystem path before relative_to() resolution.
        decoded = unquote(raw)
        path = Path(decoded)
        if papercrown_root is not None:
            try:
                rel = path.resolve().relative_to(papercrown_root.resolve())
                return f"{_TOKEN_PAPERCROWN}/{rel.as_posix()}"
            except (ValueError, OSError):
                pass
        if fixture_root is not None:
            try:
                rel = path.resolve().relative_to(fixture_root.resolve())
                return f"{_TOKEN_FIXTURE}/{rel.as_posix()}"
            except (ValueError, OSError):
                pass
        return f"{_TOKEN_TMP}/{path.name}"

    # 1. file:// URIs (legacy / test-only path).
    def _replace_uri(match: re.Match[str]) -> str:
        uri = match.group(0)
        parsed = urlsplit(uri)
        path_str = parsed.path
        if parsed.netloc and parsed.netloc != "localhost":
            path_str = f"//{parsed.netloc}{path_str}"
        if re.match(r"^/[A-Za-z]:[\\/]", path_str):
            path_str = path_str[1:]
        return _normalize_path(path_str)

    out = re.sub(r"file:///?[^\s\"'<>]+", _replace_uri, out)

    # 2. Plain absolute paths inside known roots. We search for the literal
    # root path in the HTML (with backslashes normalized to forward slashes
    # and vice versa) and replace each occurrence with the token + the
    # remaining path. This covers `<link href="C:\path\to\book.css">` and
    # similar without trying to enumerate every absolute-path shape on disk.
    def _root_replace(root: Path | None, token: str) -> None:
        nonlocal out
        if root is None:
            return
        root_abs = root.resolve()
        # Build candidate string forms to look for in the HTML. On Windows
        # paths can appear with either separator; normalize to both.
        forms: list[str] = []
        s = str(root_abs)
        forms.append(s)
        forms.append(s.replace("\\", "/"))
        forms.append(s.replace("/", "\\"))
        # De-dup while preserving order
        seen: set[str] = set()
        unique_forms: list[str] = []
        for form in forms:
            if form in seen:
                continue
            seen.add(form)
            unique_forms.append(form)

        def _build_repl(form: str) -> re.Pattern[str]:
            # Match the form followed by either / or \ then the relative path
            # up to the next whitespace / quote / angle-bracket.
            return re.compile(re.escape(form) + r"[\\/]([^\s\"'<>]+)")

        for form in unique_forms:
            pat = _build_repl(form)
            out = pat.sub(
                lambda m: f"{token}/{m.group(1).replace(chr(92), '/')}",
                out,
            )

    _root_replace(papercrown_root, _TOKEN_PAPERCROWN)
    _root_replace(fixture_root, _TOKEN_FIXTURE)

    return out
