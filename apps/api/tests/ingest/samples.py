"""Builders for real sample files, generated in code so no binary fixtures are committed."""

import io

import pymupdf
from docx import Document as DocxDocument
from openpyxl import Workbook
from pptx import Presentation
from pptx.util import Inches


def pdf_bytes(pages: list[str], *, password: str | None = None) -> bytes:
    """One page per string; an empty string makes an image-only/blank page."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=11)
    options: dict[str, object] = {}
    if password:
        options = {
            "encryption": pymupdf.PDF_ENCRYPT_AES_256,
            "owner_pw": password,
            "user_pw": password,
        }
    data: bytes = doc.tobytes(**options)
    doc.close()
    return data


def docx_bytes(structure: list[tuple[str, str]]) -> bytes:
    """(style, text) pairs; style is 'Heading 1', 'Heading 2' or 'Normal'."""
    document = DocxDocument()
    for style, text in structure:
        if style.startswith("Heading"):
            document.add_heading(text, level=int(style.split()[-1]))
        else:
            document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def pptx_bytes(slides: list[tuple[str, str, str]]) -> bytes:
    """(title, body, speaker_notes) per slide."""
    deck = Presentation()
    for title, body, notes in slides:
        slide = deck.slides.add_slide(deck.slide_layouts[5])
        slide.shapes.title.text = title
        box = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(3))
        box.text_frame.text = body
        if notes:
            slide.notes_slide.notes_text_frame.text = notes
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


def xlsx_bytes(sheets: dict[str, list[list[object]]]) -> bytes:
    """Sheet name -> rows (first row is the header). Strings starting with '=' are formulas."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
