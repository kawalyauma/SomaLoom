"""Load all feature metadata for migration comparison and test database setup."""

from sqlalchemy import Index

from app.core.models import extractions
from services.assessment import models as assessment  # noqa: F401
from services.curriculum import models as curriculum  # noqa: F401
from services.export import models as publishing  # noqa: F401
from services.extraction import persistence as extraction  # noqa: F401
from services.ingestion import models as ingestion  # noqa: F401
from services.knowledge import models as knowledge  # noqa: F401
from services.schemes import models as schemes  # noqa: F401

Index(
    "uq_extractions_tenant_version_engine",
    extractions.c.tenant_id,
    extractions.c.resource_version_id,
    extractions.c.engine,
    unique=True,
)

from services.images import models as image_models  # noqa: F401
