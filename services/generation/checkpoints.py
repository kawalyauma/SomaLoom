"""Durable request-local checkpoints; retries keep source selection and completed AI calls."""
import hashlib
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.models import generations, evidence, resources, resource_versions
from services.ai.provider import AIResult
from services.generation.schema import EvidenceBundle


def parameters(db,school,gid):
    return dict(db.scalar(select(generations.c.parameters).where(generations.c.id==gid,generations.c.tenant_id==school)) or {})


def patch(db,school,gid,**updates):
    values=parameters(db,school,gid);values.update(updates)
    db.execute(generations.update().where(generations.c.id==gid,generations.c.tenant_id==school).values(parameters=values));db.commit()


def save_bundle(db,school,gid,bundle):
    values=parameters(db,school,gid);checkpoint=dict(values.get('checkpoint',{}));checkpoint['evidence_bundle']=bundle.model_dump(mode='json')
    patch(db,school,gid,checkpoint=checkpoint)


def saved_bundle(db,school,gid):
    raw=parameters(db,school,gid).get('checkpoint',{}).get('evidence_bundle')
    if not raw:return None
    bundle=EvidenceBundle.model_validate(raw)
    for passage in bundle.passages:
        row=db.execute(select(evidence.c.provenance).where(evidence.c.id==passage.id,evidence.c.tenant_id==school)).first()
        if not row:raise ValueError('saved_source_unavailable')
        vid=row.provenance.get('resource_version_id')
        if vid:
            from uuid import UUID
            rights=db.scalar(select(resources.c.provenance).join(resource_versions,(resource_versions.c.resource_id==resources.c.id)&(resource_versions.c.tenant_id==school)).where(resource_versions.c.id==UUID(vid),resources.c.tenant_id==school))
            if not rights or not rights.get('access_approved') or rights.get('deleted_at'):raise ValueError('saved_source_unavailable')
    return bundle


class CheckpointProvider:
    def __init__(self,provider,school,gid):self.provider,self.school,self.gid=provider,school,gid
    async def generate(self,request):
        key=hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        with SessionLocal() as db:
            cached=parameters(db,self.school,self.gid).get('checkpoint',{}).get('ai_calls',{}).get(key)
        if cached:return AIResult.model_validate(cached)
        result=await self.provider.generate(request)
        with SessionLocal() as db:
            values=parameters(db,self.school,self.gid);checkpoint=dict(values.get('checkpoint',{}));calls=dict(checkpoint.get('ai_calls',{}));calls[key]=result.model_dump(mode='json');checkpoint['ai_calls']=calls
            patch(db,self.school,self.gid,checkpoint=checkpoint)
        return result
