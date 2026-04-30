"""Unit tests for project scaffolding."""

from __future__ import annotations

from pathlib import Path

from papercrown.project.manifest import build_manifest
from papercrown.project.recipe import load_recipe
from papercrown.project.starter import StarterBookType, init_project


def test_init_project_creates_verifiable_titled_starter(tmp_path):
    result = init_project(tmp_path, force=True)

    recipe = load_recipe(tmp_path / "book.yaml")
    manifest = build_manifest(recipe)

    assert recipe.title == "My Paper Crown Book"
    assert recipe.cover.enabled is True
    assert recipe.contents[0].kind == "inline"
    assert recipe.contents[1].kind == "toc"
    assert recipe.vaults["content"].path == tmp_path.resolve()
    assert (tmp_path / "Overview.md").is_file()
    recipe_text = (tmp_path / "book.yaml").read_text(encoding="utf-8")
    assert "output_dir:" not in recipe_text
    assert "output_name:" not in recipe_text
    assert "vaults:" not in recipe_text
    assert [chapter.title for chapter in manifest.chapters] == [
        "Overview",
        "Running the Campaign",
    ]
    assert "papercrown manifest" in result.next_steps[0]


def test_init_project_uses_title_theme_book_type_vault_and_cover_options(tmp_path):
    init_project(
        tmp_path,
        title="The Pinlight Colony",
        subtitle="A frontier campaign",
        theme="pinlight-industrial",
        book_type=StarterBookType.REFERENCE,
        vault=Path("notes"),
        with_cover=False,
        force=True,
    )

    recipe = load_recipe(tmp_path / "book.yaml")
    manifest = build_manifest(recipe)

    assert recipe.title == "The Pinlight Colony"
    assert recipe.subtitle == "A frontier campaign"
    assert recipe.theme == "pinlight-industrial"
    assert recipe.cover.enabled is False
    assert recipe.vaults["content"].path == (tmp_path / "notes").resolve()
    assert (tmp_path / "notes" / "Entries" / "Sample Entry.md").is_file()
    assert [chapter.title for chapter in manifest.chapters] == [
        "Introduction",
        "Reference Entries",
        "Quick Reference",
    ]


def test_init_project_can_use_external_absolute_vault(tmp_path):
    project = tmp_path / "project"
    shared_vault = tmp_path / "shared-vault"

    init_project(project, vault=shared_vault, force=True)

    recipe = load_recipe(project / "book.yaml")

    assert recipe.vaults["content"].path == shared_vault.resolve()
    assert (shared_vault / "Overview.md").is_file()


def test_empty_init_prints_next_steps_without_default_book(tmp_path):
    result = init_project(tmp_path, empty=True, force=True)

    config = (tmp_path / "papercrown.yaml").read_text(encoding="utf-8")

    assert "# default_book: book.yaml" in config
    assert "Create book.yaml" in result.next_steps[0]
    assert not (tmp_path / "vault").exists()
