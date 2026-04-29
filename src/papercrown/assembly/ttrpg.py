"""Typed TTRPG block registry, generated matter, and cross-reference support."""

from __future__ import annotations

import html
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

from papercrown.project.manifest import slugify
from papercrown.project.recipe import MatterSpec, Recipe, TtrpgArtAssetSpec
from papercrown.system.diagnostics import Diagnostic, DiagnosticSeverity

# Custom div block types that Paper Crown upgrades into TTRPG components.
SUPPORTED_BLOCK_TYPES = {
    "npc",
    "background",
    "frame",
    "item",
    "power",
    "spell",
    "rule",
    "clue",
    "clock",
    "location",
    "faction",
    "encounter",
    "readaloud",
    "sidebar",
    "handout",
}

# Matches Pandoc-style colon fences and captures their attribute text.
_DIV_FENCE_RE = re.compile(r"^(?P<fence>:{3,})\s*(?P<attrs>.*?)\s*$")
# Matches ATX headings used while building anchors and generated matter.
_HEADING_RE = re.compile(
    r"^#{1,6}\s+(?P<title>.+?)(?:\s+\{[^}]*\})?\s*$",
)
# Matches inline typed references such as @npc.guard.
_REF_RE = re.compile(
    r"(?<![\w/])@(?P<type>[a-z][A-Za-z0-9_-]*)\.(?P<id>[A-Za-z0-9_-]+)"
)
# Matches assembly source markers used to attach source-file context.
_SOURCE_FILE_MARKER_RE = re.compile(
    r"^<!--\s*papercrown-source-file:\s*(?P<path>.+?)\s*-->$"
)


@dataclass(frozen=True)
class TtrpgObject:
    """One typed game object found in assembled markdown."""

    type: str
    id: str
    anchor: str
    title: str
    tags: list[str] = field(default_factory=list)
    chapter_slug: str | None = None
    source_file: Path | None = None
    line: int | None = None


@dataclass(frozen=True)
class ObjectRegistry:
    """Lookup table for typed TTRPG objects."""

    objects: list[TtrpgObject]

    def by_key(self) -> dict[tuple[str, str], TtrpgObject]:
        """Return object lookup by ``(type, id)``."""
        return {(obj.type, obj.id): obj for obj in self.objects}

    def by_type(self) -> dict[str, list[TtrpgObject]]:
        """Return objects grouped by type."""
        grouped: dict[str, list[TtrpgObject]] = {}
        for obj in self.objects:
            grouped.setdefault(obj.type, []).append(obj)
        for values in grouped.values():
            values.sort(key=lambda obj: (obj.title.lower(), obj.id))
        return grouped


@dataclass(frozen=True)
class PreparedMarkdown:
    """Markdown plus registry diagnostics from the TTRPG preparation pass."""

    markdown: str
    registry: ObjectRegistry
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class _DivAttrs:
    classes: list[str] = field(default_factory=list)
    identifier: str | None = None
    attrs: dict[str, str] = field(default_factory=dict)


def prepare_book_markdown(
    markdown: str,
    recipe: Recipe,
    *,
    include_generated_matter: bool,
) -> PreparedMarkdown:
    """Normalize typed blocks, resolve refs, and add generated matter."""
    normalized, registry, diagnostics = _normalize_ttrpg_blocks(markdown)
    normalized, art_diagnostics = _inject_ttrpg_art(normalized, recipe, registry)
    diagnostics.extend(art_diagnostics)
    normalized, ref_diagnostics = _resolve_ttrpg_refs(normalized, registry)
    diagnostics.extend(ref_diagnostics)
    if include_generated_matter:
        normalized = _with_generated_matter(normalized, recipe, registry)
    return PreparedMarkdown(
        markdown=normalized,
        registry=registry,
        diagnostics=diagnostics,
    )


def add_generated_matter(
    markdown: str,
    recipe: Recipe,
    registry: ObjectRegistry,
) -> str:
    """Wrap prepared book markdown with configured front and back matter."""
    return _with_generated_matter(markdown, recipe, registry)


