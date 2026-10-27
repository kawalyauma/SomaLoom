"""CLI for measured extraction quality; never supplies fabricated model scores.

Ground truth format:
{"cases": [{"name": "...", "predicted_text": "...", "reference_text": "...",
 "predicted_latex": "...", "reference_latex": "...",
 "predicted_caption_asset_ids": ["..."], "reference_caption_asset_ids": ["..."]}]}
Only fields supplied by the evaluator count toward reported metrics.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def distance(a: list[str], b: list[str]) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        new = [i]
        for j, y in enumerate(b, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = new
    return row[-1]


def evaluate(cases: list[dict]) -> dict:
    words = errors = math_correct = math_count = linked_correct = linked_count = 0
    for case in cases:
        if "reference_text" in case and "predicted_text" in case:
            ref = re.findall(r"\S+", case["reference_text"].lower())
            pred = re.findall(r"\S+", case["predicted_text"].lower())
            words += len(ref)
            errors += distance(ref, pred)
        if "reference_latex" in case and "predicted_latex" in case:
            math_count += 1
            math_correct += case["reference_latex"].strip() == case["predicted_latex"].strip()
        if "reference_caption_asset_ids" in case and "predicted_caption_asset_ids" in case:
            expected = set(case["reference_caption_asset_ids"])
            produced = set(case["predicted_caption_asset_ids"])
            linked_count += len(expected)
            linked_correct += len(expected & produced)
    return {
        "ocr_wer": errors / words if words else None,
        "ocr_reference_words": words,
        "math_exact_match": math_correct / math_count if math_count else None,
        "math_cases": math_count,
        "visual_caption_recall": linked_correct / linked_count if linked_count else None,
        "visual_caption_reference_links": linked_count,
        "note": "Null means no eligible verified fixture was supplied, not a perfect score.",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ground_truth_json", type=Path)
    args = parser.parse_args()
    payload = json.loads(args.ground_truth_json.read_text())
    if not isinstance(payload.get("cases"), list):
        raise ValueError("Expected cases array")
    print(json.dumps(evaluate(payload["cases"]), indent=2))


if __name__ == "__main__":
    main()
