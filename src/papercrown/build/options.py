"""Typed build options shared by builders, paths, diagnostics, and the CLI."""

from __future__ import annotations

from enum import Enum


class BuildTarget(Enum):
    """Top-level output target for a build invocation."""

    PDF = "pdf"
    WEB = "web"


class BuildScope(Enum):
    """Subset of PDF outputs requested by a build invocation."""

    ALL = "all"
    BOOK = "book"
    SECTIONS = "sections"
    INDIVIDUALS = "individuals"


class OutputProfile(Enum):
    """PDF rendering profile for output filenames and style metadata."""

    PRINT = "print"
    DIGITAL = "digital"
    DRAFT = "draft"


class PaginationMode(Enum):
    """Post-layout pagination analysis/fix mode."""

    OFF = "off"
    REPORT = "report"
    FIX = "fix"


class DraftMode(Enum):
    """Draft build behavior."""

    FAST = "fast"
    VISUAL = "visual"


class PageDamageMode(Enum):
    """How recipe page-damage art is applied to PDFs."""

    AUTO = "auto"
    OFF = "off"
    FAST = "fast"
    FULL = "full"
    PROOF = "proof"


def profile_filename_suffix(profile: OutputProfile) -> str:
    """Return the filename suffix used by ``profile`` before ``.pdf``."""
    if profile is OutputProfile.DIGITAL:
        return " (Digital)"
    if profile is OutputProfile.DRAFT:
        return " (Draft)"
    return ""
