"""Unit tests for layout-aware filler selection."""

from __future__ import annotations

from pathlib import Path

import papercrown.fillers as fillers_mod
from papercrown.fillers import (
    FillerMeasurement,
    FillerPlacement,
    _select_filler_with_reason,
    inject_fillers,
    plan_fillers,
    select_filler,
)
from papercrown.manifest import FillerAsset, FillerCatalog, FillerSlot


def _catalog(tmp_path: Path) -> FillerCatalog:
    return FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=0.65,
                max_space_in=3.5,
                shapes=["tailpiece", "small-wide", "bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                id="small",
                art_path=tmp_path / "small.png",
                shape="tailpiece",
                height_in=0.65,
            ),
            FillerAsset(
                id="large",
                art_path=tmp_path / "large.png",
                shape="bottom-band",
                height_in=2.2,
            ),
        ],
    )


def test_selection_chooses_largest_fitting_asset(tmp_path):
    chosen = select_filler(
        _catalog(tmp_path),
        FillerMeasurement(
            slot_id="slot-a",
            slot_name="chapter-end",
            chapter_slug="a",
            page_number=3,
            available_in=2.7,
        ),
        recipe_title="Book",
    )

    assert chosen is not None
    assert chosen.id == "large"


def test_page_finish_uses_flow_mode_and_requires_page_finish_slot(tmp_path):
    asset = FillerAsset(
        id="page",
        art_path=tmp_path / "page-finish-general-finale-01.png",
        shape="page-finish",
        height_in=5.25,
    )
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=0.65,
                max_space_in=6.0,
                shapes=["page-finish"],
            )
        },
        assets=[asset],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-a",
            slot_name="chapter-end",
            chapter_slug="setting-primer",
            page_number=3,
            available_in=5.8,
        ),
        recipe_title="Book",
    )

    assert chosen is asset
    assert fillers_mod._placement_mode(asset) == "flow"


def test_bottom_band_slots_do_not_accept_page_finish_assets(tmp_path):
    asset = FillerAsset(
        id="page",
        art_path=tmp_path / "page-finish-general-finale-01.png",
        shape="page-finish",
        height_in=5.25,
    )
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=0.65,
                max_space_in=6.0,
                shapes=["bottom-band"],
            )
        },
        assets=[asset],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-a",
            slot_name="chapter-end",
            chapter_slug="setting-primer",
            page_number=3,
            available_in=5.8,
        ),
        recipe_title="Book",
    )

    assert chosen is None


def test_plate_is_preferred_for_medium_large_gap(tmp_path):
    plate = FillerAsset(
        id="plate",
        art_path=tmp_path / "filler-plate-general-market-01.png",
        shape="plate",
        height_in=3.5,
    )
    bottom = FillerAsset(
        id="bottom",
        art_path=tmp_path / "filler-bottom-general-band-01.png",
        shape="bottom-band",
        height_in=3.5,
    )
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=0.65,
                max_space_in=4.5,
                shapes=["plate", "bottom-band"],
            )
        },
        assets=[bottom, plate],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-a",
            slot_name="chapter-end",
            chapter_slug="setting-primer",
            page_number=3,
            available_in=4.1,
        ),
        recipe_title="Book",
    )

    assert chosen is plate


def test_selection_returns_none_when_space_is_insufficient(tmp_path):
    chosen = select_filler(
        _catalog(tmp_path),
        FillerMeasurement(
            slot_id="slot-a",
            slot_name="chapter-end",
            chapter_slug="a",
            page_number=3,
            available_in=0.7,
        ),
        recipe_title="Book",
    )

    assert chosen is None


def test_tiny_tailpiece_is_rejected_for_large_blank_region(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=0.65,
                max_space_in=3.5,
                shapes=["tailpiece"],
            )
        },
        assets=[
            FillerAsset(
                "tail",
                tmp_path / "ornament-tailpiece-airlock.png",
                "tailpiece",
                0.65,
            )
        ],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-a",
            slot_name="chapter-end",
            chapter_slug="setting-primer",
            page_number=3,
            available_in=3.0,
            preferred_asset_id="tail",
        ),
        recipe_title="Book",
    )

    assert chosen is None


