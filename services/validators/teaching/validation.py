"""Deterministic quality gates, not a substitute for academic/teacher review."""

from __future__ import annotations

import ast
import operator
import re
from collections import Counter
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from services.templates.teaching.schemas import (
    BlockKind,
    EvidenceBundle,
    TeachingBody,
    TeachingSpec,
    TeachingType,
    TeachingValidation,
    ValidationFinding,
)
from services.templates.teaching.templates import REQUIRED_SECTIONS
from services.templates.teaching.note_style import note_style_spec


def validate_teaching_inputs(spec: TeachingSpec, bundle: EvidenceBundle) -> None:
    """Fail closed on absent/unverified mapping; never fabricate curricula."""
    if (
        spec.curriculum_id != bundle.curriculum_id
        or spec.curriculum_version != bundle.curriculum_version
    ):
        raise ValueError("unsupported curriculum ID/version: no exact curriculum evidence bundle")
    targets = {x.id: x for x in bundle.outcomes}
    if len(targets) != len(bundle.outcomes):
        raise ValueError("duplicate evidence outcome IDs")
    for outcome_id in spec.outcome_ids:
        outcome = targets.get(outcome_id)
        if (
            not outcome
            or (outcome.curriculum_id, outcome.level_id, outcome.subject_id)
            != (spec.curriculum_id, spec.level_id, spec.subject_id)
            or outcome.topic_id not in spec.topic_ids
        ):
            raise ValueError(
                f"outcome {outcome_id} not verified for requested curriculum/level/subject/topic"
            )
    sources = {x.id: x for x in bundle.evidence}
    if len(sources) != len(bundle.evidence):
        raise ValueError("duplicate evidence item IDs")
    if not set(spec.outcome_ids).intersection(
        outcome_id for source in bundle.evidence for outcome_id in source.outcome_ids
    ):
        raise ValueError("no evidence connects to any requested outcome")
    for src in bundle.evidence:
        if not set(src.outcome_ids).issubset(targets):
            raise ValueError("evidence contains unrecognized outcomes")


