"""Unit tests for the Paper Crown art role registry."""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

from papercrown.art import audit as audit_mod
from papercrown.art.audit import audit_recipe_art
from papercrown.art.roles import ROLE_REGISTRY, classify_art_path
from papercrown.project.manifest import build_manifest
from papercrown.project.recipe import load_book_config


def test_classify_art_path_recognizes_canonical_roles(tmp_path: Path):
    art = tmp_path / "Art"
    examples = {
        "covers/cover-front-test-01.png": "cover-front",
        "covers/cover-back-test-01.png": "cover-back",
        "classes/dividers/class-marshal.png": "class-divider",
        "classes/spots/spot-class-marshal.png": "class-opening-spot",
        "frames/dividers/frame-baseline-human.png": "frame-divider",
        "fillers/spot/filler-spot-class-helmet-01.png": "filler-spot",
        "fillers/plate/filler-plate-setting-station-01.png": "filler-plate",
        "fillers/page-finish/page-finish-frame-vault-01.png": "page-finish",
        "ornaments/tailpieces/ornament-tailpiece-casing.png": "ornament-tailpiece",
        "ornaments/corners/ornament-corner-north-01.png": "ornament-corner",
        "ornaments/folios/ornament-folio-frame-01.png": "ornament-folio",
        "page-wear/wear-coffee-small-01.png": "page-wear",
        "spreads/spread-orbital-market-01.png": "spread",
        "content/diagrams/diagram-action-flow-01.png": "diagram",
        "content/screenshots/screenshot-cli-build-01.png": "screenshot",
        "icons/icon-action-01.png": "icon",
        "logos/logo-publisher-01.png": "logo",
        "content/factions/faction-corp-sec.png": "faction",
    }

    for rel, role in examples.items():
        path = art / rel
        assert classify_art_path(path, art_root=art).role == role
    assert (
        classify_art_path(
            art / "fillers" / "plate" / "filler-plate-setting-station-01.png",
            art_root=art,
        ).shape
        == "plate"
    )
    assert (
        classify_art_path(
            art / "fillers" / "page-finish" / "page-finish-frame-vault-01.png",
            art_root=art,
        ).shape
        == "page-finish"
    )


def test_classify_art_path_recognizes_flat_filename_roles(tmp_path: Path):
    art = tmp_path / "Art"
    examples = {
        "cover-front-test-01.png": "cover-front",
        "class-marshal.png": "class-divider",
        "spot-class-marshal.png": "class-opening-spot",
        "frame-baseline-human.png": "frame-divider",
        "filler-spot-class-helmet-01.png": "filler-spot",
        "page-finish-frame-vault-01.png": "page-finish",
        "ornament-tailpiece-casing.png": "ornament-tailpiece",
        "wear-coffee-small-01.png": "page-wear",
        "bg-dockside-alias.png": "spot",
        "scene-01-port-meridian-arrival.png": "scene",
    }

    for filename, role in examples.items():
        assert classify_art_path(art / filename, art_root=art).role == role


def test_classify_art_path_accepts_css_declared_labels(tmp_path: Path):
    art = tmp_path / "Art"

    classified = classify_art_path(
        art / "power-header-void-lance.png",
        art_root=art,
        art_labels=("power-header",),
    )

    assert classified.role == "power-header"
    assert classified.context == "void"
    assert classified.subject == "lance"
    assert classified.variant is None
    assert classified.nominal_width_in is None
    assert classified.matched_convention == "css-label"


