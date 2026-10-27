import asyncio
import importlib.util
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

spec=importlib.util.spec_from_file_location('download_engine',Path(__file__).parents[1]/'infra/telegram/download_engine.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class ArchiveTests(unittest.TestCase):
    def test_calendar_ten_years(self):
        self.assertEqual(module.history_cutoff(datetime(2024,2,29,tzinfo=timezone.utc)),datetime(2014,2,28,tzinfo=timezone.utc))

    def test_exact_ten_concurrent_transfers(self):
        async def check():
            active=peak=finished=0
            async def download(item):
                nonlocal active,peak,finished
                active+=1;peak=max(peak,active)
                await asyncio.sleep(.01)
                active-=1;finished+=1
            await module.run_batch(list(range(25)),download)
            self.assertEqual((peak,finished),(10,10))
        asyncio.run(check())

    def test_restart_checkpoint_and_tenant_isolation(self):
        with tempfile.TemporaryDirectory() as root:
            engine=module.DownloadEngine(root,'test');tenant=str(uuid4());other=str(uuid4());source=str(uuid4())
            config={'id':source,'tenant_id':tenant,'link':'https://t.me/TeacherInUganda'}
            engine.sync_sources([config])
            with engine.db() as db:
                cutoff=db.execute('SELECT cutoff FROM sources').fetchone()[0]
                db.execute('UPDATE sources SET backfill_cursor=123')
                for n in range(15):
                    db.execute('INSERT INTO files(id,tenant_id,source_id,message_id,posted_at,filename,object_key,state,updated) VALUES(?,?,?,?,?,?,?,?,?)',(str(uuid4()),tenant,source,n,'2026-01-01','file.pdf',f'{tenant}/{n}','pending',0))
            self.assertEqual(engine.status(tenant)['sources'][0]['discovered'],15)
            with engine.db() as db:
                db.execute("UPDATE files SET state='downloaded',size=100 WHERE message_id<3")
                db.execute("UPDATE files SET library_status='quarantined' WHERE message_id=0")
                db.execute("UPDATE files SET object_key=? WHERE message_id=2",(tenant+'/1',))
            stats=engine.status(tenant)
            self.assertEqual(stats['summary']['downloaded'],3)
            self.assertEqual(stats['summary']['available'],2)
            self.assertEqual(stats['summary']['unique_files'],2)
            self.assertEqual(stats['summary']['unique_bytes'],200)
            self.assertEqual(engine.status(other)['summary']['discovered'],0)
            with engine.db() as db:
                db.execute("UPDATE files SET state='pending'")
            self.assertEqual(len(engine.claim()),10)
            restarted=module.DownloadEngine(root,'test');restarted.sync_sources([config])
            with restarted.db() as db:
                row=db.execute('SELECT cutoff,backfill_cursor FROM sources').fetchone()
                self.assertEqual((row['cutoff'],row['backfill_cursor']),(cutoff,123))
                self.assertEqual(db.execute("SELECT count(*) FROM files WHERE state='downloading'").fetchone()[0],0)
            self.assertEqual(restarted.files(tenant=other)['total'],0)
            self.assertEqual(restarted.files(tenant=tenant)['total'],15)
            restarted.sync_sources([])
            self.assertEqual(restarted.claim(),[])

if __name__=='__main__':unittest.main()
