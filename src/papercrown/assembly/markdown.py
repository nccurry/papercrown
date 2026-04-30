"""Assembling chapter markdown from source files.

Once a Chapter has its `source_files` resolved, this module produces the
single markdown blob that gets fed to Pandoc. Handles:

  - Stripping YAML frontmatter (defensive; the vault doesn't really use it
    but obsidian-export occasionally emits it)
  - Mapping source files to their obsidian-exported counterparts when an
    export was performed (so wikilinks/embeds are pre-resolved)
  - Demoting headings when concatenating multiple files or exported embed
    catalogs under one chapter (so the chapter's own title heading remains
    the only H1)
  - Prepending the chapter title heading if the first source file doesn't
    open with one
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator
from pathlib import Path

from papercrown.assembly import art_blocks as _art_blocks
from papercrown.assembly import headings as _headings
from papercrown.assembly import sources as _source_notes
from papercrown.project.manifest import (
    BookPart,
    Chapter,
    ChapterFillerSlot,
    ChapterHeadingFillerMarker,
    GeneratedPart,
    InlinePart,
    Splash,
    TocPart,
    resolve_art_asset,
    slugify,
)
from papercrown.project.recipe import Recipe
from papercrown.project.vaults import VaultIndex

render_back_cover_splashes = _art_blocks.render_back_cover_splashes

# Placeholder replaced with generated frame summary tables during assembly.
FRAME_TABLE_MARKER = "<!-- AUTO_FRAME_TABLE -->"
TOC_MARKER_RE = re.compile(
    r"^<!--\s*papercrown-toc:\s*(?P<title>.*?)\s*\|\s*(?P<depth>.*?)\s*-->$"
)
GENERATED_MARKER_RE = re.compile(
    r"^<!--\s*papercrown-generated:\s*(?P<kind>.*?)\s*\|\s*(?P<title>.*?)\s*\|\s*(?P<style>.*?)\s*-->$"
)


# ---------------------------------------------------------------------------
# Public assembly functions
# ---------------------------------------------------------------------------


def assemble_chapter_markdown(
    chapter: Chapter,
    *,
    export_map: dict[Path, Path] | None = None,
    vault_index: VaultIndex | None = None,
    splashes: list[Splash] | None = None,
    include_art: bool = True,
    include_splashes: bool = True,
    include_fillers: bool = True,
    include_tailpiece_art: bool = False,
    include_source_markers: bool = False,
    recipe: Recipe | None = None,
) -> str:
    """Concatenate the chapter's source files into one markdown blob.

    `export_map` is an optional mapping from source-file path to the
    obsidian-exported equivalent. If provided, files are read through the
    map (so embeds are resolved); otherwise raw vault files are used.
    """
    if not chapter.source_files:
        # Empty leaf -- still emit a chapter heading so it's visible
        return f"# {chapter.title}\n\n*(empty)*\n"

    parts: list[str] = []
    for i, src in enumerate(chapter.source_files):
        body = _source_notes.read_via_export(src, export_map, vault_index=vault_index)
        body = _source_notes.strip_frontmatter(body).strip()
        body = _source_notes.normalize_heading_spacing(body)
        if i < len(chapter.source_strip_related) and chapter.source_strip_related[i]:
            body = _source_notes.strip_trailing_related_section(body)
        source_title = (
            chapter.source_titles[i] if i < len(chapter.source_titles) else None
        )
        stripped_wrapper_heading = False
        if source_title:
            body, stripped_wrapper_heading = _strip_redundant_wrapper_heading(
                body,
                source_title,
            )
        if (
            source_title
            and not stripped_wrapper_heading
            and not _source_notes.starts_with_h1(body)
            and not _source_notes.starts_with_heading_title(body, source_title)
        ):
            body = f"# {source_title}\n\n{body}"
        if chapter.slug.startswith("original-"):
            body = _prefix_original_source_anchor(
                body,
                src,
                is_first_source=i == 0,
                chapter_slug=chapter.slug,
            )
        if (
            include_fillers
            and chapter.fillers_enabled
            and chapter.style == "class"
            and chapter.subclass_filler_slots
            and _source_filler_enabled(chapter, i)
            and not chapter.slug.startswith("original-")
            and _is_subclass_source(src)
        ):
            for slot_name in chapter.subclass_filler_slots:
                body = _append_source_end_filler_slot(
                    body,
                    chapter,
                    src,
                    slot_name=slot_name,
                )
        if (
            include_fillers
            and chapter.fillers_enabled
            and chapter.source_boundary_filler_slots
            and _source_filler_enabled(chapter, i)
            and i < len(chapter.source_files) - 1
        ):
            for slot_name in chapter.source_boundary_filler_slots:
                body = _append_source_end_filler_slot(
                    body,
                    chapter,
                    src,
                    slot_name=slot_name,
                    slot_kind="source-boundary",
                    context=_source_filler_context(chapter, src, source_title),
                )
        if include_source_markers:
            body = _inject_source_file_marker(body, src)
        if i == 0:
            parts.append(body)
        else:
            parts.append("\n\n" + _source_notes.demote_h1s(body).strip())

    combined = "\n\n".join(parts)

    # Make sure the chapter has an h1. If the first file didn't open with one,
    # prepend the chapter title.
    if not _source_notes.starts_with_h1(combined):
        combined = f"# {chapter.title}\n\n" + combined
    combined = _normalize_original_frame_size_line(combined, chapter)
    if chapter.style == "source-reference":
        combined = _normalize_source_reference_size_line(combined)
    combined = _replace_auto_frame_tables(combined)
    if include_art:
        combined = _inject_class_spot(combined, chapter)
        combined = _inject_headpiece(combined, chapter.headpiece_path)
    section_art: dict[str, str] = {}
    if chapter.slug == "frames":
        combined, section_art = _extract_frame_section_art_blocks(combined)
    if include_fillers and chapter.fillers_enabled:
        for marker in _chapter_heading_filler_markers(chapter):
            combined = _insert_heading_section_end_filler_slots(
                combined,
                chapter,
                slot_name=marker.slot,
                heading_level=marker.heading_level,
                slot_kind=marker.slot_kind,
                skip_first=marker.skip_first,
                context=marker.context,
            )
    combined = _demote_repeated_h1s(
        combined,
        divider_eyebrow=chapter.title,
        divider_parent_slug=chapter.slug,
        section_art=section_art,
    )
    combined = _apply_full_page_sections(
        combined,
        chapter.full_page_sections,
        divider_eyebrow=chapter.title,
        divider_parent_slug=chapter.slug,
    )
    if include_splashes:
        combined = _insert_chapter_splashes(combined, splashes or [])
    if recipe is not None:
        combined = _replace_art_slot_blocks(
            combined,
            recipe,
            include_art=include_art,
        )
    if include_art:
        combined = _replace_thematic_breaks_with_ornament(
            combined,
            chapter.break_ornament_path,
        )
    if include_art and include_tailpiece_art:
        combined = _append_tailpiece(combined, chapter.tailpiece_path)
    if include_fillers and chapter.fillers_enabled:
        combined = _append_filler_slots(combined, chapter.filler_slots)
    if chapter.slug.startswith("original-"):
        combined = _inject_original_reference_anchors(combined)
    return combined


def assemble_combined_book_markdown(
    contents: list[Chapter],
    *,
    export_map: dict[Path, Path] | None = None,
    vault_index: VaultIndex | None = None,
    include_toc: bool = False,
    include_art: bool = True,
    include_fillers: bool = True,
    include_tailpiece_art: bool = False,
    splashes: list[Splash] | None = None,
    include_source_markers: bool = False,
    include_back_cover_splashes: bool = True,
    recipe: Recipe | None = None,
) -> str:
    """Concatenate every chapter into one big markdown blob for the combined book.

    Heading hierarchy + section-divider pages:

      * Every TOP-LEVEL chapter gets a full-page section-divider before
        its content. The divider title is emitted as a real `<h1>` and is
        the chapter's canonical TOC / PDF outline / cross-link target.

      * NESTED chapters (depth >= 1 inside a wrapper) get a section-
        divider page only if their `divider` flag is set (controlled by
        the recipe via `child_divider: true`). When they do, the
        divider's title heading is rendered at the demoted level
        (`depth + 1`), and the chapter's body has its own leading h1
        stripped so the divider replaces it (no duplicate TOC entry).
        Headings deeper than the leading h1 are demoted by `depth` so
        they continue to nest correctly.

      * Nested chapters WITHOUT the divider flag fall back to today's
        behavior: no extra divider page, body's leading h1 becomes the
        TOC entry, all headings demoted by `depth`.
    """
    parts: list[str] = []
    for top in contents:
        # The top-level divider supplies the canonical chapter heading for
        # every chapter, including non-wrapper file/catalog chapters.
        parts.append(
            _render_section_divider(
                top,
                with_heading=True,
                level=1,
                include_art=include_art,
                breadcrumb=_chapter_breadcrumb([top]),
            )
        )

        for descendant, depth, ancestors in _walk_with_ancestry(top):
            is_top = descendant is top
            has_body = bool(descendant.source_files)
            # Per-child dividers fire only for non-top descendants flagged
            # with `divider=True` (set by `child_divider: true` in a recipe).
            # The top's divider was already emitted above, so we never emit
            # a second one here.
            wants_descendant_divider = (not is_top) and descendant.divider

            if wants_descendant_divider:
                # Heading inside the divider sits at h(depth+1) so it nests
                # under the wrapper's h1 in the TOC.
                divider_level = min(6, depth + 1)
                parts.append(
                    _render_section_divider(
                        descendant,
                        with_heading=True,
                        level=divider_level,
                        include_art=include_art,
                        breadcrumb=_chapter_breadcrumb([*ancestors, descendant]),
                    )
                )

            if not has_body:
                # Wrapper-style chapter (own divider IS the output, no body).
                continue

            body = assemble_chapter_markdown(
                descendant,
                export_map=export_map,
                vault_index=vault_index,
                splashes=_splashes_for_chapter(splashes or [], descendant),
                include_art=include_art,
                include_splashes=include_art,
                include_fillers=include_art and include_fillers,
                include_tailpiece_art=include_tailpiece_art,
                include_source_markers=include_source_markers,
                recipe=recipe,
            ).strip()
            slug = descendant.slug or "chapter"

            # Strip the body's leading h1 whenever a divider supplied that
            # chapter/major-section heading. Top-level chapters always use
            # their divider as the canonical heading; descendant chapters do
            # so only when `divider=True`.
            if is_top or wants_descendant_divider:
                body = _strip_leading_h1(body)
            elif slug:
                body = _headings.ensure_leading_heading_id(body, slug)
            if depth >= 1:
                body = _demote_headings(body, by=depth)

            style = descendant.style or "default"
            wrapped = (
                f"\n\n:::::: {{.chapter-wrap .section-{style} #ch-{slug}}}\n\n"
                f"{body}\n\n"
                "::::::\n\n"
            )
            parts.append(wrapped)
    if include_art and include_back_cover_splashes:
        back_cover_pages = render_back_cover_splashes(splashes)
        if back_cover_pages:
            parts.append(back_cover_pages)
    markdown = "\n\n".join(parts)
    if include_toc:
        return add_manual_toc(markdown, contents)
    return markdown


def assemble_book_contents_markdown(
    contents: list[BookPart],
    *,
    export_map: dict[Path, Path] | None = None,
    vault_index: VaultIndex | None = None,
    include_art: bool = True,
    include_fillers: bool = True,
    include_tailpiece_art: bool = False,
    splashes: list[Splash] | None = None,
    include_source_markers: bool = False,
    include_back_cover_splashes: bool = True,
    recipe: Recipe | None = None,
) -> str:
    """Concatenate the ordered book contents stream into markdown."""
    parts: list[str] = []
    for part in contents:
        if isinstance(part, InlinePart):
            continue
        if isinstance(part, TocPart):
            depth = "" if part.depth is None else str(part.depth)
            parts.append(f"<!-- papercrown-toc: {part.title} | {depth} -->")
            continue
        if isinstance(part, GeneratedPart):
            parts.append(
                "<!-- papercrown-generated: "
                f"{part.type} | {part.title} | {part.style} -->"
            )
            continue
        _append_combined_chapter_parts(
            parts,
            part,
            export_map=export_map,
            vault_index=vault_index,
            include_art=include_art,
            include_fillers=include_fillers,
            include_tailpiece_art=include_tailpiece_art,
            splashes=splashes,
            include_source_markers=include_source_markers,
            recipe=recipe,
        )
    if include_art and include_back_cover_splashes:
        back_cover_pages = render_back_cover_splashes(splashes)
        if back_cover_pages:
            parts.append(back_cover_pages)
    return "\n\n".join(parts)


def _append_combined_chapter_parts(
    parts: list[str],
    top: Chapter,
    *,
    export_map: dict[Path, Path] | None,
    vault_index: VaultIndex | None,
    include_art: bool,
    include_fillers: bool,
    include_tailpiece_art: bool,
    splashes: list[Splash] | None,
    include_source_markers: bool,
    recipe: Recipe | None,
) -> None:
    """Append one top-level chapter and descendants to combined-book parts."""
    parts.append(
        _render_section_divider(
            top,
            with_heading=True,
            level=1,
            include_art=include_art,
            breadcrumb=_chapter_breadcrumb([top]),
        )
    )

    for descendant, depth, ancestors in _walk_with_ancestry(top):
        is_top = descendant is top
        has_body = bool(descendant.source_files)
        wants_descendant_divider = (not is_top) and descendant.divider

        if wants_descendant_divider:
            divider_level = min(6, depth + 1)
            parts.append(
                _render_section_divider(
                    descendant,
                    with_heading=True,
                    level=divider_level,
                    include_art=include_art,
                    breadcrumb=_chapter_breadcrumb([*ancestors, descendant]),
                )
            )

        if not has_body:
            continue

        body = assemble_chapter_markdown(
            descendant,
            export_map=export_map,
            vault_index=vault_index,
            splashes=_splashes_for_chapter(splashes or [], descendant),
            include_art=include_art,
            include_splashes=include_art,
            include_fillers=include_art and include_fillers,
            include_tailpiece_art=include_tailpiece_art,
            include_source_markers=include_source_markers,
            recipe=recipe,
        ).strip()
        slug = descendant.slug or "chapter"
        if is_top or wants_descendant_divider:
            body = _strip_leading_h1(body)
        elif slug:
            body = _headings.ensure_leading_heading_id(body, slug)
        if depth >= 1:
            body = _demote_headings(body, by=depth)

        style = descendant.style or "default"
        wrapped = (
            f"\n\n:::::: {{.chapter-wrap .section-{style} #ch-{slug}}}\n\n"
            f"{body}\n\n"
            "::::::\n\n"
        )
        parts.append(wrapped)


def add_manual_toc(
    markdown: str,
    contents: list[Chapter],
    *,
    max_depth: int | None = None,
) -> str:
    """Attach heading ids and prepend the generated manual table of contents."""
    markdown = _headings.ensure_heading_ids(markdown)
    markdown = _headings.dedupe_generated_anchor_ids(markdown)
    return (
        _headings.render_manual_toc(
            markdown,
            toc_depths=_toc_depths_for_top_level(contents),
            max_depth=max_depth,
        )
        + "\n\n"
        + markdown
    )


def replace_manual_toc_markers(
    markdown: str,
    chapters: list[Chapter],
    *,
    default_max_depth: int | None = None,
) -> str:
    """Replace explicit TOC markers with generated manual TOCs."""
    markdown = _headings.ensure_heading_ids(markdown)
    markdown = _headings.dedupe_generated_anchor_ids(markdown)
    toc_source = "\n".join(
        line for line in markdown.splitlines() if TOC_MARKER_RE.match(line) is None
    )
    out: list[str] = []
    for line in markdown.splitlines():
        match = TOC_MARKER_RE.match(line)
        if match is None:
            out.append(line)
            continue
        raw_depth = match.group("depth").strip()
        depth = int(raw_depth) if raw_depth.isdigit() else default_max_depth
        out.append(
            _headings.render_manual_toc(
                toc_source,
                toc_depths=_toc_depths_for_top_level(chapters),
                max_depth=depth,
            )
        )
    return "\n".join(out)


def _walk_with_ancestry(root: Chapter) -> Iterator[tuple[Chapter, int, list[Chapter]]]:
    """Depth-first walk yielding `(chapter, depth, ancestors)` tuples."""

    def _go(
        ch: Chapter,
        depth: int,
        ancestors: list[Chapter],
    ) -> Iterator[tuple[Chapter, int, list[Chapter]]]:
        yield ch, depth, ancestors
        for c in ch.children:
            yield from _go(c, depth + 1, [*ancestors, ch])

    yield from _go(root, 0, [])


def _chapter_breadcrumb(chapters: list[Chapter]) -> str:
    """Return the text used in page-margin running headers."""
    return _breadcrumb_text(*(ch.title for ch in chapters if ch.title))


def _breadcrumb_text(*parts: str | None) -> str:
    return " / ".join(part for part in parts if part)


def _toc_depths_for_top_level(chapters: list[Chapter]) -> dict[str, int]:
    """Return explicit TOC depth caps keyed by top-level chapter slug."""
    return {
        ch.slug: ch.toc_depth for ch in chapters if ch.slug and ch.toc_depth is not None
    }


def _render_section_divider(
    chapter: Chapter,
    *,
    with_heading: bool = False,
    level: int = 1,
    eyebrow_link: str | None = None,
    include_art: bool = True,
    breadcrumb: str | None = None,
    art_src: str | None = None,
) -> str:
    """Emit a section-divider page using Pandoc fenced div syntax.

    Why fenced divs instead of raw HTML: Pandoc's raw-HTML-block parser
    closes the block early when it hits a self-closing tag (like `<img/>`),
    causing the trailing children to leak as plain text. Fenced divs are
    Pandoc-native and render cleanly to nested `<div>` elements; the CSS
    only cares about the class names so the tag (`<div>` vs `<section>`)
    is irrelevant.

    If `with_heading=True`, the title is emitted as a real ATX heading
    (with the `.section-divider-title` class so it still picks up the
    divider typography). `level` (1-6) controls the heading depth so a
    nested divider can sit at h2/h3/etc. and slot into the TOC under its
    parent. Without `with_heading=True`, the title is just a styled div
    and won't appear in the TOC/outline.
    """
    eyebrow = chapter.eyebrow or "Section"
    if eyebrow_link:
        eyebrow = f"[{_headings.markdown_link_text(eyebrow)}](#{eyebrow_link})"
    title = chapter.title
    slug = chapter.slug or "section"
    running_title = breadcrumb or title

    art_block = ""
    if include_art and art_src:
        art_block = (
            "::: section-divider-art-wrap\n"
            f"![]({_markdown_image_target(art_src)})"
            "{.section-divider-art .section-divider-frame-art}\n"
            ":::\n\n"
        )
    elif include_art and chapter.art_path and chapter.art_path.is_file():
        # Forward-slash absolute path inside Pandoc angle-bracket URL syntax
        # `<...>`. Two Windows-specific reasons:
        #   * `file:///...%20...` URIs make Pandoc fail to URL-decode and
        #     leave literal `%20` in the filename it tries to read.
        #   * Backslash paths (`C:\Users\you\...`) make Pandoc's IO layer
        #     reject `\U`, `\N`, `\a`, etc. as invalid characters.
        # The angle brackets let the path contain spaces without
        # URL-encoding; forward slashes keep Pandoc's path parser happy.
        art_path = chapter.art_path.as_posix()
        art_block = (
            "::: section-divider-art-wrap\n"
            f"![](<{art_path}>){{.section-divider-art}}\n"
            ":::\n\n"
        )

    if with_heading:
        # ATX heading at the requested level (clamped to 1-6) with id +
        # class attributes. Pandoc emits `<hN id="..." class="...">Title</hN>`,
        # which the TOC and PDF outline both pick up.
        n = max(1, min(6, level))
        hashes = "#" * n
        title_block = f"{hashes} {title} {{.section-divider-title #{slug}}}\n\n"
    else:
        title_block = f"::: section-divider-title\n{title}\n:::\n\n"

    # Outer fence with attributes (data-* attribute requires the explicit
    # attribute syntax with quotes). Pandoc renders this as a `<div>` with
    # the listed classes/id/data-attrs.
    running_title_attr = _headings.attribute_value(running_title)
    divider_attrs = (
        f'.section-divider data-chapter-name="{running_title_attr}" id="div-{slug}"'
    )
    return (
        "\n\n"
        f"::::: {{{divider_attrs}}}\n\n"
        f"{art_block}"
        ":::: section-divider-text\n\n"
        "::: section-divider-eyebrow\n"
        f"{eyebrow}\n"
        ":::\n\n"
        f"{title_block}"
        "::::\n\n"
        ":::::\n\n"
    )


def _strip_leading_h1(text: str) -> str:
    """Remove a leading `# Heading` line and immediately following blanks.

    Used when a section-divider supplies the chapter heading so the body's own
    h1 does not appear as a duplicate TOC entry.
    """
    lines = text.splitlines()
    i = 0
    # Skip leading blank lines
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines):
        return text
    line = lines[i]
    if not line.startswith("# "):
        return text
    # Drop the h1 line itself.
    i += 1
    # Also swallow any immediately-following blank lines so the body
    # doesn't start with awkward whitespace.
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return "\n".join(lines[i:])


def _inject_source_file_marker(body: str, source: Path) -> str:
    """Insert a source-file marker without disturbing a leading H1."""
    marker = f"<!-- papercrown-source-file: {source.resolve().as_posix()} -->"
    lines = body.splitlines()
    if lines and re.match(r"^#(?:\s+|$)", lines[0]):
        return "\n".join([lines[0], marker, *lines[1:]])
    return marker + "\n" + body


def _strip_redundant_wrapper_heading(text: str, source_title: str) -> tuple[str, bool]:
    """Drop a source-title H1 when it only wraps immediate child headings."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines) or not _headings.is_atx_h1(lines[i]):
        return text, False

    heading = _headings.heading_title_for_slug(lines[i])
    if heading is None or not _source_notes.heading_matches_source_title(
        heading,
        source_title,
    ):
        return text, False

    j = i + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j >= len(lines) or _headings.heading_level(lines[j]) is None:
        return text, False

    return "\n".join(lines[:i] + lines[j:]).lstrip("\n"), True


