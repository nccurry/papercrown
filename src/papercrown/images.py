"""Image diagnostics and cached optimization helpers."""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlparse

from PIL import Image, ImageOps, UnidentifiedImageError

from .diagnostics import Diagnostic, DiagnosticSeverity
from .options import OutputProfile

IMAGE_SUFFIXES: set[str] = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
PASSTHROUGH_SUFFIXES: set[str] = {".svg"}
_MARKDOWN_IMAGE_RE = re.compile(
    r"!\[(?P<alt>[^\]]*)\]\((?P<target>[^)]+)\)(?P<attrs>\{[^}\n]*\})?"
)
_WINDOWS_ABSOLUTE_RE = re.compile(r"^[A-Za-z]:[\\/]")


@dataclass(frozen=True)
class ImageOptimizationSettings:
    """Optimization settings for one output profile."""

    target_dpi: int
    max_long_edge: int | None
    jpeg_quality: int
    jpeg_subsampling: int = 2

    def with_max_long_edge(
        self,
        max_long_edge: int | None,
    ) -> ImageOptimizationSettings:
        """Return settings with an overridden long-edge cap."""
        return ImageOptimizationSettings(
            target_dpi=self.target_dpi,
            max_long_edge=max_long_edge,
            jpeg_quality=self.jpeg_quality,
            jpeg_subsampling=self.jpeg_subsampling,
        )

    def fingerprint_payload(self) -> dict[str, int | str | None]:
        """Return stable settings metadata suitable for cache fingerprints."""
        return {
            "version": IMAGE_OPTIMIZATION_VERSION,
            "target_dpi": self.target_dpi,
            "max_long_edge": self.max_long_edge,
            "jpeg_quality": self.jpeg_quality,
            "jpeg_subsampling": self.jpeg_subsampling,
        }


@dataclass
class ImageOptimizationSession:
    """Per-build memoization for optimized image paths."""

    optimized_paths: dict[tuple[Path, str, int | None], Path]

    def __init__(self) -> None:
        self.optimized_paths = {}


IMAGE_OPTIMIZATION_VERSION = "image-optimization-v2"
LETTER_LONG_EDGE_IN = 11.0


IMAGE_PROFILES: dict[str, ImageOptimizationSettings] = {
    OutputProfile.PRINT.value: ImageOptimizationSettings(
        target_dpi=300,
        max_long_edge=round(LETTER_LONG_EDGE_IN * 300),
        jpeg_quality=95,
        jpeg_subsampling=0,
    ),
    OutputProfile.DIGITAL.value: ImageOptimizationSettings(
        target_dpi=220,
        max_long_edge=round(LETTER_LONG_EDGE_IN * 220),
        jpeg_quality=92,
    ),
    OutputProfile.DRAFT.value: ImageOptimizationSettings(
        target_dpi=110,
        max_long_edge=900,
        jpeg_quality=68,
    ),
    "draft-visual": ImageOptimizationSettings(
        target_dpi=150,
        max_long_edge=round(LETTER_LONG_EDGE_IN * 150),
        jpeg_quality=82,
    ),
    "web": ImageOptimizationSettings(
        target_dpi=180,
        max_long_edge=round(LETTER_LONG_EDGE_IN * 180),
        jpeg_quality=84,
    ),
}


def diagnose_image(path: Path, *, code_prefix: str = "image") -> list[Diagnostic]:
    """Inspect one referenced image and return quality diagnostics."""
    resolved = path.resolve()
    if not resolved.is_file():
        return [
            Diagnostic(
                code=f"{code_prefix}.missing",
                severity=DiagnosticSeverity.ERROR,
                message="referenced image does not exist",
                path=resolved,
            )
        ]

    suffix = resolved.suffix.lower()
    if suffix in PASSTHROUGH_SUFFIXES:
        return []
    if suffix not in IMAGE_SUFFIXES:
        return [
            Diagnostic(
                code=f"{code_prefix}.unsupported",
                severity=DiagnosticSeverity.WARNING,
                message=f"image type {suffix or '<none>'} may not render everywhere",
                path=resolved,
            )
        ]

    diagnostics: list[Diagnostic] = []
    try:
        with Image.open(resolved) as image:
            width, height = image.size
    except (OSError, UnidentifiedImageError):
        return [
            Diagnostic(
                code=f"{code_prefix}.unreadable",
                severity=DiagnosticSeverity.ERROR,
                message="Pillow could not read this image",
                path=resolved,
            )
        ]

    megapixels = (width * height) / 1_000_000
    size_mb = resolved.stat().st_size / 1_000_000
    if megapixels > 24:
        diagnostics.append(
            Diagnostic(
                code=f"{code_prefix}.large-dimensions",
                severity=DiagnosticSeverity.INFO,
                message=f"large image dimensions ({width}x{height})",
                path=resolved,
                hint="digital, draft, and web builds use cached resized copies",
            )
        )
    if size_mb > 8:
        diagnostics.append(
            Diagnostic(
                code=f"{code_prefix}.large-file",
                severity=DiagnosticSeverity.INFO,
                message=f"large image file ({size_mb:.1f} MB)",
                path=resolved,
                hint="consider replacing the source asset if builds become slow",
            )
        )
    return diagnostics