def test_art_audit_uses_css_declared_labels(tmp_path: Path):
    vault = tmp_path / "vault"
    art = tmp_path / "art"
    styles = tmp_path / "styles"
    vault.mkdir()
    art.mkdir()
    styles.mkdir()
    (styles / "power-header.css").write_text(".power-header {}\n", encoding="utf-8")
    (styles / "power-icon.css").write_text(".power-icon {}\n", encoding="utf-8")
    (vault / "Foo.md").write_text("# Foo\n", encoding="utf-8")
    Image.new("RGB", (1800, 600), (255, 255, 255)).save(
        art / "power-header-void-lance.png"
    )
    Image.new("RGBA", (150, 150), (0, 0, 0, 0)).save(art / "power-icon-void-lance.png")
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: Custom Art Book
            art:
              library: art
            vaults:
              v: vault
            contents:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_book_config(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)

    assert result.role_counts["power-header"] == 1
    assert result.role_counts["power-icon"] == 1
    assert not result.unclassified


def test_art_audit_validates_alpha_and_unclassified_assets(tmp_path: Path):
    vault = tmp_path / "vault"
    art = tmp_path / "art"
    (vault).mkdir()
    (art / "fillers" / "spot").mkdir(parents=True)
    (art / "page-wear").mkdir(parents=True)
    (vault / "Foo.md").write_text("# Foo\n", encoding="utf-8")
    Image.new("RGB", (128, 128), (255, 255, 255)).save(
        art / "fillers" / "spot" / "filler-spot-general-01.png"
    )
    Image.new("RGB", (128, 128), (255, 255, 255)).save(
        art / "page-wear" / "wear-dust-small-01.png"
    )
    Image.new("RGBA", (128, 128), (0, 0, 0, 0)).save(art / "mystery.png")
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: Audit Book
            art:
              library: art
            vaults:
              v: vault
            contents:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_book_config(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)
    warning_codes = {diagnostic.code for diagnostic in result.diagnostics.warnings}

    assert result.role_counts["filler-spot"] == 1
    assert "art.alpha-missing" in warning_codes
    assert "art.unclassified" in warning_codes


def test_art_audit_warns_about_duplicates_sparse_art_and_backgrounds(
    tmp_path: Path,
):
    vault = tmp_path / "vault"
    art = tmp_path / "art"
    vault.mkdir()
    (art / "fillers" / "page-finish").mkdir(parents=True)
    (art / "fillers" / "spot").mkdir(parents=True)
    (vault / "Foo.md").write_text("# Foo\n", encoding="utf-8")

    sparse = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sparse)
    draw.rectangle((240, 240, 272, 272), fill=(0, 0, 0, 255))
    sparse.save(art / "fillers" / "page-finish" / "page-finish-sparse-one-01.png")
    sparse.save(art / "fillers" / "page-finish" / "page-finish-sparse-two-01.png")
    Image.new("RGB", (128, 128), (60, 50, 45)).save(
        art / "fillers" / "spot" / "filler-spot-bad-edge-01.png"
    )

    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: Art Quality Book
            art:
              library: art
            vaults:
              v: vault
            contents:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_book_config(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)
    warning_codes = {diagnostic.code for diagnostic in result.diagnostics.warnings}

    assert "art.duplicate-exact" in warning_codes
    assert "art.visible-content-small" in warning_codes
    assert "art.background-mismatch" in warning_codes


def test_art_audit_warns_about_bottom_band_slot_and_top_safety(
    tmp_path: Path,
):
    vault = tmp_path / "vault"
    art = tmp_path / "art"
    vault.mkdir()
    (art / "fillers" / "bottom").mkdir(parents=True)
    (vault / "Foo.md").write_text("# Foo\n", encoding="utf-8")

    bottom_band = Image.new("RGBA", (1800, 620), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bottom_band)
    draw.rectangle((0, 0, 1800, 500), fill=(40, 35, 30, 255))
    bottom_band.save(art / "fillers" / "bottom" / "filler-bottom-general-dock-01.png")

    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: Bottom Band Audit Book
            art:
              library: art
              fillers:
                enabled: true
                slots:
                  chapter-end:
                    min_space: 0.65in
                    max_space: 5.0in
                    shapes: [spot, bottom-band]
            vaults:
              v: vault
            contents:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_book_config(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)
    warning_codes = {diagnostic.code for diagnostic in result.diagnostics.warnings}

    assert "art.filler-slot-mixed-placement" in warning_codes
    assert "art.bottom-band-top-crowded" in warning_codes


