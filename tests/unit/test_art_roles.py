"""Unit tests for the Paper Crown art role registry."""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

from papercrown.art_audit import audit_recipe_art
from papercrown.art_roles import classify_art_path
from papercrown.manifest import build_manifest
from papercrown.recipe import load_recipe


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
        "fillers/page/filler-page-frame-vault-01.png": "filler-page",
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
            art / "fillers" / "page" / "filler-page-frame-vault-01.png",
            art_root=art,
        ).shape
        == "page-finish"
    )


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
            art_dir: art
            vaults:
              v: vault
            chapters:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_recipe(recipe_path)
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
    (art / "fillers" / "page").mkdir(parents=True)
    (art / "fillers" / "spot").mkdir(parents=True)
    (vault / "Foo.md").write_text("# Foo\n", encoding="utf-8")

    sparse = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sparse)
    draw.rectangle((240, 240, 272, 272), fill=(0, 0, 0, 255))
    sparse.save(art / "fillers" / "page" / "filler-page-sparse-one-01.png")
    sparse.save(art / "fillers" / "page" / "filler-page-sparse-two-01.png")
    Image.new("RGB", (128, 128), (60, 50, 45)).save(
        art / "fillers" / "spot" / "filler-spot-bad-edge-01.png"
    )

    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: Art Quality Book
            art_dir: art
            vaults:
              v: vault
            chapters:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_recipe(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)
    warning_codes = {diagnostic.code for diagnostic in result.diagnostics.warnings}

    assert "art.duplicate-exact" in warning_codes
    assert "art.visible-content-small" in warning_codes
    assert "art.background-mismatch" in warning_codes


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
            art_dir: art
            cover:
              enabled: true
              art: covers/cover-front-foo-01.png
            vaults:
              v: vault
            splashes:
              - id: back
                art: covers/cover-back-foo-01.png
                target: back-cover
                placement: back-cover
            chapters:
              - kind: file
                title: Foo
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_recipe(recipe_path)
    manifest = build_manifest(recipe)

    result = audit_recipe_art(recipe, manifest)
    warning_codes = {diagnostic.code for diagnostic in result.diagnostics.warnings}

    assert result.role_counts["cover-front"] == 1
    assert result.role_counts["cover-back"] == 1
    assert "art.reference-role" not in warning_codes
