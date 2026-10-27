"""Resolve reviewed visual bytes from tenant-owned storage, never model-supplied URLs."""

from io import BytesIO
from uuid import UUID

from app.core.models import extractions, resource_versions, resources, visuals
from app.core.storage import configured_store
from sqlalchemy import select

from services.rendering.document import DocumentValidationError


def resolver(db, tenant):
    def resolve(block):
        try:
            identifier = UUID(str(block["asset_ref"]))
        except (ValueError, KeyError):
            raise DocumentValidationError("Invalid visual reference") from None
        row = (
            db.execute(
                select(visuals)
                .join(
                    extractions,
                    (extractions.c.id == visuals.c.extraction_id)
                    & (extractions.c.tenant_id == visuals.c.tenant_id),
                )
                .join(
                    resource_versions,
                    (resource_versions.c.id == extractions.c.resource_version_id)
                    & (resource_versions.c.tenant_id == extractions.c.tenant_id),
                )
                .join(
                    resources,
                    (resources.c.id == resource_versions.c.resource_id)
                    & (resources.c.tenant_id == resource_versions.c.tenant_id),
                )
                .where(
                    visuals.c.id == identifier,
                    visuals.c.tenant_id == tenant,
                    resources.c.provenance["deleted_at"].as_string().is_(None),
                    resources.c.provenance["access_approved"].as_boolean().is_(True),
                )
            )
            .mappings()
            .first()
        )
        if not row:
            raise DocumentValidationError("Visual is unavailable in this school")
        prov = row["provenance"]
        if not prov.get("reviewed_by") or prov.get("needs_review", True):
            raise DocumentValidationError("Visual requires accuracy and licensing review")
        if (
            not prov.get("license")
            or prov["license"].lower() in {"unknown", "unverified"}
            or not prov.get("source_uri")
        ):
            raise DocumentValidationError("Visual attribution and rights required")
        raw = configured_store().get(tenant, row["object_key"])
        if len(raw) > 10 * 1024 * 1024:
            raise DocumentValidationError("Visual exceeds print limit")
        from PIL import Image

        with Image.open(BytesIO(raw)) as image:
            if image.width * image.height > 15_000_000:
                raise DocumentValidationError("Visual exceeds pixel limit")
            image.verify()
        return {
            "bytes": raw,
            "caption": row["caption"] or block.get("caption", "Visual"),
            "attribution": f"{prov['source_uri']} | {prov['license']}",
        }

    return resolve
