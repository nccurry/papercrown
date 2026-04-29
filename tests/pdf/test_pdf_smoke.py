"""End-to-end smoke test: build the mini fixture into a real PDF."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

import pytest
from PIL import Image

from papercrown.assembly import markdown as assembly
from papercrown.build.options import DraftMode, OutputProfile, PaginationMode
from papercrown.project.manifest import (
    PageDamageAsset,
    PageDamageCatalog,
    build_manifest,
)
from papercrown.project.recipe import load_recipe
from papercrown.project.resources import CORE_CSS_FILES, TEMPLATE_FILE
from papercrown.render import build, pipeline
from papercrown.system import export

pytestmark = [
    pytest.mark.usefixtures("require_pandoc"),
    pytest.mark.usefixtures("require_weasyprint"),
]


def _outline_titles(outline: list[object]) -> list[str]:
    titles: list[str] = []
    for item in outline:
        if isinstance(item, list):
            titles.extend(_outline_titles(item))
            continue
        title = getattr(item, "title", None)
        if title is None and hasattr(item, "get"):
            title = item.get("/Title")
        if title is not None:
            titles.append(str(title))
    return titles


def _build_mage_pdf(mini_recipe_path: Path, tmp_path: Path) -> Path:
    """Shared helper: render the fixture's Mage class chapter to a PDF."""
    recipe = load_recipe(mini_recipe_path)
    manifest = build_manifest(recipe)
    chapter = manifest.find_chapter("Mage")
    assert chapter is not None

    tools = export.discover_tools()
    out_pdf = tmp_path / "mage-smoke.pdf"
    md = assembly.assemble_chapter_markdown(chapter)
    ctx = build.context_for_chapter(
        tools,
        recipe,
        chapter,
        profile=OutputProfile.PRINT,
    )
    pipeline.render_markdown_to_pdf(md, out_pdf, ctx)
    return out_pdf


def _build_mini_combined_pdf(mini_recipe_path: Path, tmp_path: Path) -> Path:
    """Shared helper: render the full mini-fixture combined book to a PDF.

    Produces a multi-page PDF with a cover + section dividers + bodies,
    so running-header / cover-title assertions have pages to check.
    """
    recipe = load_recipe(mini_recipe_path)
    manifest = build_manifest(recipe)
    tools = export.discover_tools()
    out_pdf = tmp_path / "mini-combined.pdf"
    md = assembly.assemble_combined_book_markdown(manifest.chapters)
    ctx = build.context_for_book(tools, recipe, manifest, profile=OutputProfile.PRINT)
    pipeline.render_markdown_to_pdf(md, out_pdf, ctx)
    return out_pdf


def test_mini_fixture_pdf_smoke(mini_recipe_path, tmp_path):
    """Build the Mage class chapter as a PDF; assert it exists and is non-trivial."""
    try:
        from pypdf import PdfReader
    except ImportError:
        pytest.skip("pypdf required for page-size assertions")

    out_pdf = _build_mage_pdf(mini_recipe_path, tmp_path)

    assert out_pdf.is_file(), f"PDF not produced at {out_pdf}"
    assert out_pdf.stat().st_size > 1024, (
        f"PDF too small ({out_pdf.stat().st_size} bytes); "
        "likely empty or a renderer error"
    )
    # Quick header sanity: every PDF starts with %PDF-
    assert out_pdf.read_bytes()[:5] == b"%PDF-"

    first_page = PdfReader(str(out_pdf)).pages[0]
    assert round(float(first_page.mediabox.width)) == 612
    assert round(float(first_page.mediabox.height)) == 792


def test_pdf_renderer_embeds_bundled_book_fonts(tmp_path):
    """The default core CSS should use bundled fonts, not system fallbacks."""
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF required for embedded font assertions")

    out_pdf = tmp_path / "font-probe.pdf"
    ctx = pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=TEMPLATE_FILE,
        css_files=list(CORE_CSS_FILES),
        lua_filters=[],
        resource_paths=[],
        clean_pdf=False,
    )
    pipeline.render_html_to_pdf(
        """
        <!doctype html>
        <html>
          <body>
            <h1>Heading Text</h1>
            <p>Body text with <strong>bold</strong> and <em>italic</em>.</p>
            <p><code>MONO 123</code></p>
          </body>
        </html>
        """,
        out_pdf,
        ctx,
    )

    doc = fitz.open(out_pdf)
    try:
        font_names = {font[3] for page in doc for font in page.get_fonts(full=True)}
    finally:
        doc.close()

    joined = "\n".join(sorted(font_names))
    assert "Rajdhani" in joined
    assert "IBM-Plex-Serif" in joined
    assert "Share-Tech-Mono" in joined
    assert "Georgia" not in joined
    assert "Segoe" not in joined
    assert "Consolas" not in joined


