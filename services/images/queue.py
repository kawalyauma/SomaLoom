"""Durable image prompts for the existing ChatGPT browser coordinator; no inference here."""
from uuid import uuid4
from sqlalchemy import select
from services.images.models import requests
from app.core.models import documents, versions, generations


def enqueue_document_images(db, tenant, document_id, actor_id=None):
    document = db.execute(select(documents).where(documents.c.id==document_id,
        documents.c.tenant_id==tenant).with_for_update()).mappings().first()
    if not document:
        return []
    version = db.execute(select(versions).where(versions.c.document_id==document_id,
        versions.c.tenant_id==tenant).order_by(versions.c.version.desc()).limit(1)).mappings().first()
    if not version:
        return []
    gen = db.execute(select(generations).where(generations.c.id==document['generation_job_id'],
        generations.c.tenant_id==tenant)).mappings().first()
    actor_id = actor_id or (gen['requested_by'] if gen else None)
    if not actor_id:
        return []
    existing = db.execute(select(requests).where(requests.c.tenant_id==tenant,
        requests.c.generation_job_id==document['generation_job_id'])).mappings().all()
    found=[]
    for section in version['body'].get('sections', []):
        for block in section.get('blocks', []):
            if block.get('type')!='visual_needed':
                continue
            old=next((r for r in existing if r['metadata'].get('document_id')==str(document_id)
                      and r['metadata'].get('block_id')==block['id']), None)
            if old:
                found.append(old['id']);continue
            title=str(block.get('caption') or block.get('text') or section.get('title') or 'Lesson illustration')[:250]
            description=str(block.get('description') or block.get('text') or block.get('caption') or title)
            context=(gen['parameters'] or {}).get('request',{}).get('options',{}).get('planning_scope',{}) if gen else {}
            prompt=(f"Generate an original educational illustration for {context.get('class','')} {context.get('subject','')}. "
                f"Lesson: {section.get('title','')}. Required image: {description}. "
                "Use a clean white background, high resolution for A4 printing, accurate shapes and proportions, clear readable labels. "
                "Use only required labels. Do not add logos, watermarks, citations, source notes or AI/process text. "
                "Create the actual downloadable image, not just an image prompt or textual description. Check accuracy before returning it.")
            identifier=uuid4()
            db.execute(requests.insert().values(id=identifier,tenant_id=tenant,requested_by=actor_id,
                generation_job_id=document['generation_job_id'],title=title,prompt=prompt,status='prompt_ready',
                metadata={'document_id':str(document_id),'block_id':block['id'],'document_version_id':str(version['id']),
                          'description':description,'grade':context.get('class',''),'subject':context.get('subject',''),
                          'outcome_ids':block.get('outcome_ids',[]),'transport':'server_chrome_chatgpt',
                          'generation_source':'ChatGPT browser image generation','needs_accuracy_review':True}))
            found.append(identifier)
    return found
