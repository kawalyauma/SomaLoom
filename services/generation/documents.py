"""One editable publishing representation; retain original validated family payloads."""

from copy import deepcopy
from uuid import NAMESPACE_URL, uuid5


def canonical_body(raw, evidence_ids, *, seed):
    body = deepcopy(raw)
    body["evidence_ids"] = [str(x) for x in evidence_ids]
    body["review_state"] = "awaiting_review"
    for si, section in enumerate(body["sections"]):
        section["title"] = section.get("title") or section.get("heading") or "Section"
        for bi, block in enumerate(section["blocks"]):
            block["id"] = str(block.get("id") or uuid5(NAMESPACE_URL, f"{seed}:{si}:{bi}"))
            block["type"] = block.get("type") or block.get("kind")
            block["citations"] = block.get("citations", block.get("citation_ids", []))
            if block["type"] == "reflection":
                block["type"] = "paragraph"
            if block["type"] == "visual":
                block["type"] = "figure"
                block["asset_ref"] = str(block.get("asset_ref") or block.get("asset_id") or "")
            if block["type"] == "table":
                block["rows"] = block.get("rows") or block.get("table")
    return body
