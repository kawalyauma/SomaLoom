"""Build tenant-owned lesson/week/term books from saved, source-mapped revisions."""
from copy import deepcopy
from uuid import UUID

from sqlalchemy import select

from app.core.models import documents, generations, versions, reviews
from services.schemes.schema import grade_name as normalize_class, subject_name as normalize_subject
from services.schemes.service import active_body
from services.schemes.models import masters
from services.rendering.document import DocumentValidationError


class ScopeNotReady(DocumentValidationError):
    pass


def catalog(db, tenant):
    plans = db.execute(select(masters).where(masters.c.tenant_id == tenant)).mappings().all()
    docs = db.execute(select(documents, generations.c.parameters).join(
        generations, (generations.c.id == documents.c.generation_job_id)
        & (generations.c.tenant_id == documents.c.tenant_id)
    ).where(documents.c.tenant_id == tenant, documents.c.document_type == 'lesson_notes')
    .order_by(documents.c.created_at.desc())).mappings().all()
    result = []
    for plan in plans:
        slots = active_body(db, tenant, plan).get('lessons', [])
        for term in sorted({int(s['term']) for s in slots}):
            lessons = []
            for slot in sorted((s for s in slots if int(s['term']) == term), key=lambda s:(s['week'], s['lesson'])):
                candidates = []
                for doc in docs:
                    scope = (doc['parameters'] or {}).get('request', {}).get('options', {}).get('planning_scope', {})
                    if (normalize_class(scope.get('class', '')) != normalize_class(plan['grade'])
                        or normalize_subject(scope.get('subject', '')) != normalize_subject(plan['subject'])
                        or scope.get('term') != term or scope.get('week') != slot['week']
                        or scope.get('lesson') not in (None, slot['lesson'])):
                        continue
                    # Never relabel old content with a changed master scheme's outcomes.
                    if str(slot['topic_id']) not in (doc['parameters'] or {}).get('request', {}).get('topic_ids', []):
                        continue
                    candidates.append((scope.get('lesson') is not None, doc))
                candidates.sort(key=lambda x:x[0], reverse=True)  # stable newest within specificity
                chosen = candidates[0][1] if candidates else None
                lessons.append({'week':slot['week'], 'lesson':slot['lesson'], 'topic':slot['topic'],
                    'subtopic':slot['subtopic'], 'outcome_id':str(slot['outcome_id']),
                    'document_id':str(chosen['id']) if chosen else None,
                    'document_lessons': ((chosen['parameters'] or {}).get('request', {}).get('options', {}).get('planning_scope', {}).get('lessons', []) if chosen else []), 'inferred':bool(slot.get('inferred'))})
            result.append({'grade':plan['grade'], 'subject':plan['subject'], 'term':term,
                           'lessons':lessons, 'available':sum(bool(s['document_id']) for s in lessons),
                           'expected':len(lessons)})
    return result


def select_body(body, outcome_ids, *, whole_document):
    """Subset by explicit outcome links; never pretend a combined paragraph is one lesson."""
    if whole_document:
        return deepcopy(body)
    result = deepcopy(body)
    sections = []
    administrative = {'introduction','outcomes','learning_outcomes','prior_knowledge','vocabulary',
                       'summary','references','review','teacher_review','misconceptions'}
    for section in result.get('sections', []):
        blocks = []
        for block in section.get('blocks', []):
            linked = set(map(str, block.get('outcome_ids', [])))
            if not linked.intersection(outcome_ids):
                continue
            if not linked <= outcome_ids:
                if section.get('key') not in administrative and block.get('type') not in {'heading','page_break','reference'}:
                    raise ScopeNotReady('This draft combines several lessons in one block. Split those lessons before downloading individually.')
                continue
            blocks.append(block)
        if blocks:
            titles={'learning_outcomes':'Learning outcomes','explanation':'Lesson notes','examples':'Worked examples','activities':'Activities','summary':'Summary','revision':'Practice and revision','prior_knowledge':'Before you begin','vocabulary':'Key words','misconceptions':'Common mistakes'}
            sections.append({**section, 'title':titles.get(section.get('key'),section.get('title','')), 'blocks':blocks})
    if not any(b.get('type') in {'paragraph','question','activity','equation','table'} for s in sections for b in s['blocks']):
        raise ScopeNotReady('This lesson has no separately mapped content yet. Download the full week or finish its lesson mapping.')
    result['sections'] = sections
    return result


def assemble(db, tenant, grade, subject, term, week=None, lesson=None, approved=False):
    plans = catalog(db, tenant)
    plan = next((p for p in plans if normalize_class(p['grade']) == normalize_class(grade)
                 and normalize_subject(p['subject']) == normalize_subject(subject) and p['term'] == term), None)
    if not plan:
        raise ScopeNotReady('No source scheme is available for this class, subject and term.')
    selected = [s for s in plan['lessons'] if (week is None or s['week'] == week)
                and (lesson is None or s['lesson'] == lesson)]
    if not selected:
        raise ScopeNotReady('The selected lesson or week is not in the source scheme.')
    missing = [f"Week {s['week']} lesson {s['lesson']}" for s in selected if not s['document_id']]
    if missing:
        raise ScopeNotReady('Notes are still missing for '+', '.join(missing[:12])+('.' if len(missing)<=12 else f' and {len(missing)-12} more.'))
    sections, evidence, manifest = [], set(), []
    groups = {}
    for slot in selected:
        groups.setdefault(slot['document_id'], []).append(slot)
    for did, slots in groups.items():
        row = db.execute(select(versions).where(versions.c.document_id == UUID(did), versions.c.tenant_id == tenant)
                         .order_by(versions.c.version.desc()).limit(1)).mappings().first()
        if not row:
            raise ScopeNotReady('A saved document has no revision. Finish saving it first.')
        decision = db.scalar(select(reviews.c.decision).where(reviews.c.document_version_id == row['id'],
            reviews.c.tenant_id == tenant).order_by(reviews.c.created_at.desc()).limit(1))
        if approved and decision != 'approved':
            raise ScopeNotReady(f"Week {slots[0]['week']} needs educator approval before a final PDF can be downloaded.")
        original_lessons = {s['lesson'] for s in slots[0]['document_lessons']}
        body = select_body(row['body'], {s['outcome_id'] for s in slots},
                           whole_document={s['lesson'] for s in slots} == original_lessons)
        chapter = f"Week {slots[0]['week']}"
        if len(slots) == 1:
            chapter += f" · Lesson {slots[0]['lesson']}: {slots[0]['subtopic']}"
        sections.append({'title':chapter,'chapter':True,'blocks':[]})
        # Namespace IDs to avoid collisions when assembling separate revisions.
        for s in body.get('sections', []):
            s = deepcopy(s)
            for b in s['blocks']:
                b['id'] = str(row['id'])+':'+b['id']
            sections.append(s)
        evidence.update(body.get('evidence_ids', []))
        manifest.append({'document_id':did,'version_id':str(row['id']),'version':row['version'],
                         'week':slots[0]['week'],'lessons':[s['lesson'] for s in slots], 'approved':decision=='approved'})
    label = f"{plan['grade']} {plan['subject']} · Term {term}"
    if week is not None:
        label += f' · Week {week}'
    if lesson is not None:
        label += f' · Lesson {lesson}'
    return {'title':label, 'review_state':'approved' if approved else 'draft',
            'evidence_ids':sorted(evidence), 'body':{'sections':sections,'evidence_ids':sorted(evidence)},
            'export_scope':{'grade':plan['grade'],'subject':plan['subject'],'term':term,'week':week,'lesson':lesson},
            'source_versions':manifest}
