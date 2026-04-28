"""Post-layout pagination analysis and conservative fixups."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# CSS pixel to inch conversion for WeasyPrint layout measurements.
PX_PER_IN = 96.0
# Remaining page space below which a heading may be stranded.
STRANDED_HEADING_REMAINING_IN = 0.8
# Minimum following content needed to avoid a stranded-heading warning.
STRANDED_HEADING_FOLLOWING_IN = 0.25
# Blank trailing space threshold for excessive-gap warnings.
EXCESSIVE_GAP_IN = 2.75
# Minimum content height expected on a terminal non-special page.
TINY_TERMINAL_FRAGMENT_IN = 1.0
# Allowed rendered overflow before reporting a page overflow issue.
OVERFLOW_TOLERANCE_PX = 3.0
# WeasyPrint page names excluded from pagination quality checks.
SKIP_PAGE_NAMES = {"cover-page", "divider-page", "digital-divider-page"}
# DOM classes excluded from pagination quality checks.
SKIP_PAGE_CLASSES = {"cover", "toc", "section-divider", "splash-page"}
# Heading tags considered for stranded-heading detection.
HEADING_TAGS = {"h2", "h3", "h4"}


@dataclass(frozen=True)
class PaginationIssue:
    """One pagination quality issue found in a rendered document."""

    kind: str
    page_number: int
    score: int
    message: str
    element_id: str | None = None
    element_tag: str | None = None


@dataclass(frozen=True)
class PaginationReport:
    """Pagination score and issues for one rendered document."""

    page_count: int
    issues: list[PaginationIssue] = field(default_factory=list)

    @property
    def total_badness(self) -> int:
        """Return the total weighted badness score."""
        return sum(issue.score for issue in self.issues)


@dataclass(frozen=True)
class PaginationFixResult:
    """Result of applying conservative HTML pagination fixups."""

    html: str
    applied_ids: list[str]

    @property
    def changed(self) -> bool:
        """Return whether any fix was inserted."""
        return bool(self.applied_ids)


@dataclass(frozen=True)
class _PageMetrics:
    """Cached layout facts for one WeasyPrint page."""

    page_number: int
    page_box: Any
    boxes: list[Any]
    content_top: float
    content_bottom: float
    content_left: float
    content_right: float
    lowest_occupied_bottom: float


def analyze_document(document: object) -> PaginationReport:
    """Analyze a WeasyPrint document and return pagination issues."""
    pages = list(getattr(document, "pages", []))
    issues: list[PaginationIssue] = []
    non_skip_pages: list[_PageMetrics] = []
    for page_index, page in enumerate(pages, start=1):
        metrics = _page_metrics(page, page_index)
        if metrics is None or _should_skip_page(metrics):
            continue
        non_skip_pages.append(metrics)
        issues.extend(_stranded_heading_issues(metrics))
        issues.extend(_overflow_issues(metrics))
        gap_issue = _excessive_gap_issue(metrics)
        if gap_issue is not None:
            issues.append(gap_issue)

    if non_skip_pages:
        terminal = _tiny_terminal_fragment_issue(non_skip_pages[-1])
        if terminal is not None:
            issues.append(terminal)

    return PaginationReport(page_count=len(pages), issues=issues)


def inject_page_break_fixes(
    source_html: str,
    report: PaginationReport,
    *,
    max_fixes: int = 8,
) -> PaginationFixResult:
    """Insert page breaks before stranded headings with stable HTML ids."""
    out = source_html
    applied: list[str] = []
    candidates = [
        issue
        for issue in report.issues
        if issue.kind == "stranded-heading" and issue.element_id
    ]
    for issue in sorted(candidates, key=lambda item: (item.page_number, item.score)):
        if len(applied) >= max_fixes:
            break
        element_id = issue.element_id
        if element_id is None or _has_existing_fix(out, element_id):
            continue
        updated, count = _insert_break_before_heading(out, element_id)
        if count:
            out = updated
            applied.append(element_id)
    return PaginationFixResult(html=out, applied_ids=applied)


def write_report(
    path: Path,
    report: PaginationReport,
    *,
    fix_ids: list[str] | None = None,
    accepted_fix: bool | None = None,
    fix_reason: str | None = None,
) -> None:
    """Write a Markdown pagination report."""
    lines = [
        "# Pagination Report",
        "",
        f"- Pages: {report.page_count}",
        f"- Badness: {report.total_badness}",
        f"- Issues: {len(report.issues)}",
    ]
    if accepted_fix is not None:
        status = "accepted" if accepted_fix else "rejected"
        lines.append(f"- Auto-fix: {status}")
    if fix_ids:
        lines.append(f"- Inserted breaks: {', '.join(fix_ids)}")
    if fix_reason:
        lines.append(f"- Fix note: {fix_reason}")
    lines.extend(["", "## Issues", ""])
    if not report.issues:
        lines.append("No pagination issues detected.")
    for issue in report.issues:
        element = f" `{issue.element_id}`" if issue.element_id else ""
        lines.append(
            "- "
            f"p{issue.page_number} {issue.kind}{element}: "
            f"{issue.message} (score {issue.score})"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _stranded_heading_issues(metrics: _PageMetrics) -> list[PaginationIssue]:
    issues: list[PaginationIssue] = []
    for box in metrics.boxes:
        element = getattr(box, "element", None)
        tag = str(getattr(box, "element_tag", "") or "").lower()
        if element is None or tag not in HEADING_TAGS:
            continue
        element_id = _element_id(element)
        if not element_id:
            continue
        bottom = _box_bottom(box)
        remaining_in = max(0.0, metrics.content_bottom - bottom) / PX_PER_IN
        if remaining_in > STRANDED_HEADING_REMAINING_IN:
            continue
        following_in = _occupied_height_after(metrics, bottom) / PX_PER_IN
        if following_in >= STRANDED_HEADING_FOLLOWING_IN:
            continue
        title = _element_text(element) or element_id
        score = 120 + int((STRANDED_HEADING_REMAINING_IN - remaining_in) * 40)
        issues.append(
            PaginationIssue(
                kind="stranded-heading",
                page_number=metrics.page_number,
                score=score,
                message=f"heading near page bottom: {title}",
                element_id=element_id,
                element_tag=tag,
            )
        )
    return issues


def _overflow_issues(metrics: _PageMetrics) -> list[PaginationIssue]:
    issues: list[PaginationIssue] = []
    seen: set[tuple[str | None, str, int]] = set()
    for box in metrics.boxes:
        element = getattr(box, "element", None)
        tag = str(getattr(box, "element_tag", "") or "").lower()
        if element is None or tag in {"html", "body"}:
            continue
        right_overflow = _box_right(box) - metrics.content_right
        left_overflow = metrics.content_left - _box_left(box)
        bottom_overflow = _box_bottom(box) - metrics.content_bottom
        overflow = max(right_overflow, left_overflow, bottom_overflow)
        if overflow <= OVERFLOW_TOLERANCE_PX:
            continue
        element_id = _element_id(element)
        key = (element_id, tag, metrics.page_number)
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            PaginationIssue(
                kind="overflow",
                page_number=metrics.page_number,
                score=180 + int(overflow / PX_PER_IN * 40),
                message=f"{tag or 'element'} extends outside the content box",
                element_id=element_id,
                element_tag=tag,
            )
        )
    return issues


def _excessive_gap_issue(metrics: _PageMetrics) -> PaginationIssue | None:
    gap_in = (
        max(0.0, metrics.content_bottom - metrics.lowest_occupied_bottom) / PX_PER_IN
    )
    if gap_in < EXCESSIVE_GAP_IN:
        return None
    return PaginationIssue(
        kind="bottom-gap",
        page_number=metrics.page_number,
        score=30 + int(gap_in * 10),
        message=f"{gap_in:.2f}in blank at bottom of page",
    )


def _tiny_terminal_fragment_issue(metrics: _PageMetrics) -> PaginationIssue | None:
    content_height_in = (
        max(0.0, metrics.lowest_occupied_bottom - metrics.content_top) / PX_PER_IN
    )
    if metrics.page_number <= 1 or content_height_in >= TINY_TERMINAL_FRAGMENT_IN:
        return None
    return PaginationIssue(
        kind="tiny-terminal-fragment",
        page_number=metrics.page_number,
        score=70 + int((TINY_TERMINAL_FRAGMENT_IN - content_height_in) * 50),
        message=f"last content page has only {content_height_in:.2f}in of content",
    )


def _insert_break_before_heading(source_html: str, element_id: str) -> tuple[str, int]:
    escaped_id = re.escape(element_id)
    pattern = re.compile(
        r"(?P<tag><h[2-4]\b[^>]*\bid=[\"']" + escaped_id + r"[\"'][^>]*>)",
        re.IGNORECASE,
    )
    marker = html.escape(element_id, quote=True)
    page_break = (
        '<div class="page-break pagination-auto-break" '
        f'data-pagination-fix-for="{marker}"></div>\n'
    )
    return pattern.subn(page_break + r"\g<tag>", source_html, count=1)


def _has_existing_fix(source_html: str, element_id: str) -> bool:
    marker = html.escape(element_id, quote=True)
    return f'data-pagination-fix-for="{marker}"' in source_html


def _should_skip_page(metrics: _PageMetrics) -> bool:
    page_type = getattr(metrics.page_box, "page_type", None)
    if getattr(page_type, "name", "") in SKIP_PAGE_NAMES:
        return True
    for box in metrics.boxes:
        element = getattr(box, "element", None)
        if element is not None and _classes(element) & SKIP_PAGE_CLASSES:
            return True
    return False


def _page_metrics(page: object, page_number: int) -> _PageMetrics | None:
    page_box = _page_box(page)
    if page_box is None:
        return None
    boxes = _content_boxes(page)
    content_top = _page_content_top(page)
    lowest = _lowest_occupied_bottom(boxes, content_top=content_top)
    return _PageMetrics(
        page_number=page_number,
        page_box=page_box,
        boxes=boxes,
        content_top=content_top,
        content_bottom=_page_content_bottom(page),
        content_left=_page_content_left(page),
        content_right=_page_content_right(page),
        lowest_occupied_bottom=lowest,
    )


def _content_boxes(page: object) -> list[Any]:
    page_box = _page_box(page)
    if page_box is None:
        return []
    descendants = getattr(page_box, "descendants", None)
    if not callable(descendants):
        return []
    return [
        box
        for box in descendants()
        if getattr(box, "element", None) is not None
        and _box_bottom(box) > _box_top(box) + 0.5
    ]


def _occupied_height_after(metrics: _PageMetrics, y_position: float) -> float:
    lowest = y_position
    for box in metrics.boxes:
        tag = str(getattr(box, "element_tag", "") or "").lower()
        if tag in {"html", "body"}:
            continue
        if _box_top(box) >= y_position - 0.5:
            lowest = max(lowest, _box_bottom(box))
    return max(0.0, lowest - y_position)


def _lowest_occupied_bottom(boxes: list[Any], *, content_top: float) -> float:
    lowest = content_top
    for box in boxes:
        tag = str(getattr(box, "element_tag", "") or "").lower()
        if tag in {"html", "body"}:
            continue
        lowest = max(lowest, _box_bottom(box))
    return lowest


def _page_box(page: object) -> Any | None:
    return getattr(page, "_page_box", None)


def _page_content_top(page: object) -> float:
    page_box = _page_box(page)
    if page_box is None:
        return 0.0
    return float(getattr(page_box, "margin_top", 0.0))


def _page_content_bottom(page: object) -> float:
    page_box = _page_box(page)
    if page_box is None:
        return 0.0
    return float(getattr(page_box, "margin_top", 0.0)) + float(
        getattr(page_box, "height", 0.0)
    )


def _page_content_left(page: object) -> float:
    page_box = _page_box(page)
    if page_box is None:
        return 0.0
    return float(getattr(page_box, "margin_left", 0.0))


def _page_content_right(page: object) -> float:
    page_box = _page_box(page)
    if page_box is None:
        return 0.0
    return float(getattr(page_box, "margin_left", 0.0)) + float(
        getattr(page_box, "width", 0.0)
    )


def _box_top(box: object) -> float:
    return float(getattr(box, "position_y", 0.0))


def _box_left(box: object) -> float:
    return float(getattr(box, "position_x", 0.0))


def _box_bottom(box: object) -> float:
    margin_height = getattr(box, "margin_height", None)
    height = margin_height() if callable(margin_height) else getattr(box, "height", 0.0)
    return _box_top(box) + float(height or 0.0)


def _box_right(box: object) -> float:
    margin_width = getattr(box, "margin_width", None)
    width = margin_width() if callable(margin_width) else getattr(box, "width", 0.0)
    return _box_left(box) + float(width or 0.0)


def _classes(element: Any) -> set[str]:
    raw = element.get("class") or ""
    return set(str(raw).split())


def _element_id(element: Any) -> str | None:
    raw = element.get("id")
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _element_text(element: Any) -> str:
    itertext = getattr(element, "itertext", None)
    if callable(itertext):
        return " ".join(str(part).strip() for part in itertext() if str(part).strip())
    return ""
