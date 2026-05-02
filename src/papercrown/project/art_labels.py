"""CSS-declared art label discovery for fixed Markdown images."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_LABEL_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class ArtLabelCatalog:
    """Resolved CSS labels that can be inferred from image filename prefixes."""

    labels: tuple[str, ...] = ()
    css_files: tuple[Path, ...] = ()

    def match_stem(self, stem: str) -> str | None:
        """Return the longest label matching an image stem."""
        normalized = stem.lower()
        for label in sorted(self.labels, key=len, reverse=True):
            if normalized == label or normalized.startswith(f"{label}-"):
                return label
        return None


def discover_art_label_catalog(*roots: Path) -> ArtLabelCatalog:
    """Discover art labels from one or more CSS declaration directories."""
    labels: dict[str, Path] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for css_file in sorted(root.glob("*.css"), key=lambda item: item.name.lower()):
            label = art_label_from_css_file(css_file)
            if label is not None:
                labels[label] = css_file.resolve()
    return ArtLabelCatalog(
        labels=tuple(labels),
        css_files=tuple(dict.fromkeys(labels.values())),
    )


def art_label_from_css_file(path: Path) -> str | None:
    """Return the label declared by a CSS filename, or ``None`` if invalid."""
    label = path.stem.lower()
    return label if _LABEL_RE.fullmatch(label) else None


def project_art_label_catalog(project_dir: Path) -> ArtLabelCatalog:
    """Return CSS-declared labels from ``styles/<label>.css``."""
    return discover_art_label_catalog(project_dir / "styles")


def theme_art_label_catalog(theme_root: Path) -> ArtLabelCatalog:
    """Return CSS-declared labels from ``art-labels/<label>.css``."""
    return discover_art_label_catalog(theme_root / "art-labels")


def merge_art_label_catalogs(*catalogs: ArtLabelCatalog) -> ArtLabelCatalog:
    """Merge catalogs while preserving first-seen label order and CSS order."""
    labels: list[str] = []
    css_files: list[Path] = []
    seen_labels: set[str] = set()
    seen_files: set[Path] = set()
    for catalog in catalogs:
        for label in catalog.labels:
            if label not in seen_labels:
                labels.append(label)
                seen_labels.add(label)
        for css_file in catalog.css_files:
            resolved = css_file.resolve()
            if resolved not in seen_files:
                css_files.append(resolved)
                seen_files.add(resolved)
    return ArtLabelCatalog(labels=tuple(labels), css_files=tuple(css_files))
