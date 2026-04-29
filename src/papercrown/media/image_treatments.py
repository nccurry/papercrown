"""Recipe-driven image treatment CSS."""

from __future__ import annotations

from collections.abc import Mapping

# Named CSS declaration bundles that can be applied to image roles.
IMAGE_TREATMENT_PRESETS: dict[str, tuple[str, ...]] = {
    "raw": (
        "mix-blend-mode: normal",
        "filter: none",
        "opacity: 1",
    ),
    "ink-blend": (
        "mix-blend-mode: multiply",
        "filter: contrast(1.04)",
        "opacity: 1",
    ),
    "print-punch": (
        "mix-blend-mode: normal",
        "filter: contrast(1.04)",
        "opacity: 1",
    ),
    "subtle-punch": (
        "mix-blend-mode: normal",
        "filter: contrast(1.02)",
        "opacity: 1",
    ),
    "strong-punch": (
        "mix-blend-mode: normal",
        "filter: contrast(1.08)",
        "opacity: 1",
    ),
    "soft-print": (
        "mix-blend-mode: multiply",
        "filter: contrast(1.02)",
        "opacity: 0.96",
    ),
}

# CSS selectors controlled by each recipe image-treatment role.
IMAGE_TREATMENT_ROLE_SELECTORS: dict[str, tuple[str, ...]] = {
    "default": ("img",),
    "inline": (
        ".art-wide img",
        ".art-medium img",
        ".art-left img",
        ".art-right img",
        ".art-card img",
        ".art-large img",
        ".art-feature img",
    ),
    "cover": (".cover-art",),
    "cover-back": (".cover-back-art",),
    "chapter": (".chapter-art",),
    "divider": (".section-divider-art",),
    "filler": (".filler-img",),
    "ornament": (
        ".ornament-tailpiece img",
        ".ornament-headpiece img",
        ".ornament-break img",
    ),
    "tailpiece": (".ornament-tailpiece img",),
    "headpiece": (".ornament-headpiece img",),
    "break": (".ornament-break img",),
    "splash": (".splash-img", ".splash-page-art"),
    "splash-inline": (".splash-img",),
    "splash-page": (".splash-page-art",),
    "spot": (".art-spot img", ".class-opening-spot img", ".background-spot img"),
    "diagram": (".art-diagram img", ".diagram img"),
    "screenshot": (".art-screenshot img", ".screenshot img"),
    "map": (".art-map img", ".map img"),
    "logo": (".art-logo img", ".logo img"),
    "icon": (".art-icon img", ".icon img"),
}


def image_treatment_css(treatments: Mapping[str, str]) -> str | None:
    """Return late-bound CSS for configured image treatment roles."""
    if not treatments:
        return None

    blocks: list[str] = []
    for role in _ordered_roles(treatments):
        treatment = treatments[role]
        selectors = IMAGE_TREATMENT_ROLE_SELECTORS[role]
        declarations = IMAGE_TREATMENT_PRESETS[treatment]
        block = (
            ",\n".join(selectors)
            + " {\n"
            + "\n".join(f"  {declaration};" for declaration in declarations)
            + "\n}"
        )
        blocks.append(block)

    return "/* Paper Crown image treatments */\n" + "\n\n".join(blocks) + "\n"


def _ordered_roles(treatments: Mapping[str, str]) -> list[str]:
    roles = list(treatments)
    if "default" not in treatments:
        return roles
    return ["default", *[role for role in roles if role != "default"]]
