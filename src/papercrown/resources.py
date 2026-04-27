"""Filesystem locations for Paper Crown package resources."""

from __future__ import annotations

from pathlib import Path

PACKAGE_DIR: Path = Path(__file__).parent.resolve()
RESOURCE_DIR: Path = PACKAGE_DIR / "resources"
FILTERS_DIR: Path = RESOURCE_DIR / "filters"
TEMPLATES_DIR: Path = RESOURCE_DIR / "templates"
STYLES_DIR: Path = RESOURCE_DIR / "styles"
THEMES_DIR: Path = RESOURCE_DIR / "themes"
ASSETS_DIR: Path = RESOURCE_DIR / "assets"
FONTS_DIR: Path = ASSETS_DIR / "fonts"
TEXTURES_DIR: Path = ASSETS_DIR / "textures"

CSS_FILE: Path = STYLES_DIR / "book.css"
TEMPLATE_FILE: Path = TEMPLATES_DIR / "book.html"
LUA_FILTERS: list[Path] = [
    FILTERS_DIR / "internal-links.lua",
    FILTERS_DIR / "strip-links.lua",
    FILTERS_DIR / "callouts.lua",
    FILTERS_DIR / "stat-blocks.lua",
    FILTERS_DIR / "highlight-level-headings.lua",
    FILTERS_DIR / "minor-sections.lua",
]
