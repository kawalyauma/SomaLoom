"""Private Telegram account connector and durable archive control plane."""
import asyncio
import hmac
import json
import re
import ssl
from concurrent.futures import TimeoutError as FutureTimeout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from telethon.errors import FloodWaitError, InviteHashExpiredError, InviteHashInvalidError
from telethon.tl.types import Channel, Chat
from download_engine import DownloadEngine

ROOT = Path('/home/codexagent/.config/somaloom-telegram')
TOKEN = (ROOT / 'broker-token').read_text().strip()
ENGINE = DownloadEngine(ROOT, TOKEN)


async def resolve(link):
    parsed = urlsplit(link)
    if parsed.scheme != 'https' or parsed.netloc != 't.me' or parsed.query or parsed.fragment:
        raise ValueError
    if not re.fullmatch(r'(?:[A-Za-z][A-Za-z0-9_]{3,31}|\+[A-Za-z0-9_-]{8,128})', parsed.path.strip('/')):
        raise ValueError
    entity = await ENGINE.entity(link)
    if not isinstance(entity, (Channel, Chat)):
        return 422, {'error': 'group_or_channel_required'}
    from telethon import utils
    return 200, {'chat_id': str(utils.get_peer_id(entity)), 'title': entity.title, 'username': getattr(entity, 'username', None), 'account_connected': True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, data):
        raw = json.dumps(data).encode()
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + TOKEN):
            return self.reply(401, {'error': 'unauthorized'})
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= 1024*1024:
            return self.reply(413, {'error': 'request_limit'})
        try:
            data = json.loads(self.rfile.read(size))
            if self.path == '/sources/sync':
                return self.reply(200, ENGINE.sync_sources(data['sources']))
            if self.path == '/status':
                return self.reply(200, ENGINE.status(data['tenant_id']))
            if self.path == '/files':
                return self.reply(200, ENGINE.files(tenant=data['tenant_id'],source_id=data.get('source_id'),page=data.get('page',1)))
            if self.path == '/files/ready':
                return self.reply(200, ENGINE.files(ready=True))
            if self.path == '/files/ack':
                return self.reply(200, ENGINE.acknowledge(data['items']))
            if not ENGINE.ready:
                return self.reply(503, {'error': 'account_not_connected'})
            if self.path == '/files/url':
                result=ENGINE.file_url(data['tenant_id'],data['file_id'])
                return self.reply(200 if result else 404,result or {'error':'file_not_found'})
            if self.path != '/resolve':
                return self.reply(404, {'error': 'not_found'})
            status,result=asyncio.run_coroutine_threadsafe(resolve(data['link']),ENGINE.loop).result(timeout=22)
            return self.reply(status,result)
        except FloodWaitError:
            return self.reply(429, {'error': 'telegram_rate_limit'})
        except (InviteHashExpiredError, InviteHashInvalidError, ValueError, KeyError):
            return self.reply(404, {'error': 'link_not_found'})
        except Exception:
            return self.reply(503, {'error': 'account_unavailable'})


if __name__ == '__main__':
    ENGINE.start()
    server=ThreadingHTTPServer(('172.31.23.34',3012),Handler)
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.minimum_version=ssl.TLSVersion.TLSv1_2
    tls.load_cert_chain(str(ROOT/'broker-cert.pem'),str(ROOT/'broker-key.pem'))
    server.socket=tls.wrap_socket(server.socket,server_side=True)
    server.serve_forever()
