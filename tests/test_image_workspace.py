from io import BytesIO
from uuid import uuid4
from PIL import Image
from sqlalchemy import select,func
from conftest import sign_in
from app.core.models import documents,versions
from app.core.storage import LocalObjectStore
from test_generation_history import work


def test_prompts_import_and_image_attachment(client,accounts,db,monkeypatch,tmp_path):
    schools,users=accounts
    owner=next(u for u in users if u.email=='teacher0@example.org')
    gid,_=work(db,schools[0],owner,{'class':'P5','subject':'Social Studies'})
    monkeypatch.setattr('services.images.router.configured_store',lambda:LocalObjectStore(str(tmp_path)))
    monkeypatch.setattr('services.export.assets.configured_store',lambda:LocalObjectStore(str(tmp_path)))
    sign_in(client,owner.email);headers={'Origin':'http://localhost:3000'}
    response=client.post('/api/v1/image-requests',headers=headers,json={'title':'East Africa map','description':'Show the countries and their names','generation_id':str(gid)})
    assert response.status_code==201,response.text
    item=response.json();assert 'P5 Social Studies' in item['prompt'] and item['status']=='prompt_ready'
    assert client.get('/api/v1/image-requests').json()['items'][0]['id']==item['id']
    bad=client.post('/api/v1/image-requests/'+item['id']+'/import',headers=headers,files={'file':('bad.svg',b'<svg></svg>','image/svg+xml')})
    assert bad.status_code==422
    out=BytesIO();Image.new('RGB',(64,32),'white').save(out,format='PNG')
    imported=client.post('/api/v1/image-requests/'+item['id']+'/import',headers=headers,files={'file':('map.png',out.getvalue(),'image/png')},data={'credit':'Educator illustration'})
    assert imported.status_code==200,imported.text
    assert client.get(imported.json()['image_url']).headers['content-type']=='image/png'
    did=uuid4();db.execute(documents.insert().values(id=did,tenant_id=schools[0].id,generation_job_id=gid,title='P5 SST notes',document_type='lesson_notes'))
    db.execute(versions.insert().values(tenant_id=schools[0].id,document_id=did,version=1,body={'sections':[],'evidence_ids':[]}));db.commit()
    attached=client.post('/api/v1/image-requests/'+item['id']+'/attach',headers=headers,json={'document_id':str(did)})
    assert attached.status_code==200,attached.text
    row=db.execute(select(versions).where(versions.c.document_id==did).order_by(versions.c.version.desc())).mappings().first()
    assert row['version']==2 and row['body']['sections'][0]['blocks'][0]['asset_ref'].startswith('image-request:')
    from services.export.assets import resolver
    assert resolver(db,schools[0].id)(row['body']['sections'][0]['blocks'][0])['bytes']==client.get(imported.json()['image_url']).content
    client.post('/api/v1/image-requests/'+item['id']+'/attach',headers=headers,json={'document_id':str(did)})
    assert db.scalar(select(func.max(versions.c.version)).where(versions.c.document_id==did))==2
    sign_in(client,'teacher1@example.org')
    assert client.get(imported.json()['image_url']).status_code==404
    assert client.get('/api/v1/image-requests/'+item['id']).status_code==404
