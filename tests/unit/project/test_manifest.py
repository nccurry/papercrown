"""Unit tests for manifest building (Recipe -> Chapter tree)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from papercrown.project.manifest import (
    InlinePart,
    ManifestError,
    build_manifest,
    classify_filler_art_path,
    slugify,
)
from papercrown.project.recipe import RecipeError, load_recipe

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mini_workspace(tmp_path):
    """Create a small workspace with a base vault and an overlay vault."""
    base = tmp_path / "base"
    over = tmp_path / "overlay"
    base.mkdir()
    over.mkdir()

    # base vault has all the content
    (base / "Setting.md").write_text("# Setting (base)\nIntro.\n", encoding="utf-8")
    (base / "Heroes" / "Classes" / "Mage").mkdir(parents=True)
    (base / "Heroes" / "Classes" / "Mage" / "Mage Description.md").write_text(
        "# Mage (base)", encoding="utf-8"
    )
    (base / "Heroes" / "Classes" / "Mage" / "Mage Levels.md").write_text(
        "# Levels (base)", encoding="utf-8"
    )
    (base / "Heroes" / "Classes" / "Rogue").mkdir(parents=True)
    (base / "Heroes" / "Classes" / "Rogue" / "Rogue Description.md").write_text(
        "# Rogue (base)", encoding="utf-8"
    )
    (base / "Heroes" / "Classes" / "Rogue" / "Rogue Levels.md").write_text(
        "# Levels (base)", encoding="utf-8"
    )
    (base / "Heroes").mkdir(exist_ok=True)
    (base / "Heroes" / "Classes List.md").write_text(
        textwrap.dedent("""
            # Mage
            - [[Mage Description]]
            - [[Mage Levels]]
            # Rogue
            - [[Rogue Description]]
            - [[Rogue Levels]]
        """).lstrip(),
        encoding="utf-8",
    )
    (base / "Backgrounds.md").write_text(
        "# Backgrounds\nList of bgs.\n", encoding="utf-8"
    )

    # overlay reskins Mage Description only
    (over / "Heroes" / "Classes" / "Mage").mkdir(parents=True)
    (over / "Heroes" / "Classes" / "Mage" / "Mage Description.md").write_text(
        "# Mage (overlay reskin)", encoding="utf-8"
    )

    return tmp_path, base, over


def _write_recipe(workspace: Path, body: str) -> Path:
    p = workspace / "recipe.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# kind: file
# ---------------------------------------------------------------------------


class TestKindFile:
    def test_inline_title_part_does_not_create_chapter(self, tmp_path):
        (tmp_path / "Intro.md").write_text("# Intro\nBody.\n", encoding="utf-8")
        rp = _write_recipe(
            tmp_path,
            """
            contents:
              - kind: inline
                style: title
                title: Nimble Space Opera
                subtitle: Rules Book
              - Intro.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert isinstance(m.contents[0], InlinePart)
        assert m.contents[0].title == "Nimble Space Opera"
        assert len(m.chapters) == 1
        assert m.chapters[0].source_files == [(tmp_path / "Intro.md").resolve()]

    def test_basic_file_chapter(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: file
                title: Setting
                style: setting
                toc_depth: 2
                source: base:Setting.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert len(m.chapters) == 1
        ch = m.chapters[0]
        assert ch.title == "Setting"
        assert ch.style == "setting"
        assert ch.slug == "setting"
        assert ch.toc_depth == 2
        assert len(ch.source_files) == 1
        assert ch.source_files[0].name == "Setting.md"

    def test_tailpiece_resolves_relative_to_art_dir(self, mini_workspace):
        ws, base, _ = mini_workspace
        art = ws / "art"
        (art / "ornaments").mkdir(parents=True)
        tailpiece = art / "ornaments" / "tail.png"
        tailpiece.write_text("fake", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            contents:
              - kind: file
                title: Setting
                tailpiece: ornaments/tail.png
                source: base:Setting.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert m.chapters[0].tailpiece_path == tailpiece.resolve()

    def test_scoped_content_art_insert_resolves_to_chapter_splash(self, mini_workspace):
        ws, base, _ = mini_workspace
        art = ws / "art"
        (art / "splashes").mkdir(parents=True)
        splash = art / "splashes" / "boarding.png"
        splash.write_text("fake", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
                art:
                  - id: boarding
                    after_heading: Factions
                    art: splashes/boarding.png
                    placement: bottom-half
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert len(m.splashes) == 1
        assert m.splashes[0].id == "boarding"
        assert m.splashes[0].chapter_slug == "setting"
        assert m.splashes[0].heading_slug == "factions"
        assert m.splashes[0].art_path == splash.resolve()

    def test_headpiece_and_break_ornament_resolve_relative_to_art_dir(
        self, mini_workspace
    ):
        ws, base, _ = mini_workspace
        art = ws / "art"
        (art / "ornaments").mkdir(parents=True)
        headpiece = art / "ornaments" / "head.png"
        break_ornament = art / "ornaments" / "break.png"
        headpiece.write_text("fake", encoding="utf-8")
        break_ornament.write_text("fake", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            contents:
              - kind: file
                title: Setting
                headpiece: ornaments/head.png
                break_ornament: ornaments/break.png
                source: base:Setting.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert m.chapters[0].headpiece_path == headpiece.resolve()
        assert m.chapters[0].break_ornament_path == break_ornament.resolve()

    def test_splashes_resolve_relative_to_art_dir(self, mini_workspace):
        ws, base, _ = mini_workspace
        art = ws / "art"
        (art / "splashes").mkdir(parents=True)
        front = art / "splashes" / "front.png"
        corner = art / "splashes" / "corner.png"
        front.write_text("fake", encoding="utf-8")
        corner.write_text("fake", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            splashes:
              - id: front
                art: splashes/front.png
                target: front-cover
                placement: cover
              - id: setting-corner
                art: splashes/corner.png
                chapter: Setting
                target: after-heading
                heading: Factions
                placement: corner-right
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert [s.id for s in m.splashes] == ["front", "setting-corner"]
        assert m.splashes[0].art_path == front.resolve()
        assert m.splashes[1].art_path == corner.resolve()
        assert m.splashes[1].chapter_slug == "setting"
        assert m.splashes[1].heading_slug == "factions"

    def test_fillers_resolve_and_attach_chapter_end_slots(self, mini_workspace):
        ws, base, _ = mini_workspace
        art = ws / "art"
        (art / "ornaments").mkdir(parents=True)
        tailpiece = art / "ornaments" / "tail.png"
        tailpiece.write_text("fake", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 3.5in
                  shapes: [tailpiece]
              assets:
                - id: tail
                  art: ornaments/tail.png
                  shape: tailpiece
                  height: 0.65in
            contents:
              - kind: file
                title: Setting
                tailpiece: ornaments/tail.png
                source: base:Setting.md
              - kind: file
                title: Backgrounds
                source: base:Backgrounds.md
              - kind: file
                title: Original - Backgrounds
                source: base:Backgrounds.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert m.fillers.enabled is True
        assert m.fillers.assets[0].art_path == tailpiece.resolve()
        assert m.fillers.slots["chapter-end"].min_space_in == 0.65
        slot = m.chapters[0].filler_slots[0]
        assert slot.id == "filler-chapter-end-setting"
        assert slot.slot == "chapter-end"
        assert slot.preferred_asset_id == "tail"
        plain_slot = m.chapters[1].filler_slots[0]
        assert plain_slot.id == "filler-chapter-end-backgrounds"
        assert plain_slot.slot == "chapter-end"
        assert plain_slot.preferred_asset_id is None
        assert m.chapters[2].slug.startswith("original-")
        assert m.chapters[2].filler_slots == []

    def test_fillers_attach_reference_terminals_and_sequence_boundaries(
        self,
        mini_workspace,
    ):
        ws, base, _ = mini_workspace
        (base / "Combat.md").write_text("# Combat\nIntro.\n", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 8.5in
                  shapes: [spot, small-wide, bottom-band]
                section-end:
                  min_space: 1.2in
                  max_space: 8.5in
                  shapes: [spot, small-wide, bottom-band]
            contents:
              - kind: group
                title: Original Rules
                child_style: rules
                children:
                  - kind: file
                    title: Conditions
                    slug: original-conditions
                    source: base:Setting.md
              - kind: group
                title: Original Backgrounds
                child_style: backgrounds
                children:
                  - kind: file
                    title: Backgrounds
                    slug: original-backgrounds
                    source: base:Backgrounds.md
              - kind: sequence
                style: equipment
                title: Combat
                sources:
                  - base:Combat.md
                  - title: Weapons & Armor
                    source: base:Backgrounds.md
            """,
        )

        m = build_manifest(load_recipe(rp))

        original_rules = m.find_chapter("original-conditions")
        assert original_rules is not None
        assert len(original_rules.filler_slots) == 1
        assert original_rules.filler_slots[0].slot == "chapter-end"
        assert original_rules.filler_slots[0].context == "reference"
        original_backgrounds = m.find_chapter("original-backgrounds")
        assert original_backgrounds is not None
        assert original_backgrounds.filler_slots == []
        combat = m.find_chapter("combat")
        assert combat is not None
        assert combat.source_boundary_filler_slot == "section-end"
        assert combat.filler_slots[0].context == "combat"

    def test_fillers_attach_multiple_marker_slots(self, mini_workspace):
        ws, base, _ = mini_workspace
        (base / "Combat.md").write_text("# Combat\nIntro.\n", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 8.5in
                  shapes: [tailpiece, spot]
                chapter-bottom-band:
                  min_space: 2.4in
                  max_space: 4.25in
                  shapes: [bottom-band]
                section-end:
                  min_space: 1.2in
                  max_space: 8.5in
                  shapes: [spot]
                section-bottom-band:
                  min_space: 2.4in
                  max_space: 4.25in
                  shapes: [bottom-band]
              markers:
                terminal:
                  chapter_slots: [chapter-end, chapter-bottom-band]
                source_boundary:
                  sequence_slots: [section-end, section-bottom-band]
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
              - kind: sequence
                style: equipment
                title: Combat
                sources:
                  - base:Combat.md
                  - title: Weapons & Armor
                    source: base:Backgrounds.md
            """,
        )

        m = build_manifest(load_recipe(rp))

        setting = m.find_chapter("setting")
        assert setting is not None
        assert [slot.slot for slot in setting.filler_slots] == [
            "chapter-end",
            "chapter-bottom-band",
        ]
        combat = m.find_chapter("combat")
        assert combat is not None
        assert combat.source_boundary_filler_slots == [
            "section-end",
            "section-bottom-band",
        ]
        assert combat.source_boundary_filler_slot == "section-end"

    def test_filler_marker_policy_can_disable_generated_markers(
        self,
        mini_workspace,
    ):
        ws, base, _ = mini_workspace
        (base / "Combat.md").write_text("# Combat\nIntro.\n", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 8.5in
                  shapes: [spot, plate, page-finish]
                section-end:
                  min_space: 1.2in
                  max_space: 8.5in
                  shapes: [spot, plate, page-finish]
              markers:
                terminal: false
                source_boundary: false
                subclass: false
                headings: []
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
              - kind: sequence
                style: equipment
                title: Combat
                sources:
                  - source: base:Combat.md
                    filler: false
                  - title: Weapons & Armor
                    source: base:Backgrounds.md
            """,
        )

        m = build_manifest(load_recipe(rp))

        setting = m.find_chapter("setting")
        combat = m.find_chapter("combat")
        assert setting is not None
        assert combat is not None
        assert setting.filler_slots == []
        assert combat.filler_slots == []
        assert combat.source_boundary_filler_slot is None
        assert combat.source_filler_enabled == [False, True]
        assert combat.heading_filler_markers == []

    def test_page_damage_assets_resolve_from_filename_conventions(self, mini_workspace):
        ws, base, _ = mini_workspace
        art = ws / "art"
        wear_dir = art / "page-wear"
        wear_dir.mkdir(parents=True)
        coffee = wear_dir / "wear-coffee-small-01.png"
        coffee.write_text("fake", encoding="utf-8")
        (wear_dir / "wear-unknown-small-01.png").write_text(
            "fake",
            encoding="utf-8",
        )
        (wear_dir / "notes.txt").write_text("ignore", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            page_damage:
              enabled: true
              art_dir: page-wear
              seed: manifest-test
              density: 0.5
              max_assets_per_page: 2
              opacity: 0.25
              glaze_opacity: 0.5
              glaze_texture: surface-paper-fiber-wash.png
              skip: [cover, toc]
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
        """,
        )

        m = build_manifest(load_recipe(rp))

        assert m.page_damage.enabled is True
        assert m.page_damage.seed == "manifest-test"
        assert m.page_damage.density == 0.5
        assert m.page_damage.opacity == 0.25
        assert m.page_damage.glaze_opacity == 0.5
        assert m.page_damage.glaze_texture == "surface-paper-fiber-wash.png"
        assert m.page_damage.skip == ["cover", "toc"]
        assert len(m.page_damage.assets) == 1
        asset = m.page_damage.assets[0]
        assert asset.id == "wear-coffee-small-01"
        assert asset.family == "coffee"
        assert asset.size == "small"
        assert asset.art_path == coffee.resolve()
        assert any("invalid name/family/size" in warning for warning in m.warnings)

    def test_filler_asset_classifier_recognizes_filename_conventions(
        self,
        tmp_path,
    ):
        root = tmp_path / "art"

        assert (
            classify_filler_art_path(
                root / "frame-baseline-human.png",
                art_root=root,
            ).category
            == "frame-divider"
        )
        assert (
            classify_filler_art_path(
                root / "class-spots" / "spot-class-marshal.png",
                art_root=root,
            ).category
            == "class-opening"
        )

        faction = classify_filler_art_path(root / "faction-corp-sec.png", art_root=root)
        gear = classify_filler_art_path(root / "gear-ranged-loadout.png", art_root=root)
        vista = classify_filler_art_path(root / "vista-dockyard.png", art_root=root)
        spot = classify_filler_art_path(
            root / "filler-spot-class-helmet-01.png",
            art_root=root,
        )
        page = classify_filler_art_path(
            root / "page-finish-frame-vault-01.png",
            art_root=root,
        )
        cover = classify_filler_art_path(
            root / "cover-front-pinlight-01.png",
            art_root=root,
        )
        splash = classify_filler_art_path(
            root / "splash-chapter-combat-01.png",
            art_root=root,
        )
        divider = classify_filler_art_path(
            root / "divider-frames-01.png",
            art_root=root,
        )
        tailpiece = classify_filler_art_path(
            root / "ornaments" / "ornament-tailpiece-airlock.png",
            art_root=root,
        )
        wear = classify_filler_art_path(root / "wear-coffee-stain.png", art_root=root)

        assert faction.category == "setting-wide"
        assert faction.shape == "bottom-band"
        assert faction.auto_selectable is False
        assert gear.category == "equipment-wide"
        assert gear.shape == "bottom-band"
        assert gear.auto_selectable is False
        assert vista.category == "vista-wide"
        assert vista.shape == "bottom-band"
        assert vista.auto_selectable is False
        assert spot.category == "filler-spot"
        assert spot.shape == "spot"
        assert spot.auto_selectable is True
        assert page.category == "page-finish"
        assert page.shape == "page-finish"
        assert page.height_in == 5.25
        assert page.auto_selectable is True
        assert cover.category == "cover-art"
        assert cover.auto_selectable is False
        assert splash.category == "manual-splash"
        assert splash.auto_selectable is False
        assert divider.category == "divider-art"
        assert divider.auto_selectable is False
        assert tailpiece.category == "tailpiece"
        assert tailpiece.shape == "tailpiece"
        assert tailpiece.auto_selectable is False
        assert wear.category == "page-wear"
        assert wear.auto_selectable is False
        for prefix in (
            "stamp-passport.png",
            "label-cargo.png",
            "map-orbit.png",
            "diagram-reactor.png",
            "icon-action.png",
            "portrait-captain.png",
            "ship-sloop.png",
            "vehicle-rover.png",
            "location-drydock.png",
        ):
            classified = classify_filler_art_path(root / prefix, art_root=root)
            assert classified.category == prefix.split("-", 1)[0]
            assert classified.auto_selectable is False

        assert (
            classify_filler_art_path(
                root / "unused" / "corner-biocharge-lab.png",
                art_root=root,
            ).category
            == "excluded"
        )
        assert (
            classify_filler_art_path(
                root / "splashes" / "biocharge-lab-corner.png",
                art_root=root,
            ).category
            == "excluded"
        )

    def test_auto_filler_discovery_excludes_unused_corners_and_manual_roles(
        self,
        mini_workspace,
    ):
        ws, base, _ = mini_workspace
        art = ws / "art"
        for rel in (
            "faction-corp-sec.png",
            "gear-ranged-loadout.png",
            "vista-dockyard.png",
            "filler-spot-future.png",
            "filler-wide-future.png",
            "filler-bottom-future.png",
            "page-finish-future.png",
            "cover-front-future.png",
            "cover-back-future.png",
            "splash-chapter-future.png",
            "splash-section-future.png",
            "divider-future.png",
            "stamp-future.png",
            "label-future.png",
            "map-future.png",
            "diagram-future.png",
            "icon-future.png",
            "portrait-future.png",
            "ship-future.png",
            "vehicle-future.png",
            "location-future.png",
            "frame-baseline-human.png",
            "class-spots/spot-class-marshal.png",
            "ornaments/ornament-tailpiece-airlock.png",
            "splashes/boarding-queue-bottom.png",
            "splashes/biocharge-lab-corner.png",
            "unused/corner-derelict-breach.png",
        ):
            path = art / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fake", encoding="utf-8")

        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 3.5in
                  shapes: [small-wide, bottom-band]
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
        """,
        )

        m = build_manifest(load_recipe(rp))
        assets = {asset.id: asset for asset in m.fillers.assets}

        assert assets["auto-filler-spot-future"].shape == "spot"
        assert assets["auto-filler-wide-future"].shape == "small-wide"
        assert assets["auto-filler-bottom-future"].shape == "bottom-band"
        assert assets["auto-page-finish-future"].height_in == 5.25
        assert "auto-faction-corp-sec" not in assets
        assert "auto-gear-ranged-loadout" not in assets
        assert "auto-vista-dockyard" not in assets
        assert "auto-frame-baseline-human" not in assets
        assert "auto-class-spots-spot-class-marshal" not in assets
        assert "auto-ornaments-ornament-tailpiece-airlock" not in assets
        assert "auto-cover-front-future" not in assets
        assert "auto-splash-chapter-future" not in assets
        assert "auto-divider-future" not in assets
        assert "auto-ship-future" not in assets
        assert "auto-splashes-boarding-queue-bottom" not in assets
        assert all("corner" not in asset.art_path.name for asset in assets.values())
        assert all("unused" not in asset.art_path.parts for asset in assets.values())

    def test_auto_filler_discovery_includes_tailpieces_when_slots_accept_them(
        self,
        mini_workspace,
    ):
        ws, base, _ = mini_workspace
        art = ws / "art"
        tailpiece = art / "ornaments" / "ornament-tailpiece-airlock.png"
        tailpiece.parent.mkdir(parents=True, exist_ok=True)
        tailpiece.write_text("fake", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 3.5in
                  shapes: [tailpiece]
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
        """,
        )

        m = build_manifest(load_recipe(rp))
        assets = {asset.id: asset for asset in m.fillers.assets}

        assert assets["auto-ornaments-ornament-tailpiece-airlock"].shape == "tailpiece"
        assert assets["auto-ornaments-ornament-tailpiece-airlock"].art_path == (
            tailpiece.resolve()
        )

    def test_art_conventions_infer_book_and_chapter_assets(self, mini_workspace):
        from papercrown.render import build as build_mod

        ws, base, _ = mini_workspace
        art = ws / "Art"
        for rel in (
            "cover-front-opening-frontier-crew-01.png",
            "cover-back-closing-the-black-01.png",
            "ornament-folio-frame.png",
            "header-setting.png",
            "class-mage.png",
            "spot-class-mage.png",
        ):
            path = art / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fake", encoding="utf-8")

        recipe = load_recipe(
            _write_recipe(
                ws,
                """
                title: Test
                cover:
                  enabled: true
                vaults:
                  base: base
                contents:
                  - kind: file
                    title: Setting
                    source: base:Setting.md
                  - kind: classes-catalog
                    source: base:Heroes/Classes List.md
                    child_style: class
                """,
            )
        )
        manifest = build_manifest(recipe)

        assert build_mod._recipe_cover_art_path(recipe) == (
            art / "cover-front-opening-frontier-crew-01.png"
        ).resolve()
        assert build_mod._recipe_ornament_path(recipe, "folio_frame") == (
            art / "ornament-folio-frame.png"
        ).resolve()
        setting = manifest.find_chapter("setting")
        assert setting is not None
        assert setting.art_path == (art / "header-setting.png").resolve()
        mage = manifest.find_chapter("mage")
        assert mage is not None
        assert mage.art_path == (art / "class-mage.png").resolve()
        assert mage.spot_art_path == (art / "spot-class-mage.png").resolve()
        assert manifest.splashes[-1].id == "auto-cover-back"
        assert manifest.splashes[-1].art_path == (
            art / "cover-back-closing-the-black-01.png"
        ).resolve()

    def test_fillers_art_dir_limits_auto_discovery_and_explicit_paths(
        self,
        mini_workspace,
    ):
        ws, base, _ = mini_workspace
        art = ws / "art"
        for rel in (
            "filler-spot-outside.png",
            "fillers/filler-spot-inside.png",
            "fillers/explicit-spot.png",
            "ornaments/ornament-tailpiece-airlock.png",
        ):
            path = art / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("fake", encoding="utf-8")

        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            fillers:
              enabled: true
              art_dir: fillers
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 3.5in
                  shapes: [spot]
              assets:
                - id: explicit
                  art: explicit-spot.png
                  shape: spot
                  height: 1.35in
                - id: escaped
                  art: ../ornaments/ornament-tailpiece-airlock.png
                  shape: tailpiece
                  height: 0.65in
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
        """,
        )

        m = build_manifest(load_recipe(rp))
        assets = {asset.id: asset for asset in m.fillers.assets}

        assert (
            assets["explicit"].art_path == (art / "fillers/explicit-spot.png").resolve()
        )
        assert "auto-filler-spot-inside" in assets
        assert "auto-filler-spot-outside" not in assets
        assert "escaped" not in assets
        assert any(
            "filler 'escaped': art not found" in warning for warning in m.warnings
        )

    def test_splash_unknown_chapter_raises(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            splashes:
              - id: missing
                art: splashes/missing.png
                chapter: Missing
                target: chapter-start
                placement: bottom-half
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
        """,
        )
        with pytest.raises(ManifestError, match="unknown chapter"):
            build_manifest(load_recipe(rp))

    def test_missing_source_raises(self, mini_workspace):
        ws, _, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: file
                source: base:Nope.md
        """,
        )
        with pytest.raises(ManifestError, match="not found"):
            build_manifest(load_recipe(rp))

    def test_explicit_slug_overrides_title_slug(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: file
                title: Original - Setting
                slug: original-setting
                source: base:Setting.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert m.chapters[0].title == "Original - Setting"
        assert m.chapters[0].slug == "original-setting"


# ---------------------------------------------------------------------------
# kind: catalog (embed-compendium)
# ---------------------------------------------------------------------------


class TestKindCatalogEmbedCompendium:
    def test_embed_catalog_uses_catalog_file_directly(self, mini_workspace):
        """For embed catalogs we let obsidian-export inline embeds at export
        time, so manifest just points at the catalog file itself."""
        ws, base, _ = mini_workspace
        # Write an embed-style backgrounds file
        (base / "Backgrounds List.md").write_text(
            "![[Backgrounds]]\n", encoding="utf-8"
        )
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: catalog
                title: Backgrounds
                style: backgrounds
                source: base:Backgrounds List.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert len(m.chapters) == 1
        ch = m.chapters[0]
        # source_files = [the catalog file itself]
        assert len(ch.source_files) == 1
        assert ch.source_files[0].name == "Backgrounds List.md"


# ---------------------------------------------------------------------------
# kind: classes-catalog (the primary case)
# ---------------------------------------------------------------------------


class TestKindClassesCatalog:
    def test_flatten_no_wrapper(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: classes-catalog
                source: base:Heroes/Classes List.md
                wrapper: false
                child_style: class
                individual_pdfs: true
                individual_pdf_subdir: classes
        """,
        )
        m = build_manifest(load_recipe(rp))
        # Flat: 2 sibling chapters (Mage, Rogue), no wrapper
        assert len(m.chapters) == 2
        assert {c.title for c in m.chapters} == {"Mage", "Rogue"}
        for ch in m.chapters:
            assert ch.style == "class"
            assert ch.individual_pdf is True
            assert ch.individual_pdf_subdir == "classes"
            assert ch.eyebrow == "Class"
            assert len(ch.source_files) == 2
            assert ch.is_leaf

    def test_with_wrapper(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: classes-catalog
                title: Classes
                style: section-classes
                source: base:Heroes/Classes List.md
                wrapper: true
                child_style: class
        """,
        )
        m = build_manifest(load_recipe(rp))
        # Wrapper: 1 top-level chapter "Classes" with 2 children
        assert len(m.chapters) == 1
        wrapper = m.chapters[0]
        assert wrapper.title == "Classes"
        assert wrapper.style == "section-classes"
        assert len(wrapper.children) == 2
        assert {c.title for c in wrapper.children} == {"Mage", "Rogue"}

    def test_classes_catalog_propagates_ornaments_to_children(self, mini_workspace):
        ws, base, _ = mini_workspace
        art = ws / "art" / "ornaments"
        art.mkdir(parents=True)
        headpiece = art / "head.png"
        break_ornament = art / "break.png"
        tailpiece = art / "tail.png"
        for path in (headpiece, break_ornament, tailpiece):
            path.write_text("fake", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            contents:
              - kind: classes-catalog
                source: base:Heroes/Classes List.md
                headpiece: ornaments/head.png
                break_ornament: ornaments/break.png
                tailpiece: ornaments/tail.png
        """,
        )

        m = build_manifest(load_recipe(rp))

        mage = next(c for c in m.chapters if c.title == "Mage")
        assert mage.headpiece_path == headpiece.resolve()
        assert mage.break_ornament_path == break_ornament.resolve()
        assert mage.tailpiece_path == tailpiece.resolve()

    def test_overlay_substitution(self, mini_workspace):
        """Overlay vault wins for individual class file resolution."""
        ws, base, over = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
              overlay: overlay
            vault_overlay: [base, overlay]
            contents:
              - kind: classes-catalog
                source: base:Heroes/Classes List.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        mage = next(c for c in m.chapters if c.title == "Mage")
        # Mage Description should resolve to the overlay version
        desc_path = next(
            p for p in mage.source_files if p.name == "Mage Description.md"
        )
        assert desc_path.read_text(encoding="utf-8") == "# Mage (overlay reskin)"
        # Mage Levels only exists in base
        levels_path = next(p for p in mage.source_files if p.name == "Mage Levels.md")
        assert levels_path.read_text(encoding="utf-8") == "# Levels (base)"

    def test_unresolved_link_warns_not_raises(self, mini_workspace):
        ws, base, _ = mini_workspace
        # Write a Classes List with a nonexistent link
        (base / "Heroes" / "Classes List.md").write_text(
            textwrap.dedent("""
                # Mage
                - [[Mage Description]]
                - [[Mage Levels]]
                - [[NonexistentFile]]
            """).lstrip(),
            encoding="utf-8",
        )
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: classes-catalog
                source: base:Heroes/Classes List.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert len(m.chapters) == 1
        assert any("NonexistentFile" in w for w in m.warnings)
        # Class chapter still built with the resolved files
        assert len(m.chapters[0].source_files) == 2

    def test_class_spot_art_pattern_resolves_for_children(self, mini_workspace):
        ws, base, _ = mini_workspace
        art = ws / "art"
        (art / "class-spots").mkdir(parents=True)
        mage_spot = art / "class-spots" / "spot-class-mage.png"
        rogue_spot = art / "class-spots" / "spot-class-rogue.png"
        mage_spot.write_text("fake", encoding="utf-8")
        rogue_spot.write_text("fake", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            contents:
              - kind: classes-catalog
                source: base:Heroes/Classes List.md
                class_spot_art_pattern: class-spots/spot-class-{slug}.png
                replace_existing_opening_art: true
        """,
        )
        m = build_manifest(load_recipe(rp))
        mage = next(c for c in m.chapters if c.title == "Mage")
        rogue = next(c for c in m.chapters if c.title == "Rogue")
        assert mage.spot_art_path == mage_spot.resolve()
        assert rogue.spot_art_path == rogue_spot.resolve()
        assert mage.replace_opening_art is True
        assert not m.warnings

    def test_class_art_pattern_resolves_divider_art_for_children(self, mini_workspace):
        ws, base, _ = mini_workspace
        art = ws / "art"
        (art / "classes" / "dividers").mkdir(parents=True)
        mage_art = art / "classes" / "dividers" / "class-mage.png"
        rogue_art = art / "classes" / "dividers" / "class-rogue.png"
        mage_art.write_text("fake", encoding="utf-8")
        rogue_art.write_text("fake", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            art_dir: art
            vaults:
              base: base
            contents:
              - kind: classes-catalog
                source: base:Heroes/Classes List.md
                class_art_pattern: classes/dividers/class-{slug}.png
        """,
        )
        m = build_manifest(load_recipe(rp))
        mage = next(c for c in m.chapters if c.title == "Mage")
        rogue = next(c for c in m.chapters if c.title == "Rogue")
        assert mage.art_path == mage_art.resolve()
        assert rogue.art_path == rogue_art.resolve()
        assert not m.warnings


# ---------------------------------------------------------------------------
# kind: folder
# ---------------------------------------------------------------------------


class TestKindFolder:
    def test_alphabetical(self, mini_workspace):
        ws, base, _ = mini_workspace
        # Put a few files into a flat folder
        (base / "Misc").mkdir()
        (base / "Misc" / "Bravo.md").write_text("b", encoding="utf-8")
        (base / "Misc" / "Alpha.md").write_text("a", encoding="utf-8")
        (base / "Misc" / "Charlie.md").write_text("c", encoding="utf-8")
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: folder
                title: Misc
                source: base:Misc
        """,
        )
        m = build_manifest(load_recipe(rp))
        names = [p.name for p in m.chapters[0].source_files]
        assert names == ["Alpha.md", "Bravo.md", "Charlie.md"]


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------


class TestManifestHelpers:
    def test_find_chapter_by_slug_and_title(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: classes-catalog
                source: base:Heroes/Classes List.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert m.find_chapter("Mage").title == "Mage"
        assert m.find_chapter("mage").title == "Mage"
        assert m.find_chapter("rogue").title == "Rogue"
        assert m.find_chapter("Bogus") is None

    def test_dump_runs(self, mini_workspace):
        from papercrown.project.manifest import dump

        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: file
                title: Setting
                source: base:Setting.md
              - kind: classes-catalog
                source: base:Heroes/Classes List.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        text = dump(m)
        assert "Setting" in text
        assert "Mage" in text
        assert "Rogue" in text


# ---------------------------------------------------------------------------
# slugify: canonical rule shared with the Lua filter
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_lowercases(self):
        assert slugify("Berserker") == "berserker"

    def test_collapses_whitespace_and_punctuation(self):
        assert slugify("Path of the Mountainheart") == "path-of-the-mountainheart"
        assert slugify("Bonded (Mage)") == "bonded-mage"

    def test_keeps_underscores_and_hyphens(self):
        # Rule diverged between manifest and the Lua filter before the cleanup;
        # make sure both ends agree now.
        assert slugify("Heavyworlder_Native") == "heavyworlder_native"
        assert slugify("multi-word-slug") == "multi-word-slug"
        assert slugify("mix_with-dashes") == "mix_with-dashes"

    def test_strips_leading_trailing_separators(self):
        assert slugify("  --hello--  ") == "hello"
        # Underscores are word chars in the regex class, so they're kept.
        assert slugify("__edge__") == "__edge__"

    def test_empty_input_falls_back(self):
        assert slugify("") == "untitled"
        assert slugify("   ") == "untitled"
        assert slugify("???") == "untitled"


# ---------------------------------------------------------------------------
# kind: composite -- folder-as-chapter, recursive .md concatenation
# ---------------------------------------------------------------------------


class TestKindComposite:
    def test_composite_recurses(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: composite
                title: All Classes
                source: base:Heroes/Classes
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert len(m.chapters) == 1
        ch = m.chapters[0]
        assert ch.title == "All Classes"
        names = sorted(p.name for p in ch.source_files)
        assert names == [
            "Mage Description.md",
            "Mage Levels.md",
            "Rogue Description.md",
            "Rogue Levels.md",
        ]

    def test_composite_requires_explicit_vault(self, mini_workspace):
        ws, _, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: composite
                source: Heroes/Classes
        """,
        )
        with pytest.raises(ManifestError, match="explicit vault prefix"):
            build_manifest(load_recipe(rp))

    def test_composite_requires_directory(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: composite
                source: base:Setting.md
        """,
        )
        with pytest.raises(ManifestError, match="must be a directory"):
            build_manifest(load_recipe(rp))


# ---------------------------------------------------------------------------
# kind: group -- structural wrapper with hand-curated children
# ---------------------------------------------------------------------------


class TestKindGroup:
    def test_group_wraps_children(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: group
                title: Hero Reference
                eyebrow: Reference
                children:
                  - kind: file
                    title: Setting
                    source: base:Setting.md
                  - kind: file
                    title: Backgrounds
                    source: base:Backgrounds.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        assert len(m.chapters) == 1
        wrap = m.chapters[0]
        assert wrap.title == "Hero Reference"
        assert wrap.eyebrow == "Reference"
        assert wrap.source_files == []
        assert [c.title for c in wrap.children] == ["Setting", "Backgrounds"]

    def test_group_propagates_child_style_to_default_children(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: group
                title: Equipment
                child_style: equipment
                children:
                  - kind: file
                    title: Setting
                    source: base:Setting.md
                  - kind: file
                    title: Backgrounds
                    style: explicit
                    source: base:Backgrounds.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        wrap = m.chapters[0]
        # First child kept default style -> picks up the group's child_style
        assert wrap.children[0].style == "equipment"
        # Second child set its own style -> left alone
        assert wrap.children[1].style == "explicit"

    def test_group_propagates_child_divider(self, mini_workspace):
        ws, base, _ = mini_workspace
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: group
                title: Stuff
                child_divider: true
                children:
                  - kind: file
                    title: Setting
                    source: base:Setting.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        wrap = m.chapters[0]
        assert wrap.children[0].divider is True


# ---------------------------------------------------------------------------
# kind: sequence -- explicitly ordered mixed sources
# ---------------------------------------------------------------------------


class TestKindSequence:
    def test_sequence_preserves_order_and_titles(self, mini_workspace):
        ws, base, _ = mini_workspace
        (base / "Rules").mkdir()
        (base / "Rules" / "Intro.md").write_text("# Combat\nintro\n", encoding="utf-8")
        (base / "Rules" / "Structure.md").write_text("body\n", encoding="utf-8")
        (base / "Rules" / "Actions.md").write_text(
            "# Already Titled\nbody\n", encoding="utf-8"
        )
        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: sequence
                title: Combat
                source: base:Rules/Intro.md
        """,
        )
        with pytest.raises(RecipeError, match="source"):
            build_manifest(load_recipe(rp))

        rp = _write_recipe(
            ws,
            """
            title: Test
            vaults:
              base: base
            contents:
              - kind: sequence
                title: Combat
                style: rules
                sources:
                  - base:Rules/Intro.md
                  - title: Combat Structure
                    source: base:Rules/Structure.md
                    strip_related: true
                  - title: Heroic Actions
                    source: base:Rules/Actions.md
        """,
        )
        m = build_manifest(load_recipe(rp))
        ch = m.chapters[0]
        assert ch.title == "Combat"
        assert ch.style == "rules"
        assert [p.name for p in ch.source_files] == [
            "Intro.md",
            "Structure.md",
            "Actions.md",
        ]
        assert ch.source_titles == [None, "Combat Structure", "Heroic Actions"]
        assert ch.source_strip_related == [False, True, False]


# ---------------------------------------------------------------------------
# Recipe.project_dir / art_dir
# ---------------------------------------------------------------------------


class TestRecipePathProperties:
    def test_project_dir_when_recipe_in_recipes_subdir(self, tmp_path):
        from papercrown.project.recipe import CoverSpec, Recipe

        project = tmp_path / "project"
        recipes = project / "recipes"
        recipes.mkdir(parents=True)
        rp = recipes / "foo.yaml"
        rp.write_text("title: t\n", encoding="utf-8")
        r = Recipe(
            title="t",
            subtitle=None,
            cover_eyebrow=None,
            cover_footer=None,
            vaults={},
            vault_overlay=[],
            cover=CoverSpec(),
            contents=[],
            recipe_path=rp.resolve(),
        )
        assert r.project_dir == project.resolve()
        assert r.art_dir == (project / "Art").resolve()

    def test_project_dir_when_recipe_alongside(self, tmp_path):
        # When the recipe lives directly in the project root (not inside
        # `recipes/`), project_dir is just its parent.
        from papercrown.project.recipe import CoverSpec, Recipe

        rp = tmp_path / "myrecipe.yaml"
        rp.write_text("title: t\n", encoding="utf-8")
        r = Recipe(
            title="t",
            subtitle=None,
            cover_eyebrow=None,
            cover_footer=None,
            vaults={},
            vault_overlay=[],
            cover=CoverSpec(),
            contents=[],
            recipe_path=rp.resolve(),
        )
        assert r.project_dir == tmp_path.resolve()

    def test_art_dir_can_be_overridden(self, tmp_path):
        from papercrown.project.recipe import CoverSpec, Recipe

        rp = tmp_path / "recipes" / "foo.yaml"
        rp.parent.mkdir()
        rp.write_text("title: t\n", encoding="utf-8")
        art_dir = tmp_path / "Sample Vault" / "Art"
        art_dir.mkdir(parents=True)
        r = Recipe(
            title="t",
            subtitle=None,
            cover_eyebrow=None,
            cover_footer=None,
            vaults={},
            vault_overlay=[],
            cover=CoverSpec(),
            contents=[],
            recipe_path=rp.resolve(),
            art_dir_override=art_dir.resolve(),
        )
        assert r.art_dir == art_dir.resolve()
