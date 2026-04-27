"""Unit tests for deterministic page-wear planning."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from papercrown import build, page_damage
from papercrown.manifest import PageDamageAsset, PageDamageCatalog
from papercrown.options import OutputProfile
from papercrown.page_damage import (
    page_has_surface_art,
    plan_page_damage,
    should_skip_page,
)


class _Element:
    def __init__(self, classes: str, tag: str = "") -> None:
        self.classes = classes
        self.tag = tag

    def get(self, key: str) -> str | None:
        return self.classes if key == "class" else None


class _Box:
    def __init__(
        self,
        *,
        classes: str = "",
        page_type_name: str = "",
        tag: str = "",
    ) -> None:
        self.element = _Element(classes, tag) if classes or tag else None
        self.page_type = SimpleNamespace(name=page_type_name)

    def descendants(self) -> list[_Box]:
        return [self]


class _Page:
    def __init__(
        self,
        *,
        classes: str = "",
        page_type_name: str = "",
        tag: str = "",
    ) -> None:
        self._page_box = _Box(
            classes=classes,
            page_type_name=page_type_name,
            tag=tag,
        )


class _Document:
    def __init__(self, pages: list[_Page]) -> None:
        self.pages = pages


def _asset(tmp_path: Path, family: str, size: str) -> PageDamageAsset:
    return PageDamageAsset(
        id=f"wear-{family}-{size}-01",
        art_path=tmp_path / f"wear-{family}-{size}-01.png",
        family=family,
        size=size,
    )


def _catalog(tmp_path: Path, *, density: float = 1.0) -> PageDamageCatalog:
    return PageDamageCatalog(
        enabled=True,
        seed="test-seed",
        density=density,
        max_assets_per_page=2,
        opacity=0.3,
        skip=["cover", "toc", "divider", "splash"],
        assets=[
            _asset(tmp_path, "coffee", "medium"),
            _asset(tmp_path, "edge-tear", "small"),
            _asset(tmp_path, "nick-scratch", "tiny"),
            _asset(tmp_path, "printer-misfeed", "large"),
        ],
    )


def test_plan_page_damage_is_deterministic_and_capped(tmp_path):
    document = _Document([_Page(), _Page(), _Page(), _Page()])
    catalog = _catalog(tmp_path)

    first = plan_page_damage(document, catalog, recipe_title="Book")
    second = plan_page_damage(document, catalog, recipe_title="Book")

    assert first == second
    assert {placement.page_number for placement in first} == {1, 2, 3, 4}
    assert all(0.0 <= placement.opacity <= 1.0 for placement in first)
    assert all(placement.width_in > 0 for placement in first)
    assert all(
        count <= catalog.max_assets_per_page
        for count in Counter(placement.page_number for placement in first).values()
    )


def test_plan_page_damage_respects_skip_targets(tmp_path):
    document = _Document(
        [
            _Page(page_type_name="cover-page"),
            _Page(classes="toc"),
            _Page(page_type_name="divider-page"),
            _Page(classes="splash-page"),
            _Page(),
        ]
    )

    placements = plan_page_damage(document, _catalog(tmp_path), recipe_title="Book")

    assert {placement.page_number for placement in placements} == {5}


def test_plan_page_damage_prefers_soft_residue_over_edge_tears(tmp_path):
    document = _Document([_Page() for _ in range(80)])
    catalog = PageDamageCatalog(
        enabled=True,
        seed="soft-residue-test",
        density=1.0,
        max_assets_per_page=1,
        opacity=0.3,
        assets=[
            _asset(tmp_path, "smudge-grime", "medium"),
            _asset(tmp_path, "grease-fingerprint", "medium"),
            _asset(tmp_path, "tape-residue", "medium"),
            _asset(tmp_path, "edge-tear", "medium"),
        ],
    )

    placements = plan_page_damage(document, catalog, recipe_title="Book")
    counts = Counter(placement.asset.family for placement in placements)

    assert counts["edge-tear"] <= 2
    assert (
        counts["smudge-grime"] + counts["grease-fingerprint"] + counts["tape-residue"]
        >= 70
    )


def test_large_damage_size_is_sparing():
    sizes = [
        page_damage._weighted_size("large-size-test", slot_index)
        for slot_index in range(400)
    ]
    counts = Counter(sizes)

    assert counts["large"] <= 16
    assert counts["small"] > counts["large"] * 8
    assert counts["medium"] > counts["large"] * 4


def test_soft_residue_can_land_in_the_reading_field(tmp_path):
    asset = _asset(tmp_path, "smudge-grime", "medium")

    placement = page_damage._place_asset(
        asset,
        page_number=1,
        seed="seed-0",
        opacity=0.3,
    )

    assert placement.x_in > 1.0
    assert placement.y_in > 1.15
    assert placement.x_in + placement.width_in < 7.6
    assert placement.y_in + placement.width_in < 9.45


def test_edge_tears_are_kept_small_even_with_large_assets(tmp_path):
    asset = _asset(tmp_path, "edge-tear", "large")

    placement = page_damage._place_asset(
        asset,
        page_number=1,
        seed="seed-0",
        opacity=0.3,
    )

    assert placement.width_in <= 0.9


def test_fingerprints_are_kept_small_even_with_large_assets(tmp_path):
    asset = _asset(tmp_path, "grease-fingerprint", "large")

    placement = page_damage._place_asset(
        asset,
        page_number=1,
        seed="seed-0",
        opacity=0.3,
    )

    assert placement.width_in <= 0.68


def test_page_damage_image_optimization_uses_family_width_caps(tmp_path):
    source = tmp_path / "wear-grease-fingerprint-large-01.png"
    Image.new("RGBA", (1000, 1000), color=(0, 0, 0, 80)).save(source)
    asset = PageDamageAsset(
        id="wear-grease-fingerprint-large-01",
        art_path=source,
        family="grease-fingerprint",
        size="large",
    )

    optimized = build._optimized_page_damage_image(
        asset,
        profile=OutputProfile.PRINT,
        cache_root=tmp_path / "cache",
    )

    with Image.open(optimized) as result:
        assert max(result.size) <= 235


def test_should_skip_page_matches_page_type_and_classes():
    skip = ["cover", "toc", "divider", "splash"]

    assert should_skip_page(_Page(page_type_name="cover-page"), skip)
    assert should_skip_page(_Page(classes="toc"), skip)
    assert should_skip_page(_Page(classes="section-divider"), skip)
    assert should_skip_page(_Page(classes="splash-page"), skip)
    assert not should_skip_page(_Page(), skip)


def test_page_has_surface_art_matches_rendered_img_elements():
    assert page_has_surface_art(_Page(tag="img"))
    assert page_has_surface_art(_Page(tag="{http://www.w3.org/1999/xhtml}img"))
    assert not page_has_surface_art(_Page(classes="toc"))
    assert not page_has_surface_art(_Page())


def test_page_damage_overlay_png_is_transparent_when_empty():
    data = page_damage.render_page_damage_overlay_png([])

    assert data.startswith(b"\x89PNG")


def test_page_damage_image_png_is_tightly_bounded(tmp_path):
    source = tmp_path / "wear-coffee-small-01.png"
    Image.new("RGBA", (20, 10), color=(20, 10, 5, 80)).save(source)
    placement = page_damage.PageDamagePlacement(
        asset=PageDamageAsset(
            id="wear-coffee-small-01",
            art_path=source,
            family="coffee",
            size="small",
        ),
        page_number=1,
        x_in=1.0,
        y_in=2.0,
        width_in=1.0,
        rotation_deg=0.0,
        opacity=0.4,
    )

    rendered = page_damage.render_page_damage_image_png(placement)

    assert rendered.png.startswith(b"\x89PNG")
    assert rendered.x_in == 1.0
    assert rendered.y_in == 2.0
    assert rendered.width_in == 1.0
    assert rendered.height_in == 0.5


def test_disabled_empty_or_zero_density_catalog_has_no_placements(tmp_path):
    document = _Document([_Page()])
    catalog = _catalog(tmp_path, density=0.0)

    assert plan_page_damage(document, catalog, recipe_title="Book") == []
    disabled = PageDamageCatalog(enabled=False, assets=catalog.assets)
    empty = PageDamageCatalog(enabled=True, density=1.0, assets=[])
    assert plan_page_damage(document, disabled, recipe_title="Book") == []
    assert plan_page_damage(document, empty, recipe_title="Book") == []


def test_render_page_damage_overlay_pdf_is_transparent_page(tmp_path):
    source = tmp_path / "wear-coffee-small-01.png"
    Image.new("RGBA", (20, 20), color=(20, 10, 5, 80)).save(source)
    placement = page_damage.PageDamagePlacement(
        asset=PageDamageAsset(
            id="wear-coffee-small-01",
            art_path=source,
            family="coffee",
            size="small",
        ),
        page_number=1,
        x_in=1.0,
        y_in=1.0,
        width_in=0.5,
        rotation_deg=0.0,
        opacity=0.4,
    )

    pdf = page_damage.render_page_damage_overlay_pdf([placement])

    assert pdf.startswith(b"%PDF")