def lint_ttrpg_markdown(markdown: str) -> list[Diagnostic]:
    """Return typed-block and cross-reference diagnostics for markdown."""
    normalized, registry, diagnostics = _normalize_ttrpg_blocks(markdown)
    _, ref_diagnostics = _resolve_ttrpg_refs(normalized, registry)
    return [*diagnostics, *ref_diagnostics]


def _normalize_ttrpg_blocks(
    markdown: str,
) -> tuple[str, ObjectRegistry, list[Diagnostic]]:
    lines = markdown.splitlines()
    out: list[str] = []
    objects: list[TtrpgObject] = []
    diagnostics: list[Diagnostic] = []
    seen: dict[tuple[str, str], int] = {}
    current_chapter_slug: str | None = None
    current_source_file: Path | None = None
    in_code = False

    for index, line in enumerate(lines):
        line_no = index + 1
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue

        source_match = _SOURCE_FILE_MARKER_RE.match(line.strip())
        if source_match is not None:
            current_source_file = Path(source_match.group("path"))
            continue

        div_match = _DIV_FENCE_RE.match(line)
        if div_match is None:
            out.append(line)
            continue

        attrs_text = div_match.group("attrs").strip()
        if not attrs_text:
            out.append(line)
            continue

        attrs = _parse_div_attrs(attrs_text)
        if "chapter-wrap" in attrs.classes and attrs.identifier:
            current_chapter_slug = attrs.identifier.removeprefix("ch-")

        block_type = _typed_block_class(attrs.classes)
        if block_type is None:
            out.append(line)
            continue

        title = (
            attrs.attrs.get("title")
            or attrs.attrs.get("data-title")
            or _first_heading_title(lines, start=index + 1)
        )
        block_id = attrs.identifier or attrs.attrs.get("id")
        if block_id is None and title:
            block_id = slugify(title)
        if block_id is None:
            diagnostics.append(
                Diagnostic(
                    code="ttrpg-block.id-missing",
                    severity=DiagnosticSeverity.ERROR,
                    message=f"{block_type} block is missing an id or heading title",
                    line=line_no,
                )
            )
            out.append(line)
            continue

        block_id = slugify(block_id)
        title = title or _title_from_id(block_id)
        anchor = f"{block_type}-{block_id}"
        duplicate_key = (block_type, block_id)
        previous = seen.get(duplicate_key)
        if previous is not None:
            diagnostics.append(
                Diagnostic(
                    code="ttrpg-block.duplicate-id",
                    severity=DiagnosticSeverity.ERROR,
                    message=f"duplicate @{block_type}.{block_id} block id",
                    line=line_no,
                    hint=f"first declared on assembled markdown line {previous}",
                )
            )
        else:
            seen[duplicate_key] = line_no

        tags = _tags(attrs.attrs.get("tags") or attrs.attrs.get("data-tags"))
        objects.append(
            TtrpgObject(
                type=block_type,
                id=block_id,
                anchor=anchor,
                title=title,
                tags=tags,
                chapter_slug=current_chapter_slug,
                source_file=current_source_file,
                line=line_no,
            )
        )
        out.append(
            _render_typed_opening(
                div_match.group("fence"),
                attrs,
                block_type,
                block_id,
                anchor,
                title,
                tags,
                current_source_file,
                line_no,
            )
        )

    return "\n".join(out), ObjectRegistry(objects), diagnostics


def _parse_div_attrs(raw: str) -> _DivAttrs:
    text = raw.strip()
    if text.startswith("{") and text.endswith("}"):
        text = text[1:-1].strip()
    attrs = _DivAttrs()
    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = text.split()
    for token in tokens:
        if token.startswith(".") and len(token) > 1:
            attrs.classes.append(token[1:])
        elif token.startswith("#") and len(token) > 1:
            attrs.identifier = slugify(token[1:])
        elif "=" in token:
            key, value = token.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                attrs.attrs[key] = value
        elif token:
            attrs.classes.append(token.lstrip("."))
    return attrs