def test_running_header_book_title_present_in_rendered_pdf(mini_recipe_path, tmp_path):
    """The recipe's `title:` must land in the rendered PDF somewhere.

    Regression guard: the running header used to be a CSS string literal
    that silently lied whenever someone built a different recipe. The fix
    pipes the recipe's `title:` into a hidden
    `.book-title-stringset` element that CSS hooks via
    `string-set: book-title content()`. We assert the recipe title
    surfaces in the PDF text stream (via TOC, running header, or cover).

    (We deliberately don't assert margin-box placement because pypdf's
    text extraction on WeasyPrint margin boxes is fragile. A combined
    HTML-level assertion for the stringset wiring lives in the unit
    tests.)
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        pytest.skip("pypdf required for content assertions")

    out_pdf = _build_mini_combined_pdf(mini_recipe_path, tmp_path)
    reader = PdfReader(str(out_pdf))
    full_text = "\n".join((p.extract_text() or "") for p in reader.pages)
    normalized = " ".join(full_text.split()).lower()

    # The mini recipe's `title:` is "Mini Test Book".
    assert "mini test book" in normalized, (
        "Recipe title missing from PDF text; cover/TOC/running header "
        f"all failed to inject it. Got (first 300 chars): {full_text[:300]!r}"
    )
    assert "content:" not in full_text


def test_stringset_element_drives_running_header_css(mini_recipe_path):
    """Unit-level: the template + CSS wire `string(book-title)` correctly.

    Structural assertion that catches the two regression traps we hit
    today:
      1. the CSS `@top-right` must use `string(book-title)` (not a literal)
      2. the `.book-title-stringset` CSS rule must NOT use `display: none`
         (WeasyPrint strips display:none before string collection)
    """
    import re

    css_text = "\n".join(path.read_text(encoding="utf-8") for path in CORE_CSS_FILES)
    tpl_text = TEMPLATE_FILE.read_text(encoding="utf-8")

    # Template injects the stringset element fed from recipe.title.
    assert "book-title-stringset" in tpl_text, (
        "template must include a .book-title-stringset element "
        "populated from $title-prefix$ (recipe title)"
    )
    assert "$title-prefix$" in tpl_text

    # CSS rule for the stringset sets string-set: book-title and does NOT
    # use display: none (WeasyPrint skips string-set on display:none).
    stringset_rule_re = re.compile(r"\.book-title-stringset\s*\{([^}]*)\}", re.DOTALL)
    m = stringset_rule_re.search(css_text)
    assert m, "CSS must declare a .book-title-stringset rule"
    rule_body = m.group(1)
    assert "string-set" in rule_body and "book-title" in rule_body, (
        "the rule must set the book-title named string"
    )
    assert "display: none" not in rule_body, (
        "WeasyPrint strips display:none elements before string-set is "
        "collected; use position:absolute+visibility:hidden instead"
    )

    # @page rules must use string(book-title), not a literal title.
    top_right_re = re.compile(r"@top-right\s*\{([^}]*)\}", re.DOTALL)
    found = top_right_re.findall(css_text)
    assert found, "CSS must declare at least one @top-right margin-box rule"
    # At least one @top-right block must pull from string(book-title).
    assert any("string(book-title)" in block for block in found), (
        "at least one @top-right margin-box must use string(book-title) "
        "so the running header reflects the recipe title"
    )
    # None may hardcode the sample title literally.
    for block in found:
        # Allow the word in a comment; check only CSS content-property values.
        content_re = re.compile(r'content\s*:\s*"([^"]*)"', re.DOTALL)
        for val in content_re.findall(block):
            assert "Mini Test Book" not in val, (
                "@top-right content string literal contains the sample title -- "
                "the running header regressed to a hardcoded book title"
            )


@pytest.mark.skipif(
    os.name != "nt",
    reason="guards Windows absolute image URLs produced by the local build path",
)
def test_weasyprint_api_renders_windows_absolute_image_paths(tmp_path):
    """Pandoc emits C:/... image paths; the Python API must load them as files."""
    try:
        from pypdf import PdfReader
        from pypdf.generic import IndirectObject
    except ImportError:
        pytest.skip("pypdf required for image resource assertions")

    css = tmp_path / "book.css"
    css.write_text(
        "@page { size: Letter; margin: 1in; } img { width: 1in; height: 1in; }",
        encoding="utf-8",
    )
    template = tmp_path / "template.html"
    template.write_text("", encoding="utf-8")
    image_dir = tmp_path / "art with spaces"
    image_dir.mkdir()
    image_path = image_dir / "spot image.png"
    Image.new("RGB", (32, 32), color="red").save(image_path)
    src = quote(image_path.as_posix(), safe="/:")

    out_pdf = tmp_path / "image-smoke.pdf"
    ctx = pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=template,
        css_files=[css],
        lua_filters=[],
        resource_paths=[],
    )
    pipeline.render_html_to_pdf(
        f'<!doctype html><html><body><img src="{src}" /></body></html>',
        out_pdf,
        ctx,
    )

    image_count = 0
    for page in PdfReader(str(out_pdf)).pages:
        xobjects = (page.get("/Resources") or {}).get("/XObject") or {}
        for obj in xobjects.values():
            if isinstance(obj, IndirectObject):
                obj = obj.get_object()
            if obj.get("/Subtype") == "/Image":
                image_count += 1

    assert image_count >= 1


def test_local_weasyprint_fetcher_avoids_file_url_response(tmp_path):
    """Local assets are fetched as bytes, avoiding Windows file-association scans."""
    image_path = tmp_path / "asset.png"
    Image.new("RGB", (8, 8), color="red").save(image_path)

    response = pipeline._WEASYPRINT_URL_FETCHER(image_path.resolve().as_uri())
    try:
        assert response.content_type == "image/png"
        assert response.path is None
        assert response.read().startswith(b"\x89PNG")
    finally:
        response.close()


def test_page_art_merge_preserves_pdf_outline(tmp_path):
    """Page-art PDF rewriting must keep Chrome's sidebar table of contents."""
    try:
        from pypdf import PdfReader
    except ImportError:
        pytest.skip("pypdf required for outline assertions")

    css = tmp_path / "book.css"
    css.write_text("@page { size: Letter; margin: 1in; }", encoding="utf-8")
    template = tmp_path / "template.html"
    template.write_text("", encoding="utf-8")
    out_pdf = tmp_path / "outlined-page-art.pdf"

    ctx = pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=template,
        css_files=[css],
        lua_filters=[],
        resource_paths=[],
    )

    pipeline.render_html_to_pdf(
        """
        <!doctype html>
        <html>
          <body>
            <h1>Rules Reference</h1>
            <p>Opening text.</p>
            <h2>Actions</h2>
            <p>More text.</p>
          </body>
        </html>
        """,
        out_pdf,
        ctx,
        page_damage_catalog=PageDamageCatalog(enabled=True),
    )

    assert _outline_titles(PdfReader(str(out_pdf)).outline) == [
        "Rules Reference",
        "Actions",
    ]