def _inject_class_spot(text: str, chapter: Chapter) -> str:
    """Insert one configured class spot after the leading chapter heading."""
    if chapter.spot_art_path is None:
        return text
    body = text
    if chapter.replace_opening_art:
        body = _strip_opening_art_spot(body)
    insert_at = _after_leading_h1_index(body)
    if insert_at is None:
        return body

    lines = body.splitlines()
    prefix = "\n".join(lines[:insert_at]).rstrip()
    suffix = "\n".join(lines[insert_at:]).lstrip("\n")
    block = _art_blocks.render_image_block(
        chapter.spot_art_path,
        classes=".class-opening-spot .art-right .art-spot",
    )
    return f"{prefix}\n\n{block}\n\n{suffix}".rstrip() + "\n"


def _normalize_original_frame_size_line(text: str, chapter: Chapter) -> str:
    """Render original ancestry size tags as compact headings."""
    if chapter.style != "ancestries" or not chapter.slug.startswith("original-"):
        return text

    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines) or not _headings.is_atx_h1(lines[i]):
        return text

    j = i + 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    if j >= len(lines):
        return text

    match = re.fullmatch(r"\(([^()]+)\)", lines[j].strip())
    if match is None:
        return text

    size = _normalize_size_label(match.group(1))
    lines[j] = f"## {size}"
    return "\n".join(lines)


