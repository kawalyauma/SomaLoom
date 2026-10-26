"""Deterministic question-bank assembly; content drafting is delegated to Agent 5."""
from __future__ import annotations

import random
from collections import defaultdict
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.assessment.models import question_versions
from services.assessment.schemas import AssessmentSpec


def snapshot(row) -> dict:
    c = row["payload"]
    return {
        "id": str(row["id"]), "question_id": str(row["question_id"]),
        "version": row["version"], "fingerprint": row["fingerprint"],
        "marks": c["marks"], "estimated_minutes": c["estimated_minutes"],
        "type": c["type"], "difficulty": c["difficulty"],
        "curriculum_id": c["curriculum_id"], "level_id": c["level_id"],
        "subject_id": c["subject_id"], "topic_ids": c["topic_ids"], "content": c,
    }


def select_revisions(db: Session, tenant_id: UUID, spec: AssessmentSpec,
                     revision_ids: list[UUID], seed: int) -> list[dict]:
    if revision_ids:
        if len(revision_ids) != spec.question_count or len(set(revision_ids)) != len(revision_ids):
            raise HTTPException(422, "Provide exactly one distinct approved revision per question")
        records = db.execute(select(question_versions).where(
            question_versions.c.tenant_id == tenant_id,
            question_versions.c.id.in_(revision_ids),
            question_versions.c.status == "approved")).mappings().all()
        found = {r["id"]: r for r in records}
        if len(found) != len(revision_ids):
            raise HTTPException(422, "One or more revisions are unavailable or not approved")
        return [snapshot(found[x]) for x in revision_ids]

    records = db.execute(select(question_versions).where(
        question_versions.c.tenant_id == tenant_id,
        question_versions.c.status == "approved")).mappings().all()
    latest = {}
    for row in records:
        previous = latest.get(row["question_id"])
        if previous is None or row["version"] > previous["version"]:
            latest[row["question_id"]] = row
    candidates = [
        snapshot(r) for r in latest.values()
        if r["payload"]["curriculum_id"] == str(spec.curriculum_id)
        and r["payload"]["level_id"] == str(spec.level_id)
        and r["payload"]["subject_id"] == str(spec.subject_id)
        and set(r["payload"]["topic_ids"]) & {str(t) for t in spec.topic_ids}
    ]
    random.Random(seed).shuffle(candidates)
    return candidates


def assemble_sections(spec: AssessmentSpec, pool: list[dict],
                      explicit: bool) -> list[dict]:
    used: set[str] = set()
    result = []
    cursor = 0
    number = 1
    for plan in spec.sections:
        if explicit:
            selected = pool[cursor:cursor + plan.question_count]
            cursor += plan.question_count
            if sum(q["marks"] for q in selected) != plan.total_marks:
                raise HTTPException(422, f"Section {plan.title} has the wrong total marks")
        else:
            choices = [q for q in pool if q["id"] not in used
                       and q["type"] in plan.question_types
                       and q["marks"] <= plan.total_marks]
            # Bounded dynamic programming by count/marks; a selected question is never reused.
            states: dict[tuple[int, int], list[int]] = {(0, 0): []}
            for idx, q in enumerate(choices[:450]):
                for (count, marks), picked in list(states.items()):
                    key = (count + 1, marks + q["marks"])
                    if count < plan.question_count and key[1] <= plan.total_marks and key not in states:
                        states[key] = [*picked, idx]
                if (plan.question_count, plan.total_marks) in states:
                    break
            picked = states.get((plan.question_count, plan.total_marks))
            if picked is None:
                raise HTTPException(422, f"Not enough approved questions for section {plan.title} (count and marks)")
            selected = [choices[idx] for idx in picked]
        section_questions = []
        for q in selected:
            if q["id"] in used:
                raise HTTPException(422, "Question revisions must not repeat")
            used.add(q["id"])
            q = dict(q)
            q["number"] = number
            number += 1
            section_questions.append(q)
        result.append({"title": plan.title, "questions": section_questions})
    return result
