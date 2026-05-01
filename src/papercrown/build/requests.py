"""Command-neutral build request and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from papercrown.build.options import (
    BuildScope,
    BuildTarget,
    DraftMode,
    OutputProfile,
    PageDamageMode,
    PaginationMode,
)
from papercrown.project.manifest import Manifest
from papercrown.project.recipe import BookConfig


@dataclass(frozen=True)
class BuildRequest:
    """A typed build command created by the app layer from resolved options."""

    recipe: BookConfig
    manifest: Manifest
    target: BuildTarget = BuildTarget.PDF
    scope: BuildScope = BuildScope.ALL
    profile: OutputProfile = OutputProfile.PRINT
    include_art: bool = True
    single_chapter: str | None = None
    force: bool = False
    jobs: int = 1
    clean_pdf: bool = True
    pagination_mode: PaginationMode = PaginationMode.REPORT
    draft_mode: DraftMode = DraftMode.FAST
    page_damage_mode: PageDamageMode = PageDamageMode.AUTO
    filler_debug_overlay: bool = False
    timings: bool = False


@dataclass(frozen=True)
class BuildResult:
    """Artifacts produced by one build invocation."""

    produced: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    export_map: dict[Path, Path] = field(default_factory=dict)
