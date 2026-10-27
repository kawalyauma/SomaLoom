"""Persistent ten-year Telegram archive, ten concurrent streamed downloads per batch."""
import asyncio
import hashlib
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

BATCH_SIZE = 10
PART_SIZE = 8 * 1024 * 1024
BUCKET = 'somaloom-telegram-482146446766-eu-central-1'


def history_cutoff(now=None):
    now = now or datetime.now(timezone.utc)
    try:
        return now.replace(year=now.year - 10)
    except ValueError:
        return now.replace(year=now.year - 10, day=28)


async def run_batch(items, download):
    """The scheduling boundary itself enforces the requested ten-resource limit."""
    return await asyncio.gather(*(download(item) for item in items[:BATCH_SIZE]), return_exceptions=True)


class DownloadEngine:
    def __init__(self, root, token):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'downloads.sqlite'
        self.guard = threading.RLock()
        self.token = token
        self.client = None
        self.s3 = None
        self.loop = None
        self.ready = False
        self.paused_until = 0
        self.current_batch = 0
        self.max_batch_observed = 0
        self.entities = {}
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS sources (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, link TEXT NOT NULL,
              title TEXT, active INTEGER NOT NULL DEFAULT 1, cutoff TEXT NOT NULL,
              backfill_cursor INTEGER NOT NULL DEFAULT 0, live_cursor INTEGER NOT NULL DEFAULT 0,
              backfill_done INTEGER NOT NULL DEFAULT 0, scanned INTEGER NOT NULL DEFAULT 0,
              next_scan REAL NOT NULL DEFAULT 0, next_live REAL NOT NULL DEFAULT 0,
              last_batch REAL NOT NULL DEFAULT 0, error TEXT, updated REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS files (
              id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, source_id TEXT NOT NULL,
              message_id INTEGER NOT NULL, posted_at TEXT NOT NULL,
              filename TEXT NOT NULL, mime TEXT, declared_size INTEGER NOT NULL DEFAULT 0,
              object_key TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
              size INTEGER NOT NULL DEFAULT 0, checksum TEXT, attempts INTEGER NOT NULL DEFAULT 0,
              retry_at REAL NOT NULL DEFAULT 0, error TEXT, published INTEGER NOT NULL DEFAULT 0,
              library_status TEXT, resource_id TEXT, updated REAL NOT NULL,
              UNIQUE(source_id, message_id));
            CREATE INDEX IF NOT EXISTS archive_pending ON files(state, retry_at);
            CREATE INDEX IF NOT EXISTS archive_tenant ON files(tenant_id,source_id,message_id);
            ''')
            db.execute("UPDATE files SET state='pending' WHERE state='downloading'")
        self.path.chmod(0o600)

    def db(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA busy_timeout=20000')
        return db

    def sync_sources(self, sources):
        now = time.time()
        cutoff = history_cutoff().isoformat()
        rows = []
        for item in sources:
            source_id, tenant_id = str(UUID(item['id'])), str(UUID(item['tenant_id']))
            link = item['link']
            if not isinstance(link, str) or not link.startswith('https://t.me/') or len(link) > 1000:
                raise ValueError('invalid_link')
            rows.append((source_id, tenant_id, link, str(item.get('title') or '')[:500], int(item.get('active', True)), cutoff, now))
        with self.guard, self.db() as db:
            db.execute('UPDATE sources SET active=0')
            for row in rows:
                old = db.execute('SELECT tenant_id,link FROM sources WHERE id=?',(row[0],)).fetchone()
                if old and (old['tenant_id'] != row[1] or old['link'] != row[2]):
                    raise ValueError('source_identity_changed')
                db.execute('''INSERT INTO sources(id,tenant_id,link,title,active,cutoff,updated) VALUES(?,?,?,?,?,?,?)
                  ON CONFLICT(id) DO UPDATE SET title=excluded.title,active=excluded.active,updated=excluded.updated''',row)
        return {'synced': len(rows), 'history_years': 10, 'batch_size': BATCH_SIZE}

    def status(self, tenant):
        tenant = str(UUID(tenant))
        with self.db() as db:
            sources = [dict(s) for s in db.execute('SELECT * FROM sources WHERE tenant_id=? ORDER BY updated DESC',(tenant,))]
            for src in sources:
                counts = db.execute('''SELECT count(*) discovered,
                  sum(CASE WHEN state='downloaded' THEN 1 ELSE 0 END) downloaded,
                  sum(CASE WHEN state='downloading' THEN 1 ELSE 0 END) downloading,
                  sum(CASE WHEN state='unavailable' THEN 1 ELSE 0 END) unavailable,
                  sum(CASE WHEN state='pending' AND retry_at>? THEN 1 ELSE 0 END) retrying,
                  sum(CASE WHEN state='downloaded' THEN size ELSE 0 END) bytes,
                  sum(CASE WHEN library_status='imported' THEN 1 ELSE 0 END) "indexed"
                  FROM files WHERE tenant_id=? AND source_id=?''',(time.time(),tenant,src['id'])).fetchone()
                src.update({k:int(counts[k] or 0) for k in counts.keys()})
                src['status'] = 'paused' if not src['active'] else 'rate_limited' if self.paused_until>time.time() else 'watching' if src['backfill_done'] and src['downloaded']+src['unavailable']==src['discovered'] else 'downloading' if src['downloading'] else 'scanning_history'
        with self.db() as db:
            summary=dict(db.execute("""SELECT count(*) discovered,
                sum(CASE WHEN state='downloaded' THEN 1 ELSE 0 END) downloaded,
                sum(CASE WHEN state='downloaded' AND coalesce(library_status,'')!='quarantined' THEN 1 ELSE 0 END) available,
                sum(CASE WHEN state='pending' THEN 1 ELSE 0 END) pending,
                sum(CASE WHEN state='downloading' THEN 1 ELSE 0 END) downloading,
                sum(CASE WHEN state='unavailable' THEN 1 ELSE 0 END) unavailable,
                sum(CASE WHEN library_status='quarantined' THEN 1 ELSE 0 END) quarantined,
                sum(CASE WHEN state='downloaded' THEN size ELSE 0 END) bytes
                FROM files WHERE tenant_id=?""",(tenant,)).fetchone())
            summary={k:int(v or 0) for k,v in summary.items()}
            physical=db.execute("SELECT count(DISTINCT object_key),coalesce(sum(size),0) FROM (SELECT object_key,max(size) size FROM files WHERE tenant_id=? AND state='downloaded' GROUP BY object_key)",(tenant,)).fetchone()
            summary.update(unique_files=physical[0],unique_bytes=physical[1])
            formats=[dict(row) for row in db.execute("""SELECT coalesce(mime,'application/octet-stream') mime,count(*) discovered,
                sum(CASE WHEN state='downloaded' THEN 1 ELSE 0 END) downloaded,
                sum(CASE WHEN state='downloaded' THEN size ELSE 0 END) bytes
                FROM files WHERE tenant_id=? GROUP BY mime ORDER BY count(*) DESC""",(tenant,))]
            recent=[dict(row) for row in db.execute("""SELECT date(updated,'unixepoch') day,count(*) downloaded,sum(size) bytes
                FROM files WHERE tenant_id=? AND state='downloaded' AND updated>=? GROUP BY day ORDER BY day""",(tenant,time.time()-14*86400))]
        return {'summary':summary,'formats':formats,'recent':recent,'sources':sources,'batch_size':BATCH_SIZE,'active_downloads':self.current_batch,'max_batch_observed':self.max_batch_observed,'retry_at':self.paused_until or None,'account_connected':self.ready,'history_years':10}

    def files(self, tenant=None, source_id=None, page=1, ready=False, file_id=None):
        clauses=[];args=[]
        if tenant:clauses.append('tenant_id=?');args.append(str(UUID(tenant)))
        if source_id:clauses.append('source_id=?');args.append(str(UUID(source_id)))
        if file_id:clauses.append('id=?');args.append(str(UUID(file_id)))
        if ready:clauses.extend(["state='downloaded'",'published=0','source_id IN (SELECT id FROM sources WHERE active=1)'])
        where=' WHERE '+' AND '.join(clauses) if clauses else ''
        page=max(1,int(page))
        with self.db() as db:
            total=db.execute('SELECT count(*) FROM files'+where,args).fetchone()[0]
            rows=db.execute('SELECT * FROM files'+where+' ORDER BY posted_at DESC,message_id DESC LIMIT 10 OFFSET ?',[*args,(page-1)*10]).fetchall()
        return {'items':[dict(r) for r in rows],'page':page,'page_size':10,'total':total}

    def acknowledge(self, items):
        with self.db() as db:
            for item in items[:10]:
                db.execute("UPDATE files SET published=1,library_status=?,resource_id=?,updated=? WHERE id=? AND tenant_id=? AND source_id=? AND state='downloaded'",(item['status'],item.get('resource_id'),time.time(),str(UUID(item['id'])),str(UUID(item['tenant_id'])),str(UUID(item['source_id']))))
        return {'acknowledged':len(items[:10])}

    def file_url(self, tenant, file_id):
        tenant=str(UUID(tenant));file_id=str(UUID(file_id))
        with self.db() as db:
            row=db.execute("SELECT * FROM files WHERE id=? AND tenant_id=? AND state='downloaded'",(file_id,tenant)).fetchone()
        if not row or row['library_status']=='quarantined':return None
        if not row['object_key'].startswith(tenant+'/telegram-archive/'):
            raise ValueError('invalid_key')
        name=row['filename'].replace('"','_').replace('\r','').replace('\n','')
        disposition="attachment; filename*=UTF-8''"+__import__('urllib.parse',fromlist=['quote']).quote(name)
        url=self.s3.generate_presigned_url('get_object',Params={'Bucket':BUCKET,'Key':row['object_key'],'ResponseContentDisposition':disposition,'ResponseContentType':'application/octet-stream'},ExpiresIn=120)
        return {'url':url,'size':row['size'],'filename':row['filename'],'checksum':row['checksum']}

    async def entity(self, link):
        if link not in self.entities:
            if '/+' in link:
                from telethon.tl.functions.messages import CheckChatInviteRequest
                from telethon.tl.types import ChatInviteAlready
                result=await self.client(CheckChatInviteRequest(link.split('/+')[-1]))
                if not isinstance(result,ChatInviteAlready):raise ValueError('group_inaccessible')
                self.entities[link]=result.chat
            else:self.entities[link]=await self.client.get_entity(link.rsplit('/',1)[-1])
        return self.entities[link]

    def record_message(self, source, message):
        f=message.file
        media=message.document or message.photo
        kind='document' if message.document else 'photo'
        size=int(f.size or 0)
        filename=Path((f.name or f'telegram-{message.id}{f.ext or ".bin"}').replace('\\','/')).name[:240]
        key=f"{source['tenant_id']}/telegram-archive/{kind}-{media.id}-{size}/original"
        with self.db() as db:
            db.execute('''INSERT OR IGNORE INTO files(id,tenant_id,source_id,message_id,posted_at,filename,mime,declared_size,object_key,updated)
             VALUES(?,?,?,?,?,?,?,?,?,?)''',(str(uuid4()),source['tenant_id'],source['id'],message.id,message.date.isoformat(),filename,f.mime_type or 'application/octet-stream',size,key,time.time()))

    async def discover(self, source, live=False):
        from telethon.errors import FloodWaitError
        try:
            entity=await self.entity(source['link'])
            cutoff=datetime.fromisoformat(source['cutoff'])
            kwargs={'limit':100,'wait_time':1}
            if live:kwargs.update(min_id=source['live_cursor'],reverse=True)
            elif source['backfill_cursor']:kwargs['offset_id']=source['backfill_cursor']
            messages=[m async for m in self.client.iter_messages(entity,**kwargs)]
            latest=max((m.id for m in messages),default=0)
            cursor=source['backfill_cursor'];done=False
            for message in messages:
                if message.date<cutoff:
                    if not live:done=True;break
                    continue
                if message.document or message.photo:self.record_message(source,message)
                if not live:cursor=message.id
            if not live and len(messages)<100:done=True
            with self.db() as db:
                if live:db.execute('UPDATE sources SET live_cursor=max(live_cursor,?),next_live=?,error=NULL WHERE id=?',(latest,time.time()+30,source['id']))
                else:db.execute('UPDATE sources SET backfill_cursor=?,live_cursor=CASE WHEN live_cursor=0 THEN ? ELSE live_cursor END,backfill_done=?,scanned=scanned+?,next_scan=?,error=NULL WHERE id=?',(cursor,latest,int(done),len(messages),time.time()+5,source['id']))
        except FloodWaitError as e:
            self.paused_until=time.time()+int(e.seconds)+2
        except Exception as e:
            with self.db() as db:db.execute('UPDATE sources SET error=?,next_scan=?,next_live=? WHERE id=?',('Telegram history unavailable; automatic retry scheduled ('+type(e).__name__+')',time.time()+300,time.time()+300,source['id']))

    def claim(self):
        now=time.time()
        with self.guard,self.db() as db:
            source=db.execute("SELECT s.id FROM sources s JOIN files f ON f.source_id=s.id WHERE s.active=1 AND f.state='pending' AND f.retry_at<=? GROUP BY s.id ORDER BY s.last_batch LIMIT 1",(now,)).fetchone()
            if not source:return []
            candidates=db.execute("SELECT f.*,s.link FROM files f JOIN sources s ON s.id=f.source_id WHERE f.source_id=? AND f.state='pending' AND f.retry_at<=? ORDER BY f.message_id DESC LIMIT 1000",(source['id'],now)).fetchall()
            rows=[];seen=set()
            for row in candidates:
                if row['object_key'] in seen:continue
                seen.add(row['object_key']);rows.append(row)
                if len(rows)==BATCH_SIZE:break
            for row in rows:db.execute("UPDATE files SET state='downloading',attempts=attempts+1,updated=? WHERE id=?",(now,row['id']))
            db.execute('UPDATE sources SET last_batch=? WHERE id=?',(now,source['id']))
            return [dict(r) for r in rows]

    async def media_chunks(self, message):
        if message.photo:
            # Telegram photos require an explicit thumbnail location; document
            # locations are resolved directly by Telethon's streaming iterator.
            from telethon.tl.types import InputPhotoFileLocation
            photo=message.photo
            size=self.client._get_thumb(photo.sizes, -1)
            if hasattr(size,'bytes'):
                from telethon import utils
                yield utils.stripped_photo_to_jpg(size.bytes) if type(size).__name__=='PhotoStrippedSize' else size.bytes
                return
            location=InputPhotoFileLocation(id=photo.id,access_hash=photo.access_hash,file_reference=photo.file_reference,thumb_size=size.type)
            async for chunk in self.client.iter_download(location,request_size=524288,dc_id=photo.dc_id):
                yield chunk
        else:
            # Use the resolved document object: MessageMediaWebPage wrappers
            # are not valid InputFileLocations in Telethon 1.45.
            async for chunk in self.client.iter_download(message.document,request_size=524288):
                yield chunk

    async def download(self, item):
        from telethon.errors import FloodWaitError
        upload_id=None
        key=item['object_key']
        try:
            # A forwarded Telegram file is stored once per school; retain every source message.
            with self.db() as db:known=db.execute("SELECT size,checksum FROM files WHERE object_key=? AND state='downloaded' LIMIT 1",(key,)).fetchone()
            if known:
                size,checksum=known['size'],known['checksum']
            else:
                head=None
                try:head=await asyncio.to_thread(self.s3.head_object,Bucket=BUCKET,Key=key)
                except Exception:pass
                if head:
                    obj=await asyncio.to_thread(self.s3.get_object,Bucket=BUCKET,Key=key)
                    sha=hashlib.sha256();size=0
                    while True:
                        chunk=await asyncio.to_thread(obj['Body'].read,1024*1024)
                        if not chunk:break
                        size+=len(chunk);sha.update(chunk)
                    obj['Body'].close();checksum=sha.hexdigest()
                else:
                    entity=await self.entity(item['link'])
                    message=await self.client.get_messages(entity,ids=item['message_id'])
                    if not message or not (message.document or message.photo):
                        with self.db() as db:db.execute("UPDATE files SET state='unavailable',error='Telegram no longer provides this file',updated=? WHERE id=?",(time.time(),item['id']))
                        return
                    started=await asyncio.to_thread(self.s3.create_multipart_upload,Bucket=BUCKET,Key=key,ServerSideEncryption='AES256',ContentType='application/octet-stream')
                    upload_id=started['UploadId'];parts=[];buffer=bytearray();sha=hashlib.sha256();size=0
                    async for chunk in self.media_chunks(message):
                        with self.db() as db:active=db.execute('SELECT active FROM sources WHERE id=?',(item['source_id'],)).fetchone()[0]
                        if not active:raise RuntimeError('source_paused')
                        sha.update(chunk);size+=len(chunk);buffer.extend(chunk)
                        if len(buffer)>=PART_SIZE:
                            part=await asyncio.to_thread(self.s3.upload_part,Bucket=BUCKET,Key=key,UploadId=upload_id,PartNumber=len(parts)+1,Body=bytes(buffer))
                            parts.append({'PartNumber':len(parts)+1,'ETag':part['ETag']});buffer.clear()
                    if item['declared_size'] and size!=item['declared_size']:raise ValueError('incomplete_transfer')
                    if buffer or not parts:
                        part=await asyncio.to_thread(self.s3.upload_part,Bucket=BUCKET,Key=key,UploadId=upload_id,PartNumber=len(parts)+1,Body=bytes(buffer))
                        parts.append({'PartNumber':len(parts)+1,'ETag':part['ETag']})
                    checksum=sha.hexdigest()
                    await asyncio.to_thread(self.s3.complete_multipart_upload,Bucket=BUCKET,Key=key,UploadId=upload_id,MultipartUpload={'Parts':parts})
                    upload_id=None
            with self.db() as db:db.execute("UPDATE files SET state='downloaded',size=?,checksum=?,error=NULL,retry_at=0,updated=? WHERE id=?",(size,checksum,time.time(),item['id']))
        except Exception as e:
            if isinstance(e,FloodWaitError):self.paused_until=max(self.paused_until,time.time()+int(e.seconds)+2)
            retry=max(self.paused_until,time.time()+min(3600,15*(2**min(item['attempts'],8))))
            with self.db() as db:db.execute("UPDATE files SET state='pending',error=?,retry_at=?,updated=? WHERE id=?",('Transfer interrupted; automatic retry scheduled ('+type(e).__name__+')',retry,time.time(),item['id']))
        finally:
            if upload_id:
                try:await asyncio.to_thread(self.s3.abort_multipart_upload,Bucket=BUCKET,Key=key,UploadId=upload_id)
                except Exception:pass

    async def scheduler(self):
        while True:
            try:
                if self.paused_until>time.time():await asyncio.sleep(min(10,self.paused_until-time.time()));continue
                batch=self.claim()
                if batch:
                    self.current_batch=len(batch);self.max_batch_observed=max(self.max_batch_observed,len(batch))
                    await run_batch(batch,self.download)
                    with self.db() as db:
                        for item in batch:
                            db.execute("UPDATE files SET state='pending',retry_at=? WHERE id=? AND state='downloading'",(time.time()+30,item['id']))
                    self.current_batch=0
                else:await asyncio.sleep(3)
            except Exception:
                self.current_batch=0
                await asyncio.sleep(10)

    async def discovery_loop(self):
        while True:
            try:
                if self.paused_until>time.time():await asyncio.sleep(5);continue
                with self.db() as db:
                    backlog=db.execute("SELECT count(*) FROM files WHERE state='pending'").fetchone()[0]
                    sources=[dict(s) for s in db.execute('SELECT * FROM sources WHERE active=1 ORDER BY next_scan')]
                for source in sources:
                    if self.paused_until>time.time():break
                    if not source['backfill_done'] and source['next_scan']<=time.time() and backlog<10000:
                        await self.discover(source)
                    if source['live_cursor'] and source['next_live']<=time.time():
                        await self.discover(source,live=True)
            except Exception:pass
            await asyncio.sleep(5)

    async def startup(self):
        import boto3,fcntl
        from botocore.config import Config
        from telethon import TelegramClient
        self.lock=os.open('/srv/somaloom-data/telegram-sessions/owner.session.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        credentials=json.loads(await asyncio.to_thread(lambda:boto3.client('secretsmanager',region_name='eu-central-1').get_secret_value(SecretId='somaloom/staging/telegram-account/api')['SecretString']))
        self.s3=boto3.client('s3',region_name='eu-central-1',endpoint_url='https://s3.eu-central-1.amazonaws.com',config=Config(signature_version='s3v4'))
        self.client=TelegramClient('/srv/somaloom-data/telegram-sessions/owner.session',int(credentials['api_id']),credentials['api_hash'],receive_updates=False,connection_retries=3,request_retries=1,timeout=15,flood_sleep_threshold=0)
        await self.client.connect()
        self.ready=await self.client.is_user_authorized()
        if not self.ready:raise RuntimeError('Telegram account is not authorized')
        asyncio.create_task(self.scheduler())
        asyncio.create_task(self.discovery_loop())

    def start(self):
        self.loop=asyncio.new_event_loop()
        def run():
            asyncio.set_event_loop(self.loop)
            try:
                self.loop.run_until_complete(self.startup())
            except Exception:
                os._exit(1)
            self.loop.run_forever()
        self.thread=threading.Thread(target=run,daemon=True);self.thread.start()
        return self