def optimize_image(
    path: Path,
    *,
    profile: OutputProfile | str,
    cache_root: Path | None = None,
    max_long_edge: int | None = None,
    session: ImageOptimizationSession | None = None,
) -> Path:
    """Return a cached optimized raster image for the requested profile.

    Source art stays untouched. SVG and unreadable images pass through unchanged
    because there is no safe raster optimization to apply here.
    """
    profile_name = profile.value if isinstance(profile, OutputProfile) else profile
    settings = image_profile_settings(profile_name)
    if max_long_edge is not None:
        settings = settings.with_max_long_edge(max(1, max_long_edge))
    source = path.resolve()
    if source.suffix.lower() in PASSTHROUGH_SUFFIXES or not source.is_file():
        return source

    session_key = (source, profile_name, settings.max_long_edge)
    if session is not None and session_key in session.optimized_paths:
        return session.optimized_paths[session_key]

    digest = _image_cache_key(source, profile_name, settings)
    output_dir = (cache_root or _default_image_cache_root()) / profile_name
    output_dir.mkdir(parents=True, exist_ok=True)

    temp: Path | None = None
    try:
        with Image.open(source) as image:
            image.load()
            has_alpha = _has_alpha(image)
            extension = ".png" if has_alpha else ".jpg"
            dest = output_dir / f"{source.stem}-{digest[:12]}{extension}"
            if dest.is_file():
                resolved = dest.resolve()
                if session is not None:
                    session.optimized_paths[session_key] = resolved
                return resolved

            optimized = _resized_image(image, settings.max_long_edge)
            temp = _temp_output_path(dest)
            if has_alpha:
                if optimized.mode not in {"RGBA", "LA"}:
                    optimized = optimized.convert("RGBA")
                optimized.save(temp, format="PNG", optimize=True)
            else:
                optimized = optimized.convert("RGB")
                optimized.save(
                    temp,
                    format="JPEG",
                    quality=settings.jpeg_quality,
                    subsampling=settings.jpeg_subsampling,
                    optimize=True,
                    progressive=True,
                )
            temp.replace(dest)
            resolved = dest.resolve()
            if session is not None:
                session.optimized_paths[session_key] = resolved
            return resolved
    except (OSError, UnidentifiedImageError):
        return source
    finally:
        if temp is not None and temp.exists():
            temp.unlink(missing_ok=True)


def optimize_image_for_box(
    path: Path,
    *,
    profile: OutputProfile | str,
    max_width_in: float,
    max_height_in: float | None = None,
    scale_margin: float = 1.15,
    cache_root: Path | None = None,
    session: ImageOptimizationSession | None = None,
) -> Path:
    """Return a cached image capped to its largest rendered size."""
    settings = image_profile_settings(profile)
    max_dimension_in = max(max_width_in, max_height_in or max_width_in)
    display_cap = math.ceil(max_dimension_in * settings.target_dpi * scale_margin)
    profile_cap = settings.max_long_edge
    max_long_edge = (
        min(display_cap, profile_cap) if profile_cap is not None else display_cap
    )
    return optimize_image(
        path,
        profile=profile,
        cache_root=cache_root,
        max_long_edge=max_long_edge,
        session=session,
    )


def image_profile_settings(profile: OutputProfile | str) -> ImageOptimizationSettings:
    """Return image settings for a profile, defaulting to print quality."""
    profile_name = profile.value if isinstance(profile, OutputProfile) else profile
    return IMAGE_PROFILES.get(profile_name, IMAGE_PROFILES[OutputProfile.PRINT.value])


def image_optimization_fingerprint(
    profile: OutputProfile | str,
) -> dict[str, int | str | None]:
    """Return stable image-optimization settings for render-cache fingerprints."""
    profile_name = profile.value if isinstance(profile, OutputProfile) else profile
    payload = image_profile_settings(profile_name).fingerprint_payload()
    payload["profile"] = profile_name
    return payload