def _safe_numeric(expr: str) -> Decimal | None:
    """Check only simple numeric equations, never eval arbitrary generated text."""
    expr = expr.strip().replace(r"\times", "*").replace(r"\cdot", "*").replace(r"\div", "/")
    expr = expr.replace("{", "(").replace("}", ")")
    if not re.fullmatch(r"[\d+*/().\-\s]+", expr):
        return None
    ops = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
    }

    def visit(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(str(node.value))
        if isinstance(node, ast.BinOp) and type(node.op) in ops:
            return ops[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        raise ValueError("unsupported expression")

    try:
        return visit(ast.parse(expr, mode="eval").body)
    except (ValueError, SyntaxError, InvalidOperation, ZeroDivisionError, OverflowError):
        return None


def _teaching_days(spec: TeachingSpec, week: int) -> int:
    calendar = spec.calendar
    if calendar is None:
        return 0
    # Weeks are contiguous seven-day teaching windows starting at the supplied term start.
    week_start = calendar.starts_on + timedelta(days=(week - 1) * 7)
    return sum(
        1
        for i in range(7)
        if (day := week_start + timedelta(days=i)) <= calendar.ends_on
        and day.weekday() in calendar.teaching_weekdays
        and day not in calendar.excluded_dates
    )


def validate_teaching_document(
    spec: TeachingSpec,
    bundle: EvidenceBundle,
    body: TeachingBody,
) -> TeachingValidation:
    validate_teaching_inputs(spec, bundle)
    findings: list[ValidationFinding] = []

    def add(code: str, severity: str, message: str, block_id: UUID | None = None) -> None:
        findings.append(
            ValidationFinding(code=code, severity=severity, message=message, block_id=block_id)
        )

    sections_by_key = {section.key: section for section in body.sections}
    if len(sections_by_key) != len(body.sections):
        add("duplicate_section", "error", "Section keys must be unique")
    for key in REQUIRED_SECTIONS[spec.type]:
        section = sections_by_key.get(key)
        if not section or not section.blocks:
            add("missing_section", "error", f"Required nonempty section missing: {key}")
    evidence = {source.id: source for source in bundle.evidence}
    targets = set(spec.outcome_ids)
    used_coverage: set[UUID] = set()
    available_assets = {
        source.asset_id
        for source in bundle.evidence
        if source.asset_id and source.asset_permission_verified
    }
    used_visuals: set[str] = set()
    text_counts: Counter[str] = Counter()
    block_ids: set[UUID] = set()
    substantive = {
        BlockKind.paragraph,
        BlockKind.table,
        BlockKind.equation,
        BlockKind.visual,
        BlockKind.list,
        BlockKind.heading,
    }
    for section in body.sections:
        for block in section.blocks:
            if block.id in block_ids:
                add("duplicate_block_id", "error", "Editable block IDs must be unique", block.id)
            block_ids.add(block.id)
            norm = re.sub(r"\W+", " ", block.text.casefold()).strip()
            if norm and len(norm) > 50:
                text_counts[norm] += 1
            if block.kind == BlockKind.visual:
                if block.asset_id not in available_assets:
                    add(
                        "unlicensed_or_unknown_visual",
                        "error",
                        "Visual asset absent from licensed evidence",
                        block.id,
                    )
                else:
                    used_visuals.update(
                        source.asset_kind
                        for source in bundle.evidence
                        if source.asset_id == block.asset_id and source.asset_kind
                    )
            if block.kind == BlockKind.visual_needed:
                add(
                    "visual_needed",
                    "warning",
                    "Diagram/visual requires vetted creation or retrieval",
                    block.id,
                )
            if block.kind == BlockKind.equation and block.latex:
                if block.latex.count("{") != block.latex.count("}"):
                    add("math_syntax", "error", "Unbalanced LaTeX braces", block.id)
                if block.latex.count("=") == 1:
                    lhs, rhs = block.latex.split("=")
                    a, b = _safe_numeric(lhs), _safe_numeric(rhs)
                    if a is not None and b is not None and abs(a - b) > Decimal("0.000001"):
                        add(
                            "math_inconsistent",
                            "error",
                            "Simple arithmetic identity is false",
                            block.id,
                        )
            unknown = set(block.citation_ids) - evidence.keys()
            if unknown:
                add(
                    "unknown_citation",
                    "error",
                    f"Unknown evidence citations: {sorted(map(str, unknown))}",
                    block.id,
                )
            if not set(block.outcome_ids).issubset(targets):
                add("unknown_outcome", "error", "Block maps to unrequested outcome", block.id)
            if block.kind in substantive and not block.citation_ids:
                add(
                    "ungrounded_block",
                    "warning",
                    "Explanatory content has no evidence citation",
                    block.id,
                )
            if block.citation_ids and block.outcome_ids:
                supported = set().union(
                    *(set(evidence[x].outcome_ids) for x in block.citation_ids if x in evidence)
                )
                if not set(block.outcome_ids).issubset(supported):
                    add(
                        "unverified_outcome_link",
                        "error",
                        "Citation does not support mapped outcome",
                        block.id,
                    )
                used_coverage.update(set(block.outcome_ids) & supported & targets)
    if any(count > 1 for count in text_counts.values()):
        add("duplicate_content", "warning", "Repeated substantive text in multiple blocks")
    for visual in bundle.required_visual_kinds:
        if visual not in used_visuals:
            if not any(
                block.kind == BlockKind.visual_needed
                for section in body.sections
                for block in section.blocks
            ):
                add("required_visual_missing", "warning", f"Missing required visual: {visual}")
    if spec.type == TeachingType.scheme_of_work:
        if body.lesson_stages:
            add("unexpected_lesson_stages", "error", "A scheme must not contain lesson stages")
        periods = Counter()
        covered_weeks: set[int] = set()
        for row in body.scheme_weeks:
            periods[row.week] += row.periods
            covered_weeks.add(row.week)
            if row.week > (spec.weeks or 0):
                add("week_outside_term", "error", f"Week {row.week} exceeds requested weeks")
            if row.topic_id not in spec.topic_ids or not set(row.outcome_ids).issubset(targets):
                add("unknown_scheme_mapping", "error", f"Week {row.week} has unknown topic/outcome")
            if set(row.citation_ids) - evidence.keys():
                add("unknown_citation", "error", f"Week {row.week} has unknown citation")
            linked = set().union(
                *(set(evidence[x].outcome_ids) for x in row.citation_ids if x in evidence)
            )
            if not set(row.outcome_ids).issubset(linked):
                add(
                    "ungrounded_scheme_outcome",
                    "error",
                    f"Week {row.week} outcomes lack matching sources",
                )
            else:
                used_coverage.update(set(row.outcome_ids) & targets)
        for week, used in periods.items():
            if used > (spec.periods_per_week or 0):
                add(
                    "week_overallocated",
                    "error",
                    f"Week {week}: {used} periods exceed weekly capacity",
                )
            if _teaching_days(spec, week) == 0:
                add("nonteaching_week", "error", f"Week {week} has no available teaching day")
        for week in set(range(1, (spec.weeks or 0) + 1)) - covered_weeks:
            if _teaching_days(spec, week) > 0:
                add("unplanned_week", "warning", f"Week {week} has available time but no plan")
    elif body.scheme_weeks:
        add("unexpected_scheme_weeks", "error", "Non-scheme documents cannot contain scheme weeks")
    if spec.type == TeachingType.lesson_plan:
        if not body.lesson_stages:
            add("missing_lesson_stages", "error", "Timed lesson stages required")
        elapsed = sum(stage.minutes for stage in body.lesson_stages)
        if elapsed != spec.duration_minutes:
            add(
                "duration_mismatch",
                "error",
                f"Stages use {elapsed} minutes, requested {spec.duration_minutes}",
            )
        for key in ("introduction", "development", "assessment", "conclusion"):
            if not any(stage.key == key for stage in body.lesson_stages):
                add("missing_lesson_stage", "error", f"Missing stage: {key}")
        if (
            spec.calendar
            and spec.lesson_date
            and not (
                spec.calendar.starts_on <= spec.lesson_date <= spec.calendar.ends_on
                and spec.lesson_date.weekday() in spec.calendar.teaching_weekdays
                and spec.lesson_date not in spec.calendar.excluded_dates
            )
        ):
            add("lesson_not_teachable", "error", "Lesson date falls outside teaching calendar")
    elif body.lesson_stages:
        add("unexpected_lesson_stages", "error", "Non-plan documents cannot contain stages")
    missing = sorted(targets - used_coverage, key=str)
    for outcome in missing:
        add("coverage_gap", "error", f"Mandatory requested outcome not evidence-mapped: {outcome}")
    if body.review_status == "approved" and not body.reviewer_id:
        add("approval_missing_reviewer", "error", "Approval needs reviewer identity")
    # Reference-notes quality is not the same as verbose lesson planning.
    # The genre gate ensures there is meaningful, printable factual content.
    if spec.type == TeachingType.lesson_notes and note_style_spec(
        spec.planning_scope.get("source_subject_name"), spec.depth.value
    ):
        explanation = sections_by_key.get("explanation")
        if explanation:
            notes_bullets = []
            for block in explanation.blocks:
                if block.kind == BlockKind.list:
                    notes_bullets.extend(
                        point.strip(" \t•-*") for point in block.text.splitlines() if point.strip(" \t•-*")
                    )
                    for point in block.text.splitlines():
                        if len(point.split()) > 32:
                            add(
                                "reference_notes_long_fact", "warning",
                                "Use one short factual statement per bullet (usually under 32 words).",
                                block.id,
                            )
                elif block.kind == BlockKind.paragraph and len(block.text.split()) > 65:
                    add(
                        "reference_notes_dense_paragraph", "warning",
                        "Replace long explanation paragraphs with short definitions and separate facts.",
                        block.id,
                    )
            minimum = {"concise": 3, "standard": 5, "comprehensive": 8}[spec.depth.value]
            if len(notes_bullets) < minimum:
                add(
                    "reference_notes_insufficient_facts", "error",
                    f"Explanation needs at least {minimum} separately listed, evidence-grounded facts; "
                    "expand from permitted sources instead of filling with narrative.",
                )
        if len({item.source_uri for item in bundle.evidence}) < 2:
            add(
                "limited_source_diversity", "warning",
                "Only one independent source supplied. Check topic coverage before publication.",
            )
    if spec.type == TeachingType.lesson_notes and spec.depth != "concise":
        words = sum(
            len(block.text.split()) for section in body.sections for block in section.blocks
        )
        if words < (350 if spec.depth == "comprehensive" else 150):
            add("insufficient_depth", "warning", f"Only {words} prose words for selected depth")
    return TeachingValidation(
        valid=not any(f.severity == "error" for f in findings),
        teacher_review_required=True,
        missing_outcome_ids=missing,
        findings=findings,
    )
