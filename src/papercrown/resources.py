"""Filesystem locations for Paper Crown package resources."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR: Path = Path(__file__).parent.resolve()
RESOURCE_DIR: Path = PACKAGE_DIR / "resources"
FILTERS_DIR: Path = RESOURCE_DIR / "filters"
TEMPLATES_DIR: Path = RESOURCE_DIR / "templates"
STYLES_DIR: Path = RESOURCE_DIR / "styles"
CORE_STYLES_DIR: Path = STYLES_DIR / "core"
THEMES_DIR: Path = RESOURCE_DIR / "themes"
ASSETS_DIR: Path = RESOURCE_DIR / "assets"
FONTS_DIR: Path = ASSETS_DIR / "fonts"
TEXTURES_DIR: Path = ASSETS_DIR / "textures"

CORE_CSS_FILES: list[Path] = [
    CORE_STYLES_DIR / "00-tokens.css",
    CORE_STYLES_DIR / "10-paged-media.css",
    CORE_STYLES_DIR / "20-document.css",
    CORE_STYLES_DIR / "30-reference-elements.css",
    CORE_STYLES_DIR / "40-art.css",
    CORE_STYLES_DIR / "50-ttrpg-components.css",
    CORE_STYLES_DIR / "60-book-structure.css",
    CORE_STYLES_DIR / "70-generated-matter.css",
    CORE_STYLES_DIR / "80-web-and-print.css",
]
TEMPLATE_FILE: Path = TEMPLATES_DIR / "book.html"
LUA_FILTERS: list[Path] = [
    FILTERS_DIR / "internal-links.lua",
    FILTERS_DIR / "strip-links.lua",
    FILTERS_DIR / "callouts.lua",
    FILTERS_DIR / "rules-widgets.lua",
    FILTERS_DIR / "stat-blocks.lua",
    FILTERS_DIR / "highlight-level-headings.lua",
    FILTERS_DIR / "minor-sections.lua",
]
