"""Merge source-verified scheme lessons; never invent missing timetable coverage."""
import hashlib
from collections import defaultdict
from uuid import UUID, NAMESPACE_URL, uuid5
from sqlalchemy import select, func, text
from app.core.models import curricula, resources, resource_versions, outcomes, blocks, extractions, evidence
from services.curriculum.models import topics, mappings
from services.schemes.models import imports, masters
from services.schemes.schema import normalized, grade_name, subject_name


def stable(value):
    return uuid5(NAMESPACE_URL, 'somaloom-scheme:'+value)


def current_sources(db, school):
    latest = select(func.max(resource_versions.c.version)).where(resource_versions.c.resource_id == resources.c.id, resource_versions.c.tenant_id == school).correlate(resources).scalar_subquery()
    rows = db.execute(select(resource_versions.c.id, resource_versions.c.resource_id, resource_versions.c.provenance,
        resources.c.title, resources.c.provenance.label('rights'),resource_versions.c.created_at).join(resources,
        (resources.c.id == resource_versions.c.resource_id)&(resources.c.tenant_id == school)).where(
        resource_versions.c.tenant_id == school, resource_versions.c.version == latest)).mappings().all()
    return {str(r['id']):dict(r) for r in rows if r['rights'].get('access_approved') and not r['rights'].get('deleted_at')}


def active_body(db, school, master):
    active = current_sources(db, school)
    body = dict(master['body'])
    lessons = []
    for lesson in body.get('lessons', []):
        # The chosen source must still exist; a stale alternative cannot silently replace it.
        refs = [s for s in lesson['sources'] if s['version_id'] in active]
        if not refs or lesson['sources'][0]['version_id'] not in active:continue
        lessons.append({**lesson,'sources':refs})
    body['lessons'] = lessons
    body['source_count'] = len({s['version_id'] for l in lessons for s in l['sources']})
    return body


def rebuild(db, school, grade, subject):
    if db.bind.dialect.name == 'postgresql':
        db.execute(text('SELECT pg_advisory_xact_lock(hashtextextended(:key,0))'),{'key':f'master-scheme:{school}:{grade}:{subject}'})
    current = current_sources(db, school)
    records = db.execute(select(imports).where(imports.c.tenant_id == school, imports.c.stage == 'ready')).mappings().all()
    records = [r for r in records if str(r['resource_version_id']) in current]
    records.sort(key=lambda r:(current[str(r['resource_version_id'])]['created_at'],str(r['resource_version_id'])), reverse=True)
    slots = {}
    warnings = []
    for record in records:
        for section in record['payload'].get('schemes', []):
            if section['grade'] != grade or section['subject'] != subject:continue
            warnings.extend(record['payload'].get('warnings', []))
            for entry in section['lessons']:
                key=(entry['term'],entry['week'],entry['lesson'])
                signature=normalized(entry['topic']+' '+entry['subtopic'])
                if key not in slots:slots[key]={**entry,'sources':[entry['source']], 'alternatives':[],'signature':signature}
                elif slots[key]['sources'][0]['version_id']==entry['source']['version_id']:
                    # Several subtopics may share one explicitly numbered source period.
                    # Keep them in that lesson rather than misclassifying them as competing sources.
                    target=slots[key]
                    for field in ('topic','subtopic'):
                        values=list(dict.fromkeys(target[field].split(' / ')+[entry[field]]))
                        target[field]=' / '.join(values)
                    for field in ('objectives','activities','materials'):
                        target[field]=list(dict.fromkeys(target[field]+entry[field]))
                    if entry['assessment'] and entry['assessment'] not in target['assessment']:
                        target['assessment']='; '.join(filter(None,[target['assessment'],entry['assessment']]))
                    target['inferred']=target['inferred'] or entry['inferred']
                    if entry['source'] not in target['sources']:target['sources'].append(entry['source'])
                    target['signature']=normalized(target['topic']+' '+target['subtopic'])
                elif slots[key]['signature']==signature:
                    if entry['source'] not in slots[key]['sources']:slots[key]['sources'].append(entry['source'])
                else:
                    slots[key]['alternatives'].append({'topic':entry['topic'],'subtopic':entry['subtopic'],'source':entry['source']})
    mid = stable(f'{school}:{grade}:{subject}')
    cid = stable(f'curriculum:{mid}')
    if not db.scalar(select(curricula.c.id).where(curricula.c.id == cid, curricula.c.tenant_id == school)):
        db.execute(curricula.insert().values(id=cid,tenant_id=school,name=f'{grade} {subject} master scheme',country='Uganda',version='Uploaded schemes v1'))
    previous = db.execute(select(masters).where(masters.c.id == mid, masters.c.tenant_id == school)).mappings().first()
    if previous:
        owned_topics = select(topics.c.id).where(topics.c.tenant_id == school,topics.c.curriculum_id == cid)
        db.execute(mappings.update().where(mappings.c.tenant_id == school,mappings.c.topic_id.in_(owned_topics)).values(review_status='rejected'))
    lessons=[]
    for key, entry in sorted(slots.items()):
        digest=hashlib.sha256(entry['signature'].encode()).hexdigest()[:20]
        tid=stable(f'topic:{mid}:{key}:{digest}')
        oid=stable(f'outcome:{tid}')
        source=entry['sources'][0]
        values={'tenant_id':school,'curriculum_id':cid,'level':'Primary' if grade.startswith('P') else 'School',
            'grade':grade,'subject':subject,'unit':entry['topic'][:200],'title':entry['subtopic'][:300],'kind':'subtopic',
            'term':key[0],'week':key[1],'sequence':key[0]*10000+key[1]*100+key[2], 'prerequisites':[],
            'source_uri':source['source_uri'],'source_license':source['license'][:160]}
        if not db.scalar(select(topics.c.id).where(topics.c.id == tid,topics.c.tenant_id == school)):
            db.execute(topics.insert().values(id=tid,**values))
            db.execute(outcomes.insert().values(id=oid,tenant_id=school,curriculum_id=cid,code=f'{grade}-T{key[0]}W{key[1]}L{key[2]}-{digest[:6]}',description='; '.join(entry['objectives'])))
            db.execute(mappings.insert().values(id=stable(f'mapping:{tid}'),tenant_id=school,topic_id=tid,outcome_id=oid,required=1,origin='enrichment',review_status='approved',revision=1,concepts=[entry['subtopic']],source_uri=source['source_uri'],source_license=source['license'][:160]))
        else:
            db.execute(topics.update().where(topics.c.id==tid,topics.c.tenant_id==school).values(**values))
            db.execute(outcomes.update().where(outcomes.c.id==oid,outcomes.c.tenant_id==school).values(description='; '.join(entry['objectives'])))
            db.execute(mappings.update().where(mappings.c.topic_id==tid,mappings.c.tenant_id==school).values(review_status='approved',concepts=[entry['subtopic']],source_uri=source['source_uri'],source_license=source['license'][:160]))
        lessons.append({k:v for k,v in entry.items() if k not in ('source','signature')}|{'topic_id':str(tid),'outcome_id':str(oid)})
    terms=sorted({l['term'] for l in lessons})
    gaps={str(term):[w for w in range(1,max([l['week'] for l in lessons if l['term']==term])+1) if not any(l['term']==term and l['week']==w for l in lessons)] for term in terms}
    body={'lessons':lessons,'source_count':len({s['version_id'] for l in lessons for s in l['sources']}),
        'missing_terms':[t for t in (1,2,3) if t not in terms], 'missing_weeks':gaps,
        'conflict_count':sum(bool(l['alternatives']) for l in lessons),'warnings':list(dict.fromkeys(warnings)),
        'basis':'Uploaded schemes; source-derived planning targets, not official curriculum endorsement.'}
    if previous:db.execute(masters.update().where(masters.c.id==mid,masters.c.tenant_id==school).values(body=body))
    else:db.execute(masters.insert().values(id=mid,tenant_id=school,grade=grade,subject=subject,curriculum_id=cid,body=body))
    db.commit()
    return mid


