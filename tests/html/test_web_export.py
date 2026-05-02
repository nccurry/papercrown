"""HTML tests for the static web export target."""

from __future__ import annotations

import re
import shutil
import textwrap
from pathlib import Path
from urllib.parse import urlparse

from papercrown.project.manifest import build_manifest
from papercrown.project.recipe import load_book_config
from papercrown.render import build, web
from papercrown.system.export import Tools


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip(), encoding="utf-8")


def _make_web_recipe(tmp_path: Path) -> Path:
    (tmp_path / "art").mkdir()
    (tmp_path / "art" / "setting.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "art" / "tail.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    _write(
        tmp_path / "vault" / "Setting.md",
        """
        # Setting

        ## Setting Overview

        ### Setting Detail

        Body.
        """,
    )
    _write(tmp_path / "vault" / "Rules.md", "# Rules\n\nSee [Setting](#setting).\n")
    _write(
        tmp_path / "recipes" / "web.yaml",
        """
        title: Web Test Book
        output_dir: ../output
        art_dir: ../art
        vaults:
          v: ../vault
        contents:
          - kind: toc
          - kind: file
            title: Setting
            source: v:Setting.md
            art: setting.png
            tailpiece: tail.png
          - kind: file
            title: Rules
            source: v:Rules.md
    """,
    )
    return tmp_path / "recipes" / "web.yaml"


def _local_refs(html: str) -> list[str]:
    refs = re.findall(r'\b(?:href|src)=["\']([^"\']+)["\']', html)
    local: list[str] = []
    for ref in refs:
        parsed = urlparse(ref)
        if ref.startswith("#") or parsed.scheme in {
            "http",
            "https",
            "data",
            "mailto",
            "tel",
        }:
            continue
        local.append(ref)
    return local


def test_static_web_export_writes_self_contained_tree(tmp_path, require_pandoc):
    recipe = load_book_config(_make_web_recipe(tmp_path))
    manifest = build_manifest(recipe)
    web_root = recipe.generated_root / "web"
    stale = web_root / "stale.txt"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("old", encoding="utf-8")
    tools = Tools(
        pandoc=shutil.which("pandoc") or "pandoc",
        obsidian_export="obsidian-export",
        weasyprint="",
    )

    out = build.build_web_book(tools, recipe, manifest, {})
    html = out.read_text(encoding="utf-8")

    assert out == web_root / "index.html"
    assert not stale.exists()
    assert 'class="mode-web section-book"' in html
    assert "Table of Contents" in html
    assert "Setting" in html
    assert "Rules" in html
    assert 'href="#setting"' in html
    toc_start = html.index('id="table-of-contents"')
    toc_end = html.index('id="div-setting"', toc_start)
    toc_html = html[toc_start:toc_end]
    assert 'href="#setting-overview"' in toc_html
    assert 'href="#setting-detail"' not in toc_html
    assert 'id="setting-detail"' in html
    assert "[[" not in html and "]]" not in html
    assert 'class="ornament-tailpiece"' in html
    assert "tail" in html
    assert "filler-slot" not in html
    web_css = (web_root / "styles" / "book.css").read_text(encoding="utf-8")
    assert "/* --- core/00-tokens.css --- */" in web_css
    assert "/* --- themes/industrial/tokens.css --- */" in web_css
    assert "/* --- themes/industrial/components.css --- */" in web_css
    assert "url('../assets/fonts/Rajdhani-Regular.ttf')" in web_css
    assert (web_root / "styles" / "core" / "50-ttrpg-components.css").is_file()
    assert any((web_root / "assets" / "fonts").iterdir())
    assert 'src="assets/images/' in html

    for ref in _local_refs(html):
        assert not Path(ref).is_absolute()
        assert (web_root / ref).exists(), ref


def test_static_web_bundle_includes_art_role_css_outside_theme_root(tmp_path):
    (tmp_path / "styles").mkdir()
    _write(tmp_path / "styles" / "power-header.css", ".power-header-art{float:right;}")
    recipe_path = _make_web_recipe(tmp_path)
    raw = recipe_path.read_text(encoding="utf-8")
    recipe_path.write_text(
        raw
        + textwrap.dedent(
            """
            art_roles:
              power-header:
                prefix: power-header
                css: ../styles/power-header.css
            """
        ),
        encoding="utf-8",
    )
    recipe = load_book_config(recipe_path)
    web_root = tmp_path / "web"

    web.copy_web_static_assets(web_root, recipe=recipe)
    css = (web_root / "styles" / "book.css").read_text(encoding="utf-8")

    assert "power-header.css" in css
    assert ".power-header-art{float:right;}" in css


def test_static_web_export_recovers_lossy_spell_list_embeds(tmp_path, require_pandoc):
    """Regression: source-reference spell lists must not render as empty HRs."""
    _write(
        tmp_path / "vault" / "Magic" / "Original Spell Lists.md",
        """
        # Original - Spell Lists
    """,
    )
    _write(
        tmp_path / "vault" / "Magic" / "Spell List.md",
        """
        # Fire Spells

        ![[Flame Dart]]

        ---

        # Lightning Spells

        ![[Zap]]

        ---

        # Necrotic Spells
    """,
    )
    _write(
        tmp_path / "vault" / "Magic" / "Spells" / "Fire Spells" / "Flame Dart.md",
        """
        *Cantrip Fire Spell*

        **Damage:** 1d10.
    """,
    )
    _write(
        tmp_path / "vault" / "Magic" / "Spells" / "Lightning Spells" / "Zap.md",
        """
        *Cantrip Lightning Spell*

        1 Action | Single Target | Range 12

        **Damage:** 2d8.
    """,
    )
    recipe_path = tmp_path / "recipes" / "spell-list-web.yaml"
    _write(
        recipe_path,
        """
        title: Spell List Web Test
        output_dir: ../output
        vaults:
          v: ../vault
        contents:
          - kind: group
            title: Original Spells Reference
            slug: original-spells-reference
            child_divider: true
            children:
              - kind: sequence
                title: Original - Spell Lists
                slug: original-spell-lists
                sources:
                  - v:Magic/Original Spell Lists.md
                  - v:Magic/Spell List.md
    """,
    )
    recipe = load_book_config(recipe_path)
    manifest = build_manifest(recipe)
    src = (tmp_path / "vault" / "Magic" / "Spell List.md").resolve()
    lossy = tmp_path / "export" / "Spell List.md"
    _write(
        lossy,
        """
        # Fire Spells

        ---

        # Lightning Spells

        ---

        # Necrotic Spells
    """,
    )
    tools = Tools(
        pandoc=shutil.which("pandoc") or "pandoc",
        obsidian_export="obsidian-export",
        weasyprint="",
    )

    out = build.build_web_book(tools, recipe, manifest, {src: lossy.resolve()})
    html = out.read_text(encoding="utf-8")

    assert 'id="fire-spells"' in html
    lightning_start = html.index('id="lightning-spells"')
    necrotic_start = html.index("Necrotic Spells", lightning_start)
    lightning_section = html[lightning_start:necrotic_start]

    assert "![[Zap]]" not in html
    assert "Zap" in lightning_section
    assert "Cantrip Lightning Spell" in lightning_section
    assert "2d8" in lightning_section
