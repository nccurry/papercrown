"""Post-build verification for book-config-driven generated outputs."""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from papercrown.build.options import BuildScope, OutputProfile
from papercrown.project import paths
from papercrown.project.manifest import Manifest, build_manifest
from papercrown.project.recipe import BookConfig, BookConfigError, load_book_config


@dataclass(frozen=True)
class ExpectedPdf:
    """A PDF that should exist after generating a recipe."""

    path: Path
    title: str
    must_contain: list[str]
    forbidden: list[str]
    required_anchors: list[str] = field(default_factory=list)
    min_size_bytes: int = 5 * 1024

    @property
    def description(self) -> str:
        """Return a short human-readable label for verification output."""
        return f"{self.path.name} ({self.title})"


@dataclass(frozen=True)
class CheckResult:
    """The result of checking one expected PDF."""

    expected: ExpectedPdf
    ok: bool
    failures: list[str]


@dataclass(frozen=True)
class WebImageRefResult:
    """The result of checking generated static-web src references."""

    index_path: Path
    checked_count: int
    missing_refs: list[str] = field(default_factory=list)
    index_missing: bool = False

    @property
    def ok(self) -> bool:
        """Return whether the web artifact and its src references are valid."""
        return not self.index_missing and not self.missing_refs


@dataclass(frozen=True)
class PdfImageStat:
    """Size details for one unique embedded PDF image."""

    xref: int
    width: int
    height: int
    extension: str
    size_bytes: int
    occurrences: int


@dataclass(frozen=True)
class PdfSizeStats:
    """Size summary for one produced PDF."""

    path: Path
    size_bytes: int
    page_count: int
    unique_image_count: int
    unique_image_bytes: int
    largest_images: list[PdfImageStat]


_WEB_SRC_RE = re.compile(r'\bsrc=["\'](?P<value>[^"\']+)["\']', re.IGNORECASE)


def derive_expected(
    manifest: Manifest,
    *,
    include_book: bool,
    profile: OutputProfile,
    scope: BuildScope = BuildScope.ALL,
) -> list[ExpectedPdf]:
    """Derive the PDF outputs produced for a manifest at the requested scope."""
    expected: list[ExpectedPdf] = []
    seen: set[Path] = set()

    def add(
        path: Path,
        title: str,
        *,
        extra_must_contain: list[str] | None = None,
        required_anchors: list[str] | None = None,
    ) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        must = [title]
        if extra_must_contain:
            must.extend(extra_must_contain)
        expected.append(
            ExpectedPdf(
                path=path,
                title=title,
                must_contain=must,
                forbidden=["[[", "]]"],
                required_anchors=required_anchors or [],
            )
        )

    if scope in {BuildScope.ALL, BuildScope.SECTIONS}:
        for chapter in manifest.chapters:
            if chapter.source_files:
                add(
                    paths.chapter_pdf_path(manifest.recipe, chapter, profile=profile),
                    chapter.title,
                )

    if scope in {BuildScope.ALL, BuildScope.INDIVIDUALS}:
        for chapter in manifest.all_chapters():
            if chapter.individual_pdf:
                add(
                    paths.chapter_pdf_path(manifest.recipe, chapter, profile=profile),
                    chapter.title,
                )

    if include_book and scope in {BuildScope.ALL, BuildScope.BOOK}:
        anchors = sorted(_required_book_anchors(manifest))
        add(
            paths.combined_book_path(manifest.recipe, profile=profile),
            manifest.recipe.title,
            required_anchors=anchors,
        )

    return expected


def check_web_image_refs(recipe: BookConfig) -> WebImageRefResult:
    """Check that local ``src=`` references in generated web output exist."""
    index_path = paths.web_book_path(recipe)
    if not index_path.is_file():
        return WebImageRefResult(
            index_path=index_path,
            checked_count=0,
            index_missing=True,
        )

    html = index_path.read_text(encoding="utf-8")
    root = index_path.parent
    refs = list(dict.fromkeys(_local_web_src_refs(html)))
    missing = [ref for ref in refs if not (root / _web_ref_path(ref)).is_file()]
    return WebImageRefResult(
        index_path=index_path,
        checked_count=len(refs),
        missing_refs=missing,
    )


