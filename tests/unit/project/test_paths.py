"""Unit tests for output path helpers."""

from __future__ import annotations

import textwrap
from pathlib import Path

from papercrown.build.options import OutputProfile
from papercrown.project import paths
from papercrown.project.manifest import Chapter
from papercrown.project.recipe import load_book_config


def _write_recipe(tmp_path: Path, body: str) -> Path:
    (tmp_path / "vault").mkdir(exist_ok=True)
    (tmp_path / "vault" / "Foo.md").write_text("# Foo", encoding="utf-8")
    p = tmp_path / "recipe.yaml"
    p.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return p


class TestOutputRoot:
    def test_default_root_uses_recipe_project_dir_and_title_slug(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: My Book
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )

        assert paths.output_root(recipe) == tmp_path / "Paper Crown" / "my-book"

    def test_output_dir_and_name_override_root(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: My Book
                output_dir: build-output
                output_name: custom-name
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )

        assert paths.output_root(recipe) == (
            tmp_path / "build-output" / "Paper Crown" / "custom-name"
        )


class TestChapterPdfPath:
    def test_top_level_chapter(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: B
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )
        ch = Chapter(title="Berserker", slug="berserker")
        assert paths.chapter_pdf_path(recipe, ch).name == "Berserker.pdf"
        assert paths.chapter_pdf_path(recipe, ch).parent == (
            paths.pdf_root(recipe) / "sections"
        )

    def test_individual_subdir(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: B
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )
        ch = Chapter(
            title="Berserker",
            slug="berserker",
            individual_pdf_subdir="classes",
        )
        out = paths.chapter_pdf_path(recipe, ch)
        assert out.parent == paths.pdf_root(recipe) / "individuals" / "classes"
        assert out.name == "Berserker.pdf"

    def test_draft_chapter_name(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: B
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )
        ch = Chapter(title="Berserker", slug="berserker")
        assert (
            paths.chapter_pdf_path(recipe, ch, profile=OutputProfile.DRAFT).name
            == "Berserker (Draft).pdf"
        )

    def test_digital_chapter_name_matches_print_name(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: B
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )
        ch = Chapter(title="Berserker", slug="berserker")
        assert (
            paths.chapter_pdf_path(recipe, ch, profile=OutputProfile.DIGITAL).name
            == "Berserker.pdf"
        )


class TestCombinedBookPath:
    def test_print_name(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: My Book
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )
        assert (
            paths.combined_book_path(recipe, profile=OutputProfile.PRINT).name
            == "My Book.pdf"
        )
        assert (
            paths.combined_book_path(recipe).parent == paths.pdf_root(recipe) / "book"
        )

    def test_digital_name(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: My Book
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )
        assert (
            paths.combined_book_path(recipe, profile=OutputProfile.DIGITAL).name
            == "My Book (Digital).pdf"
        )

    def test_draft_name(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: My Book
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )
        assert (
            paths.combined_book_path(recipe, profile=OutputProfile.DRAFT).name
            == "My Book (Draft).pdf"
        )

    def test_sanitizes_slashes_in_title(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: "My/Book"
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )
        assert (
            paths.combined_book_path(recipe, profile=OutputProfile.PRINT).name
            == "My-Book.pdf"
        )

    def test_web_book_path(self, tmp_path):
        recipe = load_book_config(
            _write_recipe(
                tmp_path,
                """
                title: My Book
                vaults:
                  v: vault
                contents:
                  - kind: file
                    source: v:Foo.md
                """,
            )
        )
        assert (
            paths.web_book_path(recipe) == paths.output_root(recipe) / "web/index.html"
        )
