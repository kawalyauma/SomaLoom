from redis import Redis
from rq import Queue

from app.core.config import get_settings


def redis_connection():
    return Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)


def queue():
    return Queue("somaloom", connection=redis_connection(), default_timeout=600)


def ping_job():
    return "pong"
