"""Resolve Telegram links through the private, already-authorized account connector."""
import json
import os
import re
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


class TelegramLinkError(ValueError):
    pass


def normalize_link(value: str) -> str:
    value = value.strip()
    if not value.startswith('https://'):
        raise TelegramLinkError('Paste a Telegram link starting with https://t.me/.')
    try:
        parsed = urlsplit(value)
        if parsed.hostname not in {'t.me', 'www.t.me', 'telegram.me', 'www.telegram.me'} or parsed.port not in (None, 443) or parsed.username or parsed.password:
            raise ValueError
    except ValueError:
        raise TelegramLinkError('Paste a valid https://t.me/ group or channel link.') from None
    parts = parsed.path.strip('/').split('/')
    if parts[0] == 's':
        parts = parts[1:]
    if not parts or not parts[0]:
        raise TelegramLinkError('The link must include a Telegram group or channel name.')
    name = parts[0]
    if name == 'joinchat' and len(parts) == 2 and re.fullmatch(r'[A-Za-z0-9_-]{8,128}', parts[1]):
        return 'https://t.me/+' + parts[1]
    if name.startswith('+') and len(parts) == 1 and re.fullmatch(r'[A-Za-z0-9_-]{8,128}', name[1:]):
        return 'https://t.me/' + name
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{3,31}', name) or name.lower() in {'share', 'addstickers', 'proxy', 'socks', 'login', 'iv', 'c'}:
        raise TelegramLinkError('Use a Telegram group/channel link, not a numeric ID or service link.')
    if len(parts) > 2 or (len(parts) == 2 and not parts[1].isdigit()):
        raise TelegramLinkError('Use a Telegram group/channel link.')
    return 'https://t.me/' + name


def resolve_link(value: str) -> dict:
    link = normalize_link(value)
    endpoint = os.getenv('SOMALOOM_TELEGRAM_ACCOUNT_URL', '')
    if not endpoint.startswith('https://'):
        raise TelegramLinkError('The connected Telegram account is temporarily unavailable.')
    try:
        token = Path('/run/secrets/telegram-account-token').read_text().strip()
        context = ssl.create_default_context(cafile='/run/secrets/telegram-account-ca.pem')
        req = urllib.request.Request(endpoint + '/resolve', json.dumps({'link': link}).encode(), {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token})
        with urllib.request.urlopen(req, timeout=25, context=context) as response:
            result = json.loads(response.read(32768))
        if not isinstance(result.get('chat_id'), str) or not result['chat_id'].lstrip('-').isdigit():
            raise ValueError
        return {**result, 'link': link}
    except urllib.error.HTTPError as error:
        messages = {404: 'Telegram could not find that group or channel.', 403: 'This group is not accessible to the connected Telegram account.', 429: 'Telegram is limiting requests. Try again shortly.', 503: 'The Telegram account is reconnecting. Try again shortly.'}
        raise TelegramLinkError(messages.get(error.code, 'Telegram connection check failed. Try again.')) from None
    except TelegramLinkError:
        raise
    except Exception:
        raise TelegramLinkError('The connected Telegram account is temporarily unavailable.') from None


def account_request(path: str, data: dict) -> dict:
    endpoint=os.getenv('SOMALOOM_TELEGRAM_ACCOUNT_URL','')
    if not endpoint.startswith('https://'):
        raise TelegramLinkError('Telegram downloads are reconnecting. Progress will resume automatically.')
    try:
        token=Path('/run/secrets/telegram-account-token').read_text().strip()
        context=ssl.create_default_context(cafile='/run/secrets/telegram-account-ca.pem')
        req=urllib.request.Request(endpoint+path,json.dumps(data).encode(),{'Content-Type':'application/json','Authorization':'Bearer '+token})
        with urllib.request.urlopen(req,timeout=30,context=context) as response:
            raw=response.read(2*1024*1024+1)
            if len(raw)>2*1024*1024:raise ValueError('response_limit')
            return json.loads(raw)
    except Exception:
        raise TelegramLinkError('Telegram downloads are reconnecting. Try again shortly.') from None


def archive_url(tenant_id, file_id):
    return account_request('/files/url',{'tenant_id':str(tenant_id),'file_id':str(file_id)})


def archive_content(tenant_id, key):
    from uuid import UUID
    file_id=UUID(key.removeprefix('telegram-account/'))
    result=archive_url(tenant_id,file_id)
    if result['size']>20*1024*1024:
        raise ValueError('Archive is too large for automatic extraction')
    with urllib.request.urlopen(result['url'],timeout=90) as response:
        data=response.read(20*1024*1024+1)
    if len(data)>20*1024*1024:
        raise ValueError('Archive exceeds extraction limit')
    return data