def _append_filler_slots(text: str, slots: list[ChapterFillerSlot]) -> str:
    """Append zero-height conditional filler markers."""
    if not slots:
        return text
    blocks = [_art_blocks.render_filler_slot(slot) for slot in slots]
    return f"{text.rstrip()}\n\n" + "\n\n".join(blocks) + "\n"


def _append_source_end_filler_slot(
    text: str,
    chapter: Chapter,
    source: Path,
    *,
    slot_name: str,
    slot_kind: str | None = None,
    context: str | None = None,
) -> str:
    """Append a section-scoped filler marker after one assembled source file."""
    title = _source_notes.first_heading_text(text) or source.stem
    section_slug = slugify(title)
    source_slug = slugify(f"{source.parent.name}-{source.stem}")
    stable_slug = (
        source_slug if section_slug in source_slug else f"{section_slug}-{source_slug}"
    )
    slot = ChapterFillerSlot(
        id=f"filler-{slot_name}-{chapter.slug}-{stable_slug}",
        slot=slot_name,
        chapter_slug=chapter.slug,
        section_slug=section_slug,
        section_title=title,
        slot_kind=slot_kind or slot_name.removesuffix("-end"),
        context=context,
    )
    return f"{text.rstrip()}\n\n{_art_blocks.render_filler_slot(slot)}\n"


