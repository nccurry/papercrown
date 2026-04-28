"""Pandoc command construction and process execution helpers."""

from __future__ import annotations

import os
import subprocess
from typing import Any


def build_pandoc_metadata(ctx: Any) -> list[str]:
    """Return Pandoc metadata and variable arguments for a render context."""
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
            args += ["--variable", f"cover-art={ctx.cover_art.as_posix()}"]
    return args


def build_pandoc_base_args(ctx: Any, *, css: bool) -> list[str]:
    """Return common Pandoc arguments shared by HTML and PDF render paths."""
    args: list[str] = [
        "--from=markdown+pipe_tables+backtick_code_blocks+fenced_divs+bracketed_spans+implicit_figures-yaml_metadata_block-multiline_tables-simple_tables-grid_tables",
        "--standalone",
        f"--template={ctx.template.as_posix()}",
    ]
    if css:
        args.extend(f"--css={path.as_posix()}" for path in ctx.css_files)
    if ctx.resource_paths:
        args.append(
            "--resource-path="
            f"{os.pathsep.join(path.as_posix() for path in ctx.resource_paths)}"
        )
    for lua_filter in ctx.lua_filters:
        args.append(f"--lua-filter={lua_filter.as_posix()}")
    if ctx.include_toc:
        args += ["--toc", "--toc-depth=4"]
    args += build_pandoc_metadata(ctx)
    return args


def run_subprocess(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing stdout/stderr as UTF-8 text."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
