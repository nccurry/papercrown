"""Tests for themes, metadata, typed blocks, and generated indexes."""

from __future__ import annotations

import textwrap
from pathlib import Path

from papercrown import build as build_mod
from papercrown import themes, ttrpg
from papercrown.diagnostics import DiagnosticSeverity
from papercrown.manifest import Chapter
from papercrown.recipe import (
    BookMetadataSpec,
    CoverSpec,
    MatterSpec,
    Recipe,
    load_recipe,
)
from papercrown.resources import TEMPLATE_FILE


def _write_recipe(tmp_path: Path, body: str) -> Path:
    (tmp_path / "vault").mkdir(exist_ok=True)
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return recipe


def _recipe(tmp_path: Path) -> Recipe:
    return Recipe(
        title="Frostmere",
        subtitle="Winter Court Primer",
        cover_eyebrow="Campaign",
        cover_footer="Draft",
        vaults={},
        vault_overlay=[],
        cover=CoverSpec(enabled=False),
        chapters=[],
        recipe_path=tmp_path / "recipe.yaml",
        metadata=BookMetadataSpec(
            authors=["Example Author"],
            version="0.1.0",
            date="2026-04-26",
            publisher="Example Table",
            license="All rights reserved",
            keywords=["fantasy", "campaign"],
            credits={"art": ["Example Artist"]},
        ),
        front_matter=[MatterSpec("title-page"), MatterSpec("credits")],
        back_matter=[MatterSpec("appendix-index")],
    )


def test_recipe_loads_theme_metadata_and_generated_matter(tmp_path):
    recipe_path = _write_recipe(
        tmp_path,
        """
        title: Metadata Book
        theme: clean-srd
        theme_options:
          accent: "#123456"
        metadata:
          authors: Example Author
          version: "0.2.0"
          keywords: [rules, fantasy]
          credits:
            art: Example Artist
        front_matter: [title-page, credits]
        back_matter:
          - type: appendix-index
            title: Game Object Index
        vaults:
          v: vault
        chapters:
          - kind: file
            source: v:Book.md
        """,
    )

    recipe = load_recipe(recipe_path)

    assert recipe.theme == "clean-srd"
    assert recipe.theme_options == {"accent": "#123456"}
    assert recipe.metadata.authors == ["Example Author"]
    assert recipe.metadata.keywords == ["rules", "fantasy"]
    assert recipe.metadata.credits["art"] == ["Example Artist"]
    assert [matter.type for matter in recipe.front_matter] == ["title-page", "credits"]
    assert recipe.back_matter[0].title == "Game Object Index"


def test_bundled_theme_resolves_css_template_and_options(tmp_path):
    recipe_path = _write_recipe(
        tmp_path,
        """
        title: Theme Book
        theme: illuminated-fantasy
        theme_options:
          accent: "#775511"
        vaults:
          v: vault
        chapters:
          - kind: file
            source: v:Book.md
        """,
    )
    recipe = load_recipe(recipe_path)

    theme = themes.load_theme(recipe)

    assert theme.name == "illuminated-fantasy"
    assert theme.css_files[0].name == "book.css"
    assert theme.template == TEMPLATE_FILE
    assert theme.inline_css is not None
    assert "--accent: #775511;" in theme.inline_css
    assert theme.fingerprint_paths


def test_typed_blocks_resolve_refs_and_generate_index(tmp_path):
    recipe = _recipe(tmp_path)
    source = (tmp_path / "Frostmere Primer.md").resolve().as_posix()
    markdown = textwrap.dedent(
        f"""
        <!-- papercrown-source-file: {source} -->

        ::: {{.npc title="Mara Voss" tags="rival,knight"}}
        ## Mara Voss

        A winter court agent.
        :::

        ::: {{.rule title="Advantage"}}
        ## Advantage

        Roll twice and keep the better result.
        :::

        ::: {{.power title="Flame Dart" tags="thermal"}}
        ## Flame Dart

        Deal thermal damage at range.
        :::

        ::: {{.frame title="Baseline Human"}}
        ## Baseline Human

        The default frame.
        :::

        ::: {{.background title="Academy Dropout"}}
        ## Academy Dropout

        A messy educational record.
        :::

        Mara carries @npc.mara-voss rumors between keeps, uses @rule.advantage,
        and teaches @power.flame-dart to @frame.baseline-human recruits with
        @background.academy-dropout records.
        """
    ).lstrip()

    prepared = ttrpg.prepare_book_markdown(
        markdown,
        recipe,
        include_generated_matter=True,
    )

    assert prepared.diagnostics == []
    assert "#npc-mara-voss .npc .ttrpg-block .ttrpg-npc" in prepared.markdown
    assert 'data-ttrpg-id="mara-voss"' in prepared.markdown
    assert f'data-source-file="{source}"' in prepared.markdown
    assert prepared.registry.objects[0].source_file == Path(source)
    assert 'href="#npc-mara-voss"' in prepared.markdown
    assert 'href="#power-flame-dart"' in prepared.markdown
    assert "## NPCs" in prepared.markdown
    assert "## Backgrounds" in prepared.markdown
    assert "## Frames" in prepared.markdown
    assert "## Powers" in prepared.markdown
    assert "- [Mara Voss](#npc-mara-voss) (rival, knight)" in prepared.markdown
    assert "- [Advantage](#rule-advantage)" in prepared.markdown


def test_combined_book_orders_front_matter_before_manual_toc(tmp_path):
    recipe = _recipe(tmp_path)
    recipe.metadata = BookMetadataSpec(license="Legal copy.")
    recipe.front_matter = [MatterSpec("license", title="Legal & Support")]
    recipe.back_matter = [MatterSpec("copyright", title="Copyright")]
    chapters = [Chapter(title="First Chapter", slug="first-chapter")]

    prepared = build_mod._prepare_book_markdown_with_manual_toc(
        "# First Chapter\n\nMain content.\n",
        recipe,
        chapters,
    )

    legal_pos = prepared.index("# Legal & Support")
    toc_pos = prepared.index("# Table of Contents")
    chapter_pos = prepared.index("# First Chapter")
    copyright_pos = prepared.index("# Copyright")
    toc_block = prepared[toc_pos:chapter_pos]

    assert legal_pos < toc_pos < chapter_pos < copyright_pos
    assert "Legal & Support" not in toc_block
    assert "Copyright" not in toc_block
    assert "First Chapter" in toc_block


def test_duplicate_typed_block_ids_are_errors():
    diagnostics = ttrpg.lint_ttrpg_markdown(
        textwrap.dedent(
            """
            ::: {.npc title="Mara Voss"}
            ## Mara Voss
            :::

            ::: {.npc title="Mara Voss"}
            ## Mara Voss
            :::
            """
        ).lstrip()
    )

    assert any(
        diagnostic.code == "ttrpg-block.duplicate-id"
        and diagnostic.severity is DiagnosticSeverity.ERROR
        for diagnostic in diagnostics
    )


def test_unresolved_typed_refs_are_errors():
    diagnostics = ttrpg.lint_ttrpg_markdown("See @item.black-key.\n")

    assert any(
        diagnostic.code == "ttrpg-ref.unresolved"
        and diagnostic.severity is DiagnosticSeverity.ERROR
        for diagnostic in diagnostics
    )