def test_fast_page_damage_pass_renders_real_overlay(tmp_path):
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF required for image resource assertions")

    css = tmp_path / "book.css"
    css.write_text("@page { size: Letter; margin: 1in; }", encoding="utf-8")
    template = tmp_path / "template.html"
    template.write_text("", encoding="utf-8")
    damage_art = tmp_path / "wear-coffee-small-01.png"
    Image.new("RGBA", (40, 40), color=(80, 40, 20, 120)).save(damage_art)
    out_pdf = tmp_path / "fast-page-damage.pdf"

    ctx = pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=template,
        css_files=[css],
        lua_filters=[],
        resource_paths=[],
        page_damage_mode="fast",
    )
    pipeline.render_html_to_pdf(
        """
        <!doctype html>
        <html>
          <body>
            <h1>Rules Reference</h1>
            <p>Opening text.</p>
          </body>
        </html>
        """,
        out_pdf,
        ctx,
        page_damage_catalog=PageDamageCatalog(
            enabled=True,
            seed="fast-overlay-test",
            density=1.0,
            max_assets_per_page=1,
            assets=[
                PageDamageAsset(
                    id="wear-coffee-small-01",
                    art_path=damage_art,
                    family="coffee",
                    size="small",
                )
            ],
        ),
    )

    doc = fitz.open(out_pdf)
    try:
        image_count = sum(len(page.get_images(full=True)) for page in doc)
    finally:
        doc.close()

    assert out_pdf.read_bytes().startswith(b"%PDF")
    assert image_count >= 1


