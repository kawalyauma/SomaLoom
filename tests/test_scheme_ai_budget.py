"""Scheme schedules require AI, reuse completed chunks and wait without losing work."""
import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4
import pytest
from services.ai.provider import AIResult
from services.extraction.models import ExtractedBlock, ExtractedDocument, SourceRef
from services.schemes.budget import SchemeBudgetWait, daily_limit, window
from services.schemes.tasks import parse_chunks


def test_ai_chunks_resume_from_budget_without_repeating_completed_calls():
    rid, vid = uuid4(), uuid4()
    blocks = [ExtractedBlock(id=uuid4(), type='paragraph', page=i+1, order=0,
        text=('Equivalent fractions. ' if i == 0 else 'Comparing fractions. ') + 'x'*14000,
        confidence=1, source_ref=SourceRef(resource_id=rid,version_id=vid,page=i+1,order=0)) for i in range(2)]
    doc = ExtractedDocument(resource_id=rid,version_id=vid,sha256='0'*64,blocks=blocks)
    payload = {'source':{}}
    calls = []
    class Provider:
        async def generate(self, request):
            context=json.loads(request.prompt)
            calls.append(context['chunk'])
            block=context['blocks_untrusted'][0]
            response={'schemes':[{'grade':'P5','subject':'Mathematics',
                'identity_quote':'P5 Mathematics scheme term 3',
                'lessons':[{'term':3,'week':1,'lesson':context['chunk'],
                    'topic':'Fractions','subtopic':'Equivalent fractions','objectives':['Identify fractions'],
                    'activities':[],'materials':[],'assessment':'Identify halves','inferred':True,
                    'source':{'block_id':block['block_id'],'quote':block['text'][:20]}}]}],'warnings':[]}
            return AIResult(text=json.dumps(response),provider='test',model='test')
    remaining=[1]
    def charge():
        if remaining[0]<=0:raise SchemeBudgetWait('2026-10-29T00:00:00+00:00')
        remaining[0]-=1
    def save(parts, done, total):payload['parts']=dict(parts)
    with pytest.raises(SchemeBudgetWait):
        asyncio.run(parse_chunks(doc,'P5 Mathematics scheme term 3',payload,save,Provider(),charge))
    assert len(payload['parts'])==1 and calls==[1]
    remaining[0]=20
    result=asyncio.run(parse_chunks(doc,'P5 Mathematics scheme term 3',payload,save,Provider(),charge))
    assert calls.count(1)==1
    assert result['schemes'][0]['lessons']
    count=len(calls)
    asyncio.run(parse_chunks(doc,'P5 Mathematics scheme term 3',payload,save,Provider(),charge))
    assert len(calls)==count  # A completed recheck performs no model calls.


def test_daily_window_and_zero_pause(monkeypatch):
    key,reset=window(datetime(2026,10,28,23,59,tzinfo=timezone.utc))
    assert key.endswith('2026-10-28') and reset.isoformat()=='2026-10-29T00:00:00+00:00'
    monkeypatch.setenv('SCHEME_AI_DAILY_CALL_LIMIT','0')
    assert daily_limit()==0


def test_budget_reservation_and_status(monkeypatch):
    from services.schemes import budget
    class Counter:
        used=0
        def eval(self,script,numkeys,key,limit):
            assert "redis.call('INCR'" in script and numkeys==1
            if self.used>=limit:return 0
            self.used+=1
            return 1
        def get(self,key):return self.used
    counter=Counter()
    monkeypatch.setattr(budget,'redis_connection',lambda:counter)
    monkeypatch.setenv('SCHEME_AI_DAILY_CALL_LIMIT','2')
    budget.reserve_call();budget.reserve_call()
    with pytest.raises(SchemeBudgetWait):budget.reserve_call()
    assert budget.status()['remaining']==0 and counter.used==2
