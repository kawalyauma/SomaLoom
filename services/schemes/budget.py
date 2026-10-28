"""Account-wide daily ceiling for new scheme model calls; cache hits are free."""
import os
from datetime import datetime, timedelta, timezone
from app.core.queue import redis_connection


class SchemeBudgetWait(Exception):
    def __init__(self, resume_at):
        self.resume_at = resume_at
        super().__init__('scheme_daily_ai_budget')


def daily_limit():
    return max(0, min(1000, int(os.getenv('SCHEME_AI_DAILY_CALL_LIMIT', '8'))))


def window(now=None):
    now = now or datetime.now(timezone.utc)
    reset = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return 'somaloom:schemes:ai-calls:' + now.strftime('%Y-%m-%d'), reset


def reserve_call():
    key, reset = window()
    # Atomic across workers and tenants sharing this account. Attempts count even
    # when the provider fails, so a quota outage cannot produce an unlimited loop.
    allowed = redis_connection().eval('''
        local used = tonumber(redis.call('GET', KEYS[1]) or '0')
        if used >= tonumber(ARGV[1]) then return 0 end
        redis.call('INCR', KEYS[1])
        redis.call('EXPIRE', KEYS[1], 172800)
        return 1
    ''', 1, key, daily_limit())
    if not allowed:
        raise SchemeBudgetWait(reset.isoformat())


def status():
    key, reset = window()
    limit = daily_limit()
    try:
        used = int(redis_connection().get(key) or 0)
    except Exception:
        return {'limit': limit, 'used': None, 'remaining': None, 'resets_at': reset.isoformat()}
    return {'limit': limit, 'used': used, 'remaining': max(0, limit-used), 'resets_at': reset.isoformat()}
