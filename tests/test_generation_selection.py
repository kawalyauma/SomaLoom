"""Class selection resolves tenant curriculum without exposing curriculum choices."""
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from conftest import sign_in
from app.core.models import curricula, generations, outcomes
from services.curriculum.models import mappings, topics
from sqlalchemy import select


def seed(db, school, year, approved=True):
    cid, tid, oid = uuid4(), uuid4(), uuid4()
    db.execute(curricula.insert().values(id=cid, tenant_id=school.id, name='Primary', country='Uganda', version=str(year), created_at=datetime(year, 1, 1, tzinfo=timezone.utc)))
    db.execute(topics.insert().values(id=tid, tenant_id=school.id, curriculum_id=cid, level='Primary', grade='P.5', subject='Maths', unit='Numeracy', title=f'Whole numbers {year}', kind='topic', sequence=1, prerequisites=[]))
    db.execute(outcomes.insert().values(id=oid, tenant_id=school.id, curriculum_id=cid, code=f'MATH-{year}', description='Use whole numbers'))
    db.execute(mappings.insert().values(tenant_id=school.id, topic_id=tid, outcome_id=oid, required=1, origin='enrichment', review_status='approved' if approved else 'draft', revision=1, concepts=[]))
    db.commit()
    return cid, tid


def test_automatic_latest_approved_curriculum_and_tenant_scope(client, accounts, db, monkeypatch):
    schools, _ = accounts
    old, old_topic = seed(db, schools[0], 2020)
    current, topic = seed(db, schools[0], 2025)
    seed(db, schools[0], 2026, approved=False)
    _, foreign_topic = seed(db, schools[1], 2027)
    assert client.get('/api/v1/generations/options').status_code == 401
    sign_in(client, 'teacher0@example.org')
    response = client.get('/api/v1/generations/options')
    assert response.status_code == 200, response.text
    primary = next(c for c in response.json()['classes'] if c['value'] == 'P5')
    math = next(s for s in primary['subjects'] if s['value'] == 'Mathematics')
    assert math['topics'] == [{'id': str(topic), 'title': 'Whole numbers 2025'}]
    assert 'curriculum_id' not in response.text
    monkeypatch.setattr('app.routes.generation.provider_available', lambda _: True)
    monkeypatch.setattr('app.routes.generation.enqueue_generation', lambda _: True)
    payload = {'document_type': 'lesson_notes', 'grade': 'P5', 'subject': 'Mathematics', 'topic_ids': [str(topic)]}
    headers = {'Origin': 'http://localhost:3000'}
    generated = client.post('/api/v1/generations/for-class', headers=headers, json=payload)
    assert generated.status_code == 202, generated.text
    request = db.scalar(select(generations.c.parameters).where(generations.c.id == UUID(generated.json()['id'])))['request']
    assert request['curriculum_id'] == str(current)
    assert request['level_id'] == str(uuid5(NAMESPACE_URL, f'somaloom-level:{current}:P.5'))
    assert request['subject_id'] == str(uuid5(NAMESPACE_URL, f'somaloom-subject:{current}:Maths'))
    for unavailable in (old_topic, foreign_topic):
        rejected = client.post('/api/v1/generations/for-class', headers=headers, json={**payload, 'topic_ids': [str(unavailable)]})
        assert rejected.status_code == 422, rejected.text
    assert client.post('/api/v1/generations/for-class', headers=headers, json={**payload, 'grade': 'P4'}).status_code == 422
    sign_in(client, 'reviewer0@example.org')
    assert client.post('/api/v1/generations/for-class', headers=headers, json=payload).status_code == 403


def test_empty_workspace_still_has_class_subject_choices(client, accounts):
    sign_in(client, 'teacher0@example.org')
    result = client.get('/api/v1/generations/options')
    assert result.status_code == 200, result.text
    p5 = next(c for c in result.json()['classes'] if c['value'] == 'P5')
    assert next(s for s in p5['subjects'] if s['value'] == 'Mathematics')['topics'] == []
