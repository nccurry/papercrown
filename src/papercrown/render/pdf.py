"""PDF metadata and cleanup helpers for the render pipeline."""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Any

from pypdf import PdfReader, PdfWriter


def write_pdf_metadata(out_pdf: Path, *, title: str, ctx: Any) -> None:
    """Write standard PDF document metadata after cleanup passes."""
    metadata = {
        "/Title": title,
        "/Creator": "papercrown",
    }
    optional = {
        "/Author": ctx.book_author,
        "/Subject": ctx.book_description,
        "/Keywords": ctx.book_keywords,
        "/Publisher": ctx.book_publisher,
        "/Version": ctx.book_version,
        "/License": ctx.book_license,
        "/Date": ctx.book_date,
    }
    metadata.update({key: value for key, value in optional.items() if value})
    reader = PdfReader(str(out_pdf))
    writer = PdfWriter()
    writer.clone_document_from_reader(reader)
    writer.add_metadata(metadata)
    with out_pdf.open("wb") as handle:
        writer.write(handle)


def save_fitz_pdf(document: Any, out_pdf: Path) -> None:
    """Save a PyMuPDF document with the same cleanup settings used elsewhere."""
    tmp_path = out_pdf.with_name(f"{out_pdf.stem}.fitz-saving{out_pdf.suffix}")
    if tmp_path.exists():
        tmp_path.unlink()
    document.save(
        tmp_path,
        garbage=4,
        deflate=True,
        deflate_images=False,
        deflate_fonts=True,
        clean=True,
        use_objstms=1,
    )
    replace_pdf(tmp_path, out_pdf)


def clean_pdf(path: Path) -> None:
    """Rewrite the PDF to drop unused resources after page merges."""
    fitz: Any = importlib.import_module("fitz")
    tmp_path = path.with_name(f"{path.stem}.cleaning{path.suffix}")
    if tmp_path.exists():
        tmp_path.unlink()
    doc = fitz.open(path)
    try:
        doc.save(
            tmp_path,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
            use_objstms=1,
        )
    finally:
        doc.close()
    replace_pdf(tmp_path, path)


def replace_pdf(source: Path, target: Path) -> None:
    """Replace a PDF, retrying briefly for Windows handle release lag."""
    for attempt in range(8):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.25)
