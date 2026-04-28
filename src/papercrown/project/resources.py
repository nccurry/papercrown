"""Filesystem locations for Paper Crown package resources."""

from __future__ import annotations

from pathlib import Path

# Installed papercrown package directory.
PACKAGE_DIR: Path = Path(__file__).parent.parent.resolve()
# Bundled runtime resources shipped inside the package.
RESOURCE_DIR: Path = PACKAGE_DIR / "resources"
# Directory containing Pandoc Lua filters.
FILTERS_DIR: Path = RESOURCE_DIR / "filters"
# Directory containing Pandoc HTML templates.
TEMPLATES_DIR: Path = RESOURCE_DIR / "templates"
# Directory containing shared and theme stylesheet resources.
STYLES_DIR: Path = RESOURCE_DIR / "styles"
# Ordered core stylesheet modules applied before theme CSS.
CORE_STYLES_DIR: Path = STYLES_DIR / "core"
# Bundled theme-pack directory.
THEMES_DIR: Path = RESOURCE_DIR / "themes"
# Bundled static assets such as fonts and textures.
ASSETS_DIR: Path = RESOURCE_DIR / "assets"
# Bundled font files referenced by core and theme CSS.
FONTS_DIR: Path = ASSETS_DIR / "fonts"
# Bundled paper and surface texture images.
TEXTURES_DIR: Path = ASSETS_DIR / "textures"

# Core CSS modules in cascade order.
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
# Default Pandoc HTML template.
TEMPLATE_FILE: Path = TEMPLATES_DIR / "book.html"
# Lua filters applied to Pandoc in pipeline order.
LUA_FILTERS: list[Path] = [
    FILTERS_DIR / "internal-links.lua",
    FILTERS_DIR / "strip-links.lua",
    FILTERS_DIR / "callouts.lua",
    FILTERS_DIR / "rules-widgets.lua",
    FILTERS_DIR / "stat-blocks.lua",
    FILTERS_DIR / "highlight-level-headings.lua",
    FILTERS_DIR / "minor-sections.lua",
]