def _local_web_src_refs(html: str) -> list[str]:
    """Return local generated-web ``src`` references."""
    refs: list[str] = []
    for match in _WEB_SRC_RE.finditer(html):
        value = match.group("value").strip()
        if not value or _is_external_web_ref(value):
            continue
        path_value = value.split("#", 1)[0].split("?", 1)[0]
        if path_value:
            refs.append(value)
    return refs


def _is_external_web_ref(value: str) -> bool:
    """Return whether a web reference should not be checked on disk."""
    lowered = value.lower()
    if lowered.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _web_ref_path(value: str) -> Path:
    """Return the filesystem path fragment for one generated-web reference."""
    path_value = value.split("#", 1)[0].split("?", 1)[0]
    return Path(unquote(path_value))


def _required_book_anchors(manifest: Manifest) -> set[str]:
    """Return book anchors that strict verification should require."""
    anchors = {chapter.slug for chapter in manifest.all_chapters() if chapter.slug}
    original_link_targets = re.compile(r"\]\(#([A-Za-z0-9_-]+)\)")
    for chapter in manifest.all_chapters():
        for source in chapter.source_files:
            try:
                text = source.read_text(encoding="utf-8")
            except OSError:
                continue
            for target in original_link_targets.findall(text):
                if target.startswith("original-") or target in {"chaos-table"}:
                    anchors.add(target)
    return anchors


