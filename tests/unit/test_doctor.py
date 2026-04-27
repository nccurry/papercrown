"""Unit tests for doctor diagnostics."""

from __future__ import annotations

import textwrap

from PIL import Image

from papercrown import doctor
from papercrown.diagnostics import Diagnostic, DiagnosticReport, DiagnosticSeverity
from papercrown.manifest import build_manifest
from papercrown.options import BuildTarget
from papercrown.recipe import load_recipe


def test_diagnostic_report_strict_fails_on_warnings():
    report = DiagnosticReport(
        [
            Diagnostic(
                code="manifest.warning",
                severity=DiagnosticSeverity.WARNING,
                message="warning",
            )
        ]
    )

    assert report.exit_code(strict=False) == 0
    assert report.exit_code(strict=True) == 1


def test_doctor_reports_missing_recipe_art_before_tool_checks(tmp_path, monkeypatch):
    (tmp_path / "vault").mkdir()
    (tmp_path / "art").mkdir()
    (tmp_path / "vault" / "Foo.md").write_text("# Foo\n", encoding="utf-8")
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: My Book
            art_dir: art
            vaults:
              v: vault
            chapters:
              - kind: file
                title: Foo
                art: missing.png
                source: v:Foo.md
            """
        ).lstrip(),
        encoding="utf-8",
    )
    recipe = load_recipe(recipe_path)
    manifest = build_manifest(recipe)
    monkeypatch.setattr(
        doctor,
        "discover_tools",
        lambda *, require_weasyprint: (_ for _ in ()).throw(RuntimeError("no tools")),
    )

    report = doctor.run_doctor(
        recipe,
        manifest,
        target=BuildTarget.PDF,
        strict=True,
    )

    assert any(diagnostic.code == "recipe.art-missing" for diagnostic in report.errors)


def test_doctor_includes_pdf_runtime_dependency_diagnostics(
    mini_recipe,
    mini_manifest,
    monkeypatch,
):
    monkeypatch.setattr(doctor, "_discover_tools", lambda report, *, target: None)
    monkeypatch.setattr(
        doctor,
        "native_pdf_runtime_diagnostics",
        lambda: [
            Diagnostic(
                code="deps.native_pdf_runtime.windows",
                severity=DiagnosticSeverity.WARNING,
                message="Old GTK runtime is active",
            )
        ],
    )

    report = doctor.run_doctor(
        mini_recipe,
        mini_manifest,
        target=BuildTarget.PDF,
        strict=False,
    )

    assert any(
        diagnostic.code == "deps.native_pdf_runtime.windows"
        for diagnostic in report.warnings
    )


def test_doctor_warns_for_invalid_filler_and_page_wear_assets(
    tmp_path,
    monkeypatch,
):
    (tmp_path / "vault").mkdir()
    art = tmp_path / "art"
    (art / "page-wear").mkdir(parents=True)
    (tmp_path / "vault" / "Foo.md").write_text("# Foo\n", encoding="utf-8")
    Image.new("RGB", (128, 128), (255, 255, 255)).save(
        art / "filler-spot-general-bad.png"
    )
    Image.new("RGB", (128, 128), (255, 255, 255)).save(
        art / "page-wear" / "wear-coffee-small-01.png"
    )
    recipe_path = tmp_path / "recipe.yaml"
    recipe_path.write_text(
        textwrap.dedent(
            """
            title: My Book
            art_dir: art
            vaults:
              v: vault
            fillers:
              enabled: true
              slots:
                chapter-end:
                  min_space: 0.65in
                  max_space: 3.5in
                  shapes: [spot]
              assets:
                - id: bad-spot
                  art: filler-spot-general-bad.png
                  shape: spot
                  height: 1.35in
            page_damage:
              enabled: true
              art_dir: page-wear
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
    monkeypatch.setattr(doctor, "_discover_tools", lambda report, *, target: None)

    report = doctor.run_doctor(
        recipe,
        manifest,
        target=BuildTarget.PDF,
        strict=False,
    )
    warning_codes = {diagnostic.code for diagnostic in report.warnings}

    assert "filler.alpha-missing" in warning_codes
    assert "page-wear.alpha-missing" in warning_codes
    assert report.exit_code(strict=False) == 0
    assert report.exit_code(strict=True) == 1