def test_art_audit_allows_cross_role_ornament_reuse(tmp_path: Path):
    vault = tmp_path / "vault"
    art = tmp_path / "art"
    vault.mkdir()
    (art / "ornaments" / "headpieces").mkdir(parents=True)
    (art / "ornaments" / "tailpieces").mkdir(parents=True)
    (vault / "Foo.md").write_text("# Foo\n", encoding="utf-8")

    ornament = Image.new("RGBA", (1600, 260), (0, 0, 0, 0))
    draw = ImageDraw.Draw(ornament)
    draw.line((120, 130, 1480, 130), fill=(90, 70, 45, 255), width=18)
    ornament.save(art / "ornaments" / "headpieces" / "ornament-headpiece-foo.png")
    ornament.save(art / "ornaments" / "tailpieces" / "ornament-tailpiece-foo.png")

    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: Ornament Reuse Book
            art:
              library: art
            vaults:
              v: vault
            contents:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_book_config(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)
    warning_codes = {diagnostic.code for diagnostic in result.diagnostics.warnings}

    assert "art.duplicate-exact" not in warning_codes


def test_generated_docs_role_nominal_sizes_match_art_brief():
    assert ROLE_REGISTRY["cover-front"].nominal_width_in == 5.5
    assert ROLE_REGISTRY["cover-front"].nominal_height_in == 7.113
    assert ROLE_REGISTRY["chapter-divider"].nominal_width_in == 6.0
    assert ROLE_REGISTRY["chapter-divider"].nominal_height_in == 0.933
    assert ROLE_REGISTRY["splash"].nominal_width_in == 6.0
    assert ROLE_REGISTRY["splash"].nominal_height_in == 1.8
    assert ROLE_REGISTRY["ornament-headpiece"].nominal_width_in == 5.333
    assert ROLE_REGISTRY["ornament-headpiece"].nominal_height_in == 0.867
    assert ROLE_REGISTRY["ornament-tailpiece"].nominal_width_in == 5.333
    assert ROLE_REGISTRY["ornament-tailpiece"].nominal_height_in == 0.867
    assert ROLE_REGISTRY["filler-bottom"].nominal_width_in == 6.0
    assert ROLE_REGISTRY["filler-bottom"].nominal_height_in == 2.067


def test_art_audit_expected_role_helpers_are_shared():
    assert audit_mod._expected_splash_roles("front-cover") == frozenset(
        {"cover-front", "scene"}
    )
    assert audit_mod._expected_splash_roles("back-cover") == frozenset(
        {"cover-back", "scene"}
    )
    assert audit_mod._expected_splash_roles("chapter-start") == frozenset(
        {"scene", "splash"}
    )
    assert audit_mod._expected_filler_roles("tailpiece") == frozenset(
        {"ornament-tailpiece"}
    )
    assert audit_mod._expected_filler_roles("page-finish") == frozenset({"page-finish"})
    assert "cover" in audit_mod.RECIPE_CHAPTER_ART_ROLES
    assert "cover-front" in audit_mod.MANIFEST_CHAPTER_ART_ROLES


def test_art_audit_expects_cover_roles_for_cover_targets(tmp_path: Path):
    vault = tmp_path / "vault"
    art = tmp_path / "art"
    vault.mkdir()
    (art / "covers").mkdir(parents=True)
    (vault / "Foo.md").write_text("# Foo\n", encoding="utf-8")
    Image.new("RGB", (1672, 941), (251, 250, 248)).save(
        art / "covers" / "cover-front-foo-01.png"
    )
    Image.new("RGB", (1672, 941), (251, 250, 248)).save(
        art / "covers" / "cover-back-foo-01.png"
    )

    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: Cover Contract Book
            art:
              library: art
              cover:
                enabled: true
                image: covers/cover-front-foo-01.png
              placements:
                - id: back
                  image: covers/cover-back-foo-01.png
                  target: back-cover
                  placement: back-cover
            vaults:
              v: vault
            contents:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_book_config(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)
    warning_codes = {diagnostic.code for diagnostic in result.diagnostics.warnings}

    assert result.role_counts["cover-front"] == 1
    assert result.role_counts["cover-back"] == 1
    assert "art.reference-role" not in warning_codes


