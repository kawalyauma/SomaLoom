"""Bounded, auditable query expansion and cross-source evidence selection.

Pure helpers are deliberately provider independent and deterministic. Raw search
never bypasses the tenant/licensing predicates in services.knowledge.retrieval.
"""

from collections import defaultdict
import re


ALIASES = {
    "sst": ("social studies",),
    "social studies": ("sst",),
    "p7": ("primary seven", "p.7"),
    "primary seven": ("p7", "p.7"),
    "vegetation": ("natural vegetation", "plant cover", "grasslands", "savanna"),
    "savanna": ("savannah", "grassland"),
    "savannah": ("savanna", "grassland"),
    "grassland": ("savanna", "savannah"),
    "climate": ("weather patterns", "climatic conditions"),
    "agriculture": ("farming", "crop production"),
    "erosion": ("soil erosion", "land degradation"),
    "transport": ("transportation",),
    "population": ("population distribution", "settlement"),
    "oesophagus": ("esophagus",),
    "esophagus": ("oesophagus",),
}

MAX_QUERY_VARIANTS = 5
MAX_SELECTED_EVIDENCE = 40
MAX_EVIDENCE_PER_SOURCE = 8


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def query_variants(concept: str, topic: str = "", *, limit: int = MAX_QUERY_VARIANTS) -> list[str]:
    """Deterministic educational query variants; no remote model required.

    A few contextual variations are better than searching arbitrary single words
    that can dilute evidence. Callers must use every variant with both metadata-
    filtered and broadened tenant/rights-filtered search.
    """
    limit = max(1, min(8, int(limit)))
    concept, topic = _clean(concept), _clean(topic)
    if not concept:
        return []
    choices = [concept]
    # Capture punctuation-insensitive subject/grade aliases and key educational
    # phrases without generating an unbounded combinatorial expansion.
    normalized = concept.casefold().replace(".", "")
    for token, synonyms in ALIASES.items():
        if re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", normalized):
            for synonym in synonyms:
                choices.append(
                    re.sub(
                        r"(?<!\w)" + re.escape(token) + r"(?!\w)",
                        synonym,
                        normalized,
                        count=1,
                    )
                )
    if topic and topic.casefold() not in concept.casefold():
        choices.append(f"{topic} {concept}")
    # For a natural-language outcome, a multiword concept is a useful exact-
    # phrase anchor; additional jargon-only queries need teacher-curated aliases.
    unique = []
    seen = set()
    for item in choices:
        item = _clean(item)
        key = re.sub(r"[^a-z0-9]+", " ", item.casefold()).strip()
        if item and key not in seen:
            seen.add(key)
            unique.append(item[:950])
        if len(unique) >= limit:
            break
    return unique


def select_evidence(
    candidates: list[dict],
    *,
    limit: int = MAX_SELECTED_EVIDENCE,
    max_per_resource: int = MAX_EVIDENCE_PER_SOURCE,
) -> list[dict]:
    """Fair round-robin across sources without limiting a whole chapter to 3 chunks.

    Scores are retained, and each source's strongest candidates are inspected
    first. Deduplicate repeated retrievals, respecting exact source IDs and
    resource versions; never collapse different paragraphs just for same book.
    """
    limit = max(1, min(100, int(limit)))
    max_per_resource = max(1, min(30, int(max_per_resource)))
    ranked = {}
    for item in candidates:
        key = (
            str(item.get("resource_version_id")),
            str(item.get("source_id") or item.get("id")),
            str(item.get("fingerprint") or item.get("quote")),
        )
        if key not in ranked or float(item.get("score") or 0) > float(ranked[key].get("score") or 0):
            ranked[key] = item
    groups = defaultdict(list)
    for item in ranked.values():
        groups[str(item["resource_id"])].append(item)
    for bucket in groups.values():
        bucket.sort(key=lambda r: -float(r.get("score") or 0))
    order = sorted(
        groups, key=lambda key: -float(groups[key][0].get("score") or 0)
    )
    chosen = []
    counts = defaultdict(int)
    while len(chosen) < limit:
        added = False
        for source in order:
            if counts[source] >= max_per_resource or not groups[source]:
                continue
            chosen.append(groups[source].pop(0))
            counts[source] += 1
            added = True
            if len(chosen) >= limit:
                break
        if not added:
            break
    return chosen


def recall_at_k(actual: list[str], relevant: set[str], k: int) -> float:
    """Fixture-only measure: requires human-labeled relevant resource IDs."""
    if not relevant:
        return 1.0 if not actual[:k] else 0.0
    return len(set(actual[:k]) & relevant) / len(relevant)


def bound_generation_passages(passages, outcomes, *, max_total=80, max_per_outcome=6):
    """Reserve at least one source excerpt per outcome before spending prompt budget.

    Whole-book retrieval remains in the persisted research/audit; model calls
    receive a manageable, multi-outcome slice. No citation IDs are synthesized.
    """
    max_total = max(1, min(160, int(max_total)))
    max_per_outcome = max(1, min(16, int(max_per_outcome)))
    buckets = defaultdict(list)
    for passage in passages:
        buckets[passage.outcome_id].append(passage)
    order = [outcome.id for outcome in outcomes]
    selected = []
    for depth in range(max_per_outcome):
        for oid in order:
            if len(selected) >= max_total:
                return selected
            if len(buckets[oid]) > depth:
                selected.append(buckets[oid][depth])
    return selected
