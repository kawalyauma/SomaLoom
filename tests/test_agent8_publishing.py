"""Local publisher tests: pytest -q tests/test_agent8_publishing.py"""

from io import BytesIO
from zipfile import ZipFile

import pytest

from services.export.publishing import export_docx, export_pdf
from services.rendering.document import DocumentValidationError, validate_document
from services.rendering.omml import latex_to_omml


def example():
    return {
        "id": "11111111-1111-4111-8111-111111111111",
        "title": "Primary 5 Mathematics",
        "review_state": "approved",
        "evidence_ids": ["ev-1"],
        "body": {
            "sections": [
                {
                    "title": "Fractions and matrices",
                    "blocks": [
                        {
                            "id": "b1",
                            "type": "paragraph",
                            "text": "A fraction represents part of a whole.",
                            "citations": ["ev-1"],
                        },
                        {"id": "b2", "type": "equation", "latex": r"\frac{1}{2}+x^2=\sqrt{9}"},
                        {
                            "id": "b3",
                            "type": "table",
                            "rows": [["Term", "Meaning"], ["1/2", "One half"]],
                        },
                        {
                            "id": "b4",
                            "type": "question",
                            "text": "What is one half of ten?",
                            "answer": "Five",
                        },
                        {"id": "b5", "type": "answer", "text": "Five", "audience": "teacher"},
                    ],
                }
            ]
        },
    }


@pytest.mark.parametrize(
    "latex,tag",
    [
        (r"\frac{1}{2}", "f"),
        (r"x^2", "sSup"),
        (r"\sqrt{16}", "rad"),
        (r"\begin{pmatrix}1&2\\3&4\end{pmatrix}", "m"),
        (r"\sin\theta", "oMath"),
    ],
)
def test_omml_contains_math_construct(latex, tag):
    import xml.etree.ElementTree as et

    xml = et.tostring(latex_to_omml(latex), encoding="unicode")
    assert "<m:" + tag in xml


def test_student_strips_answers():
    doc = validate_document(example())
    blocks = doc["body"]["sections"][0]["blocks"]
    assert all(b["type"] != "answer" for b in blocks)
    assert all("answer" not in b for b in blocks)


def test_teacher_preserves_answers():
    blocks = validate_document(example(), audience="teacher")["body"]["sections"][0]["blocks"]
    assert any(b["type"] == "answer" for b in blocks)


def test_invalid_visuals_fail_closed():
    original = example()
    original["body"]["sections"][0]["blocks"].append(
        {"id": "visual", "type": "map", "asset_ref": "untrusted-key", "caption": "Country map"}
    )
    with pytest.raises(DocumentValidationError):
        validate_document(original)


def test_unapproved_blocked():
    original = example()
    original["review_state"] = "draft"
    with pytest.raises(DocumentValidationError):
        export_docx(original)


def test_docx_uses_native_omml_and_no_answers():
    from docx import Document

    data = export_docx(example(), {"school_name": "Test School"})
    with ZipFile(BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode()
    assert "<m:oMath" in xml and "<m:f" in xml
    assert "Five" not in xml
    document = Document(BytesIO(data))
    assert document.sections[0].page_width is not None


def test_pdf_contains_valid_pages():
    from pypdf import PdfReader

    data = export_pdf(example(), {"school_name": "Test School"})
    pdf = PdfReader(BytesIO(data))
    assert len(pdf.pages) >= 1
    assert "Primary 5 Mathematics" in (pdf.pages[0].extract_text() or "")
