"""Cron/systemd entry point for durable queued-generation redelivery."""

from services.generation.tasks import dispatch_queued

if __name__ == "__main__":
    print("Queued jobs dispatched:", dispatch_queued())