def _source_filler_context(
    chapter: Chapter,
    source: Path,
    source_title: str | None,
) -> str:
    """Return the semantic art context for a generated source-boundary slot."""
    text = " ".join(
        (
            chapter.style,
            chapter.slug,
            source_title or "",
            source.stem,
            source.parent.name,
        )
    ).lower()
    if chapter.slug.startswith("original-") or chapter.style == "source-reference":
        return "reference"
    if chapter.style == "quick-reference" or chapter.slug in {
        "quick-reference",
        "reference",
    }:
        return "reference"
    equipment_terms = (
        "adventuring equipment",
        "weapon",
        "armor",
        "gear",
        "artifact",
        "schematic",
        "module",
        "inventory",
        "wealth",
    )
    if any(term in text for term in equipment_terms):
        return "equipment"
    if chapter.style == "powers" or any(
        term in text for term in ("power", "spell", "magic", "chaos")
    ):
        return "powers"
    combat_terms = (
        "combat",
        "heroic action",
        "heroic reaction",
        "hit point",
        "wound",
        "dying",
        "grappl",
        "cover",
        "range",
        "reach",
    )
    if chapter.style == "equipment" or any(term in text for term in combat_terms):
        return "combat"
    if chapter.style == "class":
        return "class"
    if chapter.style == "ancestries" or chapter.slug == "frames":
        return "frame"
    if chapter.style == "backgrounds":
        return "setting"
    if chapter.slug in {"languages", "language"}:
        return "languages"
    return "general"


