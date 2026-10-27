"""Projection boundary: teacher answer data never appears in student output."""

from __future__ import annotations

from typing import Any

from services.assessment.schemas import AssessmentSpec


def student_document(spec: AssessmentSpec, sections: list[dict]) -> dict[str, Any]:
    def learner_item(q: dict) -> dict:
        c = q["content"]
        # Deliberate allowlist: never serialize complete question content or answer fields.
        return {
            "number": q["number"],
            "question_revision_id": q["id"],
            "type": c["type"],
            "stem": c["stem"],
            "marks": c["marks"],
            "options": c["options"],
            "matching_left": list(c["matching_pairs"].keys()),
            "matching_right": sorted(c["matching_pairs"].values(), reverse=True),
            "data_table": c["data_table"],
            "latex": c["latex"],
            "visual_asset_ids": c["visual_asset_ids"],
            "response_lines": max(1, min(20, c["marks"])),
        }

    return {
        "schema_version": "1.0",
        "document_type": spec.type,
        "audience": "student",
        "title": spec.title,
        "school_name": spec.school_name,
        "logo_asset_id": spec.school_logo_asset_id,
        "subject_id": spec.subject_id,
        "level_id": spec.level_id,
        "term": spec.term,
        "duration_minutes": spec.duration_minutes,
        "total_marks": spec.total_marks,
        "instructions": spec.instructions,
        "page_size": "A4",
        "sections": [
            {
                "title": s["title"],
                "total_marks": sum(q["marks"] for q in s["questions"]),
                "questions": [learner_item(q) for q in s["questions"]],
            }
            for s in sections
        ],
    }


def teacher_guide(spec: AssessmentSpec, sections: list[dict]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "document_type": "marking_guide",
        "audience": "teacher",
        "title": f"Marking guide — {spec.title}",
        "school_name": spec.school_name,
        "total_marks": spec.total_marks,
        "sections": [
            {
                "title": s["title"],
                "questions": [
                    {
                        "number": q["number"],
                        "marks": q["marks"],
                        "answer": q["content"]["answer"],
                        "matching_pairs": q["content"]["matching_pairs"],
                        "source_refs": q["content"]["source_refs"],
                    }
                    for q in s["questions"]
                ],
            }
            for s in sections
        ],
    }
