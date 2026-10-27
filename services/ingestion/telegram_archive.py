"""Synchronize all connected sources and index supported downloaded originals."""
import hashlib
import logging
import time
import threading
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from app.core.database import SessionLocal
from app.core.models import sources
from app.core.queue import redis_connection
from services.ingestion.telegram_links import account_request, archive_content
from services.ingestion.library import MAX_BYTES, publish_version, validate_file, safe_filename


def sync_sources():
    with SessionLocal() as db:
        rows=db.execute(select(sources).where(sources.c.kind=='telegram')).mappings().all()
        account_sources=[r for r in rows if r['config'].get('transport')=='account']
    account_request('/sources/sync',{'sources':[{'id':str(s['id']),'tenant_id':str(s['tenant_id']),'link':s['source_uri'],'title':s['config'].get('title'),'active':s['config'].get('active',True) and s['config'].get('auto_download',True)} for s in account_sources]})
    return account_sources


def cycle():
    with SessionLocal() as db:
        account_sources=[r for r in db.execute(select(sources).where(sources.c.kind=='telegram')).mappings().all() if r['config'].get('transport')=='account']
    owned={(str(s['tenant_id']),str(s['id'])):s for s in account_sources}
    result=account_request('/files/ready',{})
    acknowledgements=[]
    for item in result.get('items',[])[:10]:
        identity=(item['tenant_id'],item['source_id'])
        source=owned.get(identity)
        if not source:continue
        ack={'id':item['id'],'tenant_id':item['tenant_id'],'source_id':item['source_id'],'status':'archived_only'}
        # Every type/size is archived. Only supported, bounded, scanned files enter extraction.
        if item['size']>MAX_BYTES:
            acknowledgements.append(ack);continue
        try:
            data=archive_content(item['tenant_id'],'telegram-account/'+item['id'])
            mime=validate_file(data)
            name=safe_filename(item['filename'],mime)
            checksum=hashlib.sha256(data).hexdigest()
            if item.get('checksum') and checksum!=item['checksum']:
                raise ValueError('archive_checksum_mismatch')
            with SessionLocal() as db:
                latest=db.execute(select(sources).where(sources.c.id==UUID(item['source_id']),sources.c.tenant_id==UUID(item['tenant_id']))).mappings().first()
                if not latest or not latest['config'].get('active',True):continue
                result=publish_version(db,UUID(item['tenant_id']),None,data,mime,name,checksum,name,source['license'],source['source_uri'].rstrip('/')+'/'+str(item['message_id']),'telegram',UUID(item['source_id']),external_object_key='telegram-account/'+item['id'])
                ack.update(status='imported',resource_id=str(result['resource_id']))
            acknowledgements.append(ack)
        except HTTPException as error:
            if error.status_code in (413,422):
                if 'antivirus' in str(error.detail).lower():ack['status']='quarantined'
                acknowledgements.append(ack)
        except Exception as error:
            logging.warning('telegram_archive_index_retry type=%s',type(error).__name__)
    if acknowledgements:account_request('/files/ack',{'items':acknowledgements})


def synchronization_loop():
    while True:
        try:
            sync_sources()
            redis_connection().set('somaloom:telegram_importer:heartbeat','active',ex=180)
        except Exception as error:
            logging.warning('telegram_archive_sync_retry type=%s',type(error).__name__)
        time.sleep(10)


def main():
    logging.basicConfig(level=logging.INFO)
    threading.Thread(target=synchronization_loop,daemon=True).start()
    while True:
        try:
            redis_connection().set('somaloom:telegram_importer:heartbeat','active',ex=180)
            cycle()
        except Exception as error:logging.warning('telegram_archive_cycle_retry type=%s',type(error).__name__)
        time.sleep(10)


if __name__=='__main__':main()
