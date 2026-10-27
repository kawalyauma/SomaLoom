"""A dedicated queue keeps scheme extraction and user generation ahead of archive bulk work."""
import logging
import threading
import time
from rq import Queue, Worker
from app.core.queue import redis_connection
from services.schemes.tasks import discover, work_queue

def planner():
    while True:
        try:
            discover()
            redis_connection().set('somaloom:planning:heartbeat',str(time.time()),ex=180)
        except Exception as exc:logging.warning('scheme_planner_retry type=%s',type(exc).__name__)
        time.sleep(30)

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO)
    threading.Thread(target=planner,daemon=True).start()
    Worker([Queue('generations',connection=redis_connection()),work_queue()],connection=redis_connection()).work()
