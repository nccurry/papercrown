"""HTML snapshot tests.

Renders the mini fixture vault through Pandoc up to HTML (no WeasyPrint, no
PDF), normalizes absolute paths to stable tokens, and snapshot-compares.

To accept new snapshots after intentional changes:
    uv run pytest tests/html --snapshot-update
"""

from __future__ import annotations

import re
import shutil
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from papercrown.assembly import markdown as assembly
from papercrown.project.manifest import Chapter, ChapterFillerSlot
from papercrown.project.resources import (
    ASSETS_DIR,
    CORE_CSS_FILES,
    FONTS_DIR,
    LUA_FILTERS,
    RESOURCE_DIR,
    TEMPLATE_FILE,
)
from papercrown.render import pipeline

pytestmark = pytest.mark.usefixtures("require_pandoc")


def _write(p: Path, body: str) -> Path:
    """Write a dedented markdown body to disk; return the path."""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


def _make_ctx_for_chapter(chapter, *, recipe) -> pipeline.RenderContext:
    """Build a RenderContext suitable for HTML-only rendering (no weasyprint).

    We still need pandoc on PATH; weasyprint is unused in this stage.
    """
    return pipeline.RenderContext(
        pandoc=shutil.which("pandoc") or "pandoc",
        weasyprint="",  # unused for HTML-only
        template=TEMPLATE_FILE,
        css_files=list(CORE_CSS_FILES),
        lua_filters=list(LUA_FILTERS),
        resource_paths=[RESOURCE_DIR, ASSETS_DIR, FONTS_DIR],
        chapter_title=chapter.title,
        chapter_eyebrow=chapter.eyebrow or "Chapter",
        chapter_art=chapter.art_path,
        section_kind=chapter.style or "default",
        title_prefix=recipe.title,
    )


