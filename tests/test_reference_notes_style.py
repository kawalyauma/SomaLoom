"""Concise school reference notes from SST/Science subject metadata.

All fixture content is original synthetic text, not publisher content.
"""
from __future__ import annotations

import json

from services.templates.teaching.note_style import (
    REFERENCE_NOTES_STYLE, note_style_spec, subject_family,
)
from services.templates.teaching.schemas import (
    BlockKind, TeachingBlock, TeachingType,
)
from services.templates.teaching.templates import build_prompt
from services.validators.teaching import validate_teaching_document
from test_teaching_studio import EID, OID, fixture


def test_identifies_sst_and_science_not_math():
    assert subject_family("SST") == "sst"
    assert subject_family("Primary Seven Social Studies") == "sst"
    assert subject_family("Primary Science") == "science"
    assert subject_family("P6 SCIE") == "science"
    assert subject_family("Mathematics") is None
    assert note_style_spec("Mathematics", "standard") is None


def test_sst_prompt_matches_reference_book_style_without_copying_source():
    spec, bundle, _ = fixture(TeachingType.lesson_notes)
    spec.planning_scope = {"source_subject_name": "Social Studies", "term": "Term 3"}
    spec.depth = "comprehensive"
    system, prompt = build_prompt(spec, bundle)
    payload = json.loads(prompt)
    style = payload["reference_notes_style"]
    assert style["style"] == REFERENCE_NOTES_STYLE
    assert style["subject"] == "sst"
    assert "One short fact per newline" in style["block_rules"]["list"]
    assert "maps" in str(style["subject_specific"]).lower()
    assert "NOT a lesson-plan narrative" in system
    assert "copyright" in system.lower()
    assert payload["curriculum_evidence"]["evidence"][0]["id"] == str(EID)


def test_science_prompt_includes_classifications_and_diagrams():
    spec, bundle, _ = fixture(TeachingType.lesson_notes)
    spec.planning_scope = {"source_subject_name": "Primary Science"}
    _, prompt = build_prompt(spec, bundle)
    style = json.loads(prompt)["reference_notes_style"]
    assert style["subject"] == "science"
    assert "classifications" in str(style["subject_specific"]).lower()
    assert "diagrams" in str(style["subject_specific"]).lower()


def test_other_document_types_do_not_change():
    spec, bundle, _ = fixture(TeachingType.lesson_plan)
    spec.planning_scope = {"source_subject_name": "Social Studies"}
    system, prompt = build_prompt(spec, bundle)
    assert json.loads(prompt)["reference_notes_style"] is None
    assert "NOT a lesson-plan narrative" not in system


def test_narrative_only_sst_notes_are_not_accepted():
    spec, bundle, body = fixture(TeachingType.lesson_notes)
    spec.planning_scope = {"source_subject_name": "SST"}
    quality = validate_teaching_document(spec, bundle, body)
    assert not quality.valid
    assert any(f.code == "reference_notes_insufficient_facts" for f in quality.findings)


def test_multi_line_fact_notes_pass_and_warn_when_sources_limited():
    spec, bundle, body = fixture(TeachingType.lesson_notes)
    spec.planning_scope = {"source_subject_name": "Science"}
    spec.depth = "comprehensive"
    body.sections[4].blocks = [
        TeachingBlock(
            kind=BlockKind.heading, text="Filtering water",
            citation_ids=[EID], outcome_ids=[OID],
        ),
        TeachingBlock(
            kind=BlockKind.list,
            text="A filter traps some suspended particles.\n"
            "Clean-looking water may still contain germs.\n"
            "Use a safe filter material.\n"
            "Pour the sample through the filter.\n"
            "Observe the material left behind.\n"
            "Compare the collected water with the original sample.\n"
            "Filtration does not reliably remove all pathogens.\n"
            "Extra treatment may be needed to make water safe to drink.",
            citation_ids=[EID], outcome_ids=[OID],
        ),
    ]
    quality = validate_teaching_document(spec, bundle, body)
    assert quality.valid, quality.findings
    assert not any(f.code == "reference_notes_insufficient_facts" for f in quality.findings)
    assert any(f.code == "limited_source_diversity" for f in quality.findings)


def test_printed_list_lines_remain_separate():
    from io import BytesIO
    from docx import Document
    from pypdf import PdfReader

    from services.export.publishing import export_docx, export_pdf
    from test_agent8_publishing import example

    doc = example()
    doc["body"]["sections"][0]["blocks"].append({
        "id": "note-list",
        "type": "list",
        "text": "A short factual point.\nAnother factual point.\nA third factual point.",
    })
    source = export_docx(doc, {"school_name": "Fixture School"})
    imported = Document(BytesIO(source))
    facts = [p for p in imported.paragraphs if p.style.name == "List Bullet"]
    assert len(facts) == 3
    assert facts[1].text == "Another factual point."
    pdf = PdfReader(BytesIO(export_pdf(doc, {"school_name": "Fixture School"})))
    text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "A short factual point." in text
    assert "Another factual point." in text
