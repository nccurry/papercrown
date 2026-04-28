"""Markdown heading, anchor, and manual-TOC helpers for assembly."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import TypedDict

from .manifest import slugify


class TocNode(TypedDict):
    """A manual table-of-contents node used during markdown assembly."""

    title: str
    ident: str
    children: list[TocNode]


def append_anchor_marker(out: list[str], anchor: str) -> None:
    """Append a hidden anchor heading with block-level spacing."""
    if out and out[-1].strip():
        out.append("")
    out.append(anchor_marker(anchor))
    out.append("")


def anchor_marker(anchor: str) -> str:
    """Return a zero-height Markdown heading destination marker for PDF links."""
    return f"###### [ ](#{anchor}) {{.pdf-anchor #{anchor}}}"


def dedupe_generated_anchor_ids(text: str) -> str:
    """Rename generated hidden anchors when they collide with visible headings."""
    real_ids = {
        ident
        for line in text.splitlines()
        if not is_anchor_marker_line(line)
        for ident in [heading_id(line)]
        if ident
    }
    seen: dict[str, int] = {ident: 1 for ident in real_ids}
    out: list[str] = []
    for line in text.splitlines():
        if not is_anchor_marker_line(line):
            out.append(line)
            continue
        ident = heading_id(line)
        if ident is None:
            out.append(line)
            continue
        if ident in seen:
            deduped = unique_heading_id(ident, seen)
            out.append(line.replace(f"#{ident}", f"#{deduped}"))
        else:
            seen[ident] = 1
            out.append(line)
    return "\n".join(out)


def is_anchor_marker_line(line: str) -> bool:
    """Return whether a line is one of the hidden generated anchor headings."""
    return ".pdf-anchor" in line and heading_id(line) is not None


def is_atx_h1(line: str) -> bool:
    """Return whether a line is an ATX level-one heading."""
    return line.startswith("# ") or line == "#"


def ensure_leading_heading_id(text: str, ident: str) -> str:
    """Attach ``ident`` to the first heading when a divider did not supply it."""
    lines = text.splitlines()
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines) or heading_level(lines[i]) is None:
        return text
    if heading_id(lines[i]):
        return text
    lines[i] = add_heading_id(lines[i], ident)
    return "\n".join(lines)


def heading_title_for_slug(line: str) -> str | None:
    """Return the visible heading text from an ATX heading line."""
    level = heading_level(line)
    if level is None:
        return None
    text = line[level:].strip()
    if text.endswith("#"):
        text = text.rstrip("#").rstrip()
    if text.endswith("}"):
        text = re.sub(r"\s*\{[^}]*\}\s*$", "", text).rstrip()
    return text or None


def heading_level(line: str) -> int | None:
    """Return the ATX heading level, or ``None`` for non-heading lines."""
    i = 0
    while i < len(line) and line[i] == "#":
        i += 1
    if i == 0 or i > 6 or (i < len(line) and line[i] not in (" ", "\t")):
        return None
    return i


def ensure_heading_ids(text: str) -> str:
    """Attach explicit ids to ATX headings that do not already have one."""
    out: list[str] = []
    seen: dict[str, int] = {ident: 1 for ident in explicit_heading_ids(text)}
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

        title = heading_title_for_slug(line)
        if not title:
            out.append(line)
            continue
        explicit = heading_id(line)
        if explicit:
            out.append(line)
            continue

        base = heading_base_id(title)
        ident = unique_heading_id(base, seen)
        out.append(add_heading_id(line, ident))
    return "\n".join(out)


def explicit_heading_ids(text: str) -> set[str]:
    """Return explicit ATX heading ids already present in markdown."""
    ids: set[str] = set()
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code or not line.startswith("#"):
            continue
        ident = heading_id(line)
        if ident:
            ids.add(ident)
    return ids


def render_manual_toc(
    markdown: str,
    *,
    toc_depths: dict[str, int] | None = None,
    max_depth: int | None = None,
) -> str:
    """Render Paper Crown's generated table of contents for a markdown book."""
    entries: list[tuple[int, str, str]] = []
    default_limit = 4 if max_depth is None else max(1, min(4, max_depth))
    current_limit = default_limit
    for level, title, ident in toc_entries(markdown):
        if level == 1:
            chapter_limit = (toc_depths or {}).get(ident, 4)
            current_limit = min(chapter_limit, default_limit)
        if level <= current_limit:
            entries.append((level, title, ident))
    tree: list[TocNode] = []
    stack: list[tuple[int, list[TocNode]]] = [(0, tree)]
    for level, title, ident in entries:
        level = max(1, min(4, level))
        node = TocNode(title=title, ident=ident, children=[])
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack[-1][1].append(node)
        stack.append((level, node["children"]))

    lines: list[str] = [
        ':::: {.toc role="doc-toc"}',
        "# Table of Contents {.toc-title #table-of-contents}",
        "",
    ]

    def emit(nodes: list[TocNode], indent: int) -> None:
        if not nodes:
            return
        for node in nodes:
            title = markdown_link_text(plain_heading_title(node["title"]))
            ident = node["ident"]
            lines.append("  " * indent + f"- [{title}](#{ident})")
            emit(node["children"], indent + 1)

    emit(tree, 0)
    lines.append("")
    lines.append("::::")
    return "\n".join(lines)


def toc_entries(markdown: str) -> Iterator[tuple[int, str, str]]:
    """Yield heading level, title, and id tuples that can appear in a TOC."""
    in_code = False
    for line in markdown.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code or not line.startswith("#"):
            continue
        level = heading_level(line)
        title = heading_title_for_slug(line)
        ident = heading_id(line)
        if level is None or not title or not ident:
            continue
        yield level, title, ident


def heading_id(line: str) -> str | None:
    """Return the explicit id from a Pandoc heading attribute block."""
    match = re.search(r"\{[^}]*#([A-Za-z0-9_-]+)[^}]*\}\s*$", line)
    if not match:
        return None
    return match.group(1)


def heading_base_id(title: str) -> str:
    """Return the canonical generated heading id base for a title."""
    plain = plain_heading_title(title)
    original = re.match(r"^Original\s+-\s+(.+)$", plain)
    if original:
        return "original-" + slugify(original.group(1))
    return slugify(plain)


def add_heading_id(line: str, ident: str) -> str:
    """Attach a Pandoc heading id to an ATX heading line."""
    if line.rstrip().endswith("}"):
        return line.rstrip()[:-1].rstrip() + f" #{ident}}}"
    return line.rstrip() + f" {{#{ident}}}"


def unique_heading_id(base: str, seen: dict[str, int]) -> str:
    """Return a unique id and update ``seen`` with the claim."""
    count = seen.get(base, 0)
    seen[base] = count + 1
    if count == 0:
        return base
    ident = f"{base}-{count}"
    while ident in seen:
        count += 1
        seen[base] = count + 1
        ident = f"{base}-{count}"
    seen[ident] = 1
    return ident


def plain_heading_title(title: str) -> str:
    """Strip markdown decoration from heading text before slugging/linking."""
    text = re.sub(r"`([^`]*)`", r"\1", title)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = text.replace("*", "").replace("_", "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def markdown_link_text(text: str) -> str:
    """Escape text for use inside a markdown link label."""
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def attribute_value(text: str) -> str:
    """Escape text for use in generated HTML attribute values."""
    return (
        text.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