def test_contextual_wide_art_requires_matching_chapter(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=0.65,
                max_space_in=3.5,
                shapes=["bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "auto-gear-ranged-loadout",
                tmp_path / "gear-ranged-loadout.png",
                "bottom-band",
                2.2,
            )
        ],
    )
    setting_measurement = FillerMeasurement(
        slot_id="slot-setting",
        slot_name="chapter-end",
        chapter_slug="setting-primer",
        page_number=4,
        available_in=3.0,
    )
    combat_measurement = FillerMeasurement(
        slot_id="slot-combat",
        slot_name="chapter-end",
        chapter_slug="combat",
        page_number=5,
        available_in=3.0,
    )

    assert select_filler(catalog, setting_measurement, recipe_title="Book") is None
    chosen = select_filler(catalog, combat_measurement, recipe_title="Book")

    assert chosen is not None
    assert chosen.id == "auto-gear-ranged-loadout"


def test_vista_art_is_setting_context_only_when_explicit(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "class-end": FillerSlot(
                name="class-end",
                min_space_in=1.2,
                max_space_in=3.5,
                shapes=["bottom-band"],
            ),
            "background-section-end": FillerSlot(
                name="background-section-end",
                min_space_in=1.2,
                max_space_in=3.5,
                shapes=["bottom-band"],
            ),
        },
        assets=[
            FillerAsset(
                "auto-vista-dockyard",
                tmp_path / "vista-dockyard.png",
                "bottom-band",
                2.2,
            )
        ],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-class",
            slot_name="class-end",
            chapter_slug="shepherd",
            page_number=12,
            available_in=3.0,
        ),
        recipe_title="Book",
    )

    assert chosen is None

    setting_chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-setting",
            slot_name="background-section-end",
            chapter_slug="backgrounds",
            page_number=13,
            available_in=3.0,
        ),
        recipe_title="Book",
    )

    assert setting_chosen is not None
    assert setting_chosen.id == "auto-vista-dockyard"


def test_purpose_named_fillers_match_only_their_layout_context(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "frame-family-end": FillerSlot(
                name="frame-family-end",
                min_space_in=1.2,
                max_space_in=3.5,
                shapes=["bottom-band"],
            ),
            "class-end": FillerSlot(
                name="class-end",
                min_space_in=1.2,
                max_space_in=3.5,
                shapes=["bottom-band"],
            ),
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=1.2,
                max_space_in=3.5,
                shapes=["bottom-band"],
            ),
        },
        assets=[
            FillerAsset(
                "frame",
                tmp_path / "filler-bottom-frame-bioform-01.png",
                "bottom-band",
                2.4,
            ),
            FillerAsset(
                "class",
                tmp_path / "filler-bottom-class-field-kit-01.png",
                "bottom-band",
                2.4,
            ),
            FillerAsset(
                "combat",
                tmp_path / "filler-bottom-combat-shell-scatter-01.png",
                "bottom-band",
                2.4,
            ),
        ],
    )

    frame_chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-frame",
            slot_name="frame-family-end",
            chapter_slug="frames",
            page_number=10,
            available_in=3.0,
        ),
        recipe_title="Book",
    )
    class_chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-class",
            slot_name="class-end",
            chapter_slug="shepherd",
            page_number=11,
            available_in=3.0,
        ),
        recipe_title="Book",
    )
    combat_chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-combat",
            slot_name="chapter-end",
            chapter_slug="combat",
            page_number=12,
            available_in=3.0,
        ),
        recipe_title="Book",
    )
    language_chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-languages",
            slot_name="chapter-end",
            chapter_slug="languages",
            page_number=13,
            available_in=3.0,
        ),
        recipe_title="Book",
    )

    assert frame_chosen is not None
    assert frame_chosen.id == "frame"
    assert class_chosen is not None
    assert class_chosen.id == "class"
    assert combat_chosen is not None
    assert combat_chosen.id == "combat"
    assert language_chosen is None


