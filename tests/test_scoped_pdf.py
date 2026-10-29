from copy import deepcopy
from io import BytesIO
from uuid import uuid4

import pytest
from sqlalchemy import select
from PIL import Image

from conftest import sign_in
from test_generation_history import work
from app.core.models import documents, versions, generations
from app.core.storage import LocalObjectStore
from services.export.scoped import select_body, ScopeNotReady
from services.export.publishing import export_pdf
from services.rendering.document import validate_document


def test_lesson_selection_never_includes_other_or_combined_lesson():
    body={'sections':[{'key':'notes','blocks':[
        {'id':'a','type':'paragraph','text':'Selected lesson','outcome_ids':['one']},
        {'id':'b','type':'paragraph','text':'Other lesson','outcome_ids':['two']}]}]}
    assert select_body(body,{'one'},whole_document=False)['sections'][0]['blocks']==body['sections'][0]['blocks'][:1]
    combined=deepcopy(body);combined['sections'][0]['blocks'][1]['outcome_ids']=['one','two']
    with pytest.raises(ScopeNotReady):select_body(combined,{'one'},whole_document=False)


def test_student_pdf_clean_staff_audit_separate_and_chapters():
    from pypdf import PdfReader
    source={'title':'P6 Mathematics Term 3','review_state':'draft','evidence_ids':['ev-1'],
      'body':{'sections':[
        {'title':'Week 1','chapter':True,'blocks':[]},
        {'title':'Notes','blocks':[{'id':'a','type':'paragraph','text':'Learner explanation','citations':['ev-1']},
          {'id':'worked','type':'paragraph','text':'Worked example: 2 + 3 = 5'},
          {'id':'q','type':'question','text':'Calculate 4 + 6.'},
          {'id':'ans','type':'answer','text':'SECRET ANSWER'}]},
        {'key':'references','title':'References and teacher review','blocks':[{'id':'ref','type':'paragraph','text':'AUDIT SOURCE UUID'}]},
        {'title':'Week 2','chapter':True,'blocks':[]},
        {'title':'Practice','blocks':[{'id':'next','type':'paragraph','text':'Second week text'}]}]}}
    pdf=PdfReader(BytesIO(export_pdf(source,require_approval=False)))
    text='\n'.join(p.extract_text() for p in pdf.pages)
    assert 'Contents' in text and 'DRAFT' in text and 'Week 2' in text
    assert 'Worked example' in text
    assert 'SECRET ANSWER' not in text and 'Evidence IDs' not in text and 'AUDIT SOURCE' not in text
    assert len(pdf.pages)>=3 and pdf.outline
    teacher=validate_document(source,audience='teacher',strict_visuals=False)
    assert len(teacher['body']['sections'])==5
    assert source['body']['sections'][1]['blocks'][0]['citations']==['ev-1']


def test_scoped_routes_are_private_and_missing_scope_not_success(client, accounts):
    assert client.get('/api/v1/exports/catalog').status_code==401
    sign_in(client,'teacher0@example.org')
    assert client.get('/api/v1/exports/catalog').json()=={'items':[]}
    assert client.post('/api/v1/exports/scoped-pdf',headers={'Origin':'http://localhost:3000'},json={
        'grade':'P6','subject':'Maths','term':3}).status_code==409


def test_queue_and_image_replacement_idempotent_and_tenant_safe(client, accounts, db, monkeypatch, tmp_path):
    schools,users=accounts;owner=next(u for u in users if u.email=='teacher0@example.org')
    gid,_=work(db,schools[0],owner,{'class':'P6','subject':'Mathematics'})
    did=uuid4();db.execute(documents.insert().values(id=did,tenant_id=schools[0].id,generation_job_id=gid,
        title='P6 figures',document_type='lesson_notes'))
    original={'sections':[{'title':'Lesson 1','blocks':[{'id':'position','type':'visual_needed','text':'A labelled cube',
        'outcome_ids':['specific-outcome'],'citations':[]}]}],'evidence_ids':[]}
    db.execute(versions.insert().values(document_id=did,tenant_id=schools[0].id,version=1,body=original));db.commit()
    sign_in(client,owner.email);headers={'Origin':'http://localhost:3000'}
    url='/api/v1/image-requests/from-document/'+str(did)
    queued=client.post(url,headers=headers,json={});assert queued.status_code==201,queued.text
    item=queued.json()['items'][0];assert item['metadata']['block_id']=='position'
    assert client.post(url,headers=headers,json={}).json()['items'][0]['id']==item['id']
    monkeypatch.setattr('services.images.router.configured_store',lambda:LocalObjectStore(str(tmp_path)))
    out=BytesIO();Image.new('RGB',(100,100),'white').save(out,format='PNG')
    assert client.post(f"/api/v1/image-requests/{item['id']}/import",headers=headers,
        files={'file':('cube.png',out.getvalue(),'image/png')}).status_code==200
    attached=f"/api/v1/image-requests/{item['id']}/attach"
    assert client.post(attached,headers=headers,json={'document_id':str(did)}).status_code==200
    latest=db.execute(select(versions).where(versions.c.document_id==did).order_by(versions.c.version.desc())).mappings().first()
    block=latest['body']['sections'][0]['blocks'][0]
    assert latest['version']==2 and block['id']=='position' and block['type']=='figure'
    assert block['outcome_ids']==['specific-outcome'] and len(latest['body']['sections'])==1
    assert client.post(attached,headers=headers,json={'document_id':str(did)}).status_code==200
    assert client.post(url,headers=headers,json={}).json()['items']==[]
    sign_in(client,'teacher1@example.org')
    assert client.post(url,headers=headers,json={}).status_code==404


