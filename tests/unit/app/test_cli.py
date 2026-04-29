"""Unit tests for the Typer CLI surface."""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image
from typer.main import get_command
from typer.testing import CliRunner

from papercrown.app import cli
from papercrown.app.config import parse_jobs
from papercrown.app.options import (
    BuildScope,
    DraftMode,
    OutputProfile,
    PageDamageMode,
    PaginationMode,
)

runner = CliRunner()


def test_build_help_exposes_clean_break_flags():
    result = runner.invoke(
        cli.app,
        ["build", "--help"],
        color=False,
        terminal_width=200,
    )

    assert result.exit_code == 0
    build = get_command(cli.app).commands["build"]
    options = {
        option
        for param in build.params
        for option in (
            *getattr(param, "opts", ()),
            *getattr(param, "secondary_opts", ()),
        )
    }
    assert "--scope" in options
    assert "--draft-mode" in options
    assert "--page-damage" in options
    assert "--pagination" in options
    assert "--jobs" in options
    assert "--clean-pdf" in options


def test_fonts_setup_is_removed():
    result = runner.invoke(cli.app, ["fonts", "setup", "--help"])

    assert result.exit_code != 0


def test_themes_list_includes_catalog_metadata():
    result = runner.invoke(cli.app, ["themes", "list"])

    assert result.exit_code == 0, result.output
    assert "clean-srd - Clean SRD: reference /" in result.output
    assert (
        "pinlight-industrial - Pinlight Industrial: science-fiction /" in result.output
    )
    assert "modern-minimal" not in result.output


def test_themes_copy_uses_modular_source_files():
    with runner.isolated_filesystem():
        result = runner.invoke(cli.app, ["themes", "copy", "clean-srd", "my-theme"])

        assert result.exit_code == 0, result.output
        copied = Path("my-theme")
        assert (copied / "tokens.css").is_file()
        assert (copied / "components.css").is_file()
        assert not (copied / "book.css").exists()
        assert "tokens.css" in (copied / "theme.yaml").read_text(encoding="utf-8")


def test_deps_check_is_a_subcommand(monkeypatch):
    class FakeReport:
        def format_text(self, *, updates_only: bool = False) -> str:
            assert updates_only is False
            return "papercrown deps\n  OK: fake"

        def exit_code(self, *, strict: bool = False) -> int:
            assert strict is False
            return 0

    monkeypatch.setattr(cli, "check_dependencies", lambda manifest: FakeReport())

    result = runner.invoke(cli.app, ["deps", "check"])

    assert result.exit_code == 0
    assert "papercrown deps" in result.output


def test_main_returns_typer_exit_code(monkeypatch):
    class FakeReport:
        def format_text(self, *, updates_only: bool = False) -> str:
            return "papercrown deps\n  ERROR: fake"

        def exit_code(self, *, strict: bool = False) -> int:
            return 1

    monkeypatch.setattr(cli, "check_dependencies", lambda manifest: FakeReport())

    assert cli.main(["deps", "check"]) == 1


def test_old_build_aliases_are_not_accepted():
    result = runner.invoke(cli.app, ["build", "recipes/player-book.yaml", "--book"])

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_old_action_aliases_are_not_accepted():
    result = runner.invoke(cli.app, ["recipes/player-book.yaml", "--dump-manifest"])

    assert result.exit_code != 0


def test_cli_patch_tracks_explicit_page_damage_mode():
    patch = cli._build_cli_patch(page_damage=PageDamageMode.PROOF)

    assert patch.page_damage_mode is PageDamageMode.PROOF


def test_jobs_auto_is_capped_to_small_worker_count():
    jobs = parse_jobs("auto")

    assert 1 <= jobs <= 4


def test_numeric_jobs_string_is_accepted():
    assert parse_jobs("3") == 3


def test_build_command_applies_config_recipe_and_cli_precedence(
    tmp_path,
    monkeypatch,
):
    recipe = _write_recipe(
        tmp_path,
        """
        title: Cli Book
        vaults:
          v: vault
        build:
          scope: book
          profile: digital
          include_art: true
          clean_pdf: true
          page_damage: fast
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
            default_book: recipe.yaml
            build:
              scope: sections
              profile: print
              include_art: false
              jobs: 2
              clean_pdf: false
              pagination: off
            """
        ).lstrip(),
        encoding="utf-8",
    )
    captured = _patch_build_side_effects(tmp_path, monkeypatch)

    result = runner.invoke(
        cli.app,
        [
            "build",
            "--config",
            str(config_path),
            "--profile",
            "draft",
            "--draft-mode",
            "visual",
            "--page-damage",
            "proof",
            "--pagination",
            "fix",
            "--jobs",
            "auto",
            "--no-art",
            "--no-clean-pdf",
            "--filler-debug-overlay",
            "--timings",
        ],
    )

    assert result.exit_code == 0, result.output
    request = captured["request"]
    assert request.recipe.recipe_path == recipe
    assert request.scope is BuildScope.BOOK
    assert request.profile is OutputProfile.DRAFT
    assert request.draft_mode is DraftMode.VISUAL
    assert request.page_damage_mode is PageDamageMode.PROOF
    assert request.pagination_mode is PaginationMode.FIX
    assert 1 <= request.jobs <= 4
    assert request.include_art is False
    assert request.clean_pdf is False
    assert request.filler_debug_overlay is True
    assert request.timings is True