def test_explicit_filler_context_selects_reference_assets_for_original_slots(
    tmp_path,
):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["page-finish"],
            )
        },
        assets=[
            FillerAsset(
                "reference",
                tmp_path / "page-finish-reference-archive-terminal-01.png",
                "page-finish",
                5.25,
            ),
            FillerAsset(
                "combat",
                tmp_path / "page-finish-combat-airlock-aftermath-01.png",
                "page-finish",
                5.25,
            ),
            FillerAsset(
                "general",
                tmp_path / "page-finish-general-observation-deck-01.png",
                "page-finish",
                5.25,
            ),
        ],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-original",
            slot_name="chapter-end",
            chapter_slug="original-conditions",
            page_number=12,
            available_in=7.0,
            context="reference",
        ),
        recipe_title="Book",
    )

    assert chosen is not None
    assert chosen.id == "reference"


def test_explicit_filler_context_distinguishes_equipment_from_combat(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "section-end": FillerSlot(
                name="section-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["page-finish"],
            )
        },
        assets=[
            FillerAsset(
                "combat",
                tmp_path / "page-finish-combat-airlock-aftermath-01.png",
                "page-finish",
                5.25,
            ),
            FillerAsset(
                "equipment",
                tmp_path / "page-finish-equipment-cargo-lockers-01.png",
                "page-finish",
                5.25,
            ),
            FillerAsset(
                "general",
                tmp_path / "page-finish-general-service-corridor-01.png",
                "page-finish",
                5.25,
            ),
        ],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-weapons",
            slot_name="section-end",
            chapter_slug="combat",
            page_number=24,
            available_in=7.0,
            section_slug="weapons-armor",
            context="equipment",
        ),
        recipe_title="Book",
    )

    assert chosen is not None
    assert chosen.id == "equipment"


def test_selection_is_deterministic_for_same_seed(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=0.65,
                max_space_in=3.5,
                shapes=["tailpiece"],
            )
        },
        assets=[
            FillerAsset("a", tmp_path / "a.png", "tailpiece", 0.65),
            FillerAsset("b", tmp_path / "b.png", "tailpiece", 0.65),
        ],
    )
    measurement = FillerMeasurement(
        slot_id="slot-a",
        slot_name="chapter-end",
        chapter_slug="a",
        page_number=3,
        available_in=1.0,
    )

    first = select_filler(catalog, measurement, recipe_title="Book")
    second = select_filler(catalog, measurement, recipe_title="Book")

    assert first == second


def test_selection_prefers_unused_assets_when_available(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=1.2,
                max_space_in=3.5,
                shapes=["bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "a",
                tmp_path / "filler-bottom-general-a.png",
                "bottom-band",
                2.4,
            ),
            FillerAsset(
                "b",
                tmp_path / "filler-bottom-general-b.png",
                "bottom-band",
                2.4,
            ),
        ],
    )
    measurement = FillerMeasurement(
        slot_id="slot-a",
        slot_name="chapter-end",
        chapter_slug="languages",
        page_number=3,
        available_in=3.0,
    )

    first, _ = _select_filler_with_reason(
        catalog,
        measurement,
        recipe_title="Book",
        used_asset_ids=set(),
    )
    assert first is not None
    second, _ = _select_filler_with_reason(
        catalog,
        measurement,
        recipe_title="Book",
        used_asset_ids={first.id},
    )

    assert second is not None
    assert second.id != first.id


def test_medium_gap_prefers_centered_small_wide_asset(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "class-end": FillerSlot(
                name="class-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["small-wide", "bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "wide",
                tmp_path / "filler-wide-class-helmet.png",
                "small-wide",
                1.25,
            ),
            FillerAsset(
                "bottom",
                tmp_path / "filler-bottom-class-dock.png",
                "bottom-band",
                2.4,
            ),
        ],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-class",
            slot_name="class-end",
            chapter_slug="shepherd",
            page_number=10,
            available_in=2.8,
        ),
        recipe_title="Book",
    )

    assert chosen is not None
    assert chosen.id == "wide"