def rewrite_markdown_image_refs(
    markdown: str,
    *,
    search_roots: list[Path],
    profile: OutputProfile | str,
    cache_root: Path | None = None,
    session: ImageOptimizationSession | None = None,
) -> str:
    """Rewrite local markdown image references to cached optimized images."""

    def replace(match: re.Match[str]) -> str:
        target = _unwrap_markdown_target(match.group("target"))
        source = resolve_local_image(target, search_roots=search_roots)
        if source is None:
            return match.group(0)
        optimized = optimize_image(
            source,
            profile=profile,
            cache_root=cache_root,
            session=session,
        )
        attrs = match.group("attrs") or ""
        return f"![{match.group('alt')}](<{optimized.as_posix()}>){attrs}"

    return _MARKDOWN_IMAGE_RE.sub(replace, markdown)


def replace_markdown_image_refs_with_placeholders(
    markdown: str,
    *,
    search_roots: list[Path],
) -> str:
    """Replace local image references with lightweight draft placeholders."""

    def replace(match: re.Match[str]) -> str:
        target = _unwrap_markdown_target(match.group("target"))
        source = resolve_local_image(target, search_roots=search_roots)
        if source is None:
            return match.group(0)
        label = match.group("alt").strip() or source.stem.replace("-", " ")
        escaped = label.replace("\n", " ").strip() or "art"
        return (
            ":::: {.draft-art-placeholder}\n"
            f"Art omitted in fast draft: {escaped}\n"
            "::::"
        )

    return _MARKDOWN_IMAGE_RE.sub(replace, markdown)


def resolve_local_image(target: str, *, search_roots: list[Path]) -> Path | None:
    """Resolve a local image target against known search roots."""
    if _is_external_reference(target):
        return None
    unquoted = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not unquoted:
        return None
    if _WINDOWS_ABSOLUTE_RE.match(unquoted):
        path = Path(unquoted)
        return path.resolve() if path.is_file() else None
    parsed = urlparse(unquoted)
    if parsed.scheme == "file":
        file_path = unquote(parsed.path)
        if re.match(r"^/[A-Za-z]:/", file_path):
            file_path = file_path[1:]
        path = Path(file_path)
        return path.resolve() if path.is_file() else None
    if parsed.scheme:
        return None
    path = Path(unquoted)
    if path.is_absolute():
        return path.resolve() if path.is_file() else None
    for root in search_roots:
        direct = root / path
        if direct.is_file():
            return direct.resolve()
    if len(path.parts) == 1:
        for root in search_roots:
            matches = sorted(
                candidate for candidate in root.rglob(path.name) if candidate.is_file()
            )
            if matches:
                return matches[0].resolve()
    return None


def copy_image(source: Path, dest: Path) -> None:
    """Copy an image file, creating the destination parent first."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def _default_image_cache_root() -> Path:
    """Return a caller-neutral cache root for direct library use."""
    return Path.cwd() / ".papercrown-cache" / "images"


def _image_cache_key(
    source: Path,
    profile_name: str,
    settings: ImageOptimizationSettings,
) -> str:
    digest = hashlib.sha256()
    for value in (
        IMAGE_OPTIMIZATION_VERSION,
        profile_name,
        source.suffix.lower(),
        str(settings.target_dpi),
        str(settings.max_long_edge),
        str(settings.jpeg_quality),
        str(settings.jpeg_subsampling),
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    digest.update(source.read_bytes())
    return digest.hexdigest()


def _temp_output_path(dest: Path) -> Path:
    """Return a unique sibling temp path for atomic cache writes."""
    token = f"{os.getpid()}-{threading.get_ident()}"
    return dest.with_name(f".{dest.name}.{token}.tmp")


def _has_alpha(image: Image.Image) -> bool:
    mode = image.mode
    return (
        mode in {"RGBA", "LA", "PA"}
        or mode.endswith("A")
        or (mode == "P" and "transparency" in image.info)
    )


def _resized_image(image: Image.Image, max_long_edge: int | None) -> Image.Image:
    transposed = ImageOps.exif_transpose(image)
    if max_long_edge is None:
        return transposed.copy()
    width, height = transposed.size
    long_edge = max(width, height)
    if long_edge <= max_long_edge:
        return transposed.copy()
    scale = max_long_edge / long_edge
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return transposed.resize(size, Image.Resampling.LANCZOS)


def _unwrap_markdown_target(target: str) -> str:
    stripped = target.strip()
    if stripped.startswith("<") and stripped.endswith(">"):
        return stripped[1:-1]
    return stripped


def _is_external_reference(value: str) -> bool:
    lowered = value.lower()
    return (
        lowered.startswith("#")
        or lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("data:")
        or lowered.startswith("mailto:")
        or lowered.startswith("tel:")
    )
