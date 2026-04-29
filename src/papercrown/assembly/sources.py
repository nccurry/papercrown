"""Source-note reading and normalization helpers for markdown assembly."""

from __future__ import annotations

import re
from pathlib import Path

from papercrown.assembly.headings import (
    heading_level,
    heading_title_for_slug,
    is_atx_h1,
    plain_heading_title,
)
from papercrown.project.vaults import VaultIndex, WikilinkTarget

# Matches a line containing only an Obsidian embed and optional indentation.
_OBSIDIAN_EMBED_LINE_RE = re.compile(r"^(?P<indent>\s*)!\[\[(?P<target>[^\]]+)\]\]\s*$")


def first_heading_text(text: str) -> str | None:
    """Return the first ATX heading title in a markdown block."""
    for line in text.splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*(?:#+\s*)?$", line)
        if match is not None:
            return plain_heading_title(match.group(1))
    return None


def starts_with_h1(text: str) -> bool:
    """Return True when the first nonblank line is an ATX H1."""
    for line in text.splitlines():
        if line.strip() == "":
            continue
        return is_atx_h1(line)
    return False


def starts_with_heading_title(text: str, title: str) -> bool:
    """Return True if the first nonblank line is any ATX heading with title."""
    for line in text.splitlines():
        if line.strip() == "":
            continue
        heading = heading_title_for_slug(line)
        if heading is None:
            return False
        return heading_matches_source_title(heading, title)
    return False


def heading_matches_source_title(heading: str, title: str) -> bool:
    """Return whether a source heading already represents the requested title."""
    wanted = plain_heading_title(title).lower()
    if plain_heading_title(heading).lower() == wanted:
        return True

    source_link = re.fullmatch(
        r"(?P<title>.+?)\s+\(\[[^\]]+\]\([^)]+\)\)",
        heading,
    )
    if source_link is None:
        return False
    return plain_heading_title(source_link.group("title")).lower() == wanted


def read_via_export(
    src: Path,
    export_map: dict[Path, Path] | None,
    *,
    vault_index: VaultIndex | None = None,
) -> str:
    """Read source file content, preferring an exported copy if available."""
    raw: str | None = None
    if export_map:
        mapped = export_map.get(src.resolve())
        if mapped is not None and mapped.is_file():
            exported = mapped.read_text(encoding="utf-8")
            if vault_index is not None:
                raw = src.read_text(encoding="utf-8")
                if should_expand_obsidian_embeds(raw, exported, src, vault_index):
                    return expand_obsidian_embeds(raw, src, vault_index=vault_index)
            return exported
    raw = src.read_text(encoding="utf-8")
    if vault_index is not None and contains_obsidian_embed(raw):
        return expand_obsidian_embeds(raw, src, vault_index=vault_index)
    return raw


def contains_obsidian_embed(text: str) -> bool:
    """Return whether a markdown block has whole-line Obsidian embeds."""
    return any(_OBSIDIAN_EMBED_LINE_RE.match(line) for line in text.splitlines())


def should_expand_obsidian_embeds(
    raw: str,
    exported: str,
    src: Path,
    vault_index: VaultIndex,
) -> bool:
    """Return true when an obsidian-export result dropped embedded-note bodies."""
    targets = obsidian_embed_targets(raw)
    if not targets:
        return False
    if "[[" in exported and "]]" in exported:
        return True
    for target in targets:
        embedded = resolve_embed_path(src, target, vault_index)
        if embedded is None:
            continue
        marker = first_meaningful_line(embedded.read_text(encoding="utf-8"))
        if marker and marker not in exported:
            return True
    return False


def obsidian_embed_targets(text: str) -> list[WikilinkTarget]:
    """Return whole-note Obsidian embed targets found in markdown."""
    targets: list[WikilinkTarget] = []
    for line in text.splitlines():
        match = _OBSIDIAN_EMBED_LINE_RE.match(line)
        if match:
            targets.append(WikilinkTarget.parse(match.group("target")))
    return targets


def expand_obsidian_embeds(
    text: str,
    src: Path,
    *,
    vault_index: VaultIndex,
    depth: int = 0,
) -> str:
    """Inline simple whole-note Obsidian embeds from the source vault."""
    if depth > 5:
        return text

    out: list[str] = []
    for line in text.splitlines():
        match = _OBSIDIAN_EMBED_LINE_RE.match(line)
        if not match:
            out.append(line)
            continue

        target = WikilinkTarget.parse(match.group("target"))
        embedded = resolve_embed_path(src, target, vault_index)
        if embedded is None:
            out.append(line)
            continue

        body = embedded.read_text(encoding="utf-8")
        body = strip_frontmatter(body).strip()
        body = expand_obsidian_embeds(
            body,
            embedded,
            vault_index=vault_index,
            depth=depth + 1,
        ).strip()

        title = target.display_text or embedded.stem
        if embedded_body_needs_wrapper_heading(body, title):
            out.extend(["", f"## {title}", ""])
        else:
            out.append("")
        if body:
            out.append(body)
            out.append("")
    return "\n".join(out)


def embedded_body_needs_wrapper_heading(body: str, title: str) -> bool:
    """Return whether an expanded embed needs a synthetic title heading."""
    first_heading = first_heading_text(body)
    if first_heading is None:
        return True
    return not heading_matches_source_title(first_heading, title)


def resolve_embed_path(
    src: Path,
    target: WikilinkTarget,
    vault_index: VaultIndex,
) -> Path | None:
    """Resolve an embed target in the vault that owns ``src`` when possible."""
    return vault_index.resolve(target, prefer_vault=source_vault_name(src, vault_index))


def source_vault_name(src: Path, vault_index: VaultIndex) -> str | None:
    """Return the vault name containing ``src``, if it can be found."""
    source = src.resolve()
    for vault in vault_index.vaults:
        try:
            source.relative_to(vault.root)
        except ValueError:
            continue
        return vault.name
    return None


def first_meaningful_line(text: str) -> str | None:
    """Return the first nonblank non-frontmatter line in markdown."""
    body = strip_frontmatter(text)
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped == "---":
            continue
        return stripped
    return None


def strip_frontmatter(text: str) -> str:
    """Drop a YAML frontmatter block at the top of a markdown file."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
        end = text.find("\n---", 4)
        if end != -1 and (end + 4 == len(text) or text[end + 4] in "\r\n"):
            return text[end + 4 :]
    return text


def normalize_heading_spacing(text: str) -> str:
    """Ensure ATX headings are separated from preceding body text."""
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if not in_code and out and out[-1].strip() and heading_level(line) is not None:
            out.append("")
        out.append(line)
    return "\n".join(out)


def strip_trailing_related_section(text: str) -> str:
    """Remove a final ``Related`` backlink block from an inline source."""
    lines = text.splitlines()
    end = len(lines)
    while end > 0 and lines[end - 1].strip() == "":
        end -= 1
    i = end - 1
    while i >= 0:
        stripped = lines[i].strip()
        if stripped == "" or stripped.startswith("- ") or stripped.startswith("* "):
            i -= 1
            continue
        break
    if i < 0 or lines[i].strip().lower() != "**related**":
        return text
    j = i - 1
    while j >= 0 and lines[j].strip() == "":
        j -= 1
    if j < 0 or lines[j].strip() != "---":
        return text
    return "\n".join(lines[:j]).rstrip()


def demote_h1s(text: str) -> str:
    """Add one ``#`` to every top-level heading, skipping code blocks."""
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        if line.startswith("#"):
            out.append("#" + line)
        else:
            out.append(line)
    return "\n".join(out)
