"""Unit tests for build orchestration helpers.

These do not invoke Pandoc or WeasyPrint; they exercise the pure helpers
that prepare anchors and resolve outputs.
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from papercrown.build.options import (
    BuildScope,
    DraftMode,
    OutputProfile,
    WearMode,
)
from papercrown.media.fillers import FillerDecision, FillerMeasurement, FillerPlacement
from papercrown.project import paths, resources
from papercrown.project.manifest import (
    Chapter,
    FillerAsset,
    PageDamageAsset,
    PageDamageCatalog,
    Splash,
    build_manifest,
)
from papercrown.project.recipe import load_book_config
from papercrown.render import build
from papercrown.system import export as export_mod
from papercrown.system.cache import ArtifactCache

# ---------------------------------------------------------------------------
# _slugs_for_anchors
# ---------------------------------------------------------------------------


class TestSlugsForAnchors:
    def test_includes_chapter_slugs(self):
        ch = Chapter(title="Berserker", slug="berserker")
        out = build.slugs_for_anchors([ch])
        assert "berserker" in out.split(",")

    def test_includes_descendants(self):
        leaf = Chapter(
            title="Path of the Mountainheart", slug="path-of-the-mountainheart"
        )
        wrap = Chapter(title="Berserker", slug="berserker", children=[leaf])
        slugs = build.slugs_for_anchors([wrap]).split(",")
        assert "berserker" in slugs
        assert "path-of-the-mountainheart" in slugs

    def test_includes_source_file_stems(self, tmp_path):
        # Cross-document Markdown link targets often include the source file
        # stem (e.g. `Berserker Description.md`); the Lua filter resolves
        # those by slugifying the stem and matching against valid-anchors.
        f = tmp_path / "Berserker Description.md"
        f.write_text("# x", encoding="utf-8")
        ch = Chapter(title="Berserker", slug="berserker", source_files=[f])
        slugs = build.slugs_for_anchors([ch]).split(",")
        assert "berserker-description" in slugs

    def test_underscore_slug_passes_through(self, tmp_path):
        # Regression: `manifest._slugify` used to drop `_`, so the chapter
        # slug never matched the Lua filter's slug for the same title.
        # After the slug unification, both keep the underscore.
        ch = Chapter(title="Heavyworlder_Native", slug="heavyworlder_native")
        slugs = build.slugs_for_anchors([ch]).split(",")
        assert "heavyworlder_native" in slugs

    def test_returns_sorted_unique_csv(self):
        a = Chapter(title="Alpha", slug="alpha")
        b = Chapter(title="Beta", slug="beta")
        # Duplicate via two top-level chapters with same title:
        out = build.slugs_for_anchors([a, b, a])
        slugs = out.split(",")
        assert slugs == sorted(set(slugs))


def test_minor_section_filter_is_enabled_after_heading_filters():
    names = [p.name for p in resources.LUA_FILTERS]
    assert "rules-widgets.lua" in names
    assert "minor-sections.lua" in names
    assert names.index("highlight-level-headings.lua") < names.index(
        "minor-sections.lua"
    )


def test_lua_filter_library_is_packaged():
    assert (resources.FILTERS_DIR / "lib" / "papercrown.lua").is_file()
    assert "resources/**/*.lua" in _read_project_package_data()


def _read_project_package_data() -> str:
    pyproject = Path(__file__).parents[3] / "pyproject.toml"
    return pyproject.read_text(encoding="utf-8")


def test_book_context_leaves_pandoc_toc_disabled():
    recipe = SimpleNamespace(
        title="B",
        subtitle=None,
        cover_eyebrow=None,
        cover_footer=None,
        cover=SimpleNamespace(enabled=False, art=None),
        art_dir=Path.cwd(),
    )
    manifest = SimpleNamespace(chapters=[Chapter(title="Foo", slug="foo")])
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )
    ctx = build.context_for_book(tools, recipe, manifest, profile=OutputProfile.PRINT)
    assert ctx.include_toc is False


def test_book_context_resolves_folio_ornament(tmp_path):
    folio = tmp_path / "ornaments" / "folio.png"
    folio.parent.mkdir()
    folio.write_text("fake", encoding="utf-8")
    recipe = SimpleNamespace(
        title="B",
        subtitle=None,
        cover_eyebrow=None,
        cover_footer=None,
        cover=SimpleNamespace(enabled=False, art=None),
        art_dir=tmp_path,
        ornaments=SimpleNamespace(folio_frame="ornaments/folio.png"),
    )
    manifest = SimpleNamespace(chapters=[Chapter(title="Foo", slug="foo")])
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )
    ctx = build.context_for_book(tools, recipe, manifest, profile=OutputProfile.PRINT)
    assert ctx.ornament_folio_frame == folio.resolve()


def test_book_context_uses_front_cover_splash_when_present(tmp_path):
    old_cover = tmp_path / "cover.png"
    front_splash = tmp_path / "front.png"
    old_cover.write_text("old", encoding="utf-8")
    front_splash.write_text("front", encoding="utf-8")
    recipe = SimpleNamespace(
        title="B",
        subtitle=None,
        cover_eyebrow=None,
        cover_footer=None,
        cover=SimpleNamespace(enabled=True, art="cover.png"),
        art_dir=tmp_path,
        ornaments=SimpleNamespace(),
    )
    manifest = SimpleNamespace(
        chapters=[Chapter(title="Foo", slug="foo")],
        splashes=[
            Splash(
                id="front",
                art_path=front_splash,
                target="front-cover",
                placement="cover",
            )
        ],
    )
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )

    ctx = build.context_for_book(tools, recipe, manifest, profile=OutputProfile.PRINT)

    assert ctx.cover_art == front_splash.resolve()


def test_fast_draft_book_context_omits_cover_art_by_default(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"fake")
    recipe = SimpleNamespace(
        title="B",
        subtitle=None,
        cover_eyebrow=None,
        cover_footer=None,
        cover=SimpleNamespace(enabled=True, art="cover.png"),
        art_dir=tmp_path,
    )
    manifest = SimpleNamespace(chapters=[Chapter(title="Foo", slug="foo")])
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )

    ctx = build.context_for_book(tools, recipe, manifest, profile=OutputProfile.DRAFT)

    assert ctx.cover_enabled is True
    assert ctx.cover_art is None


def test_visual_draft_book_context_keeps_cover_art(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"fake")
    recipe = SimpleNamespace(
        title="B",
        subtitle=None,
        cover_eyebrow=None,
        cover_footer=None,
        cover=SimpleNamespace(enabled=True, art="cover.png"),
        art_dir=tmp_path,
    )
    manifest = SimpleNamespace(chapters=[Chapter(title="Foo", slug="foo")])
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )

    ctx = build.context_for_book(
        tools,
        recipe,
        manifest,
        profile=OutputProfile.DRAFT,
        draft_mode=DraftMode.VISUAL,
    )

    assert ctx.cover_enabled is True
    assert ctx.cover_art == cover


def test_no_art_book_context_omits_cover_art(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"fake")
    recipe = SimpleNamespace(
        title="B",
        subtitle=None,
        cover_eyebrow=None,
        cover_footer=None,
        cover=SimpleNamespace(enabled=True, art="cover.png"),
        art_dir=tmp_path,
    )
    manifest = SimpleNamespace(chapters=[Chapter(title="Foo", slug="foo")])
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )

    ctx = build.context_for_book(
        tools,
        recipe,
        manifest,
        profile=OutputProfile.DRAFT,
        include_art=False,
    )

    assert ctx.cover_enabled is True
    assert ctx.cover_art is None


def test_fast_draft_chapter_context_omits_chapter_art_by_default(tmp_path):
    art = tmp_path / "chapter.png"
    art.write_bytes(b"fake")
    recipe = SimpleNamespace(
        title="B",
        art_dir=tmp_path,
    )
    chapter = Chapter(title="Foo", slug="foo", art_path=art)
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )

    print_ctx = build.context_for_chapter(
        tools,
        recipe,
        chapter,
        profile=OutputProfile.PRINT,
    )
    draft_ctx = build.context_for_chapter(
        tools,
        recipe,
        chapter,
        profile=OutputProfile.DRAFT,
    )

    assert print_ctx.chapter_art == art
    assert draft_ctx.chapter_art is None


def test_visual_draft_chapter_context_keeps_chapter_art(tmp_path):
    art = tmp_path / "chapter.png"
    art.write_bytes(b"fake")
    recipe = SimpleNamespace(
        title="B",
        art_dir=tmp_path,
    )
    chapter = Chapter(title="Foo", slug="foo", art_path=art)
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )

    ctx = build.context_for_chapter(
        tools,
        recipe,
        chapter,
        profile=OutputProfile.DRAFT,
        draft_mode=DraftMode.VISUAL,
    )

    assert ctx.chapter_art == art


def test_no_art_chapter_context_omits_chapter_art(tmp_path):
    art = tmp_path / "chapter.png"
    art.write_bytes(b"fake")
    recipe = SimpleNamespace(
        title="B",
        art_dir=tmp_path,
    )
    chapter = Chapter(title="Foo", slug="foo", art_path=art)
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )

    ctx = build.context_for_chapter(
        tools,
        recipe,
        chapter,
        profile=OutputProfile.DRAFT,
        include_art=False,
    )

    assert ctx.chapter_art is None


def test_auto_wear_resolves_to_fast_except_fast_draft():
    base = build.BuildRequest(
        recipe=SimpleNamespace(),
        manifest=SimpleNamespace(),
    )

    assert build._effective_wear_mode(base) is WearMode.FAST
    assert (
        build._effective_wear_mode(
            build.BuildRequest(
                recipe=SimpleNamespace(),
                manifest=SimpleNamespace(),
                profile=OutputProfile.DRAFT,
                draft_mode=DraftMode.FAST,
            )
        )
        is WearMode.OFF
    )
    assert (
        build._effective_wear_mode(
            build.BuildRequest(
                recipe=SimpleNamespace(),
                manifest=SimpleNamespace(),
                profile=OutputProfile.DRAFT,
                draft_mode=DraftMode.VISUAL,
            )
        )
        is WearMode.FAST
    )
    assert (
        build._effective_wear_mode(
            build.BuildRequest(
                recipe=SimpleNamespace(),
                manifest=SimpleNamespace(),
                wear_mode=WearMode.FULL,
            )
        )
        is WearMode.FULL
    )


def test_page_background_underlay_adds_late_stylesheet():
    ctx = build.pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=resources.TEMPLATE_FILE,
        css_files=[resources.CORE_CSS_FILES[0]],
        lua_filters=[],
        resource_paths=[],
    )

    assert len(build.pipeline._render_stylesheets(ctx)) == 1

    ctx.page_background_underlay = True
    stylesheets = build.pipeline._render_stylesheets(ctx)

    assert len(stylesheets) == 2


def test_render_fingerprint_tracks_renderer_source_files(monkeypatch):
    ctx = build.pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=resources.TEMPLATE_FILE,
        css_files=[resources.CORE_CSS_FILES[0]],
        lua_filters=[],
        resource_paths=[],
    )
    captured = {}

    def fake_fingerprint(paths, *, extra=None):
        captured["paths"] = list(paths)
        captured["extra"] = extra
        return "fingerprint"

    monkeypatch.setattr(build, "fingerprint_files", fake_fingerprint)

    assert build._render_fingerprint("markdown", ctx, input_paths=[]) == "fingerprint"

    package_root = Path(build.__file__).resolve().parents[1]
    renderer_files = {
        path.relative_to(package_root).as_posix()
        for path in captured["paths"]
        if path.suffix == ".py" and package_root in path.parents
    }
    assert {
        "render/build.py",
        "render/pipeline.py",
        "media/page_damage.py",
        "media/fillers.py",
        "media/images.py",
    } <= renderer_files
    assert captured["extra"]["markdown_sha256"]


def test_folio_frame_uses_late_literal_margin_box_stylesheet(tmp_path):
    folio = tmp_path / "folio.png"
    Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(folio)
    ctx = build.pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=resources.TEMPLATE_FILE,
        css_files=[resources.CORE_CSS_FILES[0]],
        lua_filters=[],
        resource_paths=[],
        ornament_folio_frame=folio,
    )

    stylesheets = build.pipeline._render_stylesheets(ctx)
    css = build.pipeline._folio_frame_css(folio)

    assert len(stylesheets) == 2
    assert "@bottom-center" in css
    assert folio.as_posix() in css


def test_clean_pdf_rewrites_pdf_with_clean_temp_file(tmp_path, monkeypatch):
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"unclean")
    calls = {}

    class FakeDoc:
        def save(self, path, **kwargs):
            calls["save_path"] = path
            calls["kwargs"] = kwargs
            Path(path).write_bytes(b"clean")

        def close(self):
            calls["closed"] = True

    fake_fitz = SimpleNamespace(open=lambda path: FakeDoc())

    monkeypatch.setattr(
        build.pipeline.importlib,
        "import_module",
        lambda name: fake_fitz,
    )

    build.pipeline._clean_pdf(pdf)

    assert pdf.read_bytes() == b"clean"
    assert calls["save_path"] == tmp_path / "book.cleaning.pdf"
    assert calls["kwargs"] == {
        "garbage": 4,
        "deflate": True,
        "deflate_images": True,
        "deflate_fonts": True,
        "clean": True,
        "use_objstms": 1,
    }
    assert calls["closed"] is True


def test_fast_page_damage_writer_uses_pymupdf_direct_insert(tmp_path, monkeypatch):
    out = tmp_path / "book.pdf"
    asset = PageDamageAsset(
        id="wear-coffee-small-01",
        art_path=tmp_path / "wear.png",
        family="coffee",
        size="small",
    )
    placement = build.page_damage_module.PageDamagePlacement(
        asset=asset,
        page_number=1,
        x_in=1.0,
        y_in=1.0,
        width_in=1.0,
        rotation_deg=0.0,
        opacity=0.3,
    )
    catalog = PageDamageCatalog(
        enabled=True,
        glaze_opacity=0.0,
        assets=[asset],
    )
    calls = {}

    class FakeRect:
        def __init__(self, x0, y0, x1, y1):
            self.x0 = x0
            self.y0 = y0
            self.x1 = x1
            self.y1 = y1

    class FakePage:
        rect = FakeRect(0, 0, 612, 792)

        def insert_image(self, rect, **kwargs):
            calls["rect"] = rect
            calls["stream"] = kwargs["stream"]
            calls["overlay"] = kwargs["overlay"]
            return 11

    class FakePdf:
        pages = [FakePage()]

        def __len__(self):
            return len(self.pages)

        def __getitem__(self, index):
            return self.pages[index]

        def save(self, path, **_kwargs):
            Path(path).write_bytes(b"saved")

        def close(self):
            calls["closed"] = True

    class FakeDoc:
        def write_pdf(self, **_kwargs):
            return b"%PDF"

    fake_fitz = SimpleNamespace(
        open=lambda *_args, **_kwargs: FakePdf(),
        Rect=FakeRect,
    )
    monkeypatch.setattr(
        build.pipeline.importlib,
        "import_module",
        lambda name: fake_fitz,
    )
    monkeypatch.setattr(
        build.pipeline.page_damage,
        "render_page_damage_image_png",
        lambda placement: build.pipeline.page_damage.PageDamageImage(
            png=b"png",
            x_in=1.0,
            y_in=2.0,
            width_in=0.5,
            height_in=0.25,
        ),
    )

    ctx = build.pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=resources.TEMPLATE_FILE,
        css_files=[resources.CORE_CSS_FILES[0]],
        lua_filters=[],
        resource_paths=[],
    )

    build.pipeline._write_pdf_with_page_damage_fast(
        FakeDoc(),
        out,
        damage_catalog=catalog,
        damage_placements=[placement],
        overlay_placements=[],
        base_url="",
        ctx=ctx,
    )

    assert out.read_bytes() == b"saved"
    assert calls["stream"] == b"png"
    assert calls["overlay"] is True
    assert calls["rect"].x0 == 72.0
    assert calls["rect"].y0 == 144.0
    assert calls["rect"].x1 == 108.0
    assert calls["rect"].y1 == 162.0
    assert calls["closed"] is True


def test_quick_reference_chapter_context_omits_opener(tmp_path):
    art = tmp_path / "chapter.png"
    art.write_bytes(b"fake")
    recipe = SimpleNamespace(
        title="B",
        art_dir=tmp_path,
    )
    chapter = Chapter(
        title="Quick Reference",
        slug="quick-reference",
        style="quick-reference",
        art_path=art,
    )
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )

    ctx = build.context_for_chapter(
        tools,
        recipe,
        chapter,
        profile=OutputProfile.PRINT,
    )

    assert ctx.chapter_opener is False
    assert ctx.chapter_art is None


def test_build_chapter_pdf_skips_when_render_cache_matches(tmp_path, monkeypatch):
    rp = _write_recipe(
        tmp_path,
        """
        title: B
        vaults:
          v: vault
        contents:
          - kind: file
            title: Foo
            source: v:Foo.md
    """,
    )
    recipe = load_book_config(rp)
    manifest = build_manifest(recipe)
    chapter = manifest.all_chapters()[0]
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )
    render_calls = 0

    def fake_render(markdown, out_pdf, ctx, **_kwargs):
        nonlocal render_calls
        render_calls += 1
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        out_pdf.write_bytes(b"pdf")
        return out_pdf

    monkeypatch.setattr(build.pipeline, "render_markdown_to_pdf", fake_render)
    cache_path = tmp_path / "render-state.json"
    skipped: list[Path] = []

    cache = ArtifactCache.load(cache_path)
    first = build.build_chapter_pdf(
        tools,
        recipe,
        chapter,
        {},
        profile=OutputProfile.PRINT,
        manifest=manifest,
        cache=cache,
        skipped=skipped,
    )
    cache.save()

    cache = ArtifactCache.load(cache_path)
    second = build.build_chapter_pdf(
        tools,
        recipe,
        chapter,
        {},
        profile=OutputProfile.PRINT,
        manifest=manifest,
        cache=cache,
        skipped=skipped,
    )

    assert first == second
    assert render_calls == 1
    assert skipped == [second]


def test_build_outputs_scope_all_runs_book_in_prepared_job_pool(tmp_path, monkeypatch):
    rp = _write_recipe(
        tmp_path,
        """
        title: B
        vaults:
          v: vault
        contents:
          - kind: file
            title: Foo
            source: v:Foo.md
    """,
    )
    recipe = load_book_config(rp)
    manifest = build_manifest(recipe)
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )
    seen_labels: list[str] = []

    monkeypatch.setattr(build, "ensure_exports_fresh", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(build, "clean_stale_pdf_outputs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        build,
        "_prepare_chapter_pdf_job",
        lambda *_args, **_kwargs: SimpleNamespace(
            label="section: Foo",
            out=tmp_path / "Foo.pdf",
        ),
    )
    monkeypatch.setattr(
        build,
        "_prepare_combined_book_job",
        lambda *_args, **_kwargs: SimpleNamespace(
            label="book: B",
            out=tmp_path / "B.pdf",
        ),
    )

    def fake_run_prepared_jobs(jobs, **_kwargs):
        seen_labels.extend(job.label for job in jobs)
        return [job.out for job in jobs], []

    monkeypatch.setattr(build, "_run_prepared_jobs", fake_run_prepared_jobs)

    result = build.build_outputs(
        tools,
        build.BuildRequest(
            recipe=recipe,
            manifest=manifest,
            scope=BuildScope.ALL,
            jobs=4,
        ),
    )

    assert seen_labels == ["section: Foo", "book: B"]
    assert [path.name for path in result.produced] == ["Foo.pdf", "B.pdf"]


def test_build_chapter_pdf_passes_page_damage_catalog(tmp_path, monkeypatch):
    art = tmp_path / "art" / "page-wear"
    art.mkdir(parents=True)
    (art / "wear-coffee-small-01.png").write_bytes(b"fake")
    rp = _write_recipe(
        tmp_path,
        """
        title: B
        art:
          library: art
          wear:
            enabled: true
            folder: page-wear
            seed: build-test
            density: 1.0
            max_assets_per_page: 1
            opacity: 0.25
            glaze_opacity: 0.65
            glaze_texture: surface-dust-speckle.png
        vaults:
          v: vault
        contents:
          - kind: file
            title: Foo
            source: v:Foo.md
    """,
    )
    recipe = load_book_config(rp)
    manifest = build_manifest(recipe)
    chapter = manifest.all_chapters()[0]
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )
    captured = {}

    def fake_render(markdown, out_pdf, ctx, **kwargs):
        captured["ctx_page_background_underlay"] = ctx.page_background_underlay
        captured["page_damage_catalog"] = kwargs["page_damage_catalog"]
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        out_pdf.write_bytes(b"pdf")
        return out_pdf

    monkeypatch.setattr(build.pipeline, "render_markdown_to_pdf", fake_render)

    build.build_chapter_pdf(
        tools,
        recipe,
        chapter,
        {},
        profile=OutputProfile.PRINT,
        manifest=manifest,
    )

    catalog = captured["page_damage_catalog"]
    assert captured["ctx_page_background_underlay"] is False
    assert catalog.enabled is True
    assert catalog.seed == "build-test"
    assert catalog.glaze_opacity == 0.65
    assert catalog.glaze_texture == "surface-dust-speckle.png"
    assert len(catalog.assets) == 1
    assert catalog.assets[0].family == "coffee"


def test_fast_draft_chapter_pdf_skips_page_art_and_cleanup(tmp_path, monkeypatch):
    art = tmp_path / "art"
    (art / "page-wear").mkdir(parents=True)
    (art / "fillers").mkdir()
    Image.new("RGBA", (8, 8), (0, 0, 0, 80)).save(
        art / "page-wear" / "wear-coffee-small-01.png"
    )
    Image.new("RGBA", (8, 8), (0, 0, 0, 80)).save(art / "fillers" / "tail.png")
    rp = _write_recipe(
        tmp_path,
        """
        title: B
        art:
          library: art
          wear:
            enabled: true
            folder: page-wear
          fillers:
            enabled: true
            folder: fillers
            slots:
              chapter-end:
                min_space: 0.65in
                max_space: 3.5in
                shapes: [tailpiece]
            assets:
              - id: tail
                image: tail.png
                shape: tailpiece
                height: 0.65in
        vaults:
          v: vault
        contents:
          - kind: file
            title: Foo
            source: v:Foo.md
    """,
    )
    (tmp_path / "vault" / "spot.png").write_bytes(b"fake")
    (tmp_path / "vault" / "Foo.md").write_text(
        "# Foo\n\n![Spot](spot.png)\n",
        encoding="utf-8",
    )
    recipe = load_book_config(rp)
    manifest = build_manifest(recipe)
    chapter = manifest.all_chapters()[0]
    tools = export_mod.Tools(
        pandoc="pandoc",
        obsidian_export="obsidian-export",
        weasyprint="weasyprint",
    )
    captured = {}

    def fake_render(markdown, out_pdf, ctx, **kwargs):
        captured["markdown"] = markdown
        captured["ctx"] = ctx
        captured["filler_catalog"] = kwargs["filler_catalog"]
        captured["page_damage_catalog"] = kwargs["page_damage_catalog"]
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        out_pdf.write_bytes(b"pdf")
        return out_pdf

    monkeypatch.setattr(build.pipeline, "render_markdown_to_pdf", fake_render)

    build.build_chapter_pdf(
        tools,
        recipe,
        chapter,
        {},
        profile=OutputProfile.DRAFT,
        manifest=manifest,
    )

    assert "draft-art-placeholder" in captured["markdown"]
    assert captured["ctx"].draft_placeholders is True
    assert captured["ctx"].clean_pdf is False
    assert captured["filler_catalog"] is None
    assert captured["page_damage_catalog"] is None


def test_bottom_bleed_display_size_does_not_upscale_small_art(tmp_path):
    image = tmp_path / "small-bottom.png"
    Image.new("RGB", (240, 120), color="red").save(image)

    width_pt, height_pt = build.pipeline._bottom_bleed_display_size_pt(
        image,
        max_width_pt=8.5 * 72.0,
        max_height_pt=2.4 * 72.0,
    )

    assert round(width_pt, 3) == 180.0
    assert round(height_pt, 3) == 90.0


def test_bottom_bleed_display_size_caps_large_art_without_distortion(tmp_path):
    image = tmp_path / "large-bottom.png"
    Image.new("RGB", (2550, 720), color="red").save(image)

    width_pt, height_pt = build.pipeline._bottom_bleed_display_size_pt(
        image,
        max_width_pt=8.5 * 72.0,
        max_height_pt=2.4 * 72.0,
    )

    assert round(width_pt, 3) == 612.0
    assert round(height_pt, 3) == 172.8


def test_bottom_bleed_stamp_uses_placement_render_height(tmp_path, monkeypatch):
    asset_path = tmp_path / "large-bottom-band.png"
    Image.new("RGB", (2550, 1575), color="red").save(asset_path)
    placement = FillerPlacement(
        "slot-bottom",
        FillerAsset("bottom", asset_path, "bottom-band", 5.25),
        page_number=7,
        slot_name="chapter-end",
        render_height_in=4.0,
    )
    captured = {}

    def fake_display_size(path, *, max_width_pt, max_height_pt):
        captured["path"] = path
        captured["max_width_pt"] = max_width_pt
        captured["max_height_pt"] = max_height_pt
        return (300.0, max_height_pt)

    class FakePage:
        rect = SimpleNamespace(x0=0.0, y1=792.0, x1=612.0, width=612.0)

        def draw_rect(self, rect, **kwargs):
            captured["mask_rect"] = rect
            captured["mask_kwargs"] = kwargs

        def insert_image(self, rect, **kwargs):
            captured["image_rect"] = rect
            captured["image_kwargs"] = kwargs

    class FakeFitz:
        @staticmethod
        def Rect(*args):
            return args

    monkeypatch.setattr(
        build.pipeline,
        "_bottom_bleed_display_size_pt",
        fake_display_size,
    )

    build.pipeline._stamp_bottom_bleed_fitz(FakePage(), placement, FakeFitz)

    assert captured["path"] == asset_path
    assert captured["max_width_pt"] == 612.0
    assert captured["max_height_pt"] == pytest.approx(279.36)
    assert captured["mask_rect"] == (0.0, 486.0, 612.0, 792.0)
    assert captured["image_rect"] == pytest.approx((156.0, 504.0, 456.0, 783.36))


def test_filler_debug_overlay_writes_separate_pdf(tmp_path):
    fitz = build.pipeline.importlib.import_module("fitz")
    source = tmp_path / "source.pdf"
    debug = tmp_path / "source.filler-debug.pdf"
    doc = fitz.open()
    try:
        doc.new_page(width=612, height=792)
        doc.save(source)
    finally:
        doc.close()
    before = source.read_bytes()
    decision = FillerDecision(
        measurement=FillerMeasurement(
            slot_id="slot-a",
            slot_name="chapter-end",
            chapter_slug="intro",
            page_number=1,
            available_in=3.0,
            slot_y_in=2.0,
            content_bottom_in=5.0,
        ),
        asset=None,
        reason="no fitting context-matched asset",
    )

    build.pipeline._write_filler_debug_overlay(source, debug, [decision], [])

    assert debug.is_file()
    assert source.read_bytes() == before


def test_draft_page_damage_catalog_is_boosted_for_inspection(tmp_path):
    asset_path = tmp_path / "wear-coffee-small-01.png"
    Image.new("RGBA", (2, 2), (0, 0, 0, 0)).save(asset_path)
    asset = PageDamageAsset(
        id="wear-coffee-small-01",
        art_path=asset_path,
        family="coffee",
        size="small",
    )
    catalog = PageDamageCatalog(
        enabled=True,
        seed="seed",
        density=0.55,
        max_assets_per_page=2,
        opacity=0.28,
        glaze_opacity=0.4,
        glaze_texture="surface-paper-fiber-wash.png",
        assets=[asset],
    )

    print_catalog = build._render_page_damage_catalog(
        catalog,
        profile=OutputProfile.PRINT,
        cache_root=tmp_path / "cache",
    )
    draft_catalog = build._render_page_damage_catalog(
        catalog,
        profile=OutputProfile.DRAFT,
        cache_root=tmp_path / "cache",
    )

    assert print_catalog is not None
    assert print_catalog.enabled == catalog.enabled
    assert print_catalog.seed == catalog.seed
    assert print_catalog.density == catalog.density
    assert print_catalog.assets[0].art_path != asset_path
    assert print_catalog.assets[0].art_path.is_file()
    assert draft_catalog is not None
    assert draft_catalog.density == 1.0
    assert draft_catalog.max_assets_per_page == 4
    assert draft_catalog.opacity == 1.0
    assert draft_catalog.glaze_opacity == 1.0
    assert draft_catalog.glaze_texture == "surface-paper-fiber-wash.png"


def test_clean_stale_pdf_outputs_removes_renamed_artifacts(tmp_path):
    rp = _write_recipe(
        tmp_path,
        """
        title: My Book
        vaults:
          v: vault
        contents:
          - kind: file
            title: For GMs
            source: v:Foo.md
    """,
    )
    recipe = load_book_config(rp)
    manifest = build_manifest(recipe)
    root = paths.output_root(recipe)
    root.mkdir(parents=True)
    stale = paths.pdf_root(recipe) / "sections" / "For DMs.pdf"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    current = paths.chapter_pdf_path(recipe, manifest.chapters[0])
    current.write_bytes(b"new")
    print_book = paths.combined_book_path(recipe, profile=OutputProfile.PRINT)
    digital_book = paths.combined_book_path(recipe, profile=OutputProfile.DIGITAL)
    print_book.parent.mkdir(parents=True, exist_ok=True)
    print_book.write_bytes(b"print")
    digital_book.write_bytes(b"digital")

    removed = build.clean_stale_pdf_outputs(recipe, manifest)

    assert removed == [stale]
    assert not stale.exists()
    assert current.exists()
    assert print_book.exists()
    assert digital_book.exists()


# ---------------------------------------------------------------------------
# Path helper behavior
# ---------------------------------------------------------------------------


def _write_recipe(tmp_path: Path, body: str) -> Path:
    (tmp_path / "vault").mkdir(exist_ok=True)
    (tmp_path / "vault" / "Foo.md").write_text("# Foo", encoding="utf-8")
    p = tmp_path / "recipe.yaml"
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


class TestPathReexports:
    def test_chapter_pdf_path_alias(self, tmp_path):
        rp = _write_recipe(
            tmp_path,
            """
            title: B
            vaults:
              v: vault
            contents:
              - kind: file
                source: v:Foo.md
        """,
        )
        recipe = load_book_config(rp)
        ch = Chapter(title="X", slug="x")
        assert paths.chapter_pdf_path(recipe, ch).name == "X.pdf"

    def test_combined_book_path_alias(self, tmp_path):
        rp = _write_recipe(
            tmp_path,
            """
            title: My Book
            vaults:
              v: vault
            contents:
              - kind: file
                source: v:Foo.md
        """,
        )
        recipe = load_book_config(rp)
        assert (
            paths.combined_book_path(recipe, profile=OutputProfile.PRINT).name
            == "My Book.pdf"
        )


# ---------------------------------------------------------------------------
# Manifest.find_chapter is what `--single` relies on
# ---------------------------------------------------------------------------


class TestSingleChapterLookup:
    def test_finds_by_title_and_slug(self, tmp_path):
        rp = _write_recipe(
            tmp_path,
            """
            title: B
            vaults:
              v: vault
            contents:
              - kind: file
                title: Berserker
                source: v:Foo.md
        """,
        )
        m = build_manifest(load_book_config(rp))
        assert m.find_chapter("Berserker").title == "Berserker"
        assert m.find_chapter("berserker").title == "Berserker"
        assert m.find_chapter("BERSERKER").title == "Berserker"

    def test_returns_none_for_unknown(self, tmp_path):
        rp = _write_recipe(
            tmp_path,
            """
            title: B
            vaults:
              v: vault
            contents:
              - kind: file
                title: Berserker
                source: v:Foo.md
        """,
        )
        m = build_manifest(load_book_config(rp))
        assert m.find_chapter("Wizard") is None