def selection(db, school, grade, subject, term, week=None, lesson=None):
    master=db.execute(select(masters).where(masters.c.tenant_id==school,masters.c.grade==grade_name(grade),masters.c.subject==subject_name(subject))).mappings().first()
    if not master:return None,[]
    entries=[l for l in active_body(db,school,master)['lessons'] if l['term']==term and (week is None or l['week']==week) and (lesson is None or l['lesson']==lesson)]
    return master,entries


def schedule_options(db,school,grade,subject):
    master=db.execute(select(masters).where(masters.c.tenant_id==school,masters.c.grade==grade,masters.c.subject==subject)).mappings().first()
    if not master:return []
    grouped=defaultdict(lambda:defaultdict(list))
    for row in active_body(db,school,master)['lessons']:
        grouped[row['term']][row['week']].append({k:row[k] for k in ('lesson','topic','subtopic','topic_id','inferred')}|{'conflicts':len(row['alternatives'])})
    return [{'term':term,'weeks':[{'week':week,'lessons':sorted(rows,key=lambda r:r['lesson'])} for week,rows in sorted(weeks.items())]} for term,weeks in sorted(grouped.items())]


def source_passages(db,school,topic_id,outcome_ids):
    """Return actual persisted scheme blocks for generated lesson targets."""
    found=[]
    for master in db.execute(select(masters).where(masters.c.tenant_id==school)).mappings():
        found.extend(l for l in active_body(db,school,master)['lessons'] if l['topic_id']==str(topic_id))
    result=[]
    for lesson in found:
        for ref in lesson['sources']:
            row=db.execute(select(blocks.c.id,blocks.c.text,blocks.c.page).join(extractions,(extractions.c.id==blocks.c.extraction_id)&(extractions.c.tenant_id==school)).where(blocks.c.id==UUID(ref['block_id']),blocks.c.tenant_id==school,extractions.c.resource_version_id==UUID(ref['version_id']))).mappings().first()
            if not row or normalized(ref['quote']) not in normalized(row['text']):continue
            for oid in outcome_ids:
                eid=stable(f'evidence:{school}:{oid}:{row["id"]}')
                provenance={'source_uri':ref['source_uri'],'license':ref['license'],'page':row['page'],'resource_version_id':ref['version_id'],'access_approved':True,'source_kind':'uploaded_scheme'}
                if not db.scalar(select(evidence.c.id).where(evidence.c.id==eid,evidence.c.tenant_id==school)):
                    db.execute(evidence.insert().values(id=eid,tenant_id=school,content_block_id=row['id'],outcome_id=oid,quote=ref['quote'],provenance=provenance))
                result.append({'id':eid,'outcome_id':oid,'quote':ref['quote'],'source_title':ref['title'],'source_uri':ref['source_uri'],'license':ref['license']})
    return result
