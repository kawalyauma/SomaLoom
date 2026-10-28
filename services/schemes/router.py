from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.auth.security import current_user, require_roles
from app.core.database import get_db
from app.core.models import User, BackgroundJob, resource_versions, resources, extractions
from services.schemes.models import masters, imports
from services.schemes.service import active_body

router=APIRouter(prefix='/master-schemes',tags=['master schemes'])

def school(user):
    if not user.tenant_id:raise HTTPException(403,'School membership required')
    return user.tenant_id

@router.get('')
def list_schemes(user:User=Depends(current_user),db:Session=Depends(get_db)):
    tenant=school(user);result=[]
    for row in db.execute(select(masters).where(masters.c.tenant_id==tenant).order_by(masters.c.grade,masters.c.subject)).mappings():
        body=active_body(db,tenant,row)
        result.append({'id':str(row['id']),'grade':row['grade'],'subject':row['subject'],'lesson_count':len(body['lessons']),
            'terms':sorted({l['term'] for l in body['lessons']}),'source_count':body['source_count'],
            'conflict_count':sum(bool(l['alternatives']) for l in body['lessons']),'missing_terms':body.get('missing_terms',[])})
    rows=db.execute(select(imports,resources.c.title,BackgroundJob.status,BackgroundJob.progress,BackgroundJob.error)
        .join(resource_versions,(resource_versions.c.id==imports.c.resource_version_id)&(resource_versions.c.tenant_id==tenant))
        .join(resources,(resources.c.id==resource_versions.c.resource_id)&(resources.c.tenant_id==tenant))
        .join(BackgroundJob,(BackgroundJob.id==imports.c.job_id)&(BackgroundJob.tenant_id==tenant))
        .where(imports.c.tenant_id==tenant).order_by(imports.c.created_at.desc()).limit(100)).mappings().all()
    sources=[{'id':str(r['id']),'title':r['title'],'stage':r['stage'],'status':r['status'],'progress':r['progress'],'error':r['error'],
        'handoff':r['payload'].get('handoff',{}),'resume_at':None,
        'warnings':r['payload'].get('warnings',[]),'lesson_count':sum(len(s['lessons']) for s in r['payload'].get('schemes',[]))} for r in rows]
    from services.schemes.budget import status
    return {'masters':result,'sources':sources,'execution_mode':'github','ai_budget':None}

@router.post('/rebuild',status_code=202)
def schedule_imports(user:User=Depends(require_roles('school_admin','teacher')),db:Session=Depends(get_db)):
    from services.schemes.tasks import discover
    count=discover(school_id=school(user))
    return {'status':'queued','new_sources':count}

@router.post('/imports/{import_id}/retry',status_code=202)
def retry_import(import_id:UUID,user:User=Depends(require_roles('school_admin','teacher')),db:Session=Depends(get_db)):
    tenant=school(user)
    row=db.execute(select(imports).where(imports.c.id==import_id,imports.c.tenant_id==tenant)).mappings().first()
    if not row:raise HTTPException(404,'Scheme source not found')
    job=db.get(BackgroundJob,row['job_id'],with_for_update=True)
    if job.status!='failed':raise HTTPException(409,'Only failed imports can be retried')
    data=dict(row['payload']);attempts=int(data.get('retry_count',0))
    if attempts>=2:raise HTTPException(409,'Retry limit reached; check the source PDF')
    data['retry_count']=attempts+1
    job.status='queued';job.error=None;job.finished_at=None
    for xjob in db.scalars(select(BackgroundJob).join(extractions,(extractions.c.job_id==BackgroundJob.id)&(extractions.c.tenant_id==tenant)).where(extractions.c.tenant_id==tenant,extractions.c.resource_version_id==row['resource_version_id'],BackgroundJob.status=='failed')):
        xjob.status='queued';xjob.error=None;xjob.finished_at=None
    db.execute(imports.update().where(imports.c.id==import_id,imports.c.tenant_id==tenant).values(stage='waiting_extraction',payload=data));db.commit()
    return {'status':'queued'}

@router.get('/{master_id}')
def detail(master_id:UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):
    tenant=school(user)
    row=db.execute(select(masters).where(masters.c.id==master_id,masters.c.tenant_id==tenant)).mappings().first()
    if not row:raise HTTPException(404,'Master scheme not found')
    return {'id':str(row['id']),'grade':row['grade'],'subject':row['subject'],'body':active_body(db,tenant,row)}
