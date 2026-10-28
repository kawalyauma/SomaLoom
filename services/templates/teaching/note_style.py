"""Reference-book writing rules for primary SST and Science.

Guidance is about presentation and independent fact synthesis, not copying
publisher text, images, diagrams or passages from reference books.
"""

from __future__ import annotations

import re


REFERENCE_NOTES_STYLE = "primary_reference_notes_v1"


def subject_family(subject: str | None) -> str | None:
    """Recognize the canonical curriculum subject name, not user prompt text."""
    cleaned = re.sub(r"\s+", " ", subject or "").strip().casefold()
    if re.search(r"\b(sst|social studies)\b", cleaned):
        return "sst"
    if re.search(r"\b(science|scie)\b", cleaned):
        return "science"
    return None


def note_style_spec(subject: str | None, depth: str) -> dict | None:
    family = subject_family(subject)
    if family is None:
        return None
    guidance = {
        "style": REFERENCE_NOTES_STYLE,
        "audience": "Ugandan primary learners; use clear standard English",
        "purpose": "Original, exam-useful notes in the style of a concise study reference book",
        "subject": family,
        "tone": [
            "Use direct factual sentences in simple language, mainly 6-20 words.",
            "Give the definition first under a meaningful topic or subtopic heading.",
            "Present each distinct fact, function, cause, effect, importance or example as its own bullet on a new line.",
            "For list blocks, separate bullet items with newline characters; never combine multiple facts in one paragraph or one list item.",
            "Follow a clear sequence: meaning, classifications/types, features/parts, examples, uses/functions, importance, problems and solutions, where relevant.",
            "Prefer a short definition and several information-rich, non-repetitive factual points over narrative exposition.",
            "Make explanation the dominant section; introductory activities and teacher instructions should be short and subordinate.",
            "Use comparison tables for meaningful contrasts. Use practical, correct diagrams/flowcharts/maps only if approved assets exist, otherwise mark visual_needed.",
            "Create original notes from verified permitted evidence. Do not copy or lightly paraphrase copyrighted textbook sections or diagrams.",
            "Do not add facts merely to reach a word or bullet target. If evidence is insufficient, flag the missing coverage and require teacher review.",
            "Never recycle obsolete political officeholders, administrative units, dates, legal requirements or scientific misconceptions from an old textbook as current facts.",
            "Support claims with genuine source references when possible. Keep formal references at the end rather than interrupting every bullet.",
            "Use brief end-of-topic review questions. Do not turn the notes into a lesson plan, sermon or verbose teacher script.",
        ],
        "depth": {
            "concise": "Cover the required subtopic accurately, using short grouped facts and necessary definitions.",
            "standard": "Cover each required idea and its meaningful examples, distinctions and applications.",
            "comprehensive": "Cover all evidence-supported subtopics thoroughly with many short points, tables and suitable visuals; not long paragraphs.",
        }.get(str(depth), "Cover the required concepts accurately."),
        "block_rules": {
            "explanation": "For each subtopic: one heading, optional one-sentence definition, then a multi-line list of concise facts. Use several heading/list blocks, not one giant prose block.",
            "list": "One short fact per newline. No leading bullet glyph required; renderer creates bullets.",
            "paragraph": "Reserve paragraphs for definitions and necessary context, normally one or two sentences.",
            "question": "End with topic-aligned practice questions; keep answer keys out of pupil-facing notes.",
        },
    }
    if family == "sst":
        guidance["subject_specific"] = [
            "Prioritize factual definitions, Uganda/East Africa examples, places and geographical relationships.",
            "Group roles, reasons, effects, advantages, disadvantages and solutions as independent facts.",
            "Use clear tables for institutions, geographical comparisons and classifications.",
            "For maps include accurate title, key/legend, labels, scale or orientation where meaningful; never invent boundaries.",
            "Verify current public offices, electoral laws and district arrangements independently or mark them for review.",
        ]
    else:
        guidance["subject_specific"] = [
            "Prioritize accurate definitions, characteristics, classifications, functions, adaptations and examples.",
            "Use step-by-step lists for processes and experiments, distinguishing materials, method, observations and conclusion.",
            "Use labeled diagrams or flowcharts for plant parts, organs, processes and classification when appropriate.",
            "State scientific cause-effect relationships precisely; avoid inherited misconceptions from old notes.",
            "Use correct formulas and notation for calculations where needed; don't manufacture experimental outcomes.",
        ]
    return guidance
