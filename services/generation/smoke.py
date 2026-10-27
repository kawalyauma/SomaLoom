"""Opt-in staging smoke: real Codex/API provider with pre-licensed evidence JSON.

Usage: AI_PROVIDER=codex AI_CODEX_RUNNER=/path/isolated-runner AI_MODEL=... \
    python -m services.generation.smoke /safe/path/evidence-bundle.json /safe/output/draft.json

No automatic credential discovery or fixture inventions. Run ONLY in controlled staging.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from services.ai.provider import configured_provider
from services.generation.orchestrator import create_draft
from services.generation.schema import EvidenceBundle, GenerationInput


async def main(source: Path, destination: Path):
    bundle = EvidenceBundle.model_validate_json(source.read_text(encoding="utf-8"))
    # IDs here are locally generated classification placeholders, NOT evidence identifiers.
    # Evidence IDs and outcome IDs must come directly from licensed staging source records.
    curriculum_id = os.getenv("AI_SMOKE_CURRICULUM_ID")
    subject_id = os.getenv("AI_SMOKE_SUBJECT_ID")
    level_id = os.getenv("AI_SMOKE_LEVEL_ID")
    if not all((curriculum_id, subject_id, level_id)):
        raise SystemExit("Set AI_SMOKE_CURRICULUM_ID, AI_SMOKE_SUBJECT_ID and AI_SMOKE_LEVEL_ID")
    data = GenerationInput(
        document_type="lesson_notes",
        curriculum_id=curriculum_id,
        subject_id=subject_id,
        level_id=level_id,
        topic_ids=[o.id for o in bundle.outcomes],
    )
    provider = configured_provider(os.getenv("AI_PROVIDER", "disabled"))
    draft = await create_draft(data, bundle, provider, os.environ["AI_MODEL"])
    if not draft.quality_report.verified_blocks or not draft.references:
        raise SystemExit("Smoke failed: model returned no source-attributed blocks")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(draft.model_dump_json(indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "document_type": draft.document_type.value,
                "outcomes": draft.quality_report.required_outcomes,
                "covered": draft.quality_report.covered_outcomes,
                "citations": len(draft.references),
                "review_state": draft.review_state,
                "quality_warnings": draft.quality_report.warnings,
            }
        )
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: python -m services.generation.smoke EVIDENCE.json DRAFT.json")
    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2])))