def _source_filler_enabled(chapter: Chapter, index: int) -> bool:
    """Return whether source-end filler markers may follow this source file."""
    return (
        index >= len(chapter.source_filler_enabled)
        or chapter.source_filler_enabled[index]
    )


def _chapter_heading_filler_markers(
    chapter: Chapter,
) -> list[ChapterHeadingFillerMarker]:
    """Return resolved heading marker policies, with direct-test defaults."""
    if chapter.heading_filler_markers is not None:
        return chapter.heading_filler_markers
    if chapter.slug == "frames":
        return [
            ChapterHeadingFillerMarker(
                slot="frame-family-end",
                heading_level=1,
                slot_kind="frame-family",
                skip_first=True,
                context="frame",
            )
        ]
    if chapter.slug == "backgrounds":
        return [
            ChapterHeadingFillerMarker(
                slot="background-section-end",
                heading_level=2,
                slot_kind="background-section",
                context="setting",
            )
        ]
    return []


def _insert_heading_section_end_filler_slots(
    text: str,
    chapter: Chapter,
    *,
    slot_name: str,
    heading_level: int,
    slot_kind: str,
    skip_first: bool,
    context: str | None = None,
) -> str:
    """Insert filler markers at the end of sections headed by a given level."""
    out: list[str] = []
    in_code = False
    current_title: str | None = None
    current_slug: str | None = None
    seen_headings = 0
    used: dict[str, int] = {}

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if not in_code:
            match = re.match(r"^(#{1,6})\s+(.+?)\s*(?:#+\s*)?$", line)
            if match is not None and len(match.group(1)) == heading_level:
                seen_headings += 1
                if current_title is not None and current_slug is not None:
                    _append_markdown_block(
                        out,
                        _render_section_end_filler_slot(
                            chapter,
                            slot_name=slot_name,
                            section_title=current_title,
                            section_slug=current_slug,
                            slot_kind=slot_kind,
                            context=context,
                            used=used,
                        ),
                    )
                title = _headings.plain_heading_title(match.group(2))
                if skip_first and seen_headings == 1:
                    current_title = None
                    current_slug = None
                else:
                    current_title = title
                    current_slug = slugify(title)
        out.append(line)

    if current_title is not None and current_slug is not None:
        _append_markdown_block(
            out,
            _render_section_end_filler_slot(
                chapter,
                slot_name=slot_name,
                section_title=current_title,
                section_slug=current_slug,
                slot_kind=slot_kind,
                context=context,
                used=used,
            ),
        )
    return "\n".join(out)


def _append_markdown_block(out: list[str], block: str) -> None:
    """Append a block with blank-line padding for Pandoc block parsing."""
    if out and out[-1].strip():
        out.append("")
    out.append(block)
    out.append("")


def _render_section_end_filler_slot(
    chapter: Chapter,
    *,
    slot_name: str,
    section_title: str,
    section_slug: str,
    slot_kind: str,
    used: dict[str, int],
    context: str | None = None,
) -> str:
    count = used.get(section_slug, 0) + 1
    used[section_slug] = count
    stable_slug = section_slug if count == 1 else f"{section_slug}-{count}"
    return _art_blocks.render_filler_slot(
        ChapterFillerSlot(
            id=f"filler-{slot_name}-{chapter.slug}-{stable_slug}",
            slot=slot_name,
            chapter_slug=chapter.slug,
            section_slug=section_slug,
            section_title=section_title,
            slot_kind=slot_kind,
            context=context,
        )
    )


