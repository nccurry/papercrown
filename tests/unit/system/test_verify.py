"""Unit tests for verifier.derive_expected and check_one."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from papercrown.app.options import BuildScope, OutputProfile
from papercrown.project.manifest import build_manifest
from papercrown.project.recipe import load_recipe
from papercrown.system import verify as verifier

# ---------------------------------------------------------------------------
# Helpers: build a small fixture vault + recipe
# ---------------------------------------------------------------------------


@pytest.fixture
def tiny_workspace(tmp_path):
    base = tmp_path / "vault"
    base.mkdir()
    (base / "Setting.md").write_text("# Setting\nbody\n", encoding="utf-8")
    (base / "Heroes").mkdir()
    (base / "Heroes" / "Mage").mkdir()
    (base / "Heroes" / "Mage" / "Mage Description.md").write_text(
        "# Mage", encoding="utf-8"
    )
    (base / "Heroes" / "Classes List.md").write_text(
        textwrap.dedent("""
            # Mage
            - [[Mage Description]]
        """).lstrip(),
        encoding="utf-8",
    )

    rp = tmp_path / "recipe.yaml"
    rp.write_text(
        textwrap.dedent("""
        title: Tiny Book
        vaults:
          v: vault
        chapters:
          - kind: file
            title: Setting
            source: v:Setting.md
          - kind: classes-catalog
            source: v:Heroes/Classes List.md
            wrapper: false
            individual_pdfs: true
            individual_pdf_subdir: classes
    """).lstrip(),
        encoding="utf-8",
    )
    return tmp_path, rp


# ---------------------------------------------------------------------------
# derive_expected
# ---------------------------------------------------------------------------


class TestDeriveExpected:
    def test_includes_section_individual_and_book(self, tiny_workspace):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        expected = verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.PRINT,
        )
        names = sorted(e.path.name for e in expected)
        # Section PDF: Mage (the only top-level "section" with source files)
        # Individual PDF: also Mage (individual_pdfs=true) -- dedup'd
        # Book PDF: Tiny Book.pdf
        assert "Mage.pdf" in names
        assert "Tiny Book.pdf" in names
        # Setting is also a top-level chapter with source_files
        assert "Setting.pdf" in names

    def test_skips_book_when_disabled(self, tiny_workspace):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        expected = verifier.derive_expected(
            m,
            include_book=False,
            profile=OutputProfile.PRINT,
        )
        names = {e.path.name for e in expected}
        assert "Tiny Book.pdf" not in names

    def test_digital_book_filename(self, tiny_workspace):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        expected = verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.DIGITAL,
        )
        names = {e.path.name for e in expected}
        assert "Tiny Book (Digital).pdf" in names

    def test_draft_filenames(self, tiny_workspace):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        expected = verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.DRAFT,
        )
        names = {e.path.name for e in expected}
        assert "Tiny Book (Draft).pdf" in names
        assert "Setting (Draft).pdf" in names

    def test_combined_book_requires_manifest_anchors(self, tiny_workspace):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        expected = verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.DIGITAL,
        )
        book = next(e for e in expected if e.path.name == "Tiny Book (Digital).pdf")
        assert "setting" in book.required_anchors
        assert "mage" in book.required_anchors

    def test_combined_book_requires_original_link_targets(self, tmp_path):
        base = tmp_path / "vault"
        base.mkdir()
        (base / "Custom.md").write_text(
            "# Custom\nSee [Original](#original-custom).\n",
            encoding="utf-8",
        )
        rp = tmp_path / "recipe.yaml"
        rp.write_text(
            textwrap.dedent(
                """
                title: Tiny Book
                vaults:
                  v: vault
                chapters:
                  - kind: file
                    title: Custom
                    source: v:Custom.md
                """
            ).lstrip(),
            encoding="utf-8",
        )
        m = build_manifest(load_recipe(rp))
        expected = verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.PRINT,
        )
        book = next(e for e in expected if e.path.name == "Tiny Book.pdf")
        assert "custom" in book.required_anchors
        assert "original-custom" in book.required_anchors

    def test_dedup_by_resolved_path(self, tiny_workspace):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        expected = verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.PRINT,
        )
        # No two expected entries should refer to the same resolved path.
        resolved = [e.path.resolve() for e in expected]
        assert len(resolved) == len(set(resolved))

    def test_scope_book_only_expects_combined_book(self, tiny_workspace):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        expected = verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.PRINT,
            scope=BuildScope.BOOK,
        )
        names = {e.path.name for e in expected}
        assert names == {"Tiny Book.pdf"}

    def test_scope_sections_does_not_expect_book_or_individuals(self, tiny_workspace):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        expected = verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.PRINT,
            scope=BuildScope.SECTIONS,
        )
        names = {e.path.name for e in expected}
        assert "Tiny Book.pdf" not in names
        assert names == {"Mage.pdf", "Setting.pdf"}


# ---------------------------------------------------------------------------
# check_one: missing file / size / content checks
# ---------------------------------------------------------------------------


class TestCheckOne:
    def test_missing_file_marked_missing(self, tmp_path):
        exp = verifier.ExpectedPdf(
            path=tmp_path / "nope.pdf",
            title="Nope",
            must_contain=["Nope"],
            forbidden=[],
        )
        r = verifier.check_one(exp)
        assert r.ok is False
        assert any("MISSING" in f for f in r.failures)

    def test_too_small_file_fails(self, tmp_path):
        p = tmp_path / "tiny.pdf"
        p.write_bytes(b"%PDF-1.4\n")  # well below the 5KB threshold
        exp = verifier.ExpectedPdf(
            path=p,
            title="Tiny",
            must_contain=[],
            forbidden=[],
        )
        r = verifier.check_one(exp)
        # Size failure is logged regardless of text-extraction; ok is False.
        # (Text extraction returns "" so the must_contain loop is skipped.)
        assert r.ok is False
        assert any("too small" in f for f in r.failures)

    def test_extraction_failure_fails_even_when_size_passes(
        self, tmp_path, monkeypatch
    ):
        # File big enough to pass the size check, but unparseable as PDF;
        # text extraction returning "" means content checks cannot be trusted.
        p = tmp_path / "big-but-bogus.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"A" * (10 * 1024))
        exp = verifier.ExpectedPdf(
            path=p,
            title="Whatever",
            must_contain=["Whatever"],
            forbidden=[],
        )
        # Force the extraction path to return empty (simulates pypdf failure).
        monkeypatch.setattr(verifier, "_extract_text", lambda _p: "")
        r = verifier.check_one(exp)
        assert r.ok is False
        assert "could not extract PDF text" in r.failures

    def test_missing_substring_fails(self, tmp_path, monkeypatch):
        p = tmp_path / "ok.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"A" * (10 * 1024))
        monkeypatch.setattr(
            verifier,
            "_extract_text",
            lambda _p: "Some extracted text without the needle",
        )
        exp = verifier.ExpectedPdf(
            path=p,
            title="Wanted",
            must_contain=["Wanted"],
            forbidden=[],
        )
        r = verifier.check_one(exp)
        assert r.ok is False
        assert any("missing expected substring" in f for f in r.failures)

    def test_forbidden_substring_fails(self, tmp_path, monkeypatch):
        p = tmp_path / "ok.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"A" * (10 * 1024))
        monkeypatch.setattr(
            verifier,
            "_extract_text",
            lambda _p: "Title Here and a leaked [[wikilink]] in the body",
        )
        exp = verifier.ExpectedPdf(
            path=p,
            title="Title Here",
            must_contain=["Title Here"],
            forbidden=["[[", "]]"],
        )
        r = verifier.check_one(exp)
        assert r.ok is False
        assert any("forbidden substring" in f for f in r.failures)

    def test_title_substring_check_is_case_insensitive(self, tmp_path, monkeypatch):
        # Regression: `verifier` originally folded both the text AND
        # the needle to lowercase. That behavior is what let today's
        # rendered cover -- which pypdf extracts a title without spacing
        # without a space -- still pass the `"Sample Space Opera"`
        # must_contain check WHEN text extraction preserved the space.
        # If anyone tightens this comparison to case-sensitive, the PDF
        # with a styled cover title will start failing verify. Lock it
        # down.
        p = tmp_path / "ok.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"A" * (10 * 1024))
        monkeypatch.setattr(
            verifier,
            "_extract_text",
            lambda _p: "MY BOOK TITLE rendered in all caps by fancy CSS",
        )
        exp = verifier.ExpectedPdf(
            path=p,
            title="My Book Title",
            must_contain=["My Book Title"],
            forbidden=[],
        )
        r = verifier.check_one(exp)
        assert r.ok is True, f"unexpected failures: {r.failures}"

    def test_title_substring_check_tolerates_extracted_spacing_loss(
        self,
        tmp_path,
        monkeypatch,
    ):
        p = tmp_path / "ok.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"A" * (10 * 1024))
        monkeypatch.setattr(
            verifier,
            "_extract_text",
            lambda _p: "SAMPLE SPACEOPERAA Player Book",
        )
        exp = verifier.ExpectedPdf(
            path=p,
            title="Sample Space Opera",
            must_contain=["Sample Space Opera"],
            forbidden=[],
        )
        r = verifier.check_one(exp)
        assert r.ok is True, f"unexpected failures: {r.failures}"

    def test_missing_required_anchor_fails(self, tmp_path, monkeypatch):
        p = tmp_path / "ok.pdf"
        p.write_bytes(b"%PDF-1.4\n" + b"A" * (10 * 1024))
        monkeypatch.setattr(verifier, "_extract_text", lambda _p: "Title")
        monkeypatch.setattr(verifier, "_named_destinations", lambda _p: {"title"})
        exp = verifier.ExpectedPdf(
            path=p,
            title="Title",
            must_contain=["Title"],
            forbidden=[],
            required_anchors=["missing-anchor"],
        )
        r = verifier.check_one(exp)
        assert r.ok is False
        assert any("missing PDF anchor" in f for f in r.failures)


# ---------------------------------------------------------------------------
# main() CLI: exit-code contract
# ---------------------------------------------------------------------------


class TestMain:
    """End-to-end tests for the CLI entry point. These are how `task verify`
    is run, so returning the wrong exit code means CI sees success when
    files are actually missing."""

    def _make_pdf(self, p: Path, *, size_kb: int = 10) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"%PDF-1.4\n" + b"A" * (size_kb * 1024))

    def test_exit_1_when_file_missing(self, tiny_workspace, capsys):
        _, rp = tiny_workspace
        # Don't create any PDFs -- everything should be MISS.
        rc = verifier.main([str(rp)])
        assert rc == 1, "missing files should produce a non-zero exit code"
        out = capsys.readouterr().out
        assert "MISS" in out
        assert "PDF(s) missing" in out

    def test_exit_0_when_files_all_present(self, tiny_workspace, capsys, monkeypatch):
        workspace, rp = tiny_workspace
        # Derive the expected PDF paths from the manifest and create each one
        # at the right generated path.
        m = build_manifest(load_recipe(rp))
        for exp in verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.PRINT,
        ):
            self._make_pdf(exp.path)

        # Stub out text extraction so missing/forbidden substring checks
        # just see the expected title (passes) and nothing forbidden.
        monkeypatch.setattr(
            verifier,
            "_extract_text",
            lambda p: f"{p.stem} content here",
        )
        monkeypatch.setattr(
            verifier,
            "_named_destinations",
            lambda _p: {"setting", "mage"},
        )
        rc = verifier.main([str(rp)])
        assert rc == 0, "all files present should exit 0"
        out = capsys.readouterr().out
        assert "All checks passed" in out

    def test_strict_mode_fails_on_content_errors(
        self, tiny_workspace, capsys, monkeypatch
    ):
        # `--strict` should turn content failures (missing title substring,
        # forbidden substrings) into a non-zero exit. Without --strict,
        # only missing files cause rc != 0.
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        for exp in verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.PRINT,
        ):
            self._make_pdf(exp.path)
        # Inject a leaked wikilink so the forbidden check fires on every
        # expected PDF.
        monkeypatch.setattr(
            verifier,
            "_extract_text",
            lambda p: f"{p.stem} but also [[leaked]] wikilink",
        )
        monkeypatch.setattr(
            verifier,
            "_named_destinations",
            lambda _p: {"setting", "mage"},
        )

        rc_loose = verifier.main([str(rp)])
        assert rc_loose == 0, "default mode must ignore content failures"

        rc_strict = verifier.main([str(rp), "--strict"])
        assert rc_strict == 1, "--strict should turn content failures into exit 1"

    def test_profile_digital_alias_matches_legacy_flag(self, tiny_workspace, capsys):
        _, rp = tiny_workspace

        rc = verifier.main([str(rp), "--profile", "digital"])

        assert rc == 1
        out = capsys.readouterr().out
        assert "Tiny Book (Digital).pdf" in out

    def test_scope_book_cli_only_requires_combined_book(
        self, tiny_workspace, capsys, monkeypatch
    ):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        for exp in verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.PRINT,
            scope=BuildScope.BOOK,
        ):
            self._make_pdf(exp.path)
        monkeypatch.setattr(verifier, "_extract_text", lambda _p: "Tiny Book")
        monkeypatch.setattr(
            verifier,
            "_named_destinations",
            lambda _p: {"setting", "mage"},
        )

        rc = verifier.main([str(rp), "--scope", "book"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "book scope" in out
        assert "All checks passed" in out

    def test_rejects_conflicting_profile_alias(self, tiny_workspace):
        _, rp = tiny_workspace

        with pytest.raises(SystemExit):
            verifier.main([str(rp), "--digital", "--profile", "draft"])

    def test_size_report_prints_pdf_image_diagnostics(
        self, tiny_workspace, capsys, monkeypatch
    ):
        _, rp = tiny_workspace
        m = build_manifest(load_recipe(rp))
        for exp in verifier.derive_expected(
            m,
            include_book=True,
            profile=OutputProfile.PRINT,
        ):
            self._make_pdf(exp.path)

        monkeypatch.setattr(
            verifier,
            "_extract_text",
            lambda p: f"{p.stem} content here",
        )
        monkeypatch.setattr(
            verifier,
            "_named_destinations",
            lambda _p: {"setting", "mage"},
        )
        monkeypatch.setattr(
            verifier,
            "pdf_size_stats",
            lambda p, *, top_images: verifier.PdfSizeStats(
                path=p,
                size_bytes=12 * 1024,
                page_count=3,
                unique_image_count=1,
                unique_image_bytes=4096,
                largest_images=[
                    verifier.PdfImageStat(
                        xref=10,
                        width=640,
                        height=480,
                        extension="jpeg",
                        size_bytes=4096,
                        occurrences=2,
                    )
                ][:top_images],
            ),
        )

        rc = verifier.main([str(rp), "--size-report", "--top-images", "1"])

        assert rc == 0
        out = capsys.readouterr().out
        assert "unique_images=1" in out
        assert "image xref=10 640x480 jpeg 4 KB uses=2" in out
