"""Unit tests for layered papercrown configuration."""

from __future__ import annotations

import textwrap

import pytest

from papercrown.app.config import (
    BuildConfigPatch,
    ConfigError,
    load_book_build_config,
    load_project_config,
    parse_jobs,
    resolve_build_config,
)
from papercrown.build.options import (
    BuildScope,
    BuildTarget,
    DraftMode,
    OutputProfile,
    PaginationMode,
    WearMode,
)


def test_project_build_block_parses_all_option_types(tmp_path):
    config_path = tmp_path / "papercrown.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            book: books/main.yaml
            build:
              target: web
              scope: sections
              profile: digital
              chapter: " Intro "
              include_art: false
              force: true
              jobs: 3
              clean_pdf: false
              pagination: fix
              draft_mode: visual
              wear: false
              timings: true
            """
        ).lstrip(),
        encoding="utf-8",
    )

    patch = load_project_config(config_path)

    assert patch.book_path == tmp_path / "books" / "main.yaml"
    assert patch.target is BuildTarget.WEB
    assert patch.scope is BuildScope.SECTIONS
    assert patch.profile is OutputProfile.DIGITAL
    assert patch.single_chapter == "Intro"
    assert patch.include_art is False
    assert patch.force is True
    assert patch.jobs == 3
    assert patch.clean_pdf is False
    assert patch.pagination_mode is PaginationMode.FIX
    assert patch.draft_mode is DraftMode.VISUAL
    assert patch.wear_mode is WearMode.OFF
    assert patch.timings is True


def test_project_config_infers_book_yml_when_unnamed(tmp_path):
    (tmp_path / "book.yml").write_text("title: B\ncontents: []\n", encoding="utf-8")
    config_path = tmp_path / "papercrown.yaml"
    config_path.write_text("build:\n  scope: book\n", encoding="utf-8")

    patch = load_project_config(config_path)

    assert patch.book_path == (tmp_path / "book.yml").resolve()


def test_missing_project_config_infers_book_yml_from_cwd(tmp_path, monkeypatch):
    (tmp_path / "book.yml").write_text("title: B\ncontents: []\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    patch = load_project_config()

    assert patch.book_path == (tmp_path / "book.yml").resolve()


def test_missing_project_config_without_book_yml_has_no_book(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    patch = load_project_config()

    assert patch.book_path is None


def test_project_and_cli_layers_apply_in_order(tmp_path):
    recipe = _write_recipe(
        tmp_path,
        """
        title: B
        vaults:
          v: vault
        contents:
          - kind: file
            title: Foo
            source: v:Foo.md
        """,
    )
    config_path = tmp_path / "papercrown.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            book: recipe.yaml
            build:
              target: pdf
              scope: book
              profile: digital
              pagination: off
              draft_mode: fast
              wear: fast
              jobs: 2
              clean_pdf: false
            """
        ).lstrip(),
        encoding="utf-8",
    )

    project = load_project_config(config_path)
    recipe_patch = load_book_build_config(recipe)
    cli = BuildConfigPatch(
        profile=OutputProfile.DRAFT,
        pagination_mode=PaginationMode.FIX,
        draft_mode=DraftMode.VISUAL,
        wear_mode=WearMode.PROOF,
    )
    resolved = resolve_build_config(
        recipe_arg=None,
        project=project,
        recipe=recipe_patch,
        cli=cli,
    )

    assert resolved.recipe_path == recipe.resolve()
    assert resolved.target is BuildTarget.PDF
    assert resolved.scope is BuildScope.BOOK
    assert resolved.profile is OutputProfile.DRAFT
    assert resolved.pagination_mode is PaginationMode.FIX
    assert resolved.draft_mode is DraftMode.VISUAL
    assert resolved.wear_mode is WearMode.PROOF
    assert resolved.jobs == 2
    assert resolved.clean_pdf is False


def test_unknown_project_config_key_fails(tmp_path):
    config_path = tmp_path / "papercrown.yaml"
    config_path.write_text("bogus: true\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown config key"):
        load_project_config(config_path)


def test_book_local_build_block_fails(tmp_path):
    recipe = _write_recipe(
        tmp_path,
        """
        title: B
        vaults:
          v: vault
        build:
          mystery: true
        contents:
          - kind: file
            title: Foo
            source: v:Foo.md
        """,
    )

    with pytest.raises(ConfigError, match="papercrown.yaml"):
        load_book_build_config(recipe)


def test_missing_book_requires_argument_or_default():
    with pytest.raises(ConfigError, match="no book provided"):
        resolve_build_config(
            recipe_arg=None,
            project=BuildConfigPatch(),
            recipe=BuildConfigPatch(),
            cli=BuildConfigPatch(),
        )


def test_chapter_requires_sections_scope(tmp_path):
    recipe = tmp_path / "recipe.yaml"

    with pytest.raises(ConfigError, match="--chapter may only be used"):
        resolve_build_config(
            recipe_arg=recipe,
            project=BuildConfigPatch(),
            recipe=BuildConfigPatch(
                scope=BuildScope.BOOK,
                single_chapter="Foo",
            ),
            cli=BuildConfigPatch(),
        )


def test_web_target_rejects_pdf_specific_options(tmp_path):
    recipe = tmp_path / "recipe.yaml"

    with pytest.raises(ConfigError, match="does not accept a PDF --profile"):
        resolve_build_config(
            recipe_arg=recipe,
            project=BuildConfigPatch(),
            recipe=BuildConfigPatch(
                target=BuildTarget.WEB,
                profile=OutputProfile.DIGITAL,
            ),
            cli=BuildConfigPatch(),
        )

    with pytest.raises(ConfigError, match="only supports --scope all"):
        resolve_build_config(
            recipe_arg=recipe,
            project=BuildConfigPatch(),
            recipe=BuildConfigPatch(
                target=BuildTarget.WEB,
                scope=BuildScope.BOOK,
            ),
            cli=BuildConfigPatch(),
        )


def test_visual_draft_mode_requires_draft_profile(tmp_path):
    recipe = tmp_path / "recipe.yaml"

    with pytest.raises(ConfigError, match="only valid with --profile draft"):
        resolve_build_config(
            recipe_arg=recipe,
            project=BuildConfigPatch(),
            recipe=BuildConfigPatch(draft_mode=DraftMode.VISUAL),
            cli=BuildConfigPatch(),
        )


@pytest.mark.parametrize("value", [0, -1, "0", "nope", True, None])
def test_invalid_jobs_values_fail(value):
    with pytest.raises(ConfigError, match="jobs must be"):
        parse_jobs(value)


def _write_recipe(tmp_path, body: str):
    (tmp_path / "vault").mkdir(exist_ok=True)
    (tmp_path / "vault" / "Foo.md").write_text("# Foo", encoding="utf-8")
    path = tmp_path / "recipe.yaml"
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path
