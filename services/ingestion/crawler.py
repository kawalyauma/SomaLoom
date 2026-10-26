"""Authorized, bounded crawler; pinned public DNS addresses prevent DNS rebinding/SSRF."""
import http.client
import ipaddress
import socket
import ssl
import time
from collections import deque
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit, unquote
from urllib.robotparser import RobotFileParser

USER_AGENT = "SomaLoomImporter/1.0 (authorized educational content ingestion)"
MAX_BODY = 20 * 1024 * 1024

def canonical(raw: str) -> str:
    parts = urlsplit(raw)
    host = (parts.hostname or "").lower().rstrip(".")
    if (parts.scheme not in ("https", "http") or not host or parts.username or parts.password
            or parts.port not in (None, 80, 443) or "\\" in raw):
        raise ValueError("Invalid web URL")
    if (parts.scheme == "https" and parts.port == 80) or (parts.scheme == "http" and parts.port == 443):
        raise ValueError("Invalid web port")
    path = unquote(parts.path or "/")
    if any(p in (".", "..") for p in path.split("/")) or any(ord(c) < 32 for c in path):
        raise ValueError("Invalid URL path")
    return urlunsplit((parts.scheme, host, parts.path or "/", parts.query, ""))

def allowed(url: str, domains: set[str], prefixes: list[str]) -> bool:
    try:
        u = urlsplit(canonical(url))
    except ValueError:
        return False
    return u.hostname in domains and any(
        unquote(u.path or "/").startswith(p.rstrip("/") + "/")
        or unquote(u.path or "/") == p.rstrip("/")
        or p == "/" for p in prefixes
    )

def safe_addresses(host: str, port: int):
    # Every DNS response must be public; this includes mixed public/private answers.
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError("DNS lookup failed") from e
    if not addresses:
        raise ValueError("DNS has no addresses")
    for family, _kind, _proto, _canon, address in addresses:
        ip = ipaddress.ip_address(address[0])
        if not ip.is_global:
            raise ValueError("Blocked non-public address")
    return addresses

def download(url: str, domains: set[str], prefixes: list[str], *,
             max_bytes: int = MAX_BODY, robots=False, redirects=3):
    for _ in range(redirects + 1):
        url = canonical(url)
        if not robots and not allowed(url, domains, prefixes):
            raise ValueError("URL outside authorized domain/path")
        parts = urlsplit(url)
        if parts.hostname not in domains:
            raise ValueError("Host not authorized")
        port = parts.port or (443 if parts.scheme == "https" else 80)
        addresses = safe_addresses(parts.hostname, port)
        address = addresses[0][4]
        sock = socket.socket(addresses[0][0], socket.SOCK_STREAM)
        sock.settimeout(15)
        conn = None
        try:
            sock.connect(address)
            if parts.scheme == "https":
                sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parts.hostname)
                conn = http.client.HTTPSConnection(parts.hostname, port=port, timeout=15)
            else:
                conn = http.client.HTTPConnection(parts.hostname, port=port, timeout=15)
            conn.sock = sock
            target = parts.path + (("?" + parts.query) if parts.query else "")
            conn.request("GET", target, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf"})
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308):
                location = resp.getheader("Location")
                if not location:
                    raise ValueError("Redirect missing Location")
                url = canonical(urljoin(url, location))
                # Redirect authorization and DNS are rechecked before next request.
                if not allowed(url, domains, prefixes) and not (robots and urlsplit(url).path == "/robots.txt"):
                    raise ValueError("Redirect outside authorization")
                continue
            if resp.status != 200:
                raise ValueError(f"HTTP {resp.status}")
            size_header = resp.getheader("Content-Length")
            if size_header and int(size_header) > max_bytes:
                raise ValueError("Resource exceeds crawl size limit")
            blob = resp.read(max_bytes + 1)
            if len(blob) > max_bytes:
                raise ValueError("Resource exceeds crawl size limit")
            return url, blob, (resp.getheader("Content-Type") or "").split(";")[0].lower()
        finally:
            if conn:
                conn.close()
            else:
                sock.close()
    raise ValueError("Too many redirects")

class ReadableHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.words = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {"script", "style", "nav", "footer", "head", "noscript"}:
            self.skip += 1
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])

    def handle_endtag(self, tag):
        if tag in {"script", "style", "nav", "footer", "head", "noscript"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.words.append(data.strip())

    @property
    def readable(self):
        return " ".join(self.words)[:MAX_BODY]

def crawl(seed: str, *, domains: set[str], paths=None, max_pages=100,
          max_depth=2, delay=1.0, checkpoint=None, save=None, dry_run=False):
    """Yield (url, bytes, MIME), save resumable JSON checkpoint after each visited page."""
    prefixes = paths or ["/"]
    if not allowed(seed, domains, prefixes):
        raise ValueError("Seed outside authorized website policy")
    if not (1 <= max_pages <= 1000 and 0 <= max_depth <= 8 and delay >= 0.5):
        raise ValueError("Invalid crawl budget")
    robots_cache = {}
    state = checkpoint or {"pending": [[canonical(seed), 0]], "visited": [], "reports": []}
    pending = deque((url, int(depth)) for url, depth in state["pending"])
    visited = set(state["visited"])
    reports = state["reports"]
    while pending and len(visited) < max_pages:
        url, depth = pending.popleft()
        if url in visited or not allowed(url, domains, prefixes):
            continue
        origin = urlsplit(url)
        robots_url = f"{origin.scheme}://{origin.hostname}/robots.txt"
        if robots_url not in robots_cache:
            try:
                _url, body, _type = download(robots_url, domains, ["/"], max_bytes=512 * 1024, robots=True)
                parser = RobotFileParser()
                parser.parse(body.decode("utf-8", errors="replace").splitlines())
                robots_cache[robots_url] = parser
            except ValueError:
                # Deny if robots policy is unavailable: no speculative permission.
                robots_cache[robots_url] = None
        policy = robots_cache[robots_url]
        if not policy or not policy.can_fetch(USER_AGENT, url):
            reports.append({"url": url, "status": "skipped_robots"})
            visited.add(url)
        else:
            try:
                time.sleep(delay)
                final_url, body, content_type = download(url, domains, prefixes)
                if final_url in visited:
                    continue
                visited.add(url)
                visited.add(final_url)
                if content_type == "application/pdf" or body.startswith(b"%PDF-"):
                    reports.append({"url": final_url, "status": "preview" if dry_run else "ready", "type": "pdf"})
                    if not dry_run:
                        yield final_url, body, "application/pdf"
                elif "html" in content_type or body.lstrip()[:20].lower().startswith(b"<!doctype html"):
                    page = ReadableHTML()
                    page.feed(body.decode("utf-8", errors="replace"))
                    for href in page.links:
                        try:
                            target = canonical(urljoin(final_url, href))
                            if depth < max_depth and allowed(target, domains, prefixes) and target not in visited:
                                if target not in [u for u, _ in pending]:
                                    pending.append((target, depth + 1))
                        except ValueError:
                            continue
                    reports.append({"url": final_url, "status": "preview" if dry_run else "ready", "type": "text"})
                    if not dry_run and page.readable:
                        yield final_url, page.readable.encode(), "text/plain"
                else:
                    reports.append({"url": final_url, "status": "skipped_type"})
            except (ValueError, OSError, http.client.HTTPException, ssl.SSLError) as exc:
                reports.append({"url": url, "status": "error", "reason": type(exc).__name__})
                visited.add(url)
        if save:
            save({"pending": list(pending), "visited": sorted(visited), "reports": reports})
    if save:
        save({"pending": list(pending), "visited": sorted(visited), "reports": reports})