def test_art_audit_allows_namespaced_art_packs_and_filler_art_dir(
    tmp_path: Path,
):
    vault = tmp_path / "vault"
    art = tmp_path / "art"
    pack = art / "docs-pack"
    vault.mkdir()
    (pack / "covers").mkdir(parents=True)
    (pack / "fillers" / "spot").mkdir(parents=True)
    (vault / "Foo.md").write_text("# Foo\n", encoding="utf-8")
    Image.new("RGB", (128, 180), (255, 255, 255)).save(
        pack / "covers" / "cover-front-docs-pack.png"
    )
    Image.new("RGBA", (128, 128), (0, 0, 0, 0)).save(
        pack / "fillers" / "spot" / "filler-spot-general-token-01.png"
    )
    Image.new("RGB", (128, 128), (255, 255, 255)).save(
        art / "contact-sheet-docs-pack.png"
    )

    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: Pack Audit Book
            art:
              library: art
              cover:
                enabled: true
                image: docs-pack/covers/cover-front-docs-pack.png
              fillers:
                enabled: true
                folder: docs-pack
                slots:
                  chapter-end:
                    min_space: 0.65in
                    max_space: 3.5in
                    shapes: [spot]
                assets:
                  - id: docs-spot
                    image: fillers/spot/filler-spot-general-token-01.png
                    shape: spot
                    height: 1.35in
            vaults:
              v: vault
            contents:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_book_config(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)
    diagnostic_codes = {
        diagnostic.code for diagnostic in result.diagnostics.diagnostics
    }

    assert "art.reference-missing" not in diagnostic_codes
    assert "art.folder-mismatch" not in diagnostic_codes
    assert "art.unclassified" not in diagnostic_codes


def test_art_audit_allows_flat_art_library(tmp_path: Path):
    vault = tmp_path / "vault"
    art = tmp_path / "art"
    vault.mkdir()
    art.mkdir()
    (vault / "Foo.md").write_text("# Foo\n", encoding="utf-8")
    Image.new("RGB", (128, 180), (255, 255, 255)).save(
        art / "cover-front-docs-pack.png"
    )
    Image.new("RGBA", (128, 128), (0, 0, 0, 0)).save(
        art / "filler-spot-general-token-01.png"
    )
    Image.new("RGB", (128, 128), (255, 255, 255)).save(art / "bg-dockside-alias.png")
    Image.new("RGB", (128, 128), (255, 255, 255)).save(
        art / "scene-01-port-meridian-arrival.png"
    )

    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: Flat Art Book
            art:
              library: art
              cover:
                enabled: true
                image: scene-01-port-meridian-arrival.png
              fillers:
                enabled: true
                slots:
                  chapter-end:
                    min_space: 0.65in
                    max_space: 3.5in
                    shapes: [spot]
                assets:
                  - id: docs-spot
                    image: filler-spot-general-token-01.png
                    shape: spot
                    height: 1.35in
            vaults:
              v: vault
            contents:
              - kind: file
                title: Foo
                art:
                  divider: scene-01-port-meridian-arrival.png
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_book_config(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)
    diagnostic_codes = {
        diagnostic.code for diagnostic in result.diagnostics.diagnostics
    }

    assert result.role_counts["scene"] == 1
    assert result.role_counts["spot"] == 1
    assert "art.reference-role" not in diagnostic_codes
    assert "art.folder-mismatch" not in diagnostic_codes
