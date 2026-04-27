"""Scan the public Paper Crown tree for private project references."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {
    ".build-cache",
    ".git",
    ".mypy_cache",
    ".papercrown-cache",
    ".pytest-tmp",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    "build",
    "dist",
    "htmlcov",
    "output",
    "Paper Crown",
    "__pycache__",
}
SKIP_FILES = {
    Path(__file__).resolve(),
    ROOT / "uv.lock",
}
SKIP_SUFFIXES = {
    ".gif",
    ".jpg",
    ".jpeg",
    ".pdf",
    ".png",
    ".pyc",
    ".ttf",
    ".webp",
    ".whl",
}
FORBIDDEN = (
    "N" + "imble",
    "Custom" + " Vault",
    "N" + "imble Docs",
    "pdf" + "gen",
    "generate" + ".py",
    "verify_output" + ".py",
    "pdf" + "gen.yaml",
)


def _skip_path(path: Path) -> bool:
    parts = path.relative_to(ROOT).parts
    return any(part in SKIP_DIRS or part.endswith(".egg-info") for part in parts)


def _iter_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if _skip_path(path):
            continue
        if path.resolve() in SKIP_FILES:
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        files.append(path)
    return sorted(files)


def main() -> int:
    """Return non-zero when private references remain."""
    hits: list[str] = []
    for path in _iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for term in FORBIDDEN:
            if term in text:
                rel = path.relative_to(ROOT)
                hits.append(f"{rel}: contains {term!r}")
    if hits:
        print("Public audit failed:")
        for hit in hits:
            print(f"  {hit}")
        return 1
    print("Public audit passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