def test_full_term_week_and_lesson_books_use_source_slots_and_detect_missing(client, accounts, db, monkeypatch):
    from test_master_schemes import seed as seed_scheme
    from services.schemes.models import imports, masters
    from services.schemes.service import rebuild
    from services.export.scoped import assemble
    from app.core.models import BackgroundJob
    from pypdf import PdfReader
    schools,users=accounts;school=schools[0];teacher=next(u for u in users if u.email=='teacher0@example.org')
    seed_scheme(db,school.id)
    imp=db.execute(select(imports).where(imports.c.tenant_id==school.id)).mappings().one()
    payload=deepcopy(imp['payload']);base=payload['schemes'][0]['lessons'][0]
    payload['schemes'][0]['lessons']=[{**base,'week':w,'lesson':l,'subtopic':f'Week{w} lesson{l}'} for w in [1,2] for l in [1,2]]
    db.execute(imports.update().where(imports.c.id==imp['id']).values(payload=payload));db.commit()
    mid=rebuild(db,school.id,'P5','Mathematics');db.commit()
    master=db.scalar(select(masters.c.body).where(masters.c.id==mid))
    for w in [1,2]:
        slots=[s for s in master['lessons'] if s['week']==w];gid,jid,did=uuid4(),uuid4(),uuid4()
        db.add(BackgroundJob(id=jid,tenant_id=school.id,kind='generation',status='succeeded',progress=100));db.flush()
        db.execute(generations.insert().values(id=gid,tenant_id=school.id,job_id=jid,requested_by=teacher.id,document_type='lesson_notes',
          parameters={'request':{'topic_ids':[s['topic_id'] for s in slots],'options':{'planning_scope':{'class':'P5','subject':'Mathematics','term':3,'week':w,'lesson':None,'lessons':slots}}}}))
        db.execute(documents.insert().values(id=did,tenant_id=school.id,generation_job_id=gid,title=f'Week {w}',document_type='lesson_notes'))
        db.execute(versions.insert().values(document_id=did,tenant_id=school.id,version=1,body={'evidence_ids':[],
          'sections':[{'title':'Notes','key':'notes','blocks':[{'id':f'b{l["lesson"]}','type':'paragraph','text':f'CONTENT_W{w}_L{l["lesson"]}',
             'outcome_ids':[l['outcome_id']]} for l in slots]}]}))
    db.commit()
    lesson=assemble(db,school.id,'P5','math',3,1,2)
    assert 'CONTENT_W1_L2' in str(lesson) and 'CONTENT_W1_L1' not in str(lesson)
    week=assemble(db,school.id,'P5','math',3,1)
    assert 'CONTENT_W1_L1' in str(week) and 'CONTENT_W2_L1' not in str(week)
    term=assemble(db,school.id,'P5','math',3)
    assert len(term['source_versions'])==2 and len(term['body']['sections'])==4
    with pytest.raises(ScopeNotReady,match='approval'):assemble(db,school.id,'P5','math',3,approved=True)
    sign_in(client,teacher.email)
    r=client.post('/api/v1/exports/scoped-pdf',headers={'Origin':'http://localhost:3000'},json={'grade':'P5','subject':'math','term':3})
    assert r.status_code==200,r.text
    text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
    assert 'CONTENT_W1_L1' in text and 'CONTENT_W2_L2' in text and 'Contents' in text
    sign_in(client,'teacher1@example.org')
    assert client.get('/api/v1/exports/catalog').json()['items']==[]
    assert client.post('/api/v1/exports/scoped-pdf',headers={'Origin':'http://localhost:3000'},json={'grade':'P5','subject':'math','term':3}).status_code==409
    # A newly added uncovered slot must block full-term books, not produce a partial PDF.
    value=deepcopy(master);value['lessons'].append({**value['lessons'][-1],'week':3,'topic_id':str(uuid4()),'outcome_id':str(uuid4())})
    db.execute(masters.update().where(masters.c.id==mid).values(body=value));db.commit()
    with pytest.raises(ScopeNotReady,match='Week 3'):assemble(db,school.id,'P5','math',3)
