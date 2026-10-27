import time

from app.core.queue import ping_job, queue

job = queue().enqueue(ping_job, result_ttl=60)
for _ in range(50):
    if job.is_finished:
        assert job.return_value() == "pong"
        print("Live Redis/worker queue execution passed")
        break
    if job.is_failed:
        raise SystemExit("Worker job failed")
    time.sleep(0.2)
else:
    raise SystemExit("Worker did not execute job within 10 seconds")