def _read_pdf(pdf_path: Path) -> Any | None:
    """Return a pypdf reader, or ``None`` when import or parsing fails."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    try:
        return PdfReader(str(pdf_path))
    except Exception:
        return None


def _extract_text(pdf_path: Path) -> str:
    """Extract all PDF text, returning an empty string if extraction fails."""
    reader = _read_pdf(pdf_path)
    if reader is None:
        return ""
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _named_destinations(pdf_path: Path) -> set[str]:
    """Return named PDF destinations, or an empty set if they cannot be read."""
    reader = _read_pdf(pdf_path)
    if reader is None:
        return set()
    try:
        return set(reader.named_destinations)
    except Exception:
        return set()


def _contains_required_text(text: str, needle: str) -> bool:
    """Return whether extracted PDF text contains a phrase despite spacing quirks."""
    text_lower = text.lower()
    needle_lower = needle.lower()
    if needle_lower in text_lower:
        return True

    compact_text = re.sub(r"[^a-z0-9]+", "", text_lower)
    compact_needle = re.sub(r"[^a-z0-9]+", "", needle_lower)
    return bool(compact_needle and compact_needle in compact_text)


def check_one(expected: ExpectedPdf) -> CheckResult:
    """Check one expected PDF for existence, size, content, and anchors."""
    failures: list[str] = []
    if not expected.path.is_file():
        return CheckResult(expected, ok=False, failures=["MISSING file"])

    size = expected.path.stat().st_size
    if size < expected.min_size_bytes:
        failures.append(f"too small ({size} bytes < {expected.min_size_bytes})")

    text = _extract_text(expected.path)
    if not text:
        failures.append("could not extract PDF text")
        return CheckResult(expected, ok=not failures, failures=failures)

    for needle in expected.must_contain:
        if not _contains_required_text(text, needle):
            failures.append(f"missing expected substring: {needle!r}")
    for needle in expected.forbidden:
        if needle in text:
            failures.append(f"contains forbidden substring: {needle!r}")
    if expected.required_anchors:
        destinations = _named_destinations(expected.path)
        for anchor in expected.required_anchors:
            if anchor not in destinations:
                failures.append(f"missing PDF anchor: {anchor!r}")
    return CheckResult(expected, ok=not failures, failures=failures)


def pdf_size_stats(pdf_path: Path, *, top_images: int = 5) -> PdfSizeStats | None:
    """Return PDF size diagnostics, or ``None`` if PyMuPDF cannot inspect it."""
    try:
        fitz: Any = importlib.import_module("fitz")
    except ImportError:
        return None

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None
    try:
        occurrences: dict[int, int] = {}
        image_meta: dict[int, tuple[int, int, str, int]] = {}
        for page in doc:
            for raw_image in page.get_images(full=True):
                if not raw_image:
                    continue
                xref = int(raw_image[0])
                occurrences[xref] = occurrences.get(xref, 0) + 1
                if xref in image_meta:
                    continue
                extracted = doc.extract_image(xref)
                if not isinstance(extracted, dict):
                    continue
                image_bytes = extracted.get("image", b"")
                if not isinstance(image_bytes, bytes):
                    image_bytes = b""
                width = int(extracted.get("width") or raw_image[2] or 0)
                height = int(extracted.get("height") or raw_image[3] or 0)
                extension = str(extracted.get("ext") or raw_image[7] or "")
                image_meta[xref] = (width, height, extension, len(image_bytes))

        image_stats = [
            PdfImageStat(
                xref=xref,
                width=width,
                height=height,
                extension=extension,
                size_bytes=size_bytes,
                occurrences=occurrences.get(xref, 0),
            )
            for xref, (width, height, extension, size_bytes) in image_meta.items()
        ]
        image_stats.sort(key=lambda item: item.size_bytes, reverse=True)
        return PdfSizeStats(
            path=pdf_path,
            size_bytes=pdf_path.stat().st_size,
            page_count=int(getattr(doc, "page_count", len(doc))),
            unique_image_count=len(image_stats),
            unique_image_bytes=sum(item.size_bytes for item in image_stats),
            largest_images=image_stats[: max(0, top_images)],
        )
    finally:
        doc.close()


def build_parser(prog: str = "papercrown verify") -> argparse.ArgumentParser:
    """Create the argparse parser for the verification CLI."""
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Verify generated outputs match the book manifest.",
    )
    parser.add_argument("recipe", help="Path to book YAML")
    parser.add_argument(
        "--profile",
        choices=[profile.value for profile in OutputProfile],
        help="PDF output profile to verify. Defaults to print.",
    )
    parser.add_argument(
        "--scope",
        choices=[scope.value for scope in BuildScope],
        default=BuildScope.ALL.value,
        help="PDF output scope to verify. Defaults to all.",
    )
    parser.add_argument(
        "--digital",
        action="store_true",
        help="Compatibility alias for `--profile digital`.",
    )
    parser.add_argument(
        "--no-book",
        action="store_true",
        help="Skip checking the combined book PDF",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero on any failure (default: only on missing files)",
    )
    parser.add_argument(
        "--size-report",
        action="store_true",
        help="Print PDF size, page count, and largest embedded images.",
    )
    parser.add_argument(
        "--top-images",
        type=int,
        default=5,
        help="Number of largest embedded images to print with --size-report.",
    )
    parser.add_argument(
        "--web-assets",
        action="store_true",
        help=(
            "Require generated web output and check that local src references exist."
        ),
    )
    parser.add_argument(
        "--no-web-assets",
        action="store_true",
        help="Skip automatic generated web src reference checks.",
    )
    return parser


def _normalize_profile(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> OutputProfile:
    """Normalize verifier profile flags and reject incompatible aliases."""
    profile = (
        OutputProfile(args.profile) if args.profile is not None else OutputProfile.PRINT
    )
    if args.digital:
        if args.profile is not None and profile is not OutputProfile.DIGITAL:
            parser.error("--digital conflicts with --profile")
        return OutputProfile.DIGITAL
    return profile


def _normalize_scope(args: argparse.Namespace) -> BuildScope:
    """Normalize verifier scope flags."""
    return BuildScope(args.scope)


def _print_result(result: CheckResult) -> None:
    """Print one check result in the existing verifier output format."""
    expected = result.expected
    size_str = (
        f"({expected.path.stat().st_size / 1024:>5.0f} KB)"
        if expected.path.is_file()
        else "(  --   )"
    )
    if result.ok:
        print(f"  OK  {expected.path.name:<40} {size_str}")
        return
    tag = "MISS" if not expected.path.is_file() else "FAIL"
    print(f"  {tag} {expected.path.name:<40} {size_str}")
    for failure in result.failures:
        print(f"        - {failure}")


def _print_size_report(path: Path, *, top_images: int) -> None:
    """Print optional size diagnostics for one PDF."""
    stats = pdf_size_stats(path, top_images=top_images)
    if stats is None:
        print("        size report unavailable")
        return
    print(
        "        "
        f"pages={stats.page_count}, "
        f"file={_format_bytes(stats.size_bytes)}, "
        f"unique_images={stats.unique_image_count}, "
        f"image_bytes={_format_bytes(stats.unique_image_bytes)}"
    )
    for image in stats.largest_images:
        print(
            "        "
            f"image xref={image.xref} "
            f"{image.width}x{image.height} "
            f"{image.extension} "
            f"{_format_bytes(image.size_bytes)} "
            f"uses={image.occurrences}"
        )


def _print_web_result(result: WebImageRefResult) -> None:
    """Print the generated-web asset check result."""
    if result.index_missing:
        print(f"  MISS web/index.html                        ({result.index_path})")
        return
    if result.ok:
        print(
            "  OK  web src assets                         "
            f"({result.checked_count} refs)"
        )
        return
    print(
        "  FAIL web src assets                       "
        f"({len(result.missing_refs)} missing / {result.checked_count} refs)"
    )
    for ref in result.missing_refs[:20]:
        print(f"        - missing src: {ref}")
    if len(result.missing_refs) > 20:
        print(f"        - ... {len(result.missing_refs) - 20} more")


def _format_bytes(size_bytes: int) -> str:
    """Return a compact human-readable byte count."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    return f"{size_bytes / 1024:.0f} KB"


