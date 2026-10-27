"""Authenticated original-asset inspection and explicit educator verification."""

from uuid import UUID

from app.auth.router import audit
from app.auth.security import current_user, require_roles
from app.core.database import get_db
from app.core.models import User, visuals
from app.core.storage import configured_store
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(tags=["visual assets"])


def asset(db, tenant, asset_id):
    row = (
        db.execute(select(visuals).where(visuals.c.id == asset_id, visuals.c.tenant_id == tenant))
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(404, "Visual asset not found")
    return row


@router.get("/assets/{asset_id}")
def inspect_asset(
    asset_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = asset(db, user.tenant_id, asset_id)
    return {
        "id": row["id"],
        "kind": row["kind"],
        "page": row["page"],
        "caption": row["caption"],
        "provenance": row["provenance"],
        "download_url": f"/api/v1/assets/{asset_id}/download",
    }


@router.get("/assets/{asset_id}/download")
def download_asset(
    asset_id: UUID, user: User = Depends(current_user), db: Session = Depends(get_db)
):
    row = asset(db, user.tenant_id, asset_id)
    raw = configured_store().get(user.tenant_id, row["object_key"])
    from io import BytesIO

    from PIL import Image

    with Image.open(BytesIO(raw)) as image:
        mime = Image.MIME.get(image.format, "application/octet-stream")
    return Response(raw, media_type=mime, headers={"Content-Security-Policy": "sandbox"})


class AssetReview(BaseModel):
    accuracy_checked: bool
    license_checked: bool


@router.post("/assets/{asset_id}/review")
def review_asset(
    asset_id: UUID,
    data: AssetReview,
    request: Request,
    user: User = Depends(require_roles("school_admin", "reviewer")),
    db: Session = Depends(get_db),
):
    row = asset(db, user.tenant_id, asset_id)
    if not data.accuracy_checked or not data.license_checked:
        raise HTTPException(422, "Accuracy and licensing verification required")
    prov = dict(row["provenance"])
    if (
        not prov.get("source_uri")
        or not prov.get("license")
        or prov["license"].lower() in {"unknown", "unverified"}
    ):
        raise HTTPException(422, "Source attribution and license required")
    prov.update(needs_review=False, reviewed_by=str(user.id))
    db.execute(
        visuals.update()
        .where(visuals.c.id == asset_id, visuals.c.tenant_id == user.tenant_id)
        .values(provenance=prov)
    )
    audit(db, user, "visual.reviewed", asset_id, request)
    db.commit()
    return {"id": asset_id, "needs_review": False}
