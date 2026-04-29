"""Integration tests for the obsidian-export step.

Exercises `papercrown.system.export.ensure_exports_fresh` against a real on-disk
vault and verifies the subprocess actually succeeds. This guards against two classes
of silent failure we've tripped on in production:

  1. `obsidian-export` aborts mid-run because the build scans unrelated vault
     files instead of the recipe's referenced source files.

  2. The export runs but produces empty / stale output, so chapter
     assembly reads whatever happens to be in `.build-cache/` from a
     previous run.

Both manifest as "build passes but PDF content is wrong" -- a terrible
failure mode.
"""

from __future__ import annotations

import pytest

from papercrown.project.manifest import build_manifest
from papercrown.project.recipe import load_recipe
from papercrown.system import export

pytestmark = pytest.mark.usefixtures("require_pandoc")


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def require_obsidian_export(has_external_tools):
    if not has_external_tools["obsidian-export"]:
        pytest.skip("obsidian-export not installed")


@pytest.fixture
def isolated_build_cache(tmp_path):
    """Return a per-test recipe cache directory."""
    return tmp_path / "cache"


# ---------------------------------------------------------------------------
# Happy-path: mini fixture vault exports cleanly
# ---------------------------------------------------------------------------


class TestEnsureExportsFreshHappyPath:
    """The mini fixture vault must round-trip through obsidian-export
    without errors, and the returned mapping must cover every referenced
    source file."""

    def test_mini_fixture_exports_succeed(
        self,
        mini_recipe_path,
        require_obsidian_export,
        isolated_build_cache,
    ):
        recipe = load_recipe(mini_recipe_path)
        recipe.cache_dir_override = isolated_build_cache
        manifest = build_manifest(recipe)
        tools = export.discover_tools()

        export_map = export.ensure_exports_fresh(tools, manifest)

        # Every referenced source file resolves to a real exported mirror.
        referenced = {
            f.resolve() for ch in manifest.all_chapters() for f in ch.source_files
        }
        missing = [
            p.name
            for p in referenced
            if p not in export_map or not export_map[p].is_file()
        ]
        assert not missing, (
            f"Referenced files without a matching export mirror: {missing}. "
            "obsidian-export likely failed and fell back to raw markdown "
            "without surfacing the error."
        )

    def test_export_resolves_wikilinks_in_mini_fixture(
        self,
        mini_recipe_path,
        require_obsidian_export,
        isolated_build_cache,
    ):
        """Sanity check on what `obsidian-export` actually does: after
        running it on the mini vault, none of the exported files should
        contain literal `[[...]]` wikilink syntax -- it should have been
        rewritten to markdown links (`[alias](Target.md)`) or inlined
        embed content."""
        recipe = load_recipe(mini_recipe_path)
        recipe.cache_dir_override = isolated_build_cache
        manifest = build_manifest(recipe)
        tools = export.discover_tools()

        export_map = export.ensure_exports_fresh(tools, manifest)
        for src, mirror in export_map.items():
            text = mirror.read_text(encoding="utf-8")
            assert "[[" not in text, (
                f"Exported {mirror.name} still contains raw wikilinks -- "
                f"obsidian-export didn't resolve them. Source: {src.name}"
            )


# ---------------------------------------------------------------------------
# Regression: unreferenced poison files must not affect referenced exports
# ---------------------------------------------------------------------------


class TestEnsureExportsFreshIgnoresUnreferencedFailures:
    """Referenced-file export must not scan unrelated notes in the vault."""

    def test_poisoned_unreferenced_file_does_not_warn(
        self,
        tmp_path,
        require_obsidian_export,
        isolated_build_cache,
        capsys,
        monkeypatch,
    ):
        # Build a minimal vault with one valid file and one poisoned file.
        # The "poison" is obsidian-export's YAML-frontmatter false positive:
        # two `---` thematic breaks bracketing `**Bold**` paragraphs make
        # obsidian-export 25.x try to YAML-parse the body, which fails
        # with "scanning an alias".
        vault = tmp_path / "poisoned-vault"
        vault.mkdir()
        (vault / "Good.md").write_text("# Good\n\njust some text.\n", encoding="utf-8")
        (vault / "Poison.md").write_text(
            "**Bold A**\n**Bold B**\n**Bold C**\n\n---\n"
            "# Header\nbody text here.\n---\n"
            "more body with **Bold D** here.\n",
            encoding="utf-8",
        )

        # Minimal recipe referencing just Good.md. Poison.md is a valid
        # Markdown note but trips obsidian-export 25.x if whole-vault export
        # scans it, so this verifies the export step stays recipe-scoped.
        recipe_path = tmp_path / "recipe.yaml"
        recipe_path.write_text(
            "title: Poisoned Vault Test\n"
            "vaults:\n  v: poisoned-vault\n"
            "contents:\n  - kind: file\n    source: v:Good.md\n",
            encoding="utf-8",
        )
        recipe = load_recipe(recipe_path)
        recipe.cache_dir_override = isolated_build_cache
        manifest = build_manifest(recipe)
        tools = export.discover_tools()

        export_map = export.ensure_exports_fresh(tools, manifest, log=print)
        captured = capsys.readouterr().out

        good = (vault / "Good.md").resolve()
        poison = (vault / "Poison.md").resolve()
        assert good in export_map
        assert export_map[good].is_file()
        assert poison not in export_map
        assert "WARNING" not in captured
        assert "fallback" not in captured.lower()