def test_medium_gap_can_use_spot_object_filler(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "class-end": FillerSlot(
                name="class-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["spot", "small-wide", "bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "spot",
                tmp_path / "filler-spot-class-helmet.png",
                "spot",
                1.35,
            ),
            FillerAsset(
                "wide",
                tmp_path / "filler-wide-class-console.png",
                "small-wide",
                1.25,
            ),
        ],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-class",
            slot_name="class-end",
            chapter_slug="shepherd",
            page_number=10,
            available_in=2.6,
        ),
        recipe_title="Book",
    )

    assert chosen is not None
    assert chosen.id == "spot"


def test_bottom_gap_prefers_bottom_band_over_small_wide_asset(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "class-end": FillerSlot(
                name="class-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["small-wide", "bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "wide",
                tmp_path / "filler-wide-class-helmet.png",
                "small-wide",
                1.25,
            ),
            FillerAsset(
                "bottom",
                tmp_path / "filler-bottom-class-dock.png",
                "bottom-band",
                2.4,
            ),
        ],
    )

    chosen = select_filler(
        catalog,
        FillerMeasurement(
            slot_id="slot-class",
            slot_name="class-end",
            chapter_slug="shepherd",
            page_number=10,
            available_in=4.0,
        ),
        recipe_title="Book",
    )

    assert chosen is not None
    assert chosen.id == "bottom"


def test_large_gap_rejects_small_spot_art(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "class-end": FillerSlot(
                name="class-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["spot", "bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "spot",
                tmp_path / "filler-spot-class-helmet.png",
                "spot",
                1.35,
            )
        ],
    )

    chosen, reason = _select_filler_with_reason(
        catalog,
        FillerMeasurement(
            slot_id="slot-class",
            slot_name="class-end",
            chapter_slug="shepherd",
            page_number=10,
            available_in=4.0,
        ),
        recipe_title="Book",
    )

    assert chosen is None
    assert reason == "no size-matched context asset"


def test_huge_gap_requires_page_finisher_art(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "bottom",
                tmp_path / "filler-bottom-general-dock.png",
                "bottom-band",
                2.4,
            )
        ],
    )

    chosen, reason = _select_filler_with_reason(
        catalog,
        FillerMeasurement(
            slot_id="slot-chapter",
            slot_name="chapter-end",
            chapter_slug="languages",
            page_number=10,
            available_in=7.0,
        ),
        recipe_title="Book",
    )

    assert chosen is None
    assert reason == "no size-matched context asset"


def test_page_finish_is_rejected_when_it_would_render_too_small(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["page-finish"],
            )
        },
        assets=[
            FillerAsset(
                "page",
                tmp_path / "page-finish-reference-terminal.png",
                "page-finish",
                5.25,
            )
        ],
    )

    chosen, reason = _select_filler_with_reason(
        catalog,
        FillerMeasurement(
            slot_id="slot-reference",
            slot_name="chapter-end",
            chapter_slug="original-conditions",
            page_number=12,
            available_in=2.9,
            context="reference",
        ),
        recipe_title="Book",
    )

    assert chosen is None
    assert reason == "no size-matched context asset"


def test_page_finish_context_and_height_can_win_for_huge_gap(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "frame-family-end": FillerSlot(
                name="frame-family-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["small-wide", "page-finish"],
            ),
            "class-end": FillerSlot(
                name="class-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["small-wide", "page-finish"],
            ),
        },
        assets=[
            FillerAsset(
                "page",
                tmp_path / "page-finish-frame-vault.png",
                "page-finish",
                5.25,
            ),
            FillerAsset(
                "bottom",
                tmp_path / "filler-bottom-frame-cradle.png",
                "bottom-band",
                2.4,
            ),
        ],
    )

    chosen, _ = _select_filler_with_reason(
        catalog,
        FillerMeasurement(
            slot_id="slot-frame",
            slot_name="frame-family-end",
            chapter_slug="frames",
            page_number=2,
            available_in=7.0,
        ),
        recipe_title="Book",
    )

    assert chosen is not None
    assert chosen.id == "page"
    assert (
        select_filler(
            catalog,
            FillerMeasurement(
                slot_id="slot-class",
                slot_name="class-end",
                chapter_slug="shepherd",
                page_number=11,
                available_in=7.0,
            ),
            recipe_title="Book",
        )
        is None
    )


