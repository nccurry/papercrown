"""Unit tests for export behavior."""

from __future__ import annotations

import subprocess
import textwrap

import pytest

from papercrown.project.manifest import build_manifest
from papercrown.project.recipe import load_recipe
from papercrown.system import export
from papercrown.system.export import Tools


def _failed_frontmatter_export() -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["obsidian-export"],
        returncode=1,
        stdout="",
        stderr=(
            "Error: Failed to export 'Artificer Levels.md'\n\n"
            "Caused by:\n"
            "   0: Failed to decode YAML frontmatter in 'Artificer Levels.md'\n"
            "   1: did not find expected alphabetic or numeric character\n"
        ),
    )


def test_plain_markdown_copies_without_obsidian_export(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "Artificer Levels.md"
    source.write_text(
        "**Key Stats:** INT, STR\n**Hit Die:** 1d8\n\n---\n# Levels\nbody\n",
        encoding="utf-8",
    )

    def fail_if_called(_cmd):
        raise AssertionError("plain markdown should not invoke obsidian-export")

    monkeypatch.setattr(export, "_run_export_command", fail_if_called)

    exported = export.export_source_file(
        Tools("pandoc", "obsidian-export", "weasyprint"),
        source,
        tmp_path / "exported",
    )

    assert exported.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_export_failure_with_wikilinks_raises(
    tmp_path,
    monkeypatch,
):
    source = tmp_path / "Linked.md"
    source.write_text("**Key Stats:** INT\n\n[[Other Note]]\n", encoding="utf-8")
    monkeypatch.setattr(
        export,
        "_run_export_command",
        lambda _cmd: _failed_frontmatter_export(),
    )

    with pytest.raises(RuntimeError, match="obsidian-export failed"):
        export.export_source_file(
            Tools("pandoc", "obsidian-export", "weasyprint"),
            source,
            tmp_path / "exported",
        )


def test_web_tool_discovery_does_not_require_weasyprint(monkeypatch):
    def fake_which(name):
        return {
            "pandoc": "pandoc",
            "obsidian-export": "obsidian-export",
            "weasyprint": None,
        }.get(name)

    def fail_weasyprint():
        raise RuntimeError("no weasyprint")

    monkeypatch.setattr(export.shutil, "which", fake_which)
    monkeypatch.setattr(export, "_find_weasyprint", fail_weasyprint)

    tools = export.discover_tools(require_weasyprint=False)

    assert tools.pandoc == "pandoc"
    assert tools.obsidian_export == "obsidian-export"
    assert tools.weasyprint == ""


def test_ensure_exports_fresh_reuses_export_cache(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    source = vault / "Foo.md"
    source.write_text("# Foo\n", encoding="utf-8")
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: My Book
            vaults:
              v: vault
            chapters:
              - kind: file
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_recipe(recipe_path)
    recipe.cache_dir_override = tmp_path / "cache"
    manifest = build_manifest(recipe)
    monkeypatch.setattr(export, "_tool_version", lambda _command: "obsidian-export 1")
    calls = 0

    def fake_export_source_file(tools, source_file, dest, *, log=None):
        nonlocal calls
        calls += 1
        dest.mkdir(parents=True, exist_ok=True)
        exported = dest / source_file.name
        exported.write_text(source_file.read_text(encoding="utf-8"), encoding="utf-8")
        return exported.resolve()

    monkeypatch.setattr(export, "export_source_file", fake_export_source_file)
    tools = Tools("pandoc", "obsidian-export", "weasyprint")

    first = export.ensure_exports_fresh(tools, manifest)
    second = export.ensure_exports_fresh(tools, manifest)

    assert calls == 1
    assert first == second
    assert first[source.resolve()].read_text(encoding="utf-8") == "# Foo\n"
