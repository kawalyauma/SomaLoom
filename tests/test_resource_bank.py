from uuid import uuid4,UUID
from pathlib import Path
import hashlib,json
import pytest
from sqlalchemy import select
from conftest import sign_in
from app.core.models import BackgroundJob,resources,resource_versions,extractions,blocks,evidence,generations,documents
from app.core.storage import LocalObjectStore
from services.ai.provider import AIRequest,AIResult
from services.generation.schema import EvidenceBundle,Outcome,Passage
from services.generation.checkpoints import CheckpointProvider
from services.resource_bank.tasks import prepare_request
from services.resource_bank.exchange import ingest_receipt
from test_generation_selection import seed


def test_reference_packet_and_issue_receipt_preserve_request(client,accounts,db,monkeypatch,tmp_path):
    schools,users=accounts;s=schools[0];owner=next(u for u in users if u.email=='teacher0@example.org')
    cid,tid=seed(db,s,2025);oid=db.scalar(select(__import__('app.core.models',fromlist=['outcomes']).outcomes.c.id).where(__import__('app.core.models',fromlist=['outcomes']).outcomes.c.curriculum_id==cid))
    rid,vid,xid,bid,eid=uuid4(),uuid4(),uuid4(),uuid4(),uuid4();xjob=BackgroundJob(tenant_id=s.id,kind='extraction',status='succeeded',progress=100);db.add(xjob);db.flush()
    raw=b'%PDF-1.4 teaching reference';sha=hashlib.sha256(raw).hexdigest();store=LocalObjectStore(str(tmp_path/'store'));store.put(s.id,'ref.pdf',raw)
    db.execute(resources.insert().values(id=rid,tenant_id=s.id,title='P5 teaching scheme',media_type='application/pdf',provenance={'access_approved':True,'source_uri':'https://example.org/scheme','license':'user-provided'}))
    db.execute(resource_versions.insert().values(id=vid,tenant_id=s.id,resource_id=rid,version=1,object_key='ref.pdf',checksum_sha256=sha,provenance={}))
    db.execute(extractions.insert().values(id=xid,tenant_id=s.id,resource_version_id=vid,job_id=xjob.id,engine='test'))
    db.execute(blocks.insert().values(id=bid,tenant_id=s.id,extraction_id=xid,page=1,kind='paragraph',text='Identify East African countries',bbox=None))
    db.execute(evidence.insert().values(id=eid,tenant_id=s.id,content_block_id=bid,outcome_id=oid,quote='Identify East African countries',provenance={'resource_version_id':str(vid)}));db.commit()
    bundle=EvidenceBundle(outcomes=[Outcome(id=oid,code='P5-SST',description='Identify East African countries')],passages=[Passage(id=eid,outcome_id=oid,quote='Identify East African countries',source_uri='https://example.org/scheme',license='user-provided')])
    monkeypatch.setenv('RESOURCE_BANK_ROOT',str(tmp_path/'bank'))
    monkeypatch.setattr('services.resource_bank.tasks.SessionLocal',lambda:db)
    monkeypatch.setattr('services.resource_bank.exchange.SessionLocal',lambda:db)
    monkeypatch.setattr('services.resource_bank.tasks.configured_store',lambda:store)
    monkeypatch.setattr('services.resource_bank.tasks.retrieve_evidence',lambda *args:bundle)
    monkeypatch.setattr('app.routes.generation.provider_available',lambda _:False)
    monkeypatch.setattr('app.routes.generation.enqueue_generation',lambda _:True)
    async def family(db_,request,bundle_,provider,model,tenant,gid):
        result=await provider.generate(AIRequest(system='Create educational notes',prompt='Use the supplied evidence',model='external-agent',response_schema={'type':'object','properties':{'answer':{'type':'string'}},'required':['answer'],'additionalProperties':False}))
        return 'External notes',{'sections':[{'title':'Notes','blocks':[{'id':str(uuid4()),'type':'paragraph','text':json.loads(result.text)['answer'],'citations':[str(eid)]}]}],'evidence_ids':[str(eid)],'review_state':'awaiting_review'}
    monkeypatch.setattr('services.generation.families.generate_family',family)
    # Avoid closing the fixture Session when task code opens an independent production session.
    class Borrow:
        def __enter__(self):return db
        def __exit__(self,*args):pass
    monkeypatch.setattr('services.resource_bank.tasks.SessionLocal',Borrow)
    monkeypatch.setattr('services.resource_bank.exchange.SessionLocal',Borrow)
    sign_in(client,owner.email)
    submitted=client.post('/api/v1/generations/for-class',headers={'Origin':'http://localhost:3000'},json={'document_type':'lesson_notes','grade':'P5','subject':'Math','topic_ids':[str(tid)],'options':{'execution_mode':'github'}})
    assert submitted.status_code==202,submitted.text
    gid=UUID(submitted.json()['id']);prepare_request(gid)
    folder=tmp_path/'bank'/'outbox'/str(gid);manifest=json.loads((folder/'manifest.json').read_text())
    assert (folder/'sources'/(sha+'.pdf')).read_bytes()==raw
    assert json.loads((folder/f'requests/{gid}/evidence.json').read_text())['passages'][0]['id']==str(eid)
    first_manifest=(folder/'manifest.json').read_bytes();prepare_request(gid)
    assert (folder/'manifest.json').read_bytes()==first_manifest
    receipt={'id':str(gid),'repository':'kawalyauma/SomaLoom','packet_sha':manifest['packet_sha'],'issue_number':12,'issue_url':'https://github.com/kawalyauma/SomaLoom/issues/12','commit_sha':'a'*40}
    ingest_receipt(receipt)
    tracking=client.get(f'/api/v1/generations/{gid}/activity').json()
    assert tracking['stage']=='awaiting_external' and tracking['handoff']['issue_url']==receipt['issue_url']
    assert tracking['checkpoint']['sources_saved'] and tracking['progress']==35
    with pytest.raises(ValueError,match='packet_mismatch'):ingest_receipt({**receipt,'packet_sha':'bad'})
    result=json.dumps({'answer':'Notes written by an external agent'}).encode();result_sha=hashlib.sha256(result).hexdigest();target=tmp_path/'bank'/'results'/str(gid)/(result_sha+'.json');target.parent.mkdir(parents=True);target.write_bytes(result)
    ingest_receipt({**receipt,'result_sha':result_sha})
    final=client.get(f'/api/v1/generations/{gid}/activity').json()
    assert final['status']=='succeeded' and final['document_id'], (final,(tmp_path/'bank'/'status'/(str(gid)+'.json')).read_text())
    ingest_receipt({**receipt,'result_sha':result_sha})
    assert len(db.execute(select(documents).where(documents.c.generation_job_id==gid)).all())==1


