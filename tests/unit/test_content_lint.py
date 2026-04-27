"""Unit tests for markdown content-quality diagnostics."""

from __future__ import annotations

import textwrap
from pathlib import Path

from papercrown.content_lint import lint_manifest_content
from papercrown.diagnostics import DiagnosticSeverity
from papercrown.manifest import build_manifest
from papercrown.recipe import load_recipe


def _write_recipe(tmp_path: Path, source_body: str) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Foo.md").write_text(
        textwrap.dedent(source_body).lstrip(), encoding="utf-8"
    )
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        textwrap.dedent(
            """
            title: My Book
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
    return recipe


def _write_two_vault_recipe(
    tmp_path: Path,
    *,
    nimble_body: str,
    custom_body: str,
    source: str = "nimble:Foo.md",
    style: str = "rules",
) -> Path:
    nimble = tmp_path / "nimble"
    custom = tmp_path / "custom"
    nimble.mkdir()
    custom.mkdir()
    (nimble / "Foo.md").write_text(nimble_body, encoding="utf-8")
    (custom / "Foo.md").write_text(custom_body, encoding="utf-8")
    recipe = tmp_path / "recipe.yaml"
    recipe.write_text(
        textwrap.dedent(
            f"""
            title: My Book
            vaults:
              nimble: nimble
              custom: custom
            vault_overlay: [nimble, custom]
            chapters:
              - kind: file
                style: {style}
                title: Foo
                source: {source}
            """
        ).lstrip(),
        encoding="utf-8",
    )
    return recipe


def test_lint_reports_unresolved_wikilinks_in_assembled_markdown(tmp_path):
    recipe = load_recipe(_write_recipe(tmp_path, "# Foo\n\n[[Missing]]\n"))
    manifest = build_manifest(recipe)

    diagnostics = lint_manifest_content(manifest)

    assert any(
        diagnostic.code == "content.raw-wikilink"
        and diagnostic.severity is DiagnosticSeverity.ERROR
        for diagnostic in diagnostics
    )


def test_lint_reports_duplicate_explicit_heading_ids(tmp_path):
    recipe = load_recipe(
        _write_recipe(tmp_path, "# Foo\n\n## One {#dup}\n\n## Two {#dup}\n")
    )
    manifest = build_manifest(recipe)

    diagnostics = lint_manifest_content(manifest)

    assert any(
        diagnostic.code == "content.heading-id-duplicate" for diagnostic in diagnostics
    )


def test_lint_accepts_exported_markdown_without_raw_wikilinks(tmp_path):
    recipe = load_recipe(_write_recipe(tmp_path, "# Foo\n\n[[Resolved]]\n"))
    manifest = build_manifest(recipe)
    source = manifest.all_chapters()[0].source_files[0]
    exported = tmp_path / "exported.md"
    exported.write_text("# Foo\n\nResolved text\n", encoding="utf-8")

    diagnostics = lint_manifest_content(
        manifest, export_map={source.resolve(): exported}
    )

    assert all(diagnostic.code != "content.raw-wikilink" for diagnostic in diagnostics)


def test_lint_reports_exact_custom_duplicate(tmp_path):
    recipe = load_recipe(
        _write_two_vault_recipe(
            tmp_path,
            nimble_body="# Foo\nsame\n",
            custom_body="# Foo\nsame\n",
        )
    )
    manifest = build_manifest(recipe)

    diagnostics = lint_manifest_content(manifest)

    assert any(
        diagnostic.code == "content.custom-duplicate-exact"
        and diagnostic.severity is DiagnosticSeverity.WARNING
        for diagnostic in diagnostics
    )


def test_lint_reports_changed_custom_file_bypassed_by_recipe(tmp_path):
    recipe = load_recipe(
        _write_two_vault_recipe(
            tmp_path,
            nimble_body="# Foo\nOriginal wording.\n",
            custom_body="# Foo\nSci-fi wording.\n",
        )
    )
    manifest = build_manifest(recipe)

    diagnostics = lint_manifest_content(manifest)

    assert any(
        diagnostic.code == "content.custom-override-bypassed"
        and "custom:Foo.md" in (diagnostic.hint or "")
        for diagnostic in diagnostics
    )


def test_lint_allows_changed_custom_file_bypassed_in_source_reference(tmp_path):
    recipe = load_recipe(
        _write_two_vault_recipe(
            tmp_path,
            nimble_body="# Foo\nOriginal wording.\n",
            custom_body="# Foo\nSci-fi wording.\n",
            style="source-reference",
        )
    )
    manifest = build_manifest(recipe)

    diagnostics = lint_manifest_content(manifest)

    assert all(
        diagnostic.code != "content.custom-override-bypassed"
        for diagnostic in diagnostics
    )


def test_lint_reports_mojibake_recipe_source_path(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Bad ΓÇ.md").write_text("# Bad\n", encoding="utf-8")
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: My Book
            vaults:
              v: vault
            chapters:
              - kind: file
                title: Bad
                source: v:Bad ΓÇ.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    manifest = build_manifest(load_recipe(recipe_path))

    diagnostics = lint_manifest_content(manifest)

    assert any(
        diagnostic.code == "recipe.source-mojibake" for diagnostic in diagnostics
    )
