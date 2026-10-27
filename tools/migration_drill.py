"""Destructive migration drill ONLY on the explicitly disposable QA database."""

import os
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

url = make_url(os.environ["TEST_DATABASE_URL"])
if url.database != "somaloom_test" or url.host not in {"127.0.0.1", "localhost"}:
    raise SystemExit("Refusing migration drill outside local disposable somaloom_test")
config = Config("alembic.ini")
engine = create_engine(url)
identifier = uuid4()
with engine.begin() as db:
    db.execute(
        text(
            "INSERT INTO organizations(id,name,created_at,updated_at) VALUES (:id,'migration sentinel',now(),now())"
        ),
        {"id": identifier},
    )
command.downgrade(config, "0001_foundation")
with engine.connect() as db:
    assert (
        db.scalar(text("SELECT name FROM organizations WHERE id=:id"), {"id": identifier})
        == "migration sentinel"
    )
command.upgrade(config, "head")
with engine.connect() as db:
    assert (
        db.scalar(text("SELECT name FROM organizations WHERE id=:id"), {"id": identifier})
        == "migration sentinel"
    )
command.downgrade(config, "base")
command.upgrade(config, "head")
print(
    "PASS: populated downgrade to foundation preserves foundation records; full downgrade/upgrade passes. Feature downgrade drops feature data by design; production uses restore/roll-forward."
)