def test_page_gap_uses_page_finish_and_downscales_to_usable_height(
    tmp_path,
    monkeypatch,
):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "frame-family-end": FillerSlot(
                name="frame-family-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["small-wide", "page-finish"],
            )
        },
        assets=[
            FillerAsset(
                "wide",
                tmp_path / "filler-wide-frame-toolkit.png",
                "small-wide",
                1.25,
            ),
            FillerAsset(
                "bottom",
                tmp_path / "filler-bottom-frame-cradle.png",
                "bottom-band",
                2.4,
            ),
            FillerAsset(
                "page",
                tmp_path / "page-finish-frame-vault.png",
                "page-finish",
                5.25,
            ),
        ],
    )
    monkeypatch.setattr(
        fillers_mod,
        "measure_slots",
        lambda document: [
            FillerMeasurement(
                slot_id="slot-frame",
                slot_name="frame-family-end",
                chapter_slug="frames",
                page_number=2,
                available_in=5.2,
            )
        ],
    )

    placements = plan_fillers(object(), catalog, recipe_title="Book")

    assert len(placements) == 1
    assert placements[0].asset.id == "page"
    assert round(placements[0].render_height_in, 2) == 4.93
    assert placements[0].fill_ratio == 1.0


def test_one_filler_max_per_page_is_enforced(tmp_path, monkeypatch):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "short",
                tmp_path / "filler-bottom-general-short.png",
                "bottom-band",
                2.4,
            ),
            FillerAsset(
                "tall",
                tmp_path / "filler-bottom-general-tall.png",
                "bottom-band",
                3.0,
            ),
        ],
    )
    monkeypatch.setattr(
        fillers_mod,
        "measure_slots",
        lambda document: [
            FillerMeasurement(
                slot_id="slot-a",
                slot_name="chapter-end",
                chapter_slug="languages",
                page_number=4,
                available_in=3.5,
            ),
            FillerMeasurement(
                slot_id="slot-b",
                slot_name="chapter-end",
                chapter_slug="languages",
                page_number=4,
                available_in=4.0,
            ),
        ],
    )

    placements = plan_fillers(object(), catalog, recipe_title="Book")

    assert len(placements) == 1
    assert placements[0].page_number == 4


def test_reuse_is_marked_and_warned_only_when_unavoidable(tmp_path, monkeypatch):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=0.65,
                max_space_in=2.0,
                shapes=["tailpiece"],
            )
        },
        assets=[
            FillerAsset(
                "only",
                tmp_path / "ornament-tailpiece-only.png",
                "tailpiece",
                0.65,
            )
        ],
    )
    monkeypatch.setattr(
        fillers_mod,
        "measure_slots",
        lambda document: [
            FillerMeasurement(
                slot_id="slot-a",
                slot_name="chapter-end",
                chapter_slug="languages",
                page_number=3,
                available_in=1.4,
            ),
            FillerMeasurement(
                slot_id="slot-b",
                slot_name="chapter-end",
                chapter_slug="languages",
                page_number=4,
                available_in=1.4,
            ),
        ],
    )

    placements = plan_fillers(object(), catalog, recipe_title="Book")
    warnings = fillers_mod.filler_warnings(placements)

    assert len(placements) == 2
    assert placements[0].reused_from is None
    assert placements[1].reused_from is not None
    assert warnings == [
        "filler warning: reused only on p4 slot-b; first used on p3 slot-a"
    ]


def test_prominent_reuse_is_skipped_when_used_recently(tmp_path, monkeypatch):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "only",
                tmp_path / "filler-bottom-general-only.png",
                "bottom-band",
                2.4,
            )
        ],
    )
    monkeypatch.setattr(
        fillers_mod,
        "measure_slots",
        lambda document: [
            FillerMeasurement(
                slot_id="slot-a",
                slot_name="chapter-end",
                chapter_slug="languages",
                page_number=3,
                available_in=3.4,
            ),
            FillerMeasurement(
                slot_id="slot-b",
                slot_name="chapter-end",
                chapter_slug="languages",
                page_number=4,
                available_in=3.4,
            ),
        ],
    )

    placements, decisions = fillers_mod.plan_filler_decisions(
        object(),
        catalog,
        recipe_title="Book",
    )

    assert len(placements) == 1
    assert placements[0].slot_id == "slot-a"
    assert decisions[1].reason == "matching filler already used recently"


