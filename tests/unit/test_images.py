"""Unit tests for image diagnostics and cached optimization."""

from __future__ import annotations

from PIL import Image

from papercrown import images
from papercrown.diagnostics import DiagnosticSeverity
from papercrown.images import (
    diagnose_image,
    optimize_image,
    optimize_image_for_box,
    replace_markdown_image_refs_with_placeholders,
    rewrite_markdown_image_refs,
)
from papercrown.options import OutputProfile


def test_diagnose_image_reports_missing_file(tmp_path):
    diagnostics = diagnose_image(tmp_path / "missing.png")

    assert diagnostics[0].severity is DiagnosticSeverity.ERROR
    assert diagnostics[0].code == "image.missing"


def test_print_profile_writes_cached_high_quality_jpeg(tmp_path):
    image = tmp_path / "cover.png"
    cache = tmp_path / "cache"
    Image.new("RGB", (10, 10), color="red").save(image)

    optimized = optimize_image(image, profile=OutputProfile.PRINT, cache_root=cache)

    assert optimized != image.resolve()
    assert optimized.suffix == ".jpg"
    assert optimized.is_file()
    assert "print" in optimized.parts
    with Image.open(optimized) as result:
        assert result.size == (10, 10)


def test_digital_profile_writes_cached_resized_copy(tmp_path):
    image = tmp_path / "cover.png"
    cache = tmp_path / "cache"
    Image.new("RGB", (2600, 1200), color="red").save(image)

    optimized = optimize_image(image, profile=OutputProfile.DIGITAL, cache_root=cache)

    assert optimized != image.resolve()
    assert optimized.is_file()
    with Image.open(optimized) as result:
        assert max(result.size) == images.IMAGE_PROFILES["digital"].max_long_edge


def test_alpha_image_preserves_png_and_transparency(tmp_path):
    image = tmp_path / "transparent.png"
    cache = tmp_path / "cache"
    Image.new("RGBA", (500, 300), color=(255, 0, 0, 64)).save(image)

    optimized = optimize_image(
        image,
        profile=OutputProfile.DRAFT,
        cache_root=cache,
        max_long_edge=100,
    )

    assert optimized.suffix == ".png"
    with Image.open(optimized) as result:
        assert result.mode == "RGBA"
        assert max(result.size) == 100
        assert result.getpixel((0, 0))[3] == 64


def test_draft_profile_uses_fast_low_resolution_settings(tmp_path):
    image = tmp_path / "cover.png"
    cache = tmp_path / "cache"
    Image.new("RGB", (2600, 1200), color="red").save(image)

    optimized = optimize_image(image, profile=OutputProfile.DRAFT, cache_root=cache)

    with Image.open(optimized) as result:
        assert max(result.size) == 900
    assert not list((cache / "draft").glob("*.tmp"))


def test_draft_placeholder_rewrite_only_replaces_local_images(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    image = art / "spot.png"
    Image.new("RGB", (10, 10), color="red").save(image)

    rewritten = images.replace_markdown_image_refs_with_placeholders(
        "![Spot](spot.png)\n![External](https://example.com/a.png)",
        search_roots=[art],
    )

    assert "Art omitted in fast draft: Spot" in rewritten
    assert "https://example.com/a.png" in rewritten


def test_draft_placeholder_rewrite_consumes_pandoc_image_attrs(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    image = art / "frame.png"
    Image.new("RGB", (10, 10), color="red").save(image)

    rewritten = images.replace_markdown_image_refs_with_placeholders(
        "![](frame.png){.section-divider-art .wide}",
        search_roots=[art],
    )

    assert "Art omitted in fast draft: frame" in rewritten
    assert "}{.section-divider-art" not in rewritten
    assert "::::{." not in rewritten


def test_optimized_image_rewrite_preserves_pandoc_image_attrs(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    image = art / "frame.png"
    Image.new("RGB", (10, 10), color="red").save(image)

    rewritten = rewrite_markdown_image_refs(
        "![](frame.png){.section-divider-art .wide}",
        search_roots=[art],
        profile=OutputProfile.DRAFT,
        cache_root=tmp_path / "cache",
    )

    assert "{.section-divider-art .wide}" in rewritten


def test_box_optimization_uses_profile_dpi_cap(tmp_path):
    image = tmp_path / "ornament.png"
    cache = tmp_path / "cache"
    Image.new("RGB", (1000, 1000), color="red").save(image)

    optimized = optimize_image_for_box(
        image,
        profile=OutputProfile.PRINT,
        cache_root=cache,
        max_width_in=0.5,
        max_height_in=0.5,
        scale_margin=1.0,
    )

    with Image.open(optimized) as result:
        assert result.size == (150, 150)


def test_cache_key_changes_when_optimization_settings_change(tmp_path):
    image = tmp_path / "cover.png"
    cache = tmp_path / "cache"
    Image.new("RGB", (600, 600), color="red").save(image)

    larger = optimize_image(
        image,
        profile=OutputProfile.DIGITAL,
        cache_root=cache,
        max_long_edge=300,
    )
    smaller = optimize_image(
        image,
        profile=OutputProfile.DIGITAL,
        cache_root=cache,
        max_long_edge=200,
    )

    assert larger != smaller
    with Image.open(larger) as large_result, Image.open(smaller) as small_result:
        assert large_result.size == (300, 300)
        assert small_result.size == (200, 200)


def test_optimization_session_memoizes_repeated_image_hashes(
    tmp_path,
    monkeypatch,
):
    image = tmp_path / "cover.png"
    cache = tmp_path / "cache"
    Image.new("RGB", (600, 600), color="red").save(image)
    calls = 0
    original = images._image_cache_key

    def count_cache_key(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(images, "_image_cache_key", count_cache_key)
    session = images.ImageOptimizationSession()

    first = optimize_image(
        image,
        profile=OutputProfile.DRAFT,
        cache_root=cache,
        session=session,
    )
    second = optimize_image(
        image,
        profile=OutputProfile.DRAFT,
        cache_root=cache,
        session=session,
    )

    assert first == second
    assert calls == 1


def test_rewrite_markdown_image_refs_uses_cached_copy(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    image = art / "spot.png"
    Image.new("RGB", (2600, 1200), color="red").save(image)

    rewritten = rewrite_markdown_image_refs(
        "![Spot](spot.png)",
        search_roots=[art],
        profile=OutputProfile.DRAFT,
        cache_root=tmp_path / "cache",
    )

    assert "spot.png" not in rewritten
    assert "/cache/draft" in rewritten.replace("\\", "/")


def test_replace_markdown_image_refs_with_placeholders(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    image = art / "spot.png"
    Image.new("RGB", (10, 10), color="red").save(image)

    rewritten = replace_markdown_image_refs_with_placeholders(
        "![Spot Art](spot.png)",
        search_roots=[art],
    )

    assert "draft-art-placeholder" in rewritten
    assert "Spot Art" in rewritten
    assert "spot.png" not in rewritten
