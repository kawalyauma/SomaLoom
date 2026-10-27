"""Strict structured-document validation and audience-safe normalization.

This layer cannot authorize access to a school; the API must fetch documents by
authenticated tenant, check approval and authorize teacher-only exports.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

ALLOWED_BLOCKS = {
    "heading",
    "paragraph",
    "list",
    "table",
    "equation",
    "question",
    "answer",
    "marking_guide",
    "activity",
    "figure",
    "diagram",
    "map",
    "chart",
    "image",
    "page_break",
    "reference",
    "visual_needed",
}


class DocumentValidationError(ValueError):
    """An unsafe, incomplete or structurally invalid publication."""


def validate_document(
    document: dict[str, Any],
    *,
    audience: str = "student",
    strict_visuals: bool = True,
    asset_resolver=None,
) -> dict[str, Any]:
    """Validate and copy a v1 GeneratedDocument without silently fixing evidence."""
    if audience not in {"student", "teacher"}:
        raise DocumentValidationError("Audience must be student or teacher")
    if not isinstance(document, dict):
        raise DocumentValidationError("Document must be an object")
    result = deepcopy(document)
    if not isinstance(result.get("title"), str) or not result["title"].strip():
        raise DocumentValidationError("Document requires a nonempty title")
    body = result.get("body")
    if not isinstance(body, dict) or not isinstance(body.get("sections"), list):
        raise DocumentValidationError("Document body.sections is required")
    if not body["sections"]:
        raise DocumentValidationError("Document must contain at least one section")
    evidence = set(result.get("evidence_ids") or [])
    if any(not isinstance(eid, str) for eid in evidence):
        raise DocumentValidationError("Evidence identifiers must be strings")
    seen: set[str] = set()
    for section in body["sections"]:
        if not isinstance(section, dict) or not isinstance(section.get("blocks"), list):
            raise DocumentValidationError("Every section needs blocks")
        for block in section["blocks"]:
            if not isinstance(block, dict) or block.get("type") not in ALLOWED_BLOCKS:
                raise DocumentValidationError("Unsupported document block")
            block_id = block.get("id")
            if not isinstance(block_id, str) or not block_id.strip() or block_id in seen:
                raise DocumentValidationError("Duplicate or missing block ID")
            seen.add(block_id)
            if not isinstance(block.get("citations", []), list):
                raise DocumentValidationError("Citations must be a list")
            citations = block.get("citations", [])
            if any(not isinstance(link, str) for link in citations):
                raise DocumentValidationError("Citation identifiers must be strings")
            if citations and (not evidence or not set(citations).issubset(evidence)):
                raise DocumentValidationError("A block cites evidence absent from the document")
            if block["type"] == "table":
                rows = block.get("rows")
                if (
                    not isinstance(rows, list)
                    or not rows
                    or not all(
                        isinstance(r, list) and r and all(isinstance(c, str) for c in r)
                        for r in rows
                    )
                ):
                    raise DocumentValidationError("Tables need nonempty string rows")
                if len({len(r) for r in rows}) != 1:
                    raise DocumentValidationError("Table columns are inconsistent")
            if block["type"] == "equation":
                if not isinstance(block.get("latex"), str) or not block["latex"].strip():
                    raise DocumentValidationError("Equation has no editable LaTeX")
            if block["type"] in {"figure", "diagram", "map", "chart", "image", "visual_needed"}:
                if strict_visuals:
                    if block["type"] == "visual_needed" or not block.get("asset_ref"):
                        raise DocumentValidationError(
                            "Missing visual asset: editorial review required"
                        )
                    if asset_resolver is not None:
                        block["_resolved_asset"] = asset_resolver(block)
                        continue
                    if not block.get("license") or not block.get("caption"):
                        raise DocumentValidationError("Illustration needs a license and caption")
                    # Asset resolution is server-owned; never resolve arbitrary URLs here.
                    raise DocumentValidationError(
                        "Visual asset must be resolved from tenant-authorized object storage"
                    )
    if audience == "student":
        for section in body["sections"]:
            permitted = []
            for block in section["blocks"]:
                if (
                    block["type"] in {"answer", "marking_guide"}
                    or block.get("audience") == "teacher"
                ):
                    continue
                block.pop("answer", None)
                block.pop("marking_scheme", None)
                block.pop("rubric", None)
                permitted.append(block)
            section["blocks"] = permitted
    return result
