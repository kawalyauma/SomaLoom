"""Trusted internal queue only. Feature agents register their own importable tasks."""

import threading
import time

from rq import Worker

from app.core.queue import queue, redis_connection


def heartbeat():
    while True:
        try:
            redis_connection().set("somaloom:worker:heartbeat", str(time.time()), ex=60)
        except Exception:
            pass
        time.sleep(15)


if __name__ == "__main__":
    threading.Thread(target=heartbeat, daemon=True).start()
    Worker([queue()], connection=redis_connection()).work()
