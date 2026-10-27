"""Trusted host bridge: prepare work and ingest repository receipts/results. No AI calls."""
import asyncio
import json
import logging
import re
import sys
from uuid import UUID
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.models import BackgroundJob, generations, utcnow, User
from services.generation.checkpoints import parameters, saved_bundle
from services.generation.repository import activity_event, save_family
from services.generation.schema import GenerationInput
from services.resource_bank.tasks import root, REPO, prepare_request, ReplayProvider, digest, encoded


def export_pending(limit=5):
    with SessionLocal() as db:
        rows=db.execute(select(generations.c.id,generations.c.parameters,BackgroundJob.status).join(BackgroundJob,BackgroundJob.id==generations.c.job_id)).all()
    count=0
    for gid,params,status in rows:
        if params.get('execution_mode')!='github':continue
        path=root()/'status'/(str(gid)+'.json')
        if status=='cancelled':
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(encoded({'id':str(gid),'state':'cancelled'}));continue
        if path.exists() and json.loads(path.read_text()).get('state')=='cancelled':path.write_bytes(encoded({'id':str(gid),'state':'resumed'}))
        if status!='queued' or params.get('handoff',{}).get('packet_sha'):continue
        try:prepare_request(gid);count+=1
        except Exception as exc:logging.warning('resource_packet_failed id=%s type=%s',gid,type(exc).__name__)
        if count>=limit:break


def ingest_receipt(receipt):
    from services.generation.families import generate_family
    gid=UUID(receipt['id'])
    if receipt.get('repository')!=REPO:raise ValueError('receipt_repository_mismatch')
    number=int(receipt['issue_number'])
    expected=f'https://github.com/{REPO}/issues/{number}'
    if receipt.get('issue_url')!=expected:raise ValueError('receipt_issue_url_invalid')
    with SessionLocal() as db:
        row=db.execute(select(generations).where(generations.c.id==gid)).mappings().first()
        if not row:return
        school=row['tenant_id'];job=db.get(BackgroundJob,row['job_id'],with_for_update=True)
        values=dict(row['parameters']);handoff=dict(values.get('handoff',{}))
        if values.get('execution_mode')!='github' or handoff.get('packet_sha')!=receipt.get('packet_sha'):raise ValueError('receipt_packet_mismatch')
        if job.status in ('cancelled','succeeded'):return
        handoff.update(issue_url=expected,issue_number=number,commit_sha=receipt.get('commit_sha'),state='awaiting_external')
        values['handoff']=handoff
        if not receipt.get('result_sha'):
            job.status='queued';job.progress=max(job.progress,35)
            db.execute(generations.update().where(generations.c.id==gid,generations.c.tenant_id==school).values(parameters=activity_event(values,'awaiting_external',job.progress,'queued')));db.commit();return
        sha=receipt['result_sha']
        if not re.fullmatch('[a-f0-9]{64}',sha):raise ValueError('invalid_result_checksum')
        if handoff.get('processed_result_sha')==sha:return
        path=root()/'results'/str(gid)/(sha+'.json')
        if not path.exists():return  # Result sync may complete on the next timer cycle.
        raw=path.read_bytes()
        if len(raw)>2*1024*1024 or digest(raw)!=sha:raise ValueError('invalid_result_file')
        actor=db.get(User,row['requested_by'])
        if not actor or not actor.active or actor.tenant_id!=school:raise ValueError('requester_access_revoked')
        try:
            body=json.loads(raw)
            request=GenerationInput.model_validate(values['request'])
            bundle=saved_bundle(db,school,gid)
            if bundle is None:raise ValueError('saved_sources_missing')
            title,canonical=asyncio.run(generate_family(db,request,bundle,ReplayProvider(body),'external-agent',school,gid))
            save_family(db,school,gid,request.document_type.value,title,canonical)
            handoff.update(processed_result_sha=sha,state='complete')
            values['handoff']=handoff
            db.execute(generations.update().where(generations.c.id==gid,generations.c.tenant_id==school).values(parameters=activity_event(values,'awaiting_review',100,'succeeded')))
            job.status='succeeded';job.progress=100;job.error=None;job.finished_at=utcnow();db.commit()
            status={'id':str(gid),'state':'complete','result_sha':sha}
        except Exception as exc:
            db.rollback();values=parameters(db,school,gid);handoff.update(processed_result_sha=sha,state='needs_revision');values['handoff']=handoff
            job=db.get(BackgroundJob,row['job_id']);job.status='failed';job.error='external_result_validation_failed';job.progress=max(job.progress,70);job.finished_at=utcnow()
            db.execute(generations.update().where(generations.c.id==gid,generations.c.tenant_id==school).values(parameters=activity_event(values,'failed',job.progress,'failed')));db.commit()
            status={'id':str(gid),'state':'needs_revision','result_sha':sha,'error':str(exc)[:500] if isinstance(exc,ValueError) else type(exc).__name__}
        target=root()/'status'/(str(gid)+'.json');target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(encoded(status))


def ingest_pending():
    for path in (root()/'receipts').glob('*.json'):
        try:
            if path.stat().st_size>20000:continue
            ingest_receipt(json.loads(path.read_text()))
        except Exception as exc:logging.warning('resource_receipt_retry file=%s type=%s',path.name,type(exc).__name__)


if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] == ['export']:export_pending()
    elif sys.argv[1:] == ['ingest']:ingest_pending()
    else:raise SystemExit('Expected export or ingest')