def test_completed_model_call_is_reused_on_retry(db,accounts,monkeypatch):
    import asyncio
    from test_generation_history import work
    schools,users=accounts;user=next(u for u in users if u.email=='teacher0@example.org')
    gid,_=work(db,schools[0],user)
    class Borrow:
        def __enter__(self):return db
        def __exit__(self,*args):pass
    monkeypatch.setattr('services.generation.checkpoints.SessionLocal',Borrow)
    class Provider:
        calls=0
        async def generate(self,request):
            self.calls+=1
            return AIResult(text='{"answer":"saved draft"}',provider='test',model='test')
    original=Provider();cached=CheckpointProvider(original,schools[0].id,gid)
    request=AIRequest(system='Draft notes',prompt='Use the selected sources',model='test')
    first=asyncio.run(cached.generate(request));second=asyncio.run(cached.generate(request))
    assert first.text==second.text and original.calls==1


def test_cli_errors_keep_specific_safe_causes():
    import importlib.util
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'infra/codex/error_codes.py'
    spec=importlib.util.spec_from_file_location('codex_error_codes',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.classify('', '{"type":"turn.failed","error":{"message":"usage limit reached"}}')=='provider_usage_limit'
    assert module.classify('Invalid JSON schema for response_format')=='provider_invalid_schema'
    assert module.classify('context length limit reached')=='provider_context_limit'
    assert module.classify('429 too many requests')=='provider_rate_limited'
