"""SSRF guard + a small, pinned HTTP client for the ``fetch_url`` / ``web_search`` tools.

* Only ``http``/``https`` on ports 80/443 (plus 8080/8443).
* Every address a hostname resolves to must be public. Private, loopback, link-local,
  CGNAT, multicast, reserved, documentation and benchmark ranges are refused.
* IPv6 forms that *embed* an IPv4 address (IPv4-mapped ``::ffff:a.b.c.d``, IPv4-compatible,
  NAT64 ``64:ff9b::/96``, 6to4 ``2002::/16``, Teredo) are decoded and the inner IPv4 is
  checked too, so ``::ffff:127.0.0.1`` can't sneak through while ``::ffff:8.8.8.8`` and
  plain public IPv4 such as ``148.135.128.60`` stay allowed.
* The connection is pinned to the IP that passed the check (no DNS-rebinding window);
  TLS still verifies the real hostname. Redirects are followed manually and re-checked.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import urllib.parse
from dataclasses import dataclass

ALLOWED_PORTS = {80, 443, 8080, 8443}
MAX_BYTES = 2_000_000
UA = "Mozilla/5.0 (compatible; AutoMotoAI/5.0; +https://github.com/ymmiah/AutoMotoAI)"

_EXTRA_V4 = [ipaddress.ip_network(n) for n in (
    "0.0.0.0/8", "100.64.0.0/10", "192.0.0.0/24", "192.0.2.0/24", "198.18.0.0/15",
    "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
)]
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


class BlockedURL(ValueError):
    pass


def _embedded_v4(ip: ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    if ip.ipv4_mapped:
        return ip.ipv4_mapped
    if ip in _NAT64:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    if ip.sixtofour:
        return ip.sixtofour
    if ip.teredo:
        return ip.teredo[1]
    # deprecated IPv4-compatible ::a.b.c.d
    if int(ip) >> 32 == 0 and int(ip) > 1:
        return ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF)
    return None


def _allowlist() -> list:
    """Opt-in exceptions, e.g. ``AUTOMOTO_NET_ALLOW_CIDRS=198.18.0.0/15`` for fake-IP DNS
    proxies (Clash, Surge, some corporate egress). Empty by default."""
    from automoto import config

    out = []
    for part in (config.env("AUTOMOTO_NET_ALLOW_CIDRS", "") or "").split(","):
        part = part.strip()
        if part:
            try:
                net = ipaddress.ip_network(part, strict=False)
            except ValueError:
                continue
            if net.prefixlen >= 8:  # never allow "everything"
                out.append(net)
    return out


def is_blocked_ip(addr: str) -> bool:
    """True if ``addr`` must not be contacted."""
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return True
    if ip.is_loopback or ip.is_link_local or ip.is_unspecified:
        return True  # never allow-listable (loopback, 169.254 cloud metadata, ::)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped and is_blocked_ip(str(ip.ipv4_mapped)):
        return True
    if any(ip in n for n in _allowlist()):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        inner = _embedded_v4(ip)
        if inner is not None:
            return is_blocked_ip(str(inner))
        if ip in _NAT64_LOCAL:
            return True
        return not ip.is_global or ip.is_multicast
    if any(ip in n for n in _EXTRA_V4):
        return True
    return not ip.is_global or ip.is_multicast or ip.is_reserved


def check_url(url: str) -> tuple[urllib.parse.SplitResult, str]:
    """Validate ``url`` and return (parts, pinned_ip). Raises BlockedURL."""
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise BlockedURL("only http(s) URLs are allowed")
    host = parts.hostname
    if not host:
        raise BlockedURL("URL has no host")
    if parts.username or parts.password:
        raise BlockedURL("credentials in URLs are not allowed")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise BlockedURL(f"port {port} is not allowed")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise BlockedURL(f"cannot resolve {host}: {exc}") from None
    addrs = sorted({i[4][0] for i in infos})
    if not addrs:
        raise BlockedURL(f"{host} did not resolve")
    bad = [a for a in addrs if is_blocked_ip(a)]
    if bad:
        raise BlockedURL(f"{host} resolves to a private/reserved address ({bad[0]})")
    v4 = [a for a in addrs if ":" not in a]
    return parts, (v4 or addrs)[0]


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, ip, port, timeout):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ip = ip

    def connect(self):
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


@dataclass
class Response:
    url: str
    status: int
    content_type: str
    body: bytes

    def text(self) -> str:
        charset = "utf-8"
        if "charset=" in self.content_type:
            charset = self.content_type.split("charset=", 1)[1].split(";")[0].strip() or "utf-8"
        return self.body.decode(charset, errors="replace")


SENSITIVE_HEADERS = {"authorization", "proxy-authorization", "cookie", "private-token", "zotero-api-key",
                     "x-api-key", "x-automoto-token", "x-figma-token"}


def request(url: str, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None,
            timeout: float = 20, max_redirects: int = 4, max_bytes: int = MAX_BYTES) -> Response:
    for _ in range(max_redirects + 1):
        parts, ip = check_url(url)
        port = parts.port or (443 if parts.scheme == "https" else 80)
        cls = _PinnedHTTPS if parts.scheme == "https" else _PinnedHTTP
        conn = cls(parts.hostname, ip, port, timeout)
        path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
        hdrs = {"User-Agent": UA, "Accept": "text/html,application/json,text/plain,*/*;q=0.5",
                "Accept-Encoding": "identity", **(headers or {})}
        try:
            conn.request(method, path, body=data, headers=hdrs)
            resp = conn.getresponse()
            if resp.status in (301, 302, 303, 307, 308) and resp.getheader("Location"):
                new_url = urllib.parse.urljoin(url, resp.getheader("Location"))
                if urllib.parse.urlsplit(new_url).hostname != parts.hostname or \
                        urllib.parse.urlsplit(new_url).scheme != parts.scheme:
                    # never forward credentials to another host (or downgrade them to http)
                    headers = {k: v for k, v in (headers or {}).items() if k.lower() not in SENSITIVE_HEADERS}
                url = new_url
                if resp.status == 303:
                    method, data = "GET", None
                continue
            body = resp.read(max_bytes + 1)[:max_bytes]
            return Response(url, resp.status, resp.getheader("Content-Type") or "", body)
        finally:
            conn.close()
    raise BlockedURL("too many redirects")
