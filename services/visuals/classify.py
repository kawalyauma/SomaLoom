"""Caption-grounded classification; missing metadata remains explicitly unknown."""
from __future__ import annotations

import re

from services.extraction.models import BlockType


def classify_visual(caption: str | None) -> tuple[BlockType, float]:
    if not caption:
        return BlockType.figure, 0.25
    t = caption.lower()
    if re.search(r"\b(map|latitude|longitude|contour map)\b", t):
        return BlockType.map, 0.80
    if re.search(r"\b(graph|chart|histogram|bar graph|pie chart)\b", t):
        return BlockType.chart, 0.80
    if re.search(r"\b(diagram|circuit|cross.section|life cycle)\b", t):
        return BlockType.diagram, 0.80
    if re.search(r"\b(illustration|drawing|sketch)\b", t):
        return BlockType.illustration, 0.75
    return BlockType.figure, 0.45


def map_metadata(caption: str | None, observed_text: str = "") -> dict:
    """Never infer boundaries, coordinates, direction or dates from topic alone."""
    source = "\n".join(filter(None, [caption, observed_text]))
    scale = re.search(r"\b(?:scale\s*[:=]?\s*)?(1\s*:\s*[\d ,]+)\b", source, re.I)
    legend = re.search(r"(?:legend|key)\s*[:\-]?\s*([^\n]{1,160})", source, re.I)
    title = re.search(r"\b(?:map of|map showing)\s+([^\n.;]{3,100})", source, re.I)
    orientation = re.search(r"\b(?:north|N\s*↑|↑\s*N)\b", source)
    return {
        "title": title.group(0).strip() if title else None,
        "geographic_area": title.group(1).strip() if title else None,
        "legend_text": legend.group(1).strip() if legend else None,
        "scale": scale.group(1).replace(" ", "") if scale else None,
        "north_observed": bool(orientation),
        "boundaries_verified": False,
        "labels": [],
        "review_reasons": ["map_age_and_boundaries_unverified", "labels_unverified"],
    }
