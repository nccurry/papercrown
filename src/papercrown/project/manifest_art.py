"""Art resolution helpers used while building manifests."""

from __future__ import annotations

import re
from pathlib import Path

from papercrown.art.roles import IMAGE_SUFFIXES, classify_art_path
from papercrown.project.manifest_models import FillerArtClassification
from papercrown.project.recipe import Recipe
from papercrown.project.slugs import slugify


def art_path(recipe: Recipe, art_filename: str | None) -> Path | None:
    """Resolve an explicit art filename relative to the recipe art directory."""
    if not art_filename:
        return None
    art = (recipe.art_dir / art_filename).resolve()
    return art if art.is_file() else None


def convention_art_path(
    recipe: Recipe,
    roles: set[str],
    *,
    slug: str | None = None,
    prefixes: tuple[str, ...] = (),
) -> Path | None:
    """Find the first art asset matching canonical filename conventions."""
    root = recipe.art_dir
    if not root.is_dir():
        return None
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        classification = classify_art_path(path.resolve(), art_root=root)
        if classification.role not in roles:
            continue
        if slug is not None and not _art_stem_matches_slug(
            path.stem,
            slug=slug,
            prefixes=prefixes,
        ):
            continue
        return path.resolve()
    return None


def resolve_art_asset(
    recipe: Recipe,
    *,
    art: str | None = None,
    role: str = "splash",
    context: str | None = None,
    subject: str | None = None,
) -> Path | None:
    """Resolve an explicit art path or convention-match a role/context slot."""
    if art:
        return art_path(recipe, art)
    root = recipe.art_dir
    if not root.is_dir():
        return None
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().lower()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        resolved = path.resolve()
        classification = classify_art_path(resolved, art_root=root)
        if classification.role != role:
            continue
        if context and not _art_candidate_matches(
            path,
            context,
            classification_context=classification.context,
            classification_subject=classification.subject,
        ):
            continue
        if subject and not _art_candidate_matches(
            path,
            subject,
            classification_context=classification.context,
            classification_subject=classification.subject,
        ):
            continue
        return resolved
    return None


def classify_filler_art_path(
    path: Path,
    *,
    art_root: Path | None = None,
) -> FillerArtClassification:
    """Classify an art path using the central art role registry."""
    classification = classify_art_path(path, art_root=art_root)
    category = _legacy_filler_category(path, classification.role)
    return FillerArtClassification(
        category=category,
        shape=classification.shape,
        height_in=classification.height_in,
        auto_selectable=classification.auto_placeable,
    )


def _art_candidate_matches(
    path: Path,
    wanted: str,
    *,
    classification_context: str | None,
    classification_subject: str | None,
) -> bool:
    """Return whether a classified art file matches a requested slot token."""
    wanted_slug = slugify(wanted)
    candidates = [
        classification_context,
        classification_subject,
        _strip_variant_suffix(slugify(path.stem)),
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        candidate_slug = slugify(candidate)
        if candidate_slug == wanted_slug:
            return True
        if candidate_slug.startswith(f"{wanted_slug}-"):
            return True
        if candidate_slug.endswith(f"-{wanted_slug}"):
            return True
        if f"-{wanted_slug}-" in candidate_slug:
            return True
    return False


def _art_stem_matches_slug(
    stem: str,
    *,
    slug: str,
    prefixes: tuple[str, ...],
) -> bool:
    """Return whether a convention filename points at a chapter slug."""
    normalized = slugify(stem)
    chapter_slug = slugify(slug)
    for prefix in sorted(prefixes, key=len, reverse=True):
        prefix_slug = slugify(prefix)
        if normalized == prefix_slug:
            continue
        token_prefix = f"{prefix_slug}-"
        if not normalized.startswith(token_prefix):
            continue
        subject = _strip_variant_suffix(normalized.removeprefix(token_prefix))
        if subject == chapter_slug:
            return True
        if subject.startswith(f"{chapter_slug}-"):
            return True
        if subject.endswith(f"-{chapter_slug}"):
            return True
    return False


def _strip_variant_suffix(value: str) -> str:
    """Remove a trailing numeric/v-prefixed filename variant token."""
    bits = value.split("-")
    if len(bits) <= 1:
        return value
    if re.fullmatch(r"v?\d+[a-z]?", bits[-1]):
        return "-".join(bits[:-1])
    return value


def _legacy_filler_category(path: Path, role: str) -> str:
    """Map the role registry back to the historical filler category names."""
    stem = path.stem.lower()
    if role in {"cover", "cover-front", "cover-back"}:
        return "cover-art"
    if role == "splash":
        return "manual-splash"
    if role == "spread":
        return "spread-art"
    if role == "chapter-divider":
        return "divider-art"
    if role == "class-opening-spot":
        return "class-opening"
    if role == "ornament-tailpiece":
        return "tailpiece"
    if role in {"ornament-corner", "ornament-folio"}:
        return role
    if role == "faction":
        return "setting-wide"
    if role == "gear":
        return "equipment-wide"
    if role == "vista":
        return "vista-wide"
    for prefix in (
        "stamp-",
        "label-",
        "map-",
        "diagram-",
        "screenshot-",
        "icon-",
        "logo-",
        "portrait-",
        "ship-",
        "vehicle-",
        "location-",
    ):
        if stem.startswith(prefix):
            return prefix.removesuffix("-")
    return role
