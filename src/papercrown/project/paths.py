"""Output path helpers shared between the builder and verifier."""

from __future__ import annotations

from pathlib import Path

from papercrown.build.options import OutputProfile, profile_filename_suffix
from papercrown.project.manifest import Chapter
from papercrown.project.recipe import BookConfig


def output_root(recipe: BookConfig) -> Path:
    """Return the root directory under which one recipe writes generated files."""
    return recipe.generated_root


def pdf_root(recipe: BookConfig) -> Path:
    """Return the generated PDF root for a recipe."""
    return output_root(recipe) / "pdf"


def _pdf_name(title: str, *, profile: OutputProfile = OutputProfile.PRINT) -> str:
    """Return a lightly sanitized PDF filename for a title and profile."""
    name = f"{title}{profile_filename_suffix(profile)}.pdf"
    return name.replace("/", "-").replace("\\", "-")


def chapter_pdf_path(
    recipe: BookConfig,
    chapter: Chapter,
    *,
    profile: OutputProfile = OutputProfile.PRINT,
) -> Path:
    """Return the expected PDF path for a standalone chapter build."""
    base = pdf_root(recipe) / "sections"
    chapter_profile = (
        OutputProfile.DRAFT if profile is OutputProfile.DRAFT else OutputProfile.PRINT
    )
    name = _pdf_name(chapter.title, profile=chapter_profile)
    if chapter.individual_pdf_subdir:
        return pdf_root(recipe) / "individuals" / chapter.individual_pdf_subdir / name
    return base / name


def combined_book_path(
    recipe: BookConfig,
    *,
    profile: OutputProfile = OutputProfile.PRINT,
) -> Path:
    """Return the expected PDF path for a combined book build."""
    return pdf_root(recipe) / "book" / _pdf_name(recipe.title, profile=profile)


def web_book_path(recipe: BookConfig) -> Path:
    """Return the static web export entrypoint path for ``recipe``."""
    return output_root(recipe) / "web" / "index.html"
