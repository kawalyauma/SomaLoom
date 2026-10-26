#!/bin/sh
set -eu
alembic upgrade head
python - <<'PYTHON'
from sqlalchemy import create_engine, text
from app.core.config import get_settings
with create_engine(get_settings().database_url).begin() as conn:
    conn.execute(text("GRANT USAGE ON SCHEMA public TO somaloom_app"))
    conn.execute(text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO somaloom_app"))
    conn.execute(text("REVOKE ALL ON alembic_version FROM somaloom_app"))
    conn.execute(text("REVOKE UPDATE, DELETE, TRUNCATE ON audit_logs FROM somaloom_app"))
PYTHON
