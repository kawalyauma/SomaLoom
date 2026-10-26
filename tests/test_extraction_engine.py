"""Focused native/scan/HTML/DOCX/visual/math fixtures. Run locally, no GitHub Actions."""
from __future__ import annotations

import base64
import io
from uuid import uuid4

import pytest

from services.extraction.engine import ExtractionError, Limits, extract_bytes
from services.extraction.models import BlockType, semantic_sections
from services.math.equations import analyze_equation, is_equation
from services.math.omml import omml_to_latex
from services.visuals.classify import classify_visual, map_metadata

TENANT_RESOURCE = uuid4()
VERSION = uuid4()


def run(content: bytes, mime: str, **kwargs):
    return extract_bytes(content, mime, resource_id=TENANT_RESOURCE,
                         version_id=VERSION, license="CC-BY-4.0", **kwargs)


def tiny_png():
    from PIL import Image, ImageDraw
    image = Image.new("RGB", (820, 640), "white")
    ImageDraw.Draw(image).rectangle((50, 50, 780, 550), outline="black", width=5)
    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def sample_html():
    data = base64.b64encode(tiny_png()).decode()
    return f"""<html><body><h1>Chapter 2: Energy</h1>
      <p>Energy can be transferred from one form to another.</p>
      <figure><img alt="Figure 2: Diagram of energy transfer"
      src="data:image/png;base64,{data}"></figure>
      <table><tr><th>Source</th><th>Energy</th></tr>
      <tr><td>Sun</td><td>Light</td></tr></table>
      <math><annotation encoding="application/x-tex">E = m c^2</annotation></math>
      <h2>Exercise 2</h2><p>Explain the figure.</p>
      </body></html>""".encode()


def test_full_mixed_passage_and_source_links():
    written = {}
    doc = run(sample_html(), "text/html", put_asset=lambda k, b: written.setdefault(k, b))
    assert len(doc.assets) == 1
    assert list(written) == [doc.assets[0].object_key]
    assert doc.assets[0].checksum_sha256
    assert doc.assets[0].caption == "Figure 2: Diagram of energy transfer"
    assert any(b.type == BlockType.heading for b in doc.blocks)
    assert any(b.type == BlockType.table and b.table[1] == ["Sun", "Light"] for b in doc.blocks)
    assert any(b.type == BlockType.equation and b.latex for b in doc.blocks)
    assert any(b.asset_id == doc.assets[0].id for b in doc.blocks)
    assert all(b.source_ref.version_id == VERSION and b.page == 1 for b in doc.blocks)
    assert semantic_sections(doc)
    assert doc.model_validate_json(doc.model_dump_json()).version_id == VERSION


def test_deterministic_reprocessing_no_duplicate_ids():
    first = run(sample_html(), "text/html")
    second = run(sample_html(), "text/html")
    assert [str(b.id) for b in first.blocks] == [str(b.id) for b in second.blocks]
    assert [str(a.id) for a in first.assets] == [str(a.id) for a in second.assets]


def test_native_pdf_structure_equations_figures():
    fitz = pytest.importorskip("fitz")
    pdf = fitz.open()
    p = pdf.new_page(width=600, height=800)
    p.insert_text((40, 60), "Chapter 3: Motion", fontsize=20)
    p.insert_text((40, 100), "Displacement is change in position.", fontsize=11)
    p.insert_text((40, 135), "v = d/t", fontsize=13)
    p.insert_image(fitz.Rect(60, 175, 320, 395), stream=tiny_png())
    p.insert_text((60, 415), "Figure 1: Diagram of displacement", fontsize=11)
    raw = pdf.tobytes()
    pdf.close()
    doc = run(raw, "application/pdf")
    assert doc.pages_processed == 1 and not doc.partial
    assert any(b.type == BlockType.heading for b in doc.blocks)
    assert any(b.type == BlockType.equation and b.latex for b in doc.blocks)
    assert len(doc.assets) >= 1
    assert all(b.source_ref.page == b.page for b in doc.blocks)


def test_scanned_pdf_calls_ocr_with_page_correspondence(monkeypatch):
    fitz = pytest.importorskip("fitz")
    from services.extraction import engine
    scanned = fitz.open()
    p = scanned.new_page()
    p.insert_image(fitz.Rect(50, 50, 450, 600), stream=tiny_png())
    raw = scanned.tobytes()
    scanned.close()
    monkeypatch.setattr(engine, "_ocr_image",
                        lambda raw, **kw: [("Transcribed scan", (20, 30, 80, 50), .93)])
    doc = run(raw, "application/pdf")
    assert any(b.text == "Transcribed scan" and b.source_ref.page == 1 for b in doc.blocks)


def test_docx_paragraph_table_and_office_math():
    docx = pytest.importorskip("docx")
    source = docx.Document()
    source.add_heading("Types of energy", level=1)
    source.add_paragraph("Kinetic energy depends on motion.")
    table = source.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Type"
    table.cell(0, 1).text = "Example"
    table.cell(1, 0).text = "Light"
    table.cell(1, 1).text = "Sun"
    mem = io.BytesIO()
    source.save(mem)
    result = run(mem.getvalue(),
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert any(b.type == BlockType.table and b.table[1] == ["Light", "Sun"]
               for b in result.blocks)
    assert any(b.type == BlockType.heading for b in result.blocks)
    assert "docx_page_numbers_unavailable_without_layout_engine" in result.processing_warnings


def test_native_equations_and_uncertainty():
    assert is_equation("a² + b² = c²")
    expr = analyze_equation("a² + b² = c²")
    assert expr.latex == "a^{2} + b^{2} = c^{2}"
    assert not expr.needs_review
    assert analyze_equation(r"\\danger{42}").needs_review
    ocr = analyze_equation("x = 12", is_ocr=True)
    assert ocr.needs_review and ocr.confidence < expr.confidence
    assert omml_to_latex(type("Fake", (), {"tag": "unknown", "__iter__": lambda s: iter(())})()) is None


def test_map_conservative_metadata():
    kind, confidence = classify_visual("Map 4: Map of Uganda")
    assert kind == BlockType.map
    metadata = map_metadata("Map 4: Map of Uganda", "Legend: Roads and rivers\nScale 1:50000")
    assert metadata["geographic_area"] == "Uganda"
    assert metadata["scale"] == "1:50000"
    assert metadata["boundaries_verified"] is False
    assert metadata["labels"] == []
    assert confidence < 1


def test_corrupt_files_and_limits():
    with pytest.raises(ExtractionError):
        run(b"not pdf", "application/pdf")
    with pytest.raises(ExtractionError):
        run(b"12345", "image/png", limits=Limits(max_bytes=4))
    with pytest.raises(ExtractionError):
        run(b"hello", "application/octet-stream")


def test_html_does_not_fetch_external_images():
    doc = run(b'<h1>Map study</h1><p><img src="https://example.org/map.png" alt="Map"></p>',
              "text/html")
    assert "external_html_image_not_fetched" in doc.processing_warnings
    assert not doc.assets
    assert any(b.needs_review and b.type == BlockType.figure for b in doc.blocks)
