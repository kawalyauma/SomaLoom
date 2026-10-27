from app.core.models import col, domain
from sqlalchemy import JSON, String

requests = domain(
    "export_requests",
    [col("audience", String(20)), col("options", JSON)],
    [("export_id", "exports"), ("requested_by", "users")],
)
