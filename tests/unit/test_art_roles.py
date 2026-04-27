"""Unit tests for the Paper Crown art role registry."""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image

from papercrown.art_audit import audit_recipe_art
from papercrown.art_roles import classify_art_path
from papercrown.manifest import build_manifest
from papercrown.recipe import load_recipe


def test_classify_art_path_recognizes_canonical_roles(tmp_path: Path):
    art = tmp_path / "Art"
    examples = {
        "covers/cover-front-test-01.png": "cover",
        "classes/dividers/class-marshal.png": "class-divider",
        "classes/spots/spot-class-marshal.png": "class-opening-spot",
        "frames/dividers/frame-baseline-human.png": "frame-divider",
        "fillers/spot/filler-spot-class-helmet-01.png": "filler-spot",
        "fillers/page/filler-page-frame-vault-01.png": "filler-page",
        "ornaments/tailpieces/ornament-tailpiece-casing.png": "ornament-tailpiece",
        "page-wear/wear-coffee-small-01.png": "page-wear",
        "content/factions/faction-corp-sec.png": "faction",
    }

    for rel, role in examples.items():
        path = art / rel
        assert classify_art_path(path, art_root=art).role == role


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