def _render_chapter_html(chapter, *, recipe, fixture_root: Path) -> str:
    md = assembly.assemble_chapter_markdown(chapter)
    ctx = _make_ctx_for_chapter(chapter, recipe=recipe)
    html = pipeline.render_markdown_to_html(md, ctx)
    return pipeline.normalize_for_snapshot(
        html,
        papercrown_root=RESOURCE_DIR,
        fixture_root=fixture_root,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSnapshots:
    def test_setting_chapter(self, mini_manifest, mini_recipe, snapshot, fixture_root):
        ch = mini_manifest.find_chapter("Setting")
        assert ch is not None, "Setting chapter not found in mini manifest"
        html = _render_chapter_html(ch, recipe=mini_recipe, fixture_root=fixture_root)
        snapshot.snapshot_dir = str(Path(__file__).parent.parent / "snapshots")
        snapshot.assert_match(html, "setting-chapter.html")

    def test_mage_class_chapter(
        self, mini_manifest, mini_recipe, snapshot, fixture_root
    ):
        ch = mini_manifest.find_chapter("Mage")
        assert ch is not None, "Mage chapter not found in mini manifest"
        html = _render_chapter_html(ch, recipe=mini_recipe, fixture_root=fixture_root)
        snapshot.snapshot_dir = str(Path(__file__).parent.parent / "snapshots")
        snapshot.assert_match(html, "mage-class.html")

    def test_rogue_class_chapter(
        self, mini_manifest, mini_recipe, snapshot, fixture_root
    ):
        ch = mini_manifest.find_chapter("Rogue")
        assert ch is not None, "Rogue chapter not found in mini manifest"
        html = _render_chapter_html(ch, recipe=mini_recipe, fixture_root=fixture_root)
        snapshot.snapshot_dir = str(Path(__file__).parent.parent / "snapshots")
        snapshot.assert_match(html, "rogue-class.html")

    def test_ornamented_class_chapter(self, tmp_path, snapshot):
        source = _write(
            tmp_path / "Mage.md",
            """
            # Mage

            :::: {.art-right .art-spot}
            ![](old-spot.png)
            ::::

            Intro text.
        """,
        )
        spot = _write(tmp_path / "art" / "class-spot.png", "fake")
        tailpiece = _write(tmp_path / "art" / "tailpiece.png", "fake")
        chapter = Chapter(
            title="Mage",
            slug="mage",
            style="class",
            source_files=[source],
            spot_art_path=spot,
            replace_opening_art=True,
            tailpiece_path=tailpiece,
            filler_slots=[
                ChapterFillerSlot(
                    id="filler-chapter-end-mage",
                    slot="chapter-end",
                    chapter_slug="mage",
                    preferred_asset_id="tail",
                )
            ],
        )
        html = _render_chapter_html(
            chapter,
            recipe=SimpleNamespace(title="Ornament Book"),
            fixture_root=tmp_path,
        )
        snapshot.snapshot_dir = str(Path(__file__).parent.parent / "snapshots")
        snapshot.assert_match(html, "ornamented-class.html")


class TestNormalization:
    def test_normalizes_papercrown_paths(self, tmp_path):
        # Use a real .as_uri() URI -- mirrors what Pandoc actually emits
        # (which percent-encodes spaces, etc).
        css_uri = CORE_CSS_FILES[0].as_uri()
        html = f'<link href="{css_uri}">'
        out = pipeline.normalize_for_snapshot(html, papercrown_root=RESOURCE_DIR)
        assert "<<papercrown>>/styles/core/00-tokens.css" in out
        assert "file://" not in out

    def test_normalizes_fixture_paths(self, fixture_root):
        target = fixture_root / "foo" / "bar.png"
        # Don't require the file to exist; we just want a valid file:// URI
        html = f'<img src="{target.as_uri()}">'
        out = pipeline.normalize_for_snapshot(html, fixture_root=fixture_root)
        assert "<<fixture>>/foo/bar.png" in out

    def test_normalizes_unrelated_paths_to_tmp(self):
        # Use a real Windows-style path via as_uri() if possible; otherwise
        # construct a clean (no-spaces) path manually so we don't conflate
        # the regex behavior with this test.
        html = '<img src="file:///C:/Windows/Temp/randomthing.png">'
        out = pipeline.normalize_for_snapshot(html)
        assert "<<tmp>>/randomthing.png" in out


class TestOutputProfileRendering:
    def test_print_digital_draft_and_web_body_classes(self):
        for profile in ("print", "digital", "draft", "web"):
            ctx = _make_ctx_for_book()
            ctx.output_profile = profile
            html = pipeline.render_markdown_to_html("# A\n\nbody\n", ctx)
            assert f'<body class="mode-{profile} section-book">' in html


class TestLuaFilterRendering:
    def test_stat_line_lists_render_without_list_markers(self):
        html = pipeline.render_markdown_to_html(
            "- **Easy:** DC 8.\n- **Medium:** DC 12.\n- **Hard:** DC 15.\n",
            _make_ctx_for_book(),
        )
        assert '<div class="pc-stat-block">' in html
        assert html.count('<div class="pc-stat-line">') == 3
        assert '<li><div class="pc-stat-block">' not in html
        assert "<li>" not in html

    def test_adjacent_stat_lines_split_after_bullet_cleanup(self):
        html = pipeline.render_markdown_to_html(
            "**Standard:** +2, +2, +0, -1\n"
            "**Balanced:** +2, +1, +1, +0\n"
            "**Min-Max:** +3, +1, -1, -1\n",
            _make_ctx_for_book(),
        )
        assert '<div class="pc-stat-block">' in html
        assert html.count('<div class="pc-stat-line">') == 3
        assert "<li>" not in html

    def test_callouts_render_pc_contract(self):
        html = pipeline.render_markdown_to_html(
            "> [!tip]- Table Hint\n"
            "> Keep the clue in front of the players.\n",
            _make_ctx_for_book(),
        )

        assert 'class="pc-callout pc-callout-tip is-foldable"' in html
        assert '<div class="pc-callout-title">' in html
        assert '<div class="pc-callout-body">' in html

    def test_internal_markdown_links_use_pc_ref_contract(self):
        html = pipeline.render_markdown_to_html(
            "# Target\n\nSee [Target](Target.md).\n",
            _make_ctx_for_book(),
        )

        assert 'href="#target"' in html
        assert 'class="pc-ref pc-ref-internal"' in html

    def test_unresolved_raw_wikilinks_fall_back_to_display_text(self):
        html = pipeline.render_markdown_to_html(
            "See [[Missing Note|missing display]].\n",
            _make_ctx_for_book(),
        )

        assert "[[" not in html
        assert "missing display" in html

    def test_dead_markdown_links_strip_to_plain_text(self):
        html = pipeline.render_markdown_to_html(
            "See [Missing](Missing.md).\n",
            _make_ctx_for_book(),
        )

        assert "Missing.md" not in html
        assert "<p>See Missing.</p>" in html

    def test_duplicate_original_heading_links_collapse(self):
        html = pipeline.render_markdown_to_html(
            "# Foo ([Foo](#original-foo))\n\nBody.\n",
            _make_ctx_for_book(),
        )

        assert "Foo (" not in html
        assert 'href="#original-foo"' in html
        assert 'class="pc-ref pc-ref-internal"' in html

    def test_minor_sections_render_pc_section_contract(self):
        html = pipeline.render_markdown_to_html(
            "### Minor\n\nBody.\n",
            _make_ctx_for_book(),
        )

        assert "pc-section-minor" in html
        assert "pc-section-level-3" in html

    def test_feature_widget_renders_common_component_shape(self):
        html = pipeline.render_markdown_to_html(
            ':::: {.pc-feature title="Sneak Attack" level="1" tags="rogue,damage"}\n'
            "Once per turn, add extra damage.\n"
            "::::\n",
            _make_ctx_for_book(),
        )

        assert 'class="pc-component pc-feature"' in html
        assert '<div class="pc-component-header">' in html
        assert '<div class="pc-component-title">' in html
        assert '<div class="pc-component-meta">' in html
        assert '<div class="pc-component-body">' in html
        assert re.search(r"Level\s+1", html)

    def test_ability_widget_renders_optional_metadata(self):
        html = pipeline.render_markdown_to_html(
            ':::: {.pc-ability title="Overcharge" cost="1 Charge" duration="Instant"}\n'
            "Push the engine past its limit.\n"
            "::::\n",
            _make_ctx_for_book(),
        )

        assert 'class="pc-component pc-ability"' in html
        assert re.search(r"Cost:\s+1\s+Charge", html)
        assert re.search(r"Duration:\s+Instant", html)

    def test_procedure_widget_can_use_first_heading_as_title(self):
        html = pipeline.render_markdown_to_html(
            ":::: {.pc-procedure usage=\"Downtime\"}\n"
            "### Recovery Turn\n\n"
            "1. Clear temporary conditions.\n"
            "2. Advance clocks.\n"
            "::::\n",
            _make_ctx_for_book(),
        )

        assert 'class="pc-component pc-procedure"' in html
        assert "Recovery Turn" in html
        assert re.search(r"Usage:\s+Downtime", html)


class TestFillerSlotRendering:
    def test_section_end_filler_slots_do_not_leak_as_text(self, tmp_path):
        source = _write(
            tmp_path / "frames.md",
            """
            # Frames
            Intro.

            # Baseline Human
            Baseline text.

            # Project Subjects
            Pocket Dimension You have access to a personal pocket dimension.
        """,
        )
        chapter = Chapter(
            title="Frames",
            slug="frames",
            style="ancestries",
            source_files=[source],
        )
        html = _render_chapter_html(
            chapter,
            recipe=SimpleNamespace(title="Filler Regression Book"),
            fixture_root=tmp_path,
        )

        assert 'id="filler-frame-family-end-frames-project-subjects"' in html
        assert 'class="filler-slot"' in html
        assert "::::" not in html
        assert "{.filler-slot" not in html


# ---------------------------------------------------------------------------
# Combined-book rendering regressions
# ---------------------------------------------------------------------------


def _make_ctx_for_book(
    *, recipe_title: str = "Regression Book"
) -> pipeline.RenderContext:
    """Minimal RenderContext matching what `generate._context_for_book` builds,
    pared down for HTML-only rendering of a combined-book markdown blob."""
    return pipeline.RenderContext(
        pandoc=shutil.which("pandoc") or "pandoc",
        weasyprint="",
        template=TEMPLATE_FILE,
        css_files=list(CORE_CSS_FILES),
        lua_filters=list(LUA_FILTERS),
        resource_paths=[RESOURCE_DIR, ASSETS_DIR, FONTS_DIR],
        chapter_title=recipe_title,
        chapter_eyebrow="Book",
        section_kind="book",
        chapter_opener=False,
        include_toc=False,
        title_prefix=recipe_title,
    )


class TestCombinedBookRendering:
    """Guardrails for problems that only surface when multiple chapter-wrap
    divs are concatenated and fed to Pandoc as one blob.

    Regression target: a chapter body with two `---` horizontal rules AND
    bold-text paragraphs between them used to be pattern-matched by
    Pandoc's `multiline_tables` extension as a multiline table whose body
    silently absorbed the surrounding `:::::` chapter-wrap closing fence.
    That fence-eating nested every subsequent chapter inside the previous
    one, which is how Bonded / Mycologist / Songweaver vanished from the
    real player-book PDF. The fix disables multiline/simple/grid tables in
    `pipeline.py`. This test builds the exact structure that used to break.
    """

    def test_pipeline_disables_dangerous_table_extensions(self):
        # The smoking-gun config guardrail. `multiline_tables`,
        # `simple_tables`, and `grid_tables` must be DISABLED in the
        # pandoc `--from=` argument. Any of these enabled will cause
        # a chapter body with two `---` thematic breaks and bold-text
        # paragraphs between them to be pattern-matched as a table,
        # whose body silently absorbs the surrounding `:::::`
        # chapter-wrap closing fence -- nesting every subsequent
        # chapter inside the previous one. Three classes vanished
        # from production this way before we disabled these.
        #
        # This test is cheap and obvious; keep it as the first line
        # of defense so if someone edits the format string they see
        # the failure immediately.
        import inspect

        src = inspect.getsource(pipeline._build_pandoc_base_args)
        assert "-multiline_tables" in src, (
            "pipeline must disable multiline_tables in the pandoc --from "
            "format string (caused Bonded / Mycologist / Songweaver to "
            "vanish from the combined book). See pipeline.py."
        )
        assert "-simple_tables" in src, (
            "pipeline must also disable simple_tables for safety"
        )
        assert "-grid_tables" in src, (
            "pipeline must also disable grid_tables for safety"
        )
        # And pipe_tables must remain ENABLED, since we actually use them.
        assert "+pipe_tables" in src, (
            "pipeline must keep pipe_tables enabled for real tables"
        )

    def test_combined_book_renders_all_chapter_wraps(self, tmp_path):
        # Integration-level: assembling a three-chapter book with a
        # regression-shaped middle chapter through the real pipeline
        # must still emit every chapter-wrap <div>. Uses a realistic
        # body structure (stat block + Levels + Abilities) with two
        # horizontal rules and many bold-text paragraphs between them.
        regression_body = textwrap.dedent("""
            # Two

            **Key Stats:** INT, WIL
            **Hit Die:** 1d6
            **Starting HP:** 10
            **Saves:** INT+, STR-

            ---
            ### Levels
            ##### Level 1
            **Feature A**
            does A.

            **Feature B**
            does B.
            ##### Level 2
            **Feature C**
            does C.

            ### Abilities

            **Alpha**
            (1 Charge) Alpha effect.

            **Bravo**
            (1 Charge) Bravo effect.

            **Charlie**
            (2 Charge) Charlie effect.

            **Delta**
            (1 Charge) Delta effect.

            ---

            ### Extra Table

            **Option One**
            does option one.

            **Option Two**
            does option two.
        """).lstrip()
        one = Chapter(
            title="One",
            slug="one",
            style="class",
            divider=True,
            source_files=[_write(tmp_path / "one.md", "# One\nbody one.\n")],
        )
        two = Chapter(
            title="Two",
            slug="two",
            style="class",
            divider=True,
            source_files=[_write(tmp_path / "two.md", regression_body)],
        )
        three = Chapter(
            title="Three",
            slug="three",
            style="class",
            divider=True,
            source_files=[_write(tmp_path / "three.md", "# Three\nbody three.\n")],
        )
        wrapper = Chapter(
            title="Classes",
            slug="classes",
            children=[one, two, three],
        )
        md = assembly.assemble_combined_book_markdown([wrapper])
        html = pipeline.render_markdown_to_html(md, _make_ctx_for_book())

        # Every chapter's chapter-wrap <div> and section-divider <div>
        # must appear exactly once. The count-equals-1 is the lower
        # bound; the config-level guard above catches the root cause.
        for slug in ("one", "two", "three"):
            assert html.count(f'id="div-{slug}"') == 1, (
                f"section-divider for {slug!r} missing or duplicated"
            )
            wrap_tag = f'<div id="ch-{slug}" class="chapter-wrap'
            assert html.count(wrap_tag) == 1, (
                f"chapter-wrap <div> for {slug!r} missing or duplicated: "
                f"found {html.count(wrap_tag)} occurrence(s)"
            )

        # And no <table> element anywhere -- a stray table in rendered
        # HTML from these inputs would mean a table-extension latched
        # onto the markdown even though pipe_tables is the only enabled
        # table dialect and the fixture has no pipe-table syntax.
        assert "<table" not in html, (
            "HTML contains a <table> element but the fixture has no pipe-table "
            "syntax -- a table-parsing extension must be eating content."
        )
