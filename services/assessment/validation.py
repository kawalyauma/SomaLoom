"""Deterministic quality gates; errors block publication, warnings require review."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

from services.assessment.schemas import (
    AssessmentSpec,
    QuestionDraft,
    QuestionType,
    ValidationReport,
)


def fingerprint(question: QuestionDraft) -> str:
    stem = re.sub(r"\s+", " ", question.stem.casefold()).strip()
    options = sorted(re.sub(r"\s+", " ", o.text.casefold()).strip() for o in question.options)
    payload = {
        "stem": stem,
        "type": question.type,
        "subject": str(question.subject_id),
        "options": options,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def calculate(expression: str) -> Decimal:
    """Evaluate numeric expressions without eval/functions/names or arbitrary code."""
    if len(expression) > 200:
        raise ValueError("Calculation is too long")

    def visit(node):
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(str(node.value))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            n = visit(node.operand)
            return n if isinstance(node.op, ast.UAdd) else -n
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
        ):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b
            if abs(b) > 12 or b != b.to_integral_value() or abs(a) > 100000:
                raise ValueError("Exponent out of range")
            return a ** int(b)
        raise ValueError("Unsupported calculation")

    try:
        result = visit(ast.parse(expression, mode="eval"))
        if not result.is_finite() or abs(result) > Decimal("1e15"):
            raise ValueError("Calculation out of range")
        return result
    except (SyntaxError, InvalidOperation, ZeroDivisionError, OverflowError) as exc:
        raise ValueError("Invalid numerical calculation") from exc


def validate_question_math(question: QuestionDraft) -> list[str]:
    errors = []
    if question.type == QuestionType.numerical and question.answer.calculation:
        try:
            result = calculate(question.answer.calculation)
            expected = Decimal(str(question.answer.numeric_value))
            if abs(result - expected) > Decimal(str(question.answer.tolerance)):
                errors.append("Numerical answer disagrees with the recorded calculation")
        except ValueError:
            errors.append("Numerical calculation is invalid or unsafe")
    return errors


def validate_paper(spec: AssessmentSpec, sections: list[dict]) -> ValidationReport:
    errors: list[str] = []
    warnings: list[str] = []
    all_questions = [q for section in sections for q in section["questions"]]
    actual_marks = sum(q["marks"] for q in all_questions)
    estimated = sum(q["estimated_minutes"] for q in all_questions)
    if len(sections) != len(spec.sections):
        errors.append("Section count does not match the blueprint")
    if actual_marks != spec.total_marks:
        errors.append(f"Question marks add to {actual_marks}, not {spec.total_marks}")
    if len(all_questions) != spec.question_count:
        errors.append("Question count does not match the blueprint")
    seen = set()
    difficulty = {k.value: 0 for k in spec.difficulty_mix}
    topics = {str(x): 0 for x in spec.topic_ids}
    for si, section in enumerate(sections):
        if si >= len(spec.sections):
            break
        planned = spec.sections[si]
        if section["title"] != planned.title:
            errors.append(f"Section {si + 1} has an unexpected title")
        if len(section["questions"]) != planned.question_count:
            errors.append(f"Section {si + 1} question count is wrong")
        if sum(q["marks"] for q in section["questions"]) != planned.total_marks:
            errors.append(f"Section {si + 1} marks are wrong")
        for q in section["questions"]:
            if q["type"] not in planned.question_types:
                errors.append(f"Section {si + 1} contains a disallowed question type")
            if q["id"] in seen:
                errors.append("The same question revision appears twice")
            seen.add(q["id"])
            if (
                q["curriculum_id"] != str(spec.curriculum_id)
                or q["level_id"] != str(spec.level_id)
                or q["subject_id"] != str(spec.subject_id)
            ):
                errors.append(
                    "A question does not match the requested curriculum, class or subject"
                )
            if not set(q["topic_ids"]) & {str(t) for t in spec.topic_ids}:
                errors.append("A question does not cover a selected topic")
            difficulty[q["difficulty"]] = difficulty.get(q["difficulty"], 0) + q["marks"]
            for topic in q["topic_ids"]:
                if topic in topics:
                    topics[topic] += q["marks"] / max(1, len(q["topic_ids"]))
    for name, pct in spec.difficulty_mix.items():
        if actual_marks and abs(100 * difficulty.get(name.value, 0) / actual_marks - pct) > 20:
            warnings.append(f"Difficulty balance differs from the requested {name.value} target")
    if spec.topic_weights and actual_marks:
        for topic, pct in spec.topic_weights.items():
            if abs(100 * topics.get(str(topic), 0) / actual_marks - pct) > 20:
                warnings.append(f"Topic {topic} differs from the planned coverage")
    if estimated > spec.duration_minutes * 1.15:
        errors.append("Estimated answering time exceeds the examination duration")
    elif estimated < spec.duration_minutes * 0.4:
        warnings.append("Examination duration is much longer than estimated answering time")
    if len({q["fingerprint"] for q in all_questions}) != len(all_questions):
        errors.append("Near-identical question wording detected")
    for q in all_questions:
        errors.extend(validate_question_math(QuestionDraft.model_validate(q["content"])))
        if q["type"] == QuestionType.essay and not q["content"]["answer"]["rubric"]:
            warnings.append("Essay lacks a detailed marking rubric")
    return ValidationReport(
        valid=not errors,
        errors=sorted(set(errors)),
        warnings=sorted(set(warnings)),
        actual_marks=actual_marks,
        estimated_minutes=round(estimated, 2),
        difficulty_marks=difficulty,
        topic_marks={k: round(v) for k, v in topics.items()},
    )