def _is_subclass_source(source: Path) -> bool:
    """Return whether a source file belongs to a class Subclasses folder."""
    return any(part.lower() == "subclasses" for part in source.parts)


def _extract_frame_section_art_blocks(text: str) -> tuple[str, dict[str, str]]:
    """Move frame-family lead art out of body flow and onto dividers."""
    lines = text.splitlines()
    out: list[str] = []
    art_by_slug: dict[str, str] = {}
    in_code = False
    seen_h1 = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            i += 1
            continue

        title = None if in_code else _headings.heading_title_for_slug(line)
        if not in_code and _headings.is_atx_h1(line):
            is_first_h1 = not seen_h1
            seen_h1 = True
            if not is_first_h1 and title:
                extracted = _extract_following_art_frame(lines, i + 1)
                if extracted is not None:
                    art_src, next_index = extracted
                    art_by_slug[slugify(_headings.plain_heading_title(title))] = art_src
                    out.append(line)
                    i = next_index
                    continue

        out.append(line)
        i += 1
    return "\n".join(out), art_by_slug


def _extract_following_art_frame(
    lines: list[str],
    start: int,
) -> tuple[str, int] | None:
    i = start
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines):
        return None
    fence_match = re.match(r"^(?P<fence>:{3,})\s*\{(?P<attrs>[^}]*)\}\s*$", lines[i])
    if fence_match is None:
        return None
    attrs = fence_match.group("attrs")
    if ".art-frame" not in attrs:
        return None

    fence = fence_match.group("fence")
    j = i + 1
    art_src: str | None = None
    while j < len(lines) and lines[j].strip() != fence:
        image_match = re.search(r"!\[[^\]]*\]\((?P<src>[^)]+)\)", lines[j].strip())
        if image_match is not None:
            art_src = image_match.group("src").strip()
        j += 1
    if art_src is None or j >= len(lines):
        return None
    j += 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    return art_src, j


def _inject_headpiece(text: str, headpiece_path: Path | None) -> str:
    """Insert one configured headpiece after the leading chapter heading."""
    if headpiece_path is None:
        return text
    insert_at = _after_leading_h1_index(text)
    if insert_at is None:
        return text
    block = _art_blocks.render_image_block(
        headpiece_path,
        classes=".ornament-headpiece",
    )
    return _insert_block_at_line(text, insert_at, block)


def _replace_thematic_breaks_with_ornament(
    text: str,
    break_ornament_path: Path | None,
) -> str:
    """Replace Markdown thematic breaks with a selected ornament in opted chapters."""
    if break_ornament_path is None:
        return text
    block = _art_blocks.render_image_block(
        break_ornament_path,
        classes=".ornament-break",
    )
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if not in_code and line.strip() == "---":
            out.extend(["", block, ""])
            continue
        out.append(line)
    return "\n".join(out).rstrip() + "\n"


def _append_tailpiece(text: str, tailpiece_path: Path | None) -> str:
    """Append a configured tailpiece as in-flow art."""
    if tailpiece_path is None:
        return text
    block = _art_blocks.render_image_block(
        tailpiece_path,
        classes=".ornament-tailpiece",
    )
    return f"{text.rstrip()}\n\n{block}\n"


def _splashes_for_chapter(splashes: list[Splash], chapter: Chapter) -> list[Splash]:
    """Return splash placements scoped to ``chapter``."""
    return [
        splash
        for splash in splashes
        if splash.chapter_slug == chapter.slug and splash.art_path is not None
    ]


def _insert_chapter_splashes(
    text: str,
    splashes: list[Splash],
) -> str:
    """Insert configured in-flow splash art for a chapter body."""
    out = text
    for splash in splashes:
        block = _art_blocks.render_splash_block(splash)
        if splash.target == "chapter-start":
            insert_at = _after_leading_h1_index(out)
            if insert_at is not None:
                out = _insert_block_at_line(out, insert_at, block)
        elif splash.target == "after-heading" and splash.heading_slug:
            out = _insert_block_after_heading(out, splash.heading_slug, block)
    return out


def _replace_art_slot_blocks(
    text: str,
    recipe: Recipe,
    *,
    include_art: bool,
) -> str:
    """Replace Markdown ``.art-slot`` fenced divs with resolved art blocks."""
    lines = text.splitlines()
    out: list[str] = []
    in_code = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            i += 1
            continue
        match = None if in_code else _art_slot_fence(line)
        if match is None:
            out.append(line)
            i += 1
            continue

        fence = match.group("fence")
        attrs = _parse_fenced_div_attrs(match.group("attrs"))
        j = i + 1
        while j < len(lines) and lines[j].strip() != fence:
            j += 1
        if j >= len(lines):
            out.append(line)
            i += 1
            continue

        block = _render_art_slot(attrs, recipe, include_art=include_art)
        if block:
            if out and out[-1].strip():
                out.append("")
            out.extend(block.splitlines())
            out.append("")
        i = j + 1
    return "\n".join(out).rstrip() + "\n"


def _art_slot_fence(line: str) -> re.Match[str] | None:
    match = re.match(r"^(?P<fence>:{3,})\s*\{(?P<attrs>[^}]*)\}\s*$", line)
    if match is None:
        return None
    if ".art-slot" not in match.group("attrs").split():
        return None
    return match


