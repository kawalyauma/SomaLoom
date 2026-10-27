"""Teaching orchestration adapter: delegates all inference to Agent 5's AIProvider."""

from __future__ import annotations

import json
from uuid import UUID

from contracts.v1.schemas import GeneratedDocument
from services.ai.provider import AIProvider, AIRequest
from services.validators.teaching import validate_teaching_document, validate_teaching_inputs

from .schemas import EvidenceBundle, TeachingBody, TeachingResult, TeachingSpec
from .templates import build_prompt


class TeachingGenerationError(ValueError):
    """Malformed or incomplete AI output; do not publish unreviewed content."""


class TeachingStudio:
    def __init__(self, provider: AIProvider, model: str):
        self.provider = provider
        self.model = model

    async def generate(
        self,
        *,
        spec: TeachingSpec,
        evidence: EvidenceBundle,
        tenant_id: UUID,
        generation_job_id: UUID,
    ) -> TeachingResult:
        validate_teaching_inputs(spec, evidence)
        system, prompt = build_prompt(spec, evidence)
        result = await self.provider.generate(
            AIRequest(
                system=system,
                prompt=prompt,
                model=self.model,
                max_output_tokens=14000,
                response_schema=TeachingBody.model_json_schema(),
            )
        )
        try:
            raw = json.loads(result.text)
            body = TeachingBody.model_validate(raw)
            # Provider output may never grant approval or impersonate an author/reviewer.
            body.review_status = "needs_review"
            body.author_id = None
            body.reviewer_id = None
            body.revision = 1
        except (json.JSONDecodeError, ValueError) as error:
            raise TeachingGenerationError("AI did not return a valid teaching.v1 body") from error
        review = validate_teaching_document(spec, evidence, body)
        # Failed quality gates are returned for repair/review, never mislabeled ready.
        document = GeneratedDocument(
            tenant_id=tenant_id,
            generation_job_id=generation_job_id,
            title=body.title,
            document_type=spec.type.value,
            evidence_ids=[item.id for item in evidence.evidence],
            body={
                **body.model_dump(mode="json"),
                "spec": spec.model_dump(mode="json"),
                "quality": review.model_dump(mode="json"),
                "provider": {"name": result.provider, "model": result.model},
                "reference_index": [
                    {
                        "id": str(item.id),
                        "source_title": item.source_title,
                        "source_uri": item.source_uri,
                        "license": item.license,
                        "page": item.page,
                    }
                    for item in evidence.evidence
                ],
            },
        )
        return TeachingResult(document=document.model_dump(mode="json"), validation=review)
