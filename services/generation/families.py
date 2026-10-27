"""Route all six document families through owning validators and the bounded provider."""

import json
from datetime import date
from uuid import uuid4

from app.core.models import School, curricula
from sqlalchemy import select

from services.curriculum.models import mappings
from services.generation.documents import canonical_body


async def generate_family(db, request, bundle, provider, model, tenant_id, generation_id):
    kind = request.document_type.value
    opts = request.options
    if not bundle.passages:
        raise ValueError("no_permitted_evidence")
    if kind in {"lesson_notes", "scheme_of_work", "lesson_plan", "teacher_guide"}:
        from services.templates.teaching.schemas import (
            CurriculumTarget,
            EvidenceBundle,
            EvidenceItem,
            TeachingSpec,
            VisualAssetEvidence,
        )
        from services.templates.teaching.service import TeachingStudio

        curriculum = (
            db.execute(
                select(curricula).where(
                    curricula.c.id == request.curriculum_id, curricula.c.tenant_id == tenant_id
                )
            )
            .mappings()
            .one()
        )
        target_rows = (
            db.execute(
                select(mappings.c.outcome_id, mappings.c.topic_id, mappings.c.required).where(
                    mappings.c.tenant_id == tenant_id,
                    mappings.c.topic_id.in_(request.topic_ids),
                    mappings.c.review_status == "approved",
                )
            )
            .mappings()
            .all()
        )
        target_map = {r["outcome_id"]: r for r in target_rows}
        spec_data = {k: v for k, v in opts.items() if k in TeachingSpec.model_fields}
        spec_data.update(
            type=kind,
            curriculum_id=request.curriculum_id,
            curriculum_version=curriculum["version"],
            level_id=request.level_id,
            subject_id=request.subject_id,
            topic_ids=request.topic_ids,
            outcome_ids=[o.id for o in bundle.outcomes],
        )
        if kind == "lesson_plan":
            spec_data.setdefault("lesson_date", date.today().isoformat())
        spec = TeachingSpec.model_validate(spec_data)
        evidence_bundle = EvidenceBundle(
            curriculum_id=request.curriculum_id,
            curriculum_version=curriculum["version"],
            outcomes=[
                CurriculumTarget(
                    **o.model_dump(),
                    curriculum_id=request.curriculum_id,
                    level_id=request.level_id,
                    subject_id=request.subject_id,
                    topic_id=target_map[o.id]["topic_id"],
                    mandatory=bool(target_map[o.id]["required"]),
                )
                for o in bundle.outcomes
            ],
            evidence=[
                EvidenceItem(
                    id=p.id,
                    source_title=p.source_title or "Reference",
                    source_uri=p.source_uri,
                    license=p.license,
                    excerpt=p.quote,
                    outcome_ids=[p.outcome_id],
                )
                for p in bundle.passages
            ],
            visuals=[
                VisualAssetEvidence(
                    asset_id=v.id,
                    outcome_id=v.outcome_id,
                    kind=v.kind,
                    caption=v.caption,
                    page=v.page,
                    source_uri=v.source_uri,
                    license=v.license,
                    permission_verified=True,
                )
                for v in bundle.visuals
                if v.source_uri and v.license
            ],
        )
        result = await TeachingStudio(provider, model).generate(
            spec=spec,
            evidence=evidence_bundle,
            tenant_id=tenant_id,
            generation_job_id=generation_id,
        )
        if not result.validation.valid:
            raise ValueError("teaching_quality_validation_failed")
        doc = result.document
        body = canonical_body(doc["body"], doc["evidence_ids"], seed=generation_id)
        # Render schedule/timing as editable tables as well as retaining typed metadata.
        if body.get("scheme_weeks"):
            rows = [["Week", "Topic", "Periods", "Activities", "Assessment", "Remarks"]]
            rows += [
                [
                    str(w["week"]),
                    ", ".join(w["subtopics"]),
                    str(w["periods"]),
                    "; ".join(w["activities"]),
                    w["assessment"],
                    w["remarks"],
                ]
                for w in body["scheme_weeks"]
            ]
            body["sections"].append(
                {
                    "title": "Weekly schedule",
                    "blocks": [{"id": str(uuid4()), "type": "table", "rows": rows}],
                }
            )
        if body.get("lesson_stages"):
            rows = [["Stage", "Minutes", "Teacher activities", "Learner activities", "Assessment"]]
            rows += [
                [
                    s["key"],
                    str(s["minutes"]),
                    "; ".join(s["teacher_actions"]),
                    "; ".join(s["learner_actions"]),
                    s["assessment"],
                ]
                for s in body["lesson_stages"]
            ]
            body["sections"].append(
                {
                    "title": "Lesson timing",
                    "blocks": [{"id": str(uuid4()), "type": "table", "rows": rows}],
                }
            )
        return doc["title"], body
    from services.assessment.ai_drafts import draft_candidates
    from services.assessment.generation import assemble_sections
    from services.assessment.schemas import AssessmentSpec
    from services.assessment.validation import fingerprint, validate_paper

    school = db.get(School, tenant_id)
    count, marks = int(opts.get("question_count", 10)), int(opts.get("total_marks", 20))
    spec = AssessmentSpec.model_validate(
        {
            "type": kind,
            "title": opts.get("title", f"{kind.title()} — curriculum assessment"),
            "curriculum_id": request.curriculum_id,
            "level_id": request.level_id,
            "subject_id": request.subject_id,
            "topic_ids": request.topic_ids,
            "outcome_ids": [o.id for o in bundle.outcomes],
            "school_name": school.name,
            "duration_minutes": opts.get("duration_minutes", 40),
            "total_marks": marks,
            "question_count": count,
            "instructions": opts.get("instructions", ["Answer all questions."]),
            "sections": opts.get(
                "sections",
                [
                    {
                        "title": "Section A",
                        "question_count": count,
                        "total_marks": marks,
                        "question_types": [
                            "multiple_choice",
                            "short_answer",
                            "numerical",
                            "structured",
                        ],
                    }
                ],
            ),
        }
    )
    questions = await draft_candidates(
        provider,
        spec,
        [
            dict(text=p.quote, source_uri=p.source_uri, license=p.license, evidence_id=str(p.id))
            for p in bundle.passages
        ],
        model=model,
    )
    allowed = {str(p.id): p for p in bundle.passages}
    pool = []
    for q in questions:
        if (
            not q.source_refs
            or not q.outcome_ids
            or not set(q.outcome_ids) <= {o.id for o in bundle.outcomes}
        ):
            raise ValueError("assessment_missing_evidence")
        for ref in q.source_refs:
            source = allowed.get(str(ref.evidence_id))
            if not source or ref.source_uri != source.source_uri or ref.license != source.license:
                raise ValueError("assessment_invalid_citation")
        if q.visual_asset_ids:
            raise ValueError("assessment_visual_requires_verified_resolution")
        c = q.model_dump(mode="json")
        pool.append(
            {
                "id": str(uuid4()),
                "marks": q.marks,
                "estimated_minutes": q.estimated_minutes,
                "type": q.type.value,
                "difficulty": q.difficulty.value,
                "curriculum_id": str(q.curriculum_id),
                "level_id": str(q.level_id),
                "subject_id": str(q.subject_id),
                "topic_ids": c["topic_ids"],
                "content": c,
                "fingerprint": fingerprint(q),
            }
        )
    sections = assemble_sections(spec, pool, explicit=True)
    report = validate_paper(spec, sections)
    if not report.valid:
        raise ValueError("assessment_quality_validation_failed")
    output = [
        {
            "title": "Instructions",
            "blocks": [
                {
                    "type": "paragraph",
                    "text": f"{school.name} | Duration: {spec.duration_minutes} minutes | Total marks: {marks}\n"
                    + "\n".join(spec.instructions),
                }
            ],
        }
    ]
    for section in sections:
        blocks = []
        for q in section["questions"]:
            c = q["content"]
            refs = [str(r["evidence_id"]) for r in c["source_refs"]]
            blocks.append(
                {
                    "type": "question",
                    "text": f"{q['number']}. {c['stem']} ({q['marks']} marks)\n"
                    + "\n".join(f"{o['id']}. {o['text']}" for o in c["options"]),
                    "citations": refs,
                }
            )
            if c["latex"]:
                blocks.append({"type": "equation", "latex": c["latex"], "citations": refs})
            blocks.append(
                {
                    "type": "marking_guide",
                    "audience": "teacher",
                    "text": f"Question {q['number']} — {q['marks']} marks: "
                    + json.dumps(c["answer"], ensure_ascii=False),
                    "citations": refs,
                }
            )
        output.append({"title": section["title"], "blocks": blocks})
    body = canonical_body(
        {
            "sections": output,
            "assessment": {"spec": spec.model_dump(mode="json"), "sections": sections},
            "quality": report.model_dump(mode="json"),
        },
        allowed.keys(),
        seed=generation_id,
    )
    return spec.title, body