def _print_missing_hint(
    *,
    recipe_path: Path,
    profile: OutputProfile,
    scope: BuildScope,
) -> None:
    """Print a next-step hint when expected generated PDFs are absent."""
    recipe = str(recipe_path)
    print(
        "Hint: run "
        f"`papercrown build {recipe} --scope {scope.value} --profile {profile.value}` "
        "before verifying this scope."
    )
    if scope is BuildScope.ALL:
        print(
            "      If you only built part of the book, rerun verify with "
            "`--scope book`, `--scope sections`, or `--scope individuals`."
        )


def main(argv: list[str] | None = None) -> int:
    """Run the verification CLI and return a process-style exit code."""
    prog = Path(sys.argv[0]).name if argv is None else "papercrown verify"
    parser = build_parser(prog=prog)
    args = parser.parse_args(argv)
    if args.web_assets and args.no_web_assets:
        parser.error("--web-assets conflicts with --no-web-assets")
    profile = _normalize_profile(args, parser)
    scope = _normalize_scope(args)

    try:
        recipe = load_book_config(args.recipe)
    except BookConfigError as error:
        print(f"Book config error: {error}", file=sys.stderr)
        return 2

    manifest = build_manifest(recipe)
    expected = derive_expected(
        manifest,
        include_book=not args.no_book,
        profile=profile,
        scope=scope,
    )

    print(
        f"papercrown verify: {len(expected)} PDF(s) expected for "
        f"{scope.value} scope / {profile.value} profile in book config "
        f"{Path(args.recipe).name}"
    )
    print()

    failures: list[CheckResult] = []
    missing: list[CheckResult] = []
    for item in expected:
        result = check_one(item)
        _print_result(result)
        if args.size_report and item.path.is_file():
            _print_size_report(item.path, top_images=args.top_images)
        if result.ok:
            continue
        if not item.path.is_file():
            missing.append(result)
        else:
            failures.append(result)

    web_result: WebImageRefResult | None = None
    web_index = paths.web_book_path(recipe)
    if args.web_assets or (not args.no_web_assets and web_index.is_file()):
        web_result = check_web_image_refs(recipe)
        _print_web_result(web_result)

    print()
    web_failed = web_result is not None and not web_result.ok
    if not failures and not missing and not web_failed:
        print("All checks passed.")
        return 0
    if missing:
        print(f"{len(missing)} PDF(s) missing.")
        _print_missing_hint(
            recipe_path=Path(args.recipe),
            profile=profile,
            scope=scope,
        )
    if failures:
        print(f"{len(failures)} PDF(s) failed content checks.")
    if web_failed:
        if web_result and web_result.index_missing:
            print("Generated web output is missing.")
            print(
                "Hint: run `papercrown build --target web` before verifying web assets."
            )
        elif web_result:
            print(f"{len(web_result.missing_refs)} generated web src ref(s) missing.")

    if missing or web_failed or (args.strict and failures):
        return 1
    return 0
