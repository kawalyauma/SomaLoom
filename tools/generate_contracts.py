import json
from pathlib import Path
from contracts.v1 import schemas
root = Path(__file__).resolve().parents[1] / "contracts/v1"
for name in ("Resource", "ResourceVersion", "Extraction", "ContentBlock", "VisualAsset", "Equation", "CurriculumOutcome", "EvidenceLink", "GenerationJob", "GeneratedDocument", "Export", "ErrorResponse"):
    (root / f"{name}.schema.json").write_text(json.dumps(getattr(schemas, name).model_json_schema(), indent=2) + "\n")
