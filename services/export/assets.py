"""Resolve reviewed visual bytes from tenant-owned storage, never model-supplied URLs."""

from io import BytesIO
from uuid import UUID

from app.core.models import extractions, resource_versions, resources, visuals
from app.core.storage import configured_store
from sqlalchemy import select

from services.rendering.document import DocumentValidationError


def resolver(db, tenant):
    def resolve(block):
        if str(block.get("asset_ref", "")).startswith("image-request:"):
            from services.images.models import requests
            parts=block["asset_ref"].split(":")
            try:identifier=UUID(parts[1])
            except ValueError:raise DocumentValidationError("Invalid imported image reference") from None
            row=db.execute(select(requests).where(requests.c.id==identifier,requests.c.tenant_id==tenant,requests.c.status=="imported")).mappings().first()
            if not row:raise DocumentValidationError("Imported image is unavailable in this school")
            asset=row["metadata"].get("assets",{}).get(parts[2]) if len(parts)==3 else row["metadata"]
            if not asset:raise DocumentValidationError("Imported image version is unavailable")
            return {"bytes":configured_store().get(tenant,asset["object_key"]),"caption":block.get("caption") or row["title"],"attribution":asset.get("credit") or "Educator-supplied illustration"}
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