def test_verify_command_uses_config_scope_and_profile(tmp_path, monkeypatch):
    _write_recipe(
        tmp_path,
        """
        title: Verify Config Book
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
            default_book: recipe.yaml
            build:
              scope: book
              profile: draft
            """
        ).lstrip(),
        encoding="utf-8",
    )
    captured = {}

    def fake_verify_main(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(cli.verify_mod, "main", fake_verify_main)

    result = runner.invoke(cli.app, ["verify", "--config", str(config_path)])

    assert result.exit_code == 0, result.output
    assert captured["argv"] == [
        str((tmp_path / "recipe.yaml").resolve()),
        "--profile",
        "draft",
        "--scope",
        "book",
    ]


def test_art_audit_command_reports_role_counts(tmp_path):
    recipe = _write_recipe(
        tmp_path,
        """
        title: Art Audit Book
        art_dir: art
        vaults:
          v: vault
        contents:
          - kind: file
            title: Foo
            source: v:Foo.md
        """,
    )
    filler = tmp_path / "art" / "fillers" / "spot" / "filler-spot-general-01.png"
    filler.parent.mkdir(parents=True)
    Image.new("RGBA", (450, 405), (0, 0, 0, 0)).save(filler)

    result = runner.invoke(cli.app, ["art", "audit", str(recipe), "--strict"])

    assert result.exit_code == 0, result.output
    assert "papercrown art audit" in result.output
    assert "filler-spot: 1" in result.output


def test_art_contact_sheet_command_writes_html(tmp_path):
    recipe = _write_recipe(
        tmp_path,
        """
        title: Art Contact Sheet Book
        art_dir: art
        vaults:
          v: vault
        contents:
          - kind: file
            title: Foo
            source: v:Foo.md
        """,
    )
    filler = tmp_path / "art" / "fillers" / "spot" / "filler-spot-general-01.png"
    filler.parent.mkdir(parents=True)
    Image.new("RGBA", (450, 405), (0, 0, 0, 0)).save(filler)
    out = tmp_path / "sheet.html"

    result = runner.invoke(
        cli.app,
        ["art", "contact-sheet", str(recipe), "--output", str(out)],
    )

    assert result.exit_code == 0, result.output
    assert out.is_file()
    assert "filler-spot" in out.read_text(encoding="utf-8")


def test_init_command_accepts_new_book_options(tmp_path):
    dest = tmp_path / "pinlight"

    result = runner.invoke(
        cli.app,
        [
            "init",
            str(dest),
            "--title",
            "The Pinlight Colony",
            "--subtitle",
            "A frontier campaign",
            "--theme",
            "pinlight-industrial",
            "--book-type",
            "campaign",
            "--vault",
            "notes",
            "--no-cover",
        ],
    )

    assert result.exit_code == 0, result.output
    recipe = (dest / "book.yaml").read_text(encoding="utf-8")
    assert 'title: "The Pinlight Colony"' in recipe
    assert 'theme: "pinlight-industrial"' in recipe
    assert "enabled: false" in recipe
    assert (dest / "notes" / "Overview.md").is_file()
    assert "Next steps:" in result.output


def test_no_config_ignores_project_config_but_keeps_recipe_build(
    tmp_path,
    monkeypatch,
):
    recipe = _write_recipe(
        tmp_path,
        """
        title: No Config Book
        vaults:
          v: vault
        build:
          scope: book
          profile: digital
          page_damage: off
        contents:
          - kind: file
            title: Foo
            source: v:Foo.md
        """,
    )
    invalid_config = tmp_path / "bad-papercrown.yaml"
    invalid_config.write_text("unknown: nope\n", encoding="utf-8")
    captured = _patch_build_side_effects(tmp_path, monkeypatch)

    result = runner.invoke(
        cli.app,
        [
            "build",
            str(recipe),
            "--config",
            str(invalid_config),
            "--no-config",
        ],
    )

    assert result.exit_code == 0, result.output
    request = captured["request"]
    assert request.scope is BuildScope.BOOK
    assert request.profile is OutputProfile.DIGITAL
    assert request.page_damage_mode is PageDamageMode.OFF


def _patch_build_side_effects(tmp_path, monkeypatch):
    captured = {}
    out_pdf = tmp_path / "out.pdf"

    def fake_build_outputs(tools, request, *, log=None):
        captured["tools"] = tools
        captured["request"] = request
        out_pdf.write_bytes(b"%PDF")
        return cli.BuildResult(produced=[out_pdf], skipped=[], export_map={})

    monkeypatch.setattr(
        cli,
        "discover_tools",
        lambda *, require_weasyprint=True: cli.Tools(
            pandoc="pandoc",
            obsidian_export="obsidian-export",
            weasyprint="weasyprint",
        ),
    )
    monkeypatch.setattr(cli, "build_outputs", fake_build_outputs)
    return captured


def _write_recipe(tmp_path, body: str):
    (tmp_path / "vault").mkdir(exist_ok=True)
    (tmp_path / "vault" / "Foo.md").write_text("# Foo", encoding="utf-8")
    path = tmp_path / "recipe.yaml"
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path.resolve()
