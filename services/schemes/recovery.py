"""Bounded local recovery without inference or discarding successful extraction."""
from datetime import timedelta
from sqlalchemy import select
from app.core.models import BackgroundJob,extractions,utcnow
from services.schemes.models import imports
from services.extraction.jobs import load_document


def text_ready(doc):
    if not doc or not any((b.text or b.table or b.latex) and not b.needs_review for b in doc.blocks):return False
    if not doc.partial:return True
    # Visual limits do not invalidate fully processed text. Missing pages/OCR do.
    return (doc.pages_total>0 and doc.pages_processed==doc.pages_total
        and all(w=='asset_limit_reached' or w.startswith('low_resolution_asset_')
                or w=='docx_page_numbers_unavailable_without_layout_engine' for w in doc.processing_warnings))


def recover_extractions(db,school_id=None,limit=5):
    query=select(imports).join(BackgroundJob,BackgroundJob.id==imports.c.job_id).where(
        imports.c.stage=='extraction_failed',BackgroundJob.status=='failed').order_by(imports.c.updated_at)
    if school_id is not None:query=query.where(imports.c.tenant_id==school_id)
    rows=db.execute(query).mappings().all();recovered=0
    for row in rows:
        if recovered>=limit:break
        payload=dict(row['payload']);recovery=dict(payload.get('recovery',{}))
        if recovery.get('next_retry_at','')>utcnow().isoformat():continue
        link=db.execute(select(extractions).where(extractions.c.resource_version_id==row['resource_version_id'],
            extractions.c.tenant_id==row['tenant_id'],extractions.c.engine=='multimodal-v1')).mappings().first()
        if not link:continue
        child=db.get(BackgroundJob,link['job_id'],with_for_update=True)
        parent=db.get(BackgroundJob,row['job_id'],with_for_update=True)
        doc=load_document(db,row['tenant_id'],link['id'])
        ready=text_ready(doc)
        if not ready and (child.status!='failed' or int(recovery.get('attempts',0))>=2):continue
        recovery['previous_error']=parent.error
        if not ready:
            attempt=int(recovery.get('attempts',0))+1
            recovery.update(attempts=attempt,next_retry_at=(utcnow()+timedelta(minutes=5*attempt)).isoformat())
            child.status='queued';child.error=None;child.finished_at=None
        recovery['action']='reused_complete_text' if ready else 'extraction_retry_queued'
        payload['recovery']=recovery
        parent.status='queued';parent.error=None;parent.finished_at=None
        db.execute(imports.update().where(imports.c.id==row['id'],imports.c.tenant_id==row['tenant_id']).values(
            stage='waiting_extraction',payload=payload,updated_at=utcnow()))
        db.commit();recovered+=1
    return recovered
