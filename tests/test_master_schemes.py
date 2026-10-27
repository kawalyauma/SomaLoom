"""Source schedules drive generation without crossing school boundaries."""
from uuid import uuid4, UUID
from sqlalchemy import select
from conftest import sign_in
from app.core.models import resources, resource_versions, BackgroundJob, generations
from services.schemes.models import imports
from services.schemes.service import rebuild, selection

def seed(db, school, topic='Fractions', version=1, resource=None):
    resource=resource or uuid4();vid=uuid4();jid=uuid4()
    if version==1:
        db.execute(resources.insert().values(id=resource,tenant_id=school,title='P5 Maths scheme term 3',media_type='application/pdf',provenance={'access_approved':True}))
    db.execute(resource_versions.insert().values(id=vid,tenant_id=school,resource_id=resource,version=version,object_key='scheme.pdf',checksum_sha256='0'*64,provenance={}))
    db.add(BackgroundJob(id=jid,tenant_id=school,kind='scheme_parse',status='succeeded',progress=100));db.flush()
    entry={'term':3,'week':1,'lesson':1,'topic':topic,'subtopic':'Equivalent '+topic,'objectives':['Identify '+topic],'activities':['Discuss examples'],'materials':[],'assessment':'Explain examples','inferred':True,'source':{'version_id':str(vid),'block_id':str(uuid4()),'page':2,'quote':'Equivalent fractions','source_uri':'upload://scheme','license':'unknown','title':'P5 scheme','resource_id':str(resource)}}
    db.execute(imports.insert().values(tenant_id=school,resource_version_id=vid,job_id=jid,parser_version='test',stage='ready',payload={'schemes':[{'grade':'P5','subject':'Mathematics','lessons':[entry]}]}));db.commit()
    return resource

def test_master_selection_generation_and_replacement(client, accounts, db, monkeypatch):
    schools,_=accounts;s=schools[0].id
    resource=seed(db,s);mid=rebuild(db,s,'P5','Mathematics')
    assert selection(db,schools[1].id,'P5','Math',3,1)[1]==[]
    sign_in(client,'teacher0@example.org')
    assert client.get('/api/v1/master-schemes/'+str(mid)).status_code==200
    assert client.get('/api/v1/master-schemes').json()['masters'][0]['lesson_count']==1
    options=client.get('/api/v1/generations/options').json()
    math=next(x for x in next(c for c in options['classes'] if c['value']=='P5')['subjects'] if x['value']=='Mathematics')
    assert math['terms'][0]['weeks'][0]['lessons'][0]['subtopic']=='Equivalent Fractions'
    monkeypatch.setattr('app.routes.generation.provider_available',lambda _:True)
    monkeypatch.setattr('app.routes.generation.enqueue_generation',lambda _:True)
    payload={'document_type':'lesson_notes','grade':'P5','subject':'Math','term':3,'week':1,'lesson':1}
    result=client.post('/api/v1/generations/for-class',headers={'Origin':'http://localhost:3000'},json=payload)
    assert result.status_code==202,result.text
    stored=db.scalar(select(generations.c.parameters).where(generations.c.id==UUID(result.json()['id'])))
    assert stored['request']['options']['planning_scope']['lessons'][0]['topic']=='Fractions'
    missing=client.post('/api/v1/generations/for-class',headers={'Origin':'http://localhost:3000'},json={**payload,'week':2})
    assert missing.status_code==422
    seed(db,s,topic='Decimals',resource=resource,version=2)
    assert selection(db,s,'P5','Math',3,1)[1]==[]  # Superseded PDF cannot remain selectable.
    rebuild(db,s,'P5','Mathematics')
    assert selection(db,s,'P5','Math',3,1)[1][0]['topic']=='Decimals'
    sign_in(client,'teacher1@example.org')
    assert client.get('/api/v1/master-schemes/'+str(mid)).status_code==404

def test_pdf_identity_and_exact_source_quotes():
    import pytest
    from services.extraction.models import ExtractedBlock, ExtractedDocument, SourceRef
    from services.schemes.schema import Scheme, is_scheme
    from services.schemes.tasks import verify_section
    rid,vid,bid=uuid4(),uuid4(),uuid4()
    block=ExtractedBlock(id=bid,type='paragraph',page=2,order=0,text='Equivalent fractions: identify halves and quarters.',confidence=1,source_ref=SourceRef(resource_id=rid,version_id=vid,page=2,order=0))
    doc=ExtractedDocument(resource_id=rid,version_id=vid,sha256='0'*64,blocks=[block])
    data={'grade':'P5','subject':'Math','identity_quote':'P5 Maths scheme term 3','lessons':[{'term':3,'week':1,'lesson':1,'topic':'Fractions','subtopic':'Equivalent fractions','objectives':['Identify fractions'],'activities':[],'materials':[],'assessment':'Identify halves','inferred':True,'source':{'block_id':str(bid),'quote':'identify halves and quarters'}}]}
    checked,rejected=verify_section(Scheme.model_validate(data),'P5 Maths scheme term 3',doc,{})
    assert rejected==0 and checked['lessons'][0]['source']['page']==2
    data['lessons'][0]['source']['quote']='An invented quotation'
    assert verify_section(Scheme.model_validate(data),'P5 Maths scheme term 3',doc,{})[1]==1
    data['grade']='P6'
    with pytest.raises(ValueError,match='class_not_supported'):
        verify_section(Scheme.model_validate(data),'P5 Maths scheme term 3',doc,{})
    assert is_scheme('P.5 Math scheme of work.pdf')
    assert not is_scheme('P.5 Math marking scheme.pdf')

def test_multiple_source_rows_in_one_period_are_all_preserved(db, accounts):
    from services.schemes.models import masters
    s=accounts[0][0].id
    seed(db,s)
    row=db.execute(select(imports).where(imports.c.tenant_id==s)).mappings().one()
    payload=dict(row['payload']);first=payload['schemes'][0]['lessons'][0]
    payload['schemes'][0]['lessons'].append({**first,'subtopic':'Comparing fractions','objectives':['Compare fractions'],'source':{**first['source'],'quote':'Compare fractions'}})
    db.execute(imports.update().where(imports.c.id==row['id']).values(payload=payload));db.commit()
    mid=rebuild(db,s,'P5','Mathematics')
    body=db.scalar(select(masters.c.body).where(masters.c.id==mid))
    assert len(body['lessons'])==1
    assert body['lessons'][0]['subtopic']=='Equivalent Fractions / Comparing fractions'
    assert body['lessons'][0]['objectives']==['Identify Fractions','Compare fractions']
    assert body['conflict_count']==0
    assert len(body['lessons'][0]['sources'])==2

def test_subject_abbreviations_share_one_master():
    from services.schemes.schema import subject_name
    assert subject_name('S.S.T')=='Social Studies'
    assert subject_name('M.T.C.')=='Mathematics'
    assert subject_name('SCI.')=='Integrated Science'
