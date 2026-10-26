"""Synthetic, reproducible integration payloads. Not real educational resources."""

import json
from pathlib import Path
from uuid import UUID

from contracts.v1 import schemas as s

root = Path(__file__).resolve().parents[1] / "contracts/v1/fixtures"
ids = {
    name: UUID(int=i + 100)
    for i, name in enumerate(
        [
            "tenant",
            "resource",
            "version",
            "extraction",
            "block",
            "visual",
            "equation",
            "curriculum",
            "outcome",
            "evidence",
            "generation",
            "document",
            "document_version",
            "export",
            "user",
        ]
    )
}
base = dict(tenant_id=ids["tenant"], created_at="2026-10-26T12:00:00Z")
prov = s.Provenance(
    source_uri="https://example.org/synthetic",
    license="synthetic-test-data",
    checksum_sha256="0" * 64,
)
items = {
    "resource": s.Resource(
        **base,
        id=ids["resource"],
        title="Synthetic mathematics reference (MOCK)",
        media_type="application/pdf",
        provenance=prov,
    ),
    "resource_version": s.ResourceVersion(
        **base,
        id=ids["version"],
        resource_id=ids["resource"],
        version=1,
        object_key="resources/mock-v1.pdf",
        provenance=prov,
    ),
    "extraction": s.Extraction(**base, id=ids["extraction"], resource_version_id=ids["version"]),
    "content_block": s.ContentBlock(
        **base,
        id=ids["block"],
        extraction_id=ids["extraction"],
        page=1,
        kind="paragraph",
        text="Synthetic mock content",
    ),
    "visual_asset": s.VisualAsset(
        **base,
        id=ids["visual"],
        extraction_id=ids["extraction"],
        object_key="visuals/mock.png",
        kind="diagram",
        page=1,
        provenance=prov,
    ),
    "equation": s.Equation(
        **base,
        id=ids["equation"],
        extraction_id=ids["extraction"],
        page=1,
        latex="x^2 + y^2 = z^2",
        confidence=1,
    ),
    "curriculum_outcome": s.CurriculumOutcome(
        **base,
        id=ids["outcome"],
        curriculum_id=ids["curriculum"],
        code="MOCK-01",
        description="Synthetic mock outcome",
    ),
    "evidence_link": s.EvidenceLink(
        **base,
        id=ids["evidence"],
        content_block_id=ids["block"],
        outcome_id=ids["outcome"],
        quote="Synthetic mock content",
        provenance=prov,
    ),
    "generation_job": s.GenerationJob(
        **base,
        id=ids["generation"],
        document_type="notes",
        requested_by=ids["user"],
        evidence_ids=[ids["evidence"]],
    ),
    "generated_document": s.GeneratedDocument(
        **base,
        id=ids["document"],
        generation_job_id=ids["generation"],
        title="MOCK document",
        document_type="notes",
        evidence_ids=[ids["evidence"]],
        body={"schema_version": "1.0", "sections": [], "mock": True},
    ),
    "export": s.Export(
        **base, id=ids["export"], document_version_id=ids["document_version"], format="pdf"
    ),
}
for name, item in items.items():
    (root / f"{name}.json").write_text(json.dumps(item.model_dump(mode="json"), indent=2) + "\n")