def _parse_fenced_div_attrs(attrs: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    try:
        tokens = shlex.split(attrs)
    except ValueError:
        tokens = attrs.split()
    for token in tokens:
        if token.startswith("#") and len(token) > 1:
            parsed["id"] = token[1:]
            continue
        if token.startswith(".") and len(token) > 1:
            classes = parsed.setdefault("classes", "")
            parsed["classes"] = f"{classes} {token[1:]}".strip()
            continue
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed


def _render_art_slot(
    attrs: dict[str, str],
    recipe: Recipe,
    *,
    include_art: bool,
) -> str:
    if not include_art:
        return ""
    role = attrs.get("role") or "splash"
    context = attrs.get("context")
    subject = attrs.get("subject")
    art = attrs.get("art")
    art_path = resolve_art_asset(
        recipe,
        art=art,
        role=role,
        context=context,
        subject=subject,
    )
    slot_id = attrs.get("id") or slugify(
        "-".join(part for part in (role, context, subject, art) if part)
    )
    if art_path is None:
        label = art or context or subject or role
        return f"<!-- papercrown art slot unresolved: {label} -->"
    if role == "splash":
        return _art_blocks.render_splash_block(
            Splash(
                id=slot_id,
                art_path=art_path,
                target="chapter-start",
                placement=attrs.get("placement") or "bottom-half",
            )
        )
    return _art_blocks.render_image_block(
        art_path,
        classes=f".art-slot-art .art-role-{slugify(role)}",
    )


def _insert_block_at_line(text: str, index: int, block: str) -> str:
    """Insert a Markdown block before line ``index``."""
    lines = text.splitlines()
    prefix = "\n".join(lines[:index]).rstrip()
    suffix = "\n".join(lines[index:]).lstrip("\n")
    if suffix:
        return f"{prefix}\n\n{block}\n\n{suffix}".rstrip() + "\n"
    return f"{prefix}\n\n{block}\n"


def _insert_block_after_heading(text: str, heading_slug: str, block: str) -> str:
    """Insert a block after the first heading whose slug matches ``heading_slug``."""
    out: list[str] = []
    inserted = False
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        out.append(line)
        if inserted or in_code or not line.startswith("#"):
            continue
        title = _headings.heading_title_for_slug(line)
        if title and _heading_matches_target_slug(title, heading_slug):
            out.extend(["", block, ""])
            inserted = True
    return "\n".join(out).rstrip() + "\n"


def _heading_matches_target_slug(title: str, heading_slug: str) -> bool:
    """Return whether a rendered heading matches a recipe heading target."""
    rendered_slug = slugify(_headings.plain_heading_title(title))
    return rendered_slug == heading_slug or rendered_slug.startswith(f"{heading_slug}-")


def _prefix_original_source_anchor(
    text: str,
    source: Path,
    *,
    is_first_source: bool,
    chapter_slug: str,
) -> str:
    """Add a stable appendix anchor for an original source file."""
    anchor = "original-" + slugify(source.stem)
    if anchor == chapter_slug:
        return text
    marker = _headings.anchor_marker(anchor)
    if not is_first_source:
        return f"{marker}\n\n{text.lstrip()}"

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip():
            return "\n".join([*lines[: index + 1], "", marker, "", *lines[index + 1 :]])
    return marker


def _inject_original_reference_anchors(text: str) -> str:
    """Expose original appendix feature labels as linkable anchors.

    Source class files often use standalone bold labels instead of
    headings for features. Reskinned parentheticals still need to link to those
    labels, so this adds invisible anchors without altering the source text.
    """
    out: list[str] = []
    seen = set(re.findall(r'id="([A-Za-z0-9_-]+)"', text))
    in_code = False
    saw_leading_h1 = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if not in_code:
            if _headings.is_anchor_marker_line(line):
                out.append(line)
                continue
            if not saw_leading_h1 and _headings.is_atx_h1(line):
                saw_leading_h1 = True
                out.append(line)
                continue
            anchor = _original_reference_anchor_id(line)
            if anchor:
                if anchor not in seen:
                    _headings.append_anchor_marker(out, anchor)
                    seen.add(anchor)
                if _headings.heading_id(line) == anchor:
                    line = _strip_heading_attributes(line)
        out.append(line)
    return "\n".join(out)


def _original_reference_anchor_id(line: str) -> str | None:
    """Return an original reference anchor for a heading/standalone-bold line."""
    title = _headings.heading_title_for_slug(line)
    if title:
        explicit = _headings.heading_id(line)
        if explicit and explicit.startswith("original-language-"):
            return explicit
        base = _headings.heading_base_id(title)
        if base.startswith("original-"):
            return None
        return base if base.startswith("original-") else "original-" + base
    match = re.fullmatch(r"\*\*(?P<title>[^*\n]+?)\*\*\s*", line.strip())
    if match is None:
        return None
    title = match.group("title").rstrip(":").strip()
    if not title:
        return None
    return "original-" + slugify(_headings.plain_heading_title(title))


def _strip_heading_attributes(line: str) -> str:
    """Remove a trailing heading attribute block after emitting an anchor marker."""
    return re.sub(r"\s*\{[^}]*\}\s*$", "", line).rstrip()


def _markdown_image_target(src: str) -> str:
    """Return a Pandoc-safe Markdown image target."""
    value = src.strip()
    if value.startswith("<") and value.endswith(">"):
        return value
    if re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value):
        return value
    return f"<{value}>"