def test_source_boundary_page_finishers_are_skipped_for_short_sections(tmp_path):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "section-end": FillerSlot(
                name="section-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["page-finish"],
            )
        },
        assets=[
            FillerAsset(
                "page",
                tmp_path / "page-finish-powers-chaos-table-01.png",
                "page-finish",
                5.25,
            )
        ],
    )

    chosen, reason = _select_filler_with_reason(
        catalog,
        FillerMeasurement(
            slot_id="slot-small-source",
            slot_name="section-end",
            chapter_slug="powers",
            page_number=12,
            available_in=7.0,
            slot_kind="source-boundary",
            context="powers",
        ),
        recipe_title="Book",
    )

    assert chosen is None
    assert reason == "not enough intervening content"


def test_missing_art_report_summarizes_unfilled_slots(tmp_path, monkeypatch):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "frame-family-end": FillerSlot(
                name="frame-family-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["spot", "small-wide", "bottom-band"],
            )
        },
        assets=[],
    )
    monkeypatch.setattr(
        fillers_mod,
        "measure_slots",
        lambda document: [
            FillerMeasurement(
                slot_id="slot-frame",
                slot_name="frame-family-end",
                chapter_slug="frames",
                page_number=22,
                available_in=3.4,
                section_slug="baseline-human",
                section_title="Baseline Human",
            )
        ],
    )
    out = tmp_path / "book.missing-art.md"

    fillers_mod.write_missing_art_report(
        out,
        object(),
        catalog,
        recipe_title="Book",
    )

    text = out.read_text(encoding="utf-8")
    assert "frame / frame-family-end" in text
    assert "available=3.40in" in text
    assert "recommended=wide transparent filler" in text
    assert "`filler-wide-frame-baseline-human-01.png`" in text
    assert "transparent background" in text


def test_filler_report_lists_reuse_and_undersized_opportunities(
    tmp_path,
    monkeypatch,
):
    catalog = FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=1.2,
                max_space_in=8.5,
                shapes=["spot", "bottom-band"],
            )
        },
        assets=[
            FillerAsset(
                "reused",
                tmp_path / "filler-bottom-general-reused.png",
                "bottom-band",
                2.4,
            )
        ],
    )
    monkeypatch.setattr(
        fillers_mod,
        "measure_slots",
        lambda document: [
            FillerMeasurement(
                slot_id="slot-a",
                slot_name="chapter-end",
                chapter_slug="languages",
                page_number=3,
                available_in=3.4,
            ),
            FillerMeasurement(
                slot_id="slot-b",
                slot_name="chapter-end",
                chapter_slug="languages",
                page_number=50,
                available_in=3.4,
            ),
            FillerMeasurement(
                slot_id="slot-c",
                slot_name="chapter-end",
                chapter_slug="languages",
                page_number=51,
                available_in=7.0,
            ),
        ],
    )
    out = tmp_path / "book.filler-report.md"

    fillers_mod.write_filler_report(
        out,
        object(),
        catalog,
        recipe_title="Book",
    )

    text = out.read_text(encoding="utf-8")
    assert "## Warnings" in text
    assert "reused reused on p50 slot-b" in text
    assert "render=2.40in, fill=77%" in text
    assert "## Undersized Opportunities" in text
    assert "recommended=page-finish art" in text
    assert "`page-finish-languages-languages-01.png`" in text


def test_inject_fillers_replaces_marker_with_fixed_block(tmp_path):
    asset = FillerAsset("tail", tmp_path / "tail.png", "tailpiece", 0.65)
    html = (
        '<div id="slot-a" class="filler-slot" data-slot="chapter-end" '
        'data-chapter="a"></div>'
    )

    out = inject_fillers(html, [FillerPlacement("slot-a", asset)])

    assert "filler-art filler-shape-tailpiece" in out
    assert "height: 0.650in" in out
    assert "filler-slot" not in out
