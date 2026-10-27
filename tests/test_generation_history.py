from uuid import uuid4
from sqlalchemy import select
from conftest import sign_in
from app.core.models import BackgroundJob, generations, documents, utcnow
from services.generation.repository import activity_event, update_progress, finish
from test_generation_selection import seed


def work(db,school,user,scope=None):
    cid,tid=seed(db,school,2025)
    jid,gid=uuid4(),uuid4()
    db.add(BackgroundJob(id=jid,tenant_id=school.id,kind='generation',status='queued',progress=0));db.flush()
    db.execute(generations.insert().values(id=gid,tenant_id=school.id,job_id=jid,requested_by=user.id,document_type='lesson_notes',parameters=activity_event({'request':{'options':{'planning_scope':scope or {}}}},'queued',0,'queued')))
    db.commit();return gid,jid


def test_durable_history_details_and_school_isolation(client,accounts,db):
    schools,users=accounts
    owner=next(u for u in users if u.email=='teacher0@example.org')
    foreign=next(u for u in users if u.email=='teacher1@example.org')
    scope={'class':'P5','subject':'Social Studies','term':3,'week':2,'lesson':4,'lessons':[{'topic':'East Africa','subtopic':'Countries'}]}
    gid,jid=work(db,schools[0],owner,scope)
    foreign_gid,_=work(db,schools[1],foreign)
    assert client.get('/api/v1/generations').status_code==401
    sign_in(client,owner.email)
    listing=client.get('/api/v1/generations').json()
    assert listing['total']==1 and listing['items'][0]['id']==str(gid)
    item=listing['items'][0]
    assert 'Week 2' in item['title'] and 'Lesson 4' in item['title']
    assert item['scope']['subject']=='Social Studies'
    assert item['activity'][0]['stage']=='queued' and item['can_manage']
    assert client.get('/api/v1/generations/'+str(foreign_gid)+'/activity').status_code==404
    assert client.get('/api/v1/generations?status=failed').json()['total']==0
    assert client.get('/api/v1/generations?page_size=1000').status_code==422
    assert update_progress(db,jid,schools[0].id,'researching',10)
    assert update_progress(db,jid,schools[0].id,'drafting',35)
    # A fresh request reads durable progress, independent of the submission page.
    item=client.get('/api/v1/generations/'+str(gid)+'/activity').json()
    assert item['progress']==35 and item['stage']=='drafting'
    assert [e['stage'] for e in item['activity']]==['queued','researching','drafting']
    assert finish(db,jid,schools[0].id,'failed','provider_timeout')
    item=client.get('/api/v1/generations?status=failed').json()['items'][0]
    assert item['error']=='provider_timeout' and item['finished_at']
    assert item['activity'][-1]['status']=='failed'
    assert client.post('/api/v1/generations/'+str(gid)+'/cancel',headers={'Origin':'http://localhost:3000'}).status_code==409


def test_legacy_requests_and_completed_document_links(client,accounts,db):
    schools,users=accounts
    owner=next(u for u in users if u.email=='teacher0@example.org')
    gid,jid=work(db,schools[0],owner)
    db.execute(generations.update().where(generations.c.id==gid).values(parameters={'request':{'options':{}},'stage':'researching'}))
    job=db.get(BackgroundJob,jid);job.status='succeeded';job.progress=100;job.finished_at=utcnow()
    did=uuid4();db.execute(documents.insert().values(id=did,tenant_id=schools[0].id,generation_job_id=gid,title='Saved notes',document_type='lesson_notes'));db.commit()
    sign_in(client,owner.email)
    item=client.get('/api/v1/generations/'+str(gid)+'/activity').json()
    assert item['document_id']==str(did) and item['document_title']=='Saved notes'
    assert item['stage']=='succeeded' and item['activity'][-1]['status']=='succeeded'


def test_retry_cancel_and_request_ownership(client,accounts,db,monkeypatch):
    import fakeredis
    schools,users=accounts
    owner=next(u for u in users if u.email=='teacher0@example.org')
    admin=next(u for u in users if u.email=='school_admin0@example.org')
    gid,jid=work(db,schools[0],owner)
    colleague,_=work(db,schools[0],admin)
    finish(db,jid,schools[0].id,'failed','provider_timeout')
    redis=fakeredis.FakeRedis()
    monkeypatch.setattr('app.core.queue.redis_connection',lambda:redis)
    monkeypatch.setattr('app.routes.generation.enqueue_generation',lambda _:True)
    sign_in(client,owner.email)
    assert client.get('/api/v1/generations').json()['total']==1
    assert not client.get('/api/v1/generations/'+str(colleague)+'/activity').json()['can_manage']
    assert client.post('/api/v1/generations/'+str(colleague)+'/cancel',headers={'Origin':'http://localhost:3000'}).status_code==404
    retry=client.post('/api/v1/generations/'+str(gid)+'/retry',headers={'Origin':'http://localhost:3000'})
    assert retry.status_code==202,retry.text
    item=client.get('/api/v1/generations/'+str(gid)+'/activity').json()
    assert item['attempts']==1 and item['activity'][-1]['status']=='queued'
    assert [e['status'] for e in item['activity']]==['queued','failed','queued']
    assert client.post('/api/v1/generations/'+str(gid)+'/cancel',headers={'Origin':'http://localhost:3000'}).status_code==200
    item=client.get('/api/v1/generations/'+str(gid)+'/activity').json()
    assert item['activity'][-1]['status']=='cancelled' and item['finished_at']