def _after_leading_h1_index(text: str) -> int | None:
    """Return insertion index immediately after the leading H1 and blanks."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines) or not _headings.is_atx_h1(lines[i]):
        return None
    i += 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    return i


def _strip_opening_art_spot(text: str) -> str:
    """Remove a leading hand-authored spot-art fenced div, if present."""
    lines = text.splitlines()
    i = _after_leading_h1_index(text)
    if i is None or i >= len(lines):
        return text

    while i < len(lines) and (
        lines[i].strip() == "" or _is_source_file_marker(lines[i])
    ):
        i += 1
    if i >= len(lines):
        return text

    match = _opening_art_spot_fence(lines[i])
    if match is None:
        return text
    fence = match.group("fence")
    j = i + 1
    while j < len(lines) and lines[j].strip() != fence:
        j += 1
    if j >= len(lines):
        return text
    j += 1
    while j < len(lines) and lines[j].strip() == "":
        j += 1
    return "\n".join(lines[:i] + lines[j:]).rstrip() + "\n"


def _is_source_file_marker(line: str) -> bool:
    return line.strip().startswith("<!-- papercrown-source-file:")


def _opening_art_spot_fence(line: str) -> re.Match[str] | None:
    match = re.match(r"^(?P<fence>:{3,})\s*\{(?P<attrs>[^}]*)\}\s*$", line)
    if match is None:
        return None
    attrs = match.group("attrs")
    if "art-spot" not in attrs:
        return None
    if "art-left" not in attrs and "art-right" not in attrs:
        return None
    return match


def _demote_repeated_h1s(
    text: str,
    *,
    divider_eyebrow: str | None = None,
    divider_parent_slug: str | None = None,
    section_art: dict[str, str] | None = None,
) -> str:
    """Keep the first ATX H1 and turn later H1s into major dividers.

    Exported embed catalogs can arrive as one already-expanded markdown file
    with many `#` headings. The first is the chapter; later ones are major
    sections inside that chapter, so they get their own full-page divider
    while staying below the chapter in the TOC/outline.
    """
    out: list[str] = []
    in_code = False
    seen_h1 = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        if _headings.is_atx_h1(line):
            if seen_h1:
                title = _headings.heading_title_for_slug(line)
                if title:
                    art_src = None
                    if section_art:
                        art_src = section_art.get(
                            slugify(_headings.plain_heading_title(title))
                        )
                    out.append(
                        _render_major_section_divider(
                            title,
                            eyebrow=divider_eyebrow,
                            parent_slug=divider_parent_slug,
                            art_src=art_src,
                        )
                    )
                else:
                    out.append("#" + line)
            else:
                seen_h1 = True
                out.append(line)
            continue
        out.append(line)
    return "\n".join(out)


def _render_major_section_divider(
    title: str,
    *,
    eyebrow: str | None = None,
    parent_slug: str | None = None,
    art_src: str | None = None,
) -> str:
    """Render a source-file H1 as an in-chapter major-section divider."""
    section = Chapter(
        title=title,
        slug=slugify(title),
        eyebrow=eyebrow or "Major Section",
    )
    return _render_section_divider(
        section,
        with_heading=True,
        level=2,
        eyebrow_link=parent_slug,
        breadcrumb=_breadcrumb_text(eyebrow, title),
        art_src=art_src,
    ).strip()


def _apply_full_page_sections(
    text: str,
    sections: list[str],
    *,
    divider_eyebrow: str | None = None,
    divider_parent_slug: str | None = None,
) -> str:
    """Turn opted-in headings into full-page section dividers."""
    wanted = {slugify(s) for s in sections if s and s.strip()}
    if not wanted:
        return text

    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code or not line.startswith("#"):
            out.append(line)
            continue

        if ".section-divider-title" in line:
            out.append(line)
            continue

        title = _headings.heading_title_for_slug(line)
        if title and slugify(title) in wanted:
            out.append(
                _render_section_divider(
                    Chapter(
                        title=title,
                        slug=slugify(title),
                        eyebrow=divider_eyebrow or "Section",
                    ),
                    with_heading=True,
                    level=_headings.heading_level(line) or 2,
                    eyebrow_link=divider_parent_slug,
                    breadcrumb=_breadcrumb_text(divider_eyebrow, title),
                ).strip()
            )
        else:
            out.append(line)
    return "\n".join(out)


def _normalize_source_reference_size_line(text: str) -> str:
    """Turn a source-reference's opening `(Medium)`-style line into a heading."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i < len(lines) and _headings.is_atx_h1(lines[i]):
        i += 1
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines):
        return text
    match = re.match(r"^\((?P<size>[^)]+)\)\s*$", lines[i].strip())
    if not match:
        return text
    size = _normalize_size_label(match.group("size"))
    lines[i] = f"## {size}"
    return "\n".join(lines)


def _normalize_size_label(label: str) -> str:
    return re.sub(r"\bMed\b", "Medium", label.strip())


def _replace_auto_frame_tables(text: str) -> str:
    """Replace frame table markers with rows derived from family/variant headings.

    The Frames chapter is assembled from family sections. Keeping the summary
    table derived from those headings means a variant's family follows the
    content structure instead of a hand-maintained row list.
    """
    if FRAME_TABLE_MARKER not in text:
        return text
    table = _render_auto_frame_table(text)
    return text.replace(FRAME_TABLE_MARKER, table)


def _render_auto_frame_table(text: str) -> str:
    rows: list[tuple[str, str]] = []
    current_family: str | None = None
    in_code = False

    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue

        level = _headings.heading_level(line)
        title = _headings.heading_title_for_slug(line)
        if level is None or not title:
            continue
        plain_title = _headings.plain_heading_title(title)
        if level == 1:
            if slugify(plain_title) in {"frames", "frames-ancestries"}:
                current_family = None
            else:
                current_family = plain_title
        elif level == 3 and current_family:
            rows.append((plain_title, current_family))

    lines = [
        ":::: {.frame-summary-table}",
        "",
        "| Variant | Frame Family |",
        "|---|---|",
    ]
    for variant, family in rows:
        lines.append(
            "| "
            f"[{_frame_variant_link_text(variant)}](#{slugify(variant)})"
            " | "
            f"[{_headings.markdown_link_text(family)}](#{slugify(family)})"
            " |"
        )
    lines.extend(["", "::::"])
    return "\n".join(lines)


def _frame_variant_link_text(title: str) -> str:
    match = re.match(r"^(?P<name>.+?)\s+\((?P<source>[^)]*)\)$", title)
    if not match:
        return _headings.markdown_link_text(title)
    name = _headings.markdown_link_text(match.group("name"))
    source = _headings.markdown_link_text(match.group("source"))
    return f"{name} *({source})*"


def _demote_headings(text: str, *, by: int) -> str:
    """Demote EVERY ATX heading by `by` levels (h1->h2, h2->h3, ...).

    Caps at h6 (Pandoc's max). Skips fenced code blocks. Used when nesting
    a chapter under a wrapper in the combined book so it sits below the
    wrapper's h1 in the TOC and PDF outline.
    """
    if by <= 0:
        return text
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code or not line.startswith("#"):
            out.append(line)
            continue
        # Count leading hashes (must be 1-6, followed by space or EOL).
        i = 0
        while i < len(line) and line[i] == "#":
            i += 1
        if i == 0 or i > 6 or (i < len(line) and line[i] not in (" ", "\t")):
            out.append(line)
            continue
        new_level = min(6, i + by)
        out.append("#" * new_level + line[i:])
    return "\n".join(out)
