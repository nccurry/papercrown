"""Integration-ish checks for WeasyPrint filler measurement."""

from __future__ import annotations

import pytest
from weasyprint import HTML

from papercrown.media.fillers import plan_fillers
from papercrown.project.manifest import FillerAsset, FillerCatalog, FillerSlot

pytestmark = pytest.mark.usefixtures("require_weasyprint")


def _catalog(tmp_path) -> FillerCatalog:
    return FillerCatalog(
        enabled=True,
        slots={
            "chapter-end": FillerSlot(
                name="chapter-end",
                min_space_in=0.65,
                max_space_in=3.5,
                shapes=["tailpiece", "bottom-band"],
            ),
            "section-end": FillerSlot(
                name="section-end",
                min_space_in=0.65,
                max_space_in=2.25,
                shapes=["tailpiece"],
            ),
        },
        assets=[
            FillerAsset(
                id="tail",
                art_path=tmp_path / "tail.png",
                shape="tailpiece",
                height_in=0.65,
            ),
            FillerAsset(
                id="band",
                art_path=tmp_path / "band.png",
                shape="bottom-band",
                height_in=2.2,
            ),
        ],
    )


def _html(paragraph_count: int) -> str:
    paragraphs = "\n".join("<p>Body text.</p>" for _ in range(paragraph_count))
    return f"""
    <!doctype html>
    <style>
      @page {{ size: Letter; margin: 1in; }}
      body {{ font-size: 11pt; line-height: 1.4; }}
      p {{ margin: 0 0 12pt 0; }}
      .filler-slot {{
        display: block;
        height: 0;
        overflow: hidden;
        visibility: hidden;
      }}
    </style>
    <h1>Short</h1>
    {paragraphs}
    <div id="slot-short" class="filler-slot" data-slot="chapter-end"
      data-chapter="short" data-preferred-filler="tail"></div>
    """


def test_short_chapter_gets_filler(tmp_path):
    doc = HTML(string=_html(2)).render()

    placements = plan_fillers(doc, _catalog(tmp_path), recipe_title="Book")

    assert [placement.asset.id for placement in placements] == ["band"]


def test_dense_chapter_gets_no_filler(tmp_path):
    doc = HTML(string=_html(20)).render()

    placements = plan_fillers(doc, _catalog(tmp_path), recipe_title="Book")

    assert placements == []


def test_slot_followed_by_same_page_content_gets_no_filler(tmp_path):
    doc = HTML(
        string="""
        <!doctype html>
        <style>
          @page { size: Letter; margin: 1in; }
          body { font-size: 11pt; line-height: 1.4; }
          .filler-slot {
            display: block;
            height: 0;
            overflow: hidden;
            visibility: hidden;
          }
        </style>
        <p>Opening text.</p>
        <div id="slot-before-next" class="filler-slot" data-slot="section-end"
          data-chapter="short" data-preferred-filler="tail"></div>
        <h2>Next Section</h2>
        <p>More text on the same page.</p>
        """
    ).render()

    placements = plan_fillers(doc, _catalog(tmp_path), recipe_title="Book")

    assert placements == []


def test_only_one_filler_is_used_per_page_preferring_chapter_end(tmp_path):
    doc = HTML(
        string="""
        <!doctype html>
        <style>
          @page { size: Letter; margin: 1in; }
          body { font-size: 11pt; line-height: 1.4; }
          .filler-slot {
            display: block;
            height: 0;
            overflow: hidden;
            visibility: hidden;
          }
        </style>
        <p>Short final section.</p>
        <div id="slot-section" class="filler-slot" data-slot="section-end"
          data-chapter="short" data-preferred-filler="tail"></div>
        <div id="slot-chapter" class="filler-slot" data-slot="chapter-end"
          data-chapter="short" data-preferred-filler="tail"></div>
        """
    ).render()

    placements = plan_fillers(doc, _catalog(tmp_path), recipe_title="Book")

    assert [placement.slot_id for placement in placements] == ["slot-chapter"]
