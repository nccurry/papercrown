"""Unit tests for pagination badness scoring and conservative fixups."""

from __future__ import annotations

from types import SimpleNamespace

from papercrown import pagination


class FakeElement(dict[str, str]):
    """Tiny element shim with the methods pagination uses."""

    def __init__(self, attrs: dict[str, str] | None = None, text: str = "") -> None:
        super().__init__(attrs or {})
        self._text = text

    def itertext(self):
        yield self._text


class FakeBox:
    """Tiny WeasyPrint box shim."""

    def __init__(
        self,
        tag: str,
        *,
        y: float,
        height: float,
        x: float = 0.0,
        width: float = 300.0,
        element: FakeElement | None = None,
    ) -> None:
        self.element_tag = tag
        self.element = element or FakeElement()
        self.position_y = y
        self.position_x = x
        self.height = height
        self.width = width


class FakePageBox:
    """Tiny page box shim."""

    def __init__(self, boxes: list[FakeBox]) -> None:
        self.margin_top = 0.0
        self.margin_left = 0.0
        self.height = 960.0
        self.width = 600.0
        self.page_type = SimpleNamespace(name="normal")
        self._boxes = boxes

    def descendants(self):
        return self._boxes


class FakePage:
    """Tiny page shim."""

    def __init__(self, boxes: list[FakeBox]) -> None:
        self._page_box = FakePageBox(boxes)


class FakeDocument:
    """Tiny document shim."""

    def __init__(self, pages: list[FakePage]) -> None:
        self.pages = pages


def test_analyze_document_detects_stranded_heading():
    heading = FakeBox(
        "h2",
        y=910.0,
        height=18.0,
        element=FakeElement({"id": "actions"}, "Actions"),
    )
    report = pagination.analyze_document(FakeDocument([FakePage([heading])]))

    assert report.total_badness > 0
    assert report.issues[0].kind == "stranded-heading"
    assert report.issues[0].element_id == "actions"


def test_inject_page_break_fixes_targets_heading_id_once():
    report = pagination.PaginationReport(
        page_count=1,
        issues=[
            pagination.PaginationIssue(
                kind="stranded-heading",
                page_number=1,
                score=100,
                message="heading near page bottom",
                element_id="actions",
                element_tag="h2",
            )
        ],
    )
    source = '<h2 id="actions">Actions</h2><p>Body</p>'

    fixed = pagination.inject_page_break_fixes(source, report)
    second = pagination.inject_page_break_fixes(fixed.html, report)

    assert fixed.applied_ids == ["actions"]
    assert 'data-pagination-fix-for="actions"' in fixed.html
    assert second.applied_ids == []


def test_analyze_document_scores_overflow():
    table = FakeBox("table", y=20.0, height=40.0, width=720.0)
    report = pagination.analyze_document(FakeDocument([FakePage([table])]))

    assert any(issue.kind == "overflow" for issue in report.issues)