def _typed_block_class(classes: list[str]) -> str | None:
    for class_name in classes:
        normalized = class_name.removeprefix("pc-ttrpg-").removeprefix("ttrpg-")
        if normalized in SUPPORTED_BLOCK_TYPES:
            return normalized
    return None


def _first_heading_title(lines: list[str], *, start: int) -> str | None:
    depth = 1
    in_code = False
    for line in lines[start:]:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        div_match = _DIV_FENCE_RE.match(line)
        if div_match is not None:
            if div_match.group("attrs").strip():
                depth += 1
            else:
                depth -= 1
                if depth <= 0:
                    return None
        heading_match = _HEADING_RE.match(line)
        if heading_match is not None:
            return _plain_title(heading_match.group("title"))
    return None


def _plain_title(raw: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw)
    text = re.sub(r"[`*_]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _title_from_id(block_id: str) -> str:
    return " ".join(part.capitalize() for part in block_id.replace("_", "-").split("-"))


def _tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    tags: list[str] = []
    for item in re.split(r"[, ]+", raw):
        tag = slugify(item)
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _render_typed_opening(
    fence: str,
    attrs: _DivAttrs,
    block_type: str,
    block_id: str,
    anchor: str,
    title: str,
    tags: list[str],
    source_file: Path | None,
    line_no: int,
) -> str:
    typed_classes = {
        block_type,
        f"ttrpg-{block_type}",
        f"pc-ttrpg-{block_type}",
        "ttrpg-block",
        "pc-ttrpg-block",
        "pc-component",
    }
    custom_classes = [name for name in attrs.classes if name not in typed_classes]
    classes = list(
        dict.fromkeys(
            [
                "pc-component",
                "pc-ttrpg-block",
                f"pc-ttrpg-{block_type}",
                *custom_classes,
            ]
        )
    )
    rendered_attrs = {
        **attrs.attrs,
        "data-ttrpg-type": block_type,
        "data-ttrpg-id": block_id,
        "data-ttrpg-title": title,
        "data-source-line": str(line_no),
    }
    if tags:
        rendered_attrs["data-tags"] = ",".join(tags)
    if source_file is not None:
        rendered_attrs["data-source-file"] = source_file.as_posix()
    class_text = " ".join(f".{class_name}" for class_name in classes)
    attr_text = " ".join(
        f'{key}="{html.escape(value, quote=True)}"'
        for key, value in sorted(rendered_attrs.items())
        if key != "id"
    )
    suffix = f" {attr_text}" if attr_text else ""
    return f"{fence} {{#{anchor} {class_text}{suffix}}}"


def _resolve_ttrpg_refs(
    markdown: str,
    registry: ObjectRegistry,
) -> tuple[str, list[Diagnostic]]:
    lookup = registry.by_key()
    diagnostics: list[Diagnostic] = []
    out: list[str] = []
    in_code = False
    for line_no, line in enumerate(markdown.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        current_line = line_no

        def replace(match: re.Match[str], *, ref_line: int = current_line) -> str:
            obj_type = match.group("type").lower()
            obj_id = slugify(match.group("id"))
            obj = lookup.get((obj_type, obj_id))
            if obj is None:
                diagnostics.append(
                    Diagnostic(
                        code="ttrpg-ref.unresolved",
                        severity=DiagnosticSeverity.ERROR,
                        message=f"unresolved typed reference @{obj_type}.{obj_id}",
                        line=ref_line,
                    )
                )
                return match.group(0)
            label = html.escape(obj.title)
            href = html.escape(f"#{obj.anchor}", quote=True)
            return (
                f'<a class="pc-ref pc-ref-internal pc-ttrpg-ref" href="{href}" '
                f'data-ttrpg-ref="{obj.type}.{obj.id}">{label}</a>'
            )

        out.append(_REF_RE.sub(replace, line))
    return "\n".join(out), diagnostics


def _inject_ttrpg_art(
    markdown: str,
    recipe: Recipe,
    registry: ObjectRegistry,
) -> tuple[str, list[Diagnostic]]:
    """Insert configured art blocks inside matching typed TTRPG blocks."""
    spec = getattr(recipe, "ttrpg_art", None)
    if spec is None or not spec.enabled or not spec.assets:
        return markdown, []

    diagnostics: list[Diagnostic] = []
    lookup = {(asset.type, asset.id): asset for asset in spec.assets}
    available = {(obj.type, obj.id) for obj in registry.objects}
    resolved_art: dict[tuple[str, str], Path] = {}

    for asset in spec.assets:
        key = (asset.type, asset.id)
        if key not in available:
            diagnostics.append(
                Diagnostic(
                    code="ttrpg-art.unmatched",
                    severity=DiagnosticSeverity.WARNING,
                    message=(
                        f"configured art for @{asset.type}.{asset.id} "
                        "did not match any typed block"
                    ),
                    path=recipe.recipe_path,
                )
            )
            continue
        art_path = (recipe.art_dir / asset.art).resolve()
        if not art_path.is_file():
            diagnostics.append(
                Diagnostic(
                    code="ttrpg-art.missing",
                    severity=DiagnosticSeverity.ERROR,
                    message=f"configured art for @{asset.type}.{asset.id} is missing",
                    path=art_path,
                )
            )
            continue
        resolved_art[key] = art_path

    if not resolved_art:
        return markdown, diagnostics

    out: list[str] = []
    for line in markdown.splitlines():
        out.append(line)
        key = _ttrpg_block_key_from_opening(line)
        if key is None:
            continue
        asset = lookup.get(key)
        art_path = resolved_art.get(key)
        if asset is None or art_path is None:
            continue
        out.extend(["", _render_ttrpg_art_block(asset, art_path), ""])
    return "\n".join(out), diagnostics


def _ttrpg_block_key_from_opening(line: str) -> tuple[str, str] | None:
    """Return the typed-block key encoded in a normalized opening fence."""
    if "pc-ttrpg-block" not in line:
        return None
    type_match = re.search(r'data-ttrpg-type="([^"]+)"', line)
    id_match = re.search(r'data-ttrpg-id="([^"]+)"', line)
    if type_match is None or id_match is None:
        return None
    return type_match.group(1), id_match.group(1)


def _render_ttrpg_art_block(asset: TtrpgArtAssetSpec, art_path: Path) -> str:
    """Render one configured typed-block art image as an in-flow float."""
    placement_class = f".pc-ttrpg-art-{asset.placement}"
    type_class = f".pc-ttrpg-{asset.type}-art"
    target_attr = f'data-ttrpg-art-for="{asset.type}.{asset.id}"'
    return (
        "::: {.pc-ttrpg-header-art .pc-ttrpg-inline-art "
        f"{placement_class} {type_class} {target_attr}"
        "}\n"
        f"![](<{art_path.as_posix()}>){{.pc-ttrpg-header-art-img}}\n"
        ":::"
    )


def _with_generated_matter(
    markdown: str,
    recipe: Recipe,
    registry: ObjectRegistry,
) -> str:
    front = _render_matter_pages(
        recipe.front_matter,
        position="front",
        recipe=recipe,
        registry=registry,
    )
    back = _render_matter_pages(
        recipe.back_matter,
        position="back",
        recipe=recipe,
        registry=registry,
    )
    parts = []
    if front:
        parts.append(front)
    parts.append(markdown)
    if back:
        parts.append(back)
    return "\n\n".join(parts)


def _render_matter_pages(
    matter: list[MatterSpec],
    *,
    position: str,
    recipe: Recipe,
    registry: ObjectRegistry,
) -> str:
    pages = [
        _render_matter_page(item, position=position, recipe=recipe, registry=registry)
        for item in matter
    ]
    return "\n\n".join(page for page in pages if page.strip())


def _render_matter_page(
    item: MatterSpec,
    *,
    position: str,
    recipe: Recipe,
    registry: ObjectRegistry,
) -> str:
    title = item.title or _default_matter_title(item.type)
    body = _matter_body(item.type, recipe=recipe, registry=registry)
    matter_id = f"matter-{slugify(title)}"
    classes = f".generated-matter .{position}-matter .matter-{item.type}"
    return f":::: {{#{matter_id} {classes}}}\n\n# {title}\n\n{body.strip()}\n\n::::"


def _matter_body(kind: str, *, recipe: Recipe, registry: ObjectRegistry) -> str:
    metadata = recipe.metadata
    if kind == "title-page":
        lines = [f"## {recipe.title}"]
        if recipe.subtitle:
            lines.append(f"*{recipe.subtitle}*")
        if metadata.authors:
            lines.append(f"**By:** {', '.join(metadata.authors)}")
        if metadata.version:
            lines.append(f"**Version:** {metadata.version}")
        if metadata.date:
            lines.append(f"**Date:** {metadata.date}")
        if metadata.publisher:
            lines.append(f"**Publisher:** {metadata.publisher}")
        return "\n\n".join(lines)
    if kind == "credits":
        credit_lines: list[str] = []
        if metadata.authors:
            credit_lines.append(f"**Writing:** {', '.join(metadata.authors)}")
        if metadata.editor:
            credit_lines.append(f"**Editing:** {metadata.editor}")
        for role, names in metadata.credits.items():
            if names:
                credit_lines.append(f"**{role.title()}:** {', '.join(names)}")
        return "\n\n".join(credit_lines) or "_No credits supplied._"
    if kind == "copyright":
        owner = metadata.publisher or ", ".join(metadata.authors) or recipe.title
        year = (metadata.date or "")[:4] if metadata.date else ""
        notice = f"Copyright {year} {owner}".strip()
        return notice + "."
    if kind == "license":
        return metadata.license or "_No license supplied._"
    if kind == "art-credits":
        names = metadata.credits.get("art") or metadata.credits.get("artist") or []
        return ", ".join(names) if names else "_No art credits supplied._"
    if kind == "changelog":
        bits = []
        if metadata.version:
            bits.append(f"**Version:** {metadata.version}")
        if metadata.date:
            bits.append(f"**Date:** {metadata.date}")
        return "\n\n".join(bits) or "_No changelog entries supplied._"
    if kind == "appendix-index":
        return _registry_index(registry)
    return ""


def _registry_index(registry: ObjectRegistry) -> str:
    grouped = registry.by_type()
    if not grouped:
        return "_No typed TTRPG blocks found._"
    sections: list[str] = []
    for object_type in sorted(grouped):
        section_lines = [f"## {_default_index_title(object_type)}"]
        for obj in grouped[object_type]:
            tags = f" ({', '.join(obj.tags)})" if obj.tags else ""
            section_lines.append(f"- [{obj.title}](#{obj.anchor}){tags}")
        sections.append("\n".join(section_lines))
    return "\n\n".join(sections)


def _default_matter_title(kind: str) -> str:
    return {
        "title-page": "Title Page",
        "credits": "Credits",
        "copyright": "Copyright",
        "license": "License",
        "art-credits": "Art Credits",
        "changelog": "Changelog",
        "appendix-index": "Index",
    }.get(kind, _title_from_id(kind))


def _default_index_title(object_type: str) -> str:
    return {
        "npc": "NPCs",
        "background": "Backgrounds",
        "frame": "Frames",
        "item": "Items",
        "power": "Powers",
        "spell": "Spells",
        "rule": "Rules",
        "clue": "Clues",
        "clock": "Clocks",
        "location": "Locations",
        "faction": "Factions",
        "encounter": "Encounters",
        "readaloud": "Readaloud",
        "sidebar": "Sidebars",
        "handout": "Handouts",
    }.get(object_type, _title_from_id(object_type))
