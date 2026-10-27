import json
from pathlib import Path

from app.main import app

Path("contracts/v1/openapi.json").write_text(json.dumps(app.openapi(), indent=2) + "\n")
