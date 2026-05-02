"""Tests for CSS-declared fixed art label conventions."""

from __future__ import annotations

from pathlib import Path

from papercrown.project.art_labels import (
    ArtLabelCatalog,
    merge_art_label_catalogs,
    project_art_label_catalog,
    theme_art_label_catalog,
)


def test_project_art_label_catalog_uses_styles_css_filenames(tmp_path: Path):
    """Project ``styles/<label>.css`` files declare fixed art labels."""
    styles = tmp_path / "styles"
    styles.mkdir()
    power_header = styles / "power-header.css"
    power_icon = styles / "power-icon.css"
    power_header.write_text(".power-header {}\n", encoding="utf-8")
    power_icon.write_text(".power-icon {}\n", encoding="utf-8")
    (styles / "Bad_Label.css").write_text(".bad {}\n", encoding="utf-8")

    catalog = project_art_label_catalog(tmp_path)

    assert catalog.labels == ("power-header", "power-icon")
    assert catalog.css_files == (power_header.resolve(), power_icon.resolve())


def test_theme_art_label_catalog_uses_art_labels_css_filenames(tmp_path: Path):
    """Theme ``art-labels/<label>.css`` files declare reusable fixed labels."""
    labels = tmp_path / "art-labels"
    labels.mkdir()
    power_header = labels / "power-header.css"
    power_header.write_text(".power-header {}\n", encoding="utf-8")

    catalog = theme_art_label_catalog(tmp_path)

    assert catalog.labels == ("power-header",)
    assert catalog.css_files == (power_header.resolve(),)


def test_art_label_catalog_matches_longest_label_first():
    """More specific CSS labels win over shorter shared prefixes."""
    catalog = ArtLabelCatalog(labels=("power", "power-header"))

    assert catalog.match_stem("power-header-void-engine") == "power-header"
    assert catalog.match_stem("power-core") == "power"
    assert catalog.match_stem("powerful-engine") is None


def test_merge_art_label_catalogs_preserves_first_seen_labels(tmp_path: Path):
    """Merged catalogs keep deterministic label and CSS ordering."""
    first_css = tmp_path / "first.css"
    second_css = tmp_path / "second.css"
    first = ArtLabelCatalog(labels=("power-header",), css_files=(first_css,))
    second = ArtLabelCatalog(
        labels=("power-icon", "power-header"),
        css_files=(second_css, first_css),
    )

    catalog = merge_art_label_catalogs(first, second)

    assert catalog.labels == ("power-header", "power-icon")
    assert catalog.css_files == (first_css.resolve(), second_css.resolve())
