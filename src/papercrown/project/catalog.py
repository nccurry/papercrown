"""Catalog parsing and format auto-detection.

A catalog is an ordered list file in one of three observed formats:

  * bullet-links     `- [[Note]]` lists, optionally grouped by `# Heading`
  * embed-compendium `![[Note]]` blocks, optionally grouped by `# Heading`,
                     possibly with prose between
  * annotated-embeds embeds with callouts/blockquotes between

The format is auto-detected from the file's contents. The parser produces
ordered `CatalogEntry` items, each carrying a structured `WikilinkTarget`
(preserving aliases and path-qualified targets) so cross-vault resolution
through `VaultIndex` is lossless.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from papercrown.project.vaults import WikilinkTarget

CatalogFormat = Literal[
    "bullet-links",
    "embed-compendium",
    "annotated-embeds",
    "mixed",
    "empty",
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class CatalogGroup:
    """A `# Heading` group in a catalog. `name=""` for ungrouped entries."""

    name: str
    entries: list[CatalogEntry] = field(default_factory=list)


@dataclass
class CatalogEntry:
    """One referenced item in a catalog (link or embed)."""

    target: WikilinkTarget
    is_embed: bool  # True for `![[X]]`, False for `- [[X]]`
    group_name: str = ""  # the enclosing # heading, if any


@dataclass
class ParsedCatalog:
    """A parsed catalog with detected format, grouped entries, and intro text."""

    format: CatalogFormat
    groups: list[CatalogGroup]
    intro_text: str = ""  # content before the first heading or first entry

    @property
    def entries(self) -> list[CatalogEntry]:
        """Return all entries flattened in source order."""
        out: list[CatalogEntry] = []
        for g in self.groups:
            out.extend(g.entries)
        return out


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------


# Matches catalog entries written as Markdown bullets containing wikilinks.
_BULLET_LINK_RE = re.compile(r"^\s*[-*]\s*\[\[([^\]]+)\]\]\s*$")
# Matches catalog entries written as standalone Obsidian embeds.
_EMBED_RE = re.compile(r"^\s*!\[\[([^\]]+)\]\]\s*$")
# Matches headings that group catalog entries.
_HEADING_RE = re.compile(r"^(#+)\s+(.+?)\s*$")


def detect_format(text: str) -> CatalogFormat:
    """Detect a catalog file's format by counting line types.

    Heuristic:
      - 'empty' if there are no entries at all
      - 'bullet-links' if bullet-links dominate
      - 'embed-compendium' if embeds dominate and there are few non-trivial
        prose lines between them
      - 'annotated-embeds' if embeds present alongside notable prose/callouts
        between them
      - 'mixed' if both formats are roughly balanced
    """
    if not text or not text.strip():
        return "empty"

    bullet_count = 0
    embed_count = 0
    callout_lines = 0
    blockquote_lines = 0
    body_text_lines = 0

    in_code = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped:
            continue
        if _BULLET_LINK_RE.match(raw_line):
            bullet_count += 1
            continue
        if _EMBED_RE.match(raw_line):
            embed_count += 1
            continue
        # blockquote (callout if it starts with [!)
        if stripped.startswith(">"):
            after = stripped[1:].strip()
            if after.startswith("[!"):
                callout_lines += 1
            else:
                blockquote_lines += 1
            continue
        # Headings, separators, frontmatter markers don't count
        if _HEADING_RE.match(raw_line) or stripped == "---":
            continue
        body_text_lines += 1

    total_entries = bullet_count + embed_count
    if total_entries == 0:
        return "empty"

    if bullet_count > 0 and embed_count == 0:
        return "bullet-links"
    if embed_count > 0 and bullet_count == 0:
        # Look for inter-entry annotation
        if callout_lines > 0 or blockquote_lines >= 2:
            return "annotated-embeds"
        return "embed-compendium"
    # Both present
    if max(bullet_count, embed_count) >= 2 * min(bullet_count, embed_count):
        return "bullet-links" if bullet_count > embed_count else "embed-compendium"
    return "mixed"


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_catalog(text: str) -> ParsedCatalog:
    """Parse a catalog file's text into a structured ParsedCatalog."""
    fmt = detect_format(text)

    groups: list[CatalogGroup] = []
    current = CatalogGroup(name="")
    groups.append(current)

    intro_lines: list[str] = []
    saw_heading = False
    saw_entry = False
    in_code = False

    for raw_line in text.splitlines():
        if raw_line.strip().startswith("```") or raw_line.strip().startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue

        # Top-level # headings open a new group (only count level-1 headings,
        # leave deeper ones inside the group's free text)
        h = _HEADING_RE.match(raw_line)
        if h and len(h.group(1)) == 1:
            heading_name = h.group(2).strip()
            saw_heading = True
            current = CatalogGroup(name=heading_name)
            groups.append(current)
            continue

        bm = _BULLET_LINK_RE.match(raw_line)
        if bm:
            target = WikilinkTarget.parse(bm.group(1))
            current.entries.append(
                CatalogEntry(target=target, is_embed=False, group_name=current.name)
            )
            saw_entry = True
            continue

        em = _EMBED_RE.match(raw_line)
        if em:
            target = WikilinkTarget.parse(em.group(1))
            current.entries.append(
                CatalogEntry(target=target, is_embed=True, group_name=current.name)
            )
            saw_entry = True
            continue

        # Pre-entry, pre-heading text contributes to intro
        if not saw_heading and not saw_entry:
            intro_lines.append(raw_line)

    # Drop the leading empty-name group if it has no entries
    if groups and groups[0].name == "" and not groups[0].entries:
        groups.pop(0)

    intro = "\n".join(intro_lines).strip()
    return ParsedCatalog(format=fmt, groups=groups, intro_text=intro)


def parse_catalog_file(path: Path) -> ParsedCatalog:
    """Read and parse a catalog markdown file from disk."""
    text = path.read_text(encoding="utf-8")
    return parse_catalog(text)
