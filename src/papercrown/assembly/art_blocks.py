"""Generated markdown blocks for assembly-time art and filler markers."""

from __future__ import annotations

from pathlib import Path

from papercrown.assembly.headings import attribute_value
from papercrown.project.manifest import ChapterFillerSlot, Splash


def alt_text_from_path(path: Path, *, role: str = "Illustration") -> str:
    """Return readable fallback alt text for generated art blocks."""
    label = path.stem.replace("_", " ").replace("-", " ").strip()
    label = " ".join(label.split())
    if label:
        return f"{role}: {label}."
    return f"{role}."


def render_back_cover_splashes(splashes: list[Splash] | None) -> str:
    """Render back-cover splash placements as terminal cover pages."""
    return "\n\n".join(
        block
        for block in (
            render_splash_page(splash)
            for splash in splashes or []
            if splash.target == "back-cover"
        )
        if block
    )


def render_filler_slot(slot: ChapterFillerSlot) -> str:
    """Render one Pandoc fenced div marker for post-layout filler selection."""
    attrs = [
        f'data-slot="{attribute_value(slot.slot)}"',
        f'data-chapter="{attribute_value(slot.chapter_slug)}"',
    ]
    if slot.preferred_asset_id:
        attrs.append(
            f'data-preferred-filler="{attribute_value(slot.preferred_asset_id)}"'
        )
    if slot.section_slug:
        attrs.append(f'data-section="{attribute_value(slot.section_slug)}"')
    if slot.section_title:
        attrs.append(f'data-section-title="{attribute_value(slot.section_title)}"')
    if slot.slot_kind:
        attrs.append(f'data-slot-kind="{attribute_value(slot.slot_kind)}"')
    if slot.context:
        attrs.append(f'data-filler-context="{attribute_value(slot.context)}"')
    return f":::: {{.filler-slot #{slot.id} {' '.join(attrs)}}}\n::::"


def render_splash_block(splash: Splash) -> str:
    """Render an in-flow splash art block."""
    if splash.art_path is None:
        return ""
    alt = alt_text_from_path(splash.art_path, role="Splash illustration")
    placement_class = {
        "corner-left": ".splash-corner-left",
        "corner-right": ".splash-corner-right",
        "bottom-half": ".splash-bottom-half",
    }.get(splash.placement, ".splash-bottom-half")
    return (
        f":::: {{.splash-art {placement_class} #splash-{splash.id}}}\n"
        f"![{alt}](<{splash.art_path.as_posix()}>){{.splash-img}}\n"
        "::::"
    )


def render_splash_page(splash: Splash) -> str:
    """Render a full-page book splash, currently used for the back cover."""
    if splash.art_path is None:
        return ""
    alt = alt_text_from_path(splash.art_path, role="Back-cover illustration")
    placement_class = ".splash-back-cover .cover-back-page"
    return (
        f":::: {{.splash-page {placement_class} #splash-{splash.id}}}\n\n"
        f"![{alt}](<{splash.art_path.as_posix()}>)"
        "{.splash-page-art .cover-back-art}\n\n"
        "::::"
    )


def render_image_block(path: Path, *, classes: str, alt: str | None = None) -> str:
    """Render a markdown image wrapped in a Pandoc fenced div."""
    resolved_alt = alt or alt_text_from_path(path)
    return f":::: {{{classes}}}\n![{resolved_alt}](<{path.as_posix()}>)\n::::"
