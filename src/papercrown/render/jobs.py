"""Prepared PDF render job types and cache-aware execution helpers."""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from papercrown.project.manifest import FillerCatalog, PageDamageCatalog
from papercrown.render.pipeline import RenderContext
from papercrown.system.cache import ArtifactCache

LogFn = Callable[[str], None]


@dataclass(frozen=True)
class PdfRenderJob:
    """Prepared PDF render work that can run independently."""

    label: str
    markdown: str
    out: Path
    ctx: RenderContext
    input_paths: list[Path]
    filler_catalog: FillerCatalog | None = None
    page_damage_catalog: PageDamageCatalog | None = None
    recipe_title: str | None = None


@dataclass
class BuildTimer:
    """Small opt-in timer for build orchestration diagnostics."""

    enabled: bool
    log: LogFn | None
    start: float = field(default_factory=time.perf_counter)

    def mark(self, label: str) -> None:
        """Log elapsed time since the previous mark."""
        if not self.enabled or self.log is None:
            return
        now = time.perf_counter()
        self.log(f"  timing build {label}: {now - self.start:.2f}s")
        self.start = now


@dataclass(frozen=True)
class RenderJobHooks:
    """Callbacks that connect generic job execution to the renderer."""

    render: Callable[[PdfRenderJob], None]
    fingerprint: Callable[[PdfRenderJob], str]
    display_path: Callable[[Path], str]


def configure_job_timings(
    jobs: list[PdfRenderJob],
    *,
    enabled: bool,
    log: LogFn | None,
) -> None:
    """Attach render diagnostics to prepared render jobs."""
    for job in jobs:
        ctx = getattr(job, "ctx", None)
        if ctx is None:
            continue
        ctx.warning_log = log
        if enabled:
            ctx.timings = True
            ctx.timing_label = job.label
            ctx.timing_log = log


def run_render_job_cached(
    job: PdfRenderJob,
    *,
    cache: ArtifactCache | None,
    force: bool,
    log: LogFn | None,
    hooks: RenderJobHooks,
) -> bool:
    """Render one prepared job unless the artifact cache is fresh."""
    fingerprint = hooks.fingerprint(job)
    if cache is not None and not force and cache.hit(job.out, fingerprint):
        if log is not None:
            log(f"  cached: {hooks.display_path(job.out)}")
        return True
    hooks.render(job)
    if cache is not None:
        cache.record(job.out, fingerprint)
    return False


def run_prepared_jobs(
    jobs: list[PdfRenderJob],
    *,
    cache: ArtifactCache,
    force: bool,
    max_workers: int,
    log: LogFn | None,
    hooks: RenderJobHooks,
) -> tuple[list[Path], list[Path]]:
    """Run prepared render jobs, optionally in parallel."""
    produced: list[Path] = []
    skipped: list[Path] = []
    pending: list[tuple[PdfRenderJob, str]] = []
    for job in jobs:
        fingerprint = hooks.fingerprint(job)
        if not force and cache.hit(job.out, fingerprint):
            if log is not None:
                log(f"  cached: {hooks.display_path(job.out)}")
            skipped.append(job.out)
            continue
        pending.append((job, fingerprint))

    if max_workers <= 1 or len(pending) <= 1:
        for job, fingerprint in pending:
            hooks.render(job)
            cache.record(job.out, fingerprint)
            produced.append(job.out)
        return produced, skipped

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(hooks.render, job): (job, fingerprint)
            for job, fingerprint in pending
        }
        for future in as_completed(futures):
            job, fingerprint = futures[future]
            future.result()
            cache.record(job.out, fingerprint)
            produced.append(job.out)
    produced.sort(key=lambda path: path.as_posix())
    return produced, skipped
