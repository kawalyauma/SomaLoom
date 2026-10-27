"""Generate reusable image prompts, import images, and attach them as teacher-supplied assets."""
from copy import deepcopy
from io import BytesIO
from uuid import UUID,uuid4
import hashlib
from fastapi import APIRouter,Depends,HTTPException,UploadFile,File,Form,Response,Query
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select,func
from sqlalchemy.orm import Session
from app.auth.security import current_user,require_roles
from app.core.database import get_db
from app.core.models import User,generations,documents,versions
from app.core.storage import configured_store
from services.images.models import requests

router=APIRouter(prefix='/image-requests',tags=['image workspace'])

def school(user):
    if not user.tenant_id:raise HTTPException(403,'School membership required')
    return user.tenant_id

def owned(db,user,identifier,edit=False):
    row=db.execute(select(requests).where(requests.c.id==identifier,requests.c.tenant_id==school(user))).mappings().first()
    if not row or (edit and user.role!='school_admin' and row['requested_by']!=user.id):raise HTTPException(404,'Image request not found')
    return row

def view(row):
    meta=row['metadata']
    return {'id':row['id'],'title':row['title'],'prompt':row['prompt'],'status':row['status'],'created_at':row['created_at'],'generation_id':row['generation_job_id'],'metadata':{k:v for k,v in meta.items() if k not in ('object_key','assets')},'image_url':f'/api/v1/image-requests/{row["id"]}/content?sha={meta.get("sha256","")}' if meta.get('object_key') else None}

class PromptInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=2,max_length=250)
    description:str=Field(min_length=5,max_length=4000)
    grade:str=Field(default='',max_length=80)
    subject:str=Field(default='',max_length=120)
    style:str=Field(default='labelled diagram',max_length=80)
    generation_id:UUID|None=None

@router.get('')
def list_images(user:User=Depends(current_user),db:Session=Depends(get_db)):
    rows=db.execute(select(requests).where(requests.c.tenant_id==school(user)).order_by(requests.c.created_at.desc()).limit(100)).mappings().all()
    return {'items':[view(r) for r in rows]}

@router.post('',status_code=201)
def create_prompt(data:PromptInput,user:User=Depends(require_roles('teacher','school_admin')),db:Session=Depends(get_db)):
    scope={}
    if data.generation_id:
        value=db.scalar(select(generations.c.parameters).where(generations.c.id==data.generation_id,generations.c.tenant_id==school(user)))
        if value is None:raise HTTPException(404,'Resource request not found')
        scope=value.get('request',{}).get('options',{}).get('planning_scope',{})
    context=' '.join(filter(None,[scope.get('class') or data.grade,scope.get('subject') or data.subject]))
    prompt=f'Create a clear educational {data.style} for {context or "a school lesson"}.\n\nSubject of the image: {data.title}\nDetails: {data.description}\n\nUse an uncluttered white background, high resolution suitable for a printed page, readable labels, and accurate proportions. Include only labels required by the description. Do not add a watermark, logo or decorative text. Check mathematical and geographic details. Leave room for a caption. The illustration will be reviewed by the teacher.'
    identifier=uuid4();db.execute(requests.insert().values(id=identifier,tenant_id=school(user),requested_by=user.id,generation_job_id=data.generation_id,title=data.title,prompt=prompt,status='prompt_ready',metadata={'description':data.description,'grade':context,'style':data.style}));db.commit()
    return view(owned(db,user,identifier))

@router.get('/{identifier}')
def detail(identifier:UUID,user:User=Depends(current_user),db:Session=Depends(get_db)):return view(owned(db,user,identifier))

@router.post('/{identifier}/import')
async def import_image(identifier:UUID,file:UploadFile=File(...),credit:str=Form('',max_length=500),user:User=Depends(require_roles('teacher','school_admin')),db:Session=Depends(get_db)):
    row=owned(db,user,identifier,True);raw=await file.read(10*1024*1024+1)
    if len(raw)>10*1024*1024:raise HTTPException(413,'Use an image smaller than 10 MB')
    from PIL import Image,UnidentifiedImageError
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in ('PNG','JPEG','WEBP') or image.width*image.height>15_000_000:raise ValueError('image_limit')
            image.load();width,height=image.size
            clean=image.convert('RGBA' if 'A' in image.getbands() else 'RGB');output=BytesIO();clean.save(output,format='PNG');raw=output.getvalue()
    except (ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombError):raise HTTPException(422,'Use a valid PNG, JPEG or WebP image up to 15 megapixels') from None
    if len(raw)>10*1024*1024:raise HTTPException(413,'The imported image exceeds the print size limit')
    sha=hashlib.sha256(raw).hexdigest();key=f'image-requests/{identifier}/{uuid4()}.png';configured_store().put(school(user),key,raw)
    assets=dict(row['metadata'].get('assets',{}));assets[sha]={'object_key':key,'credit':credit}
    metadata={**row['metadata'],'assets':assets,'object_key':key,'sha256':sha,'width':width,'height':height,'credit':credit,'teacher_supplied':True}
    db.execute(requests.update().where(requests.c.id==identifier,requests.c.tenant_id==school(user)).values(status='imported',metadata=metadata));db.commit()
    return view(owned(db,user,identifier))

@router.get('/{identifier}/content')
def content(identifier:UUID,sha:str|None=Query(None,pattern='^[a-f0-9]{64}$'),user:User=Depends(current_user),db:Session=Depends(get_db)):
    row=owned(db,user,identifier)
    if not row['metadata'].get('object_key'):raise HTTPException(404,'Import an image first')
    asset=row['metadata'].get('assets',{}).get(sha) if sha else row['metadata']
    if not asset:raise HTTPException(404,'Image version not found')
    return Response(configured_store().get(school(user),asset['object_key']),media_type='image/png',headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, max-age=60','Content-Security-Policy':'sandbox'})

class AttachInput(BaseModel):
    document_id:UUID

@router.post('/{identifier}/attach')
def attach(identifier:UUID,data:AttachInput,user:User=Depends(require_roles('teacher','school_admin')),db:Session=Depends(get_db)):
    row=owned(db,user,identifier)
    if row['status']!='imported':raise HTTPException(409,'Import an image first')
    document=db.execute(select(documents).where(documents.c.id==data.document_id,documents.c.tenant_id==school(user)).with_for_update()).mappings().first()
    if not document:raise HTTPException(404,'Document not found')
    version=db.execute(select(versions).where(versions.c.document_id==data.document_id,versions.c.tenant_id==school(user)).order_by(versions.c.version.desc()).limit(1)).mappings().first()
    if not version:raise HTTPException(409,'Document has no saved content')
    body=deepcopy(version['body']);ref='image-request:'+str(identifier)+':'+row['metadata']['sha256']
    if not any(b.get('asset_ref')==ref for s in body.get('sections',[]) for b in s.get('blocks',[])):
        body.setdefault('sections',[]).append({'title':row['title'],'blocks':[{'id':str(uuid4()),'type':'figure','asset_ref':ref,'caption':row['title'],'citations':[],'teacher_supplied':True}]})
        body['review_state']='awaiting_review'
        db.execute(versions.insert().values(id=uuid4(),tenant_id=school(user),document_id=data.document_id,version=version['version']+1,body=body));db.commit()
    return {'document_id':data.document_id,'image_id':identifier}