def test_pdf_render_settings_cap_oversized_embedded_image(tmp_path):
    """WeasyPrint should downsample raster art to rendered-size DPI caps."""
    try:
        import fitz
    except ImportError:
        pytest.skip("PyMuPDF required for embedded image assertions")

    css = tmp_path / "book.css"
    css.write_text(
        "@page { size: Letter; margin: 1in; } img { width: 2in; height: 2in; }",
        encoding="utf-8",
    )
    template = tmp_path / "template.html"
    template.write_text("", encoding="utf-8")
    image_path = tmp_path / "oversized.png"
    Image.new("RGB", (1200, 1200), color="red").save(image_path)
    src = quote(image_path.as_posix(), safe="/:")

    out_pdf = tmp_path / "optimized-image.pdf"
    ctx = pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=template,
        css_files=[css],
        lua_filters=[],
        resource_paths=[],
        pdf_settings=pipeline.PdfRenderSettings(
            optimize_images=True,
            dpi=100,
            jpeg_quality=80,
        ),
    )
    pipeline.render_html_to_pdf(
        f'<!doctype html><html><body><img src="{src}" /></body></html>',
        out_pdf,
        ctx,
    )

    doc = fitz.open(out_pdf)
    try:
        image_sizes: list[tuple[int, int]] = []
        for page in doc:
            for raw_image in page.get_images(full=True):
                extracted = doc.extract_image(raw_image[0])
                image_sizes.append((extracted["width"], extracted["height"]))
    finally:
        doc.close()

    assert image_sizes
    assert max(max(size) for size in image_sizes) <= 200


def test_pagination_report_and_fix_mode_render(tmp_path):
    css = tmp_path / "book.css"
    css.write_text(
        "@page { size: Letter; margin: 1in; } "
        ".spacer { height: 8.4in; } h1, h2 { margin: 0; }",
        encoding="utf-8",
    )
    template = tmp_path / "template.html"
    template.write_text("", encoding="utf-8")
    report = tmp_path / "pagination-report.md"
    out_pdf = tmp_path / "pagination-fix.pdf"
    ctx = pipeline.RenderContext(
        pandoc="pandoc",
        weasyprint="weasyprint",
        template=template,
        css_files=[css],
        lua_filters=[],
        resource_paths=[],
        pagination_mode="fix",
        pagination_report_path=report,
    )

    pipeline.render_html_to_pdf(
        """
        <!doctype html>
        <html>
          <body>
            <h1>Rules</h1>
            <div class="spacer"></div>
            <h2 id="late-actions">Late Actions</h2>
          </body>
        </html>
        """,
        out_pdf,
        ctx,
    )

    text = report.read_text(encoding="utf-8")
    assert out_pdf.is_file()
    assert "Pagination Report" in text
    assert "Badness" in text
    assert "Auto-fix" in text


def test_build_outputs_supports_parallel_fast_draft(
    mini_recipe_path,
    has_external_tools,
    tmp_path,
):
    if not has_external_tools["obsidian-export"]:
        pytest.skip("obsidian-export not installed")

    recipe = load_recipe(mini_recipe_path)
    recipe.output_dir_override = tmp_path / "output"
    recipe.cache_dir_override = tmp_path / "cache"
    manifest = build_manifest(recipe)
    tools = export.discover_tools()
    request = build.BuildRequest(
        recipe=recipe,
        manifest=manifest,
        scope=build.BuildScope.ALL,
        profile=OutputProfile.DRAFT,
        force=True,
        jobs=2,
        pagination_mode=PaginationMode.REPORT,
        draft_mode=DraftMode.FAST,
    )

    result = build.build_outputs(tools, request)

    assert result.produced
    assert all(path.is_file() for path in result.produced)
    assert all(recipe.generated_root in path.parents for path in result.produced)
