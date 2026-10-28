"""Hosted work cannot opt into paid inference; scheme results retain source checks."""
import asyncio
import json
from uuid import uuid4,UUID
import pytest
from sqlalchemy import select
from conftest import sign_in
from app.core.models import generations,BackgroundJob
from test_generation_selection import seed as curriculum
from test_master_schemes import seed as scheme_source
from services.schemes.models import imports
from services.schemes.github import external_provider
from services.schemes.tasks import parse_chunks
from services.extraction.models import ExtractedBlock,ExtractedDocument,SourceRef
from services.resource_bank.tasks import digest,encoded


def test_explicit_ai_request_is_github(client,accounts,db,monkeypatch):
    _,topic=curriculum(db,accounts[0][0],2025)
    sign_in(client,'teacher0@example.org')
    monkeypatch.setattr('app.routes.generation.provider_available',lambda _:False)
    result=client.post('/api/v1/generations/for-class',headers={'Origin':'http://localhost:3000'},json={
        'document_type':'lesson_notes','grade':'P5','subject':'Mathematics',
        'topic_ids':[str(topic)],'options':{'execution_mode':'ai'}})
    assert result.status_code==202,result.text
    params=db.scalar(select(generations.c.parameters).where(generations.c.id==UUID(result.json()['id'])))
    assert params['execution_mode']=='github'
    assert params['request']['options']['execution_mode']=='github'


def test_scheme_packet_result_and_exact_quotes(db,accounts,monkeypatch,tmp_path):
    school=accounts[0][0].id;scheme_source(db,school)
    row=db.execute(select(imports).where(imports.c.tenant_id==school)).mappings().one()
    job=db.get(BackgroundJob,row['job_id']);job.status='queued'
    monkeypatch.setenv('RESOURCE_BANK_ROOT',str(tmp_path))
    monkeypatch.setattr('services.schemes.github.source_files',lambda *args:({'sources/'+('0'*64)+'.pdf':b'%PDF-test'},[]))
    rid,vid,bid=uuid4(),row['resource_version_id'],uuid4()
    block=ExtractedBlock(id=bid,type='paragraph',page=1,order=0,text='Equivalent fractions: identify halves and quarters.',confidence=1,source_ref=SourceRef(resource_id=rid,version_id=vid,page=1,order=0))
    doc=ExtractedDocument(resource_id=rid,version_id=vid,sha256='0'*64,blocks=[block])
    source={'title':'P5 Mathematics scheme term 3'};payload={'source':{}}
    assert external_provider(db,row,job,source,doc,payload) is None
    manifest=json.loads((tmp_path/'outbox'/str(row['id'])/'manifest.json').read_text())
    assert manifest['kind']=='scheme' and any(f['path'].endswith('.pdf') for f in manifest['files'])
    body={'schemes':[{'grade':'P5','subject':'Mathematics','identity_quote':source['title'],
        'lessons':[{'term':3,'week':1,'lesson':1,'topic':'Fractions','subtopic':'Equivalent fractions',
            'objectives':['Identify fractions'],'activities':[],'materials':[],'assessment':'Identify halves',
            'inferred':True,'source':{'block_id':str(bid),'quote':'identify halves and quarters'}}]}],'warnings':[]}
    raw=encoded(body);sha=digest(raw);folder=tmp_path/'results'/str(row['id']);folder.mkdir(parents=True);(folder/(sha+'.json')).write_bytes(raw)
    receipts=tmp_path/'receipts';receipts.mkdir()
    receipt={'repository':'kawalyauma/SomaLoom','packet_sha':manifest['packet_sha'],'issue_number':123,
        'issue_url':'https://github.com/kawalyauma/SomaLoom/issues/123','result_sha':sha}
    (receipts/(str(row['id'])+'.json')).write_text(json.dumps(receipt))
    provider=external_provider(db,row,job,source,doc,payload)
    result=asyncio.run(parse_chunks(doc,source['title'],payload,lambda *args:None,provider=provider))
    assert result['schemes'][0]['lessons'][0]['source']['quote']=='identify halves and quarters'
    assert payload['handoff']['issue_url']==receipt['issue_url']
    body['schemes'][0]['grade']='P6'
    from services.resource_bank.tasks import ReplayProvider
    with pytest.raises(ValueError,match='class_not_supported'):
        asyncio.run(parse_chunks(doc,source['title'],{'source':{}},lambda *args:None,provider=ReplayProvider(body)))
