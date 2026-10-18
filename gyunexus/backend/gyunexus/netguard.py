"""외부 URL 조회의 안전 장치(SSRF 방지). 뉴스·원문·RSS 도구가 모두 이 모듈로만 네트워크에 나간다.

- http/https 만, 사용자 정보(user:pass@)·비표준 포트·로컬 이름 거부
- DNS 결과의 모든 IP 가 공인 주소여야 함(사설·루프백·링크로컬·CGNAT·예약·멀티캐스트 거부, IPv4-mapped IPv6 포함)
- 리다이렉트는 직접 따라가며 매 단계 대상 URL 을 다시 검증(최대 횟수 제한)
- 타임아웃, 응답 크기 상한(스트리밍으로 읽다가 초과하면 중단), Content-Type 제한
※ 남은 한계: 검증과 실제 연결 사이에 DNS 가 바뀌는 DNS rebinding 은 연결 IP 고정 없이는 완전히 막지 못한다.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urljoin, urlparse

import httpx

ALLOWED_PORTS = {None, 80, 443}
RETRYABLE = {429, 500, 502, 503, 504}
LOCAL_SUFFIXES = (".local", ".localhost", ".internal", ".lan", ".home", ".corp", ".intranet")


class FetchError(Exception):
    """kind: blocked_scheme | blocked_host | blocked_port | blocked_redirect | dns | too_many_redirects | timeout | network |
    http_<code> | too_large | unsupported_type | bad_url"""

    def __init__(self, kind: str, message: str, attempts: int = 1):
        super().__init__(message)
        self.kind, self.attempts = kind, attempts


@dataclass
class Fetched:
    url: str  # 처음 요청한 URL
    final_url: str
    status: int
    content_type: str
    body: bytes
    truncated: bool = False
    redirects: list[str] = field(default_factory=list)
    headers: dict[str, str] = field(default_factory=dict)


async def _default_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await asyncio.wait_for(loop.getaddrinfo(host, None, type=socket.SOCK_STREAM), timeout=5)
    except (socket.gaierror, asyncio.TimeoutError, OSError) as e:
        raise FetchError("dns", f"cannot resolve {host}: {type(e).__name__}") from e
    return sorted({i[4][0] for i in infos})


_resolver: Callable[[str], Awaitable[list[str]]] = _default_resolver


def set_resolver(fn: Callable[[str], Awaitable[list[str]]] | None) -> None:
    """테스트에서 DNS 를 대체한다(None 이면 기본 리졸버로 복원)."""
    global _resolver
    _resolver = fn or _default_resolver


def ip_is_public(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    if isinstance(addr, ipaddress.IPv6Address) and addr.sixtofour:  # 2002::/16 에 내장된 IPv4 도 검사
        addr = addr.sixtofour
    return addr.is_global and not (addr.is_multicast or addr.is_reserved or addr.is_loopback or addr.is_link_local or addr.is_private)


async def validate_url(url: str) -> str:
    """통과하면 정규화된 URL 문자열을 돌려주고, 아니면 FetchError. 매 요청과 매 리다이렉트마다 호출한다."""
    try:
        p = urlparse(url.strip())
        port = p.port
    except ValueError as e:
        raise FetchError("bad_url", "malformed URL") from e
    if p.scheme not in ("http", "https"):
        raise FetchError("blocked_scheme", f"only http/https allowed (got {p.scheme or 'none'})")
    if not p.hostname:
        raise FetchError("bad_url", "URL has no host")
    if p.username or p.password:
        raise FetchError("blocked_host", "credentials in URL are not allowed")
    if port not in ALLOWED_PORTS:
        raise FetchError("blocked_port", f"port {port} is not allowed")
    host = p.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(LOCAL_SUFFIXES) or "." not in host and not _is_ip(host):
        raise FetchError("blocked_host", f"local host name is not allowed: {host}")
    ips = [host] if _is_ip(host) else await _resolver(host)
    if not ips:
        raise FetchError("dns", f"no address for {host}")
    bad = [ip for ip in ips if not ip_is_public(ip)]
    if bad:
        raise FetchError("blocked_host", f"{host} resolves to a non-public address")
    return p.geturl()


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


async def safe_get(
    url: str,
    *,
    transport: httpx.AsyncBaseTransport | None,
    timeout: float,
    max_bytes: int,
    max_redirects: int = 4,
    headers: dict | None = None,
    accept_types: tuple[str, ...] | None = None,
    retry_backoff: list[float] | None = None,
) -> Fetched:
    """검증된 GET. 일시 오류(타임아웃·네트워크·429·5xx)만 backoff 길이만큼 재시도한다."""
    backoff = retry_backoff or []
    attempts = len(backoff) + 1
    last: FetchError | None = None
    for n in range(1, attempts + 1):
        try:
            return await _once(url, transport, timeout, max_bytes, max_redirects, headers or {}, accept_types)
        except FetchError as e:
            e.attempts = n
            last = e
            if not (e.kind in ("timeout", "network") or (e.kind.startswith("http_") and int(e.kind[5:]) in RETRYABLE)) or n == attempts:
                raise
            await asyncio.sleep(backoff[n - 1])
    raise last or FetchError("network", "unreachable")


async def _once(url, transport, timeout, max_bytes, max_redirects, headers, accept_types) -> Fetched:
    current = await validate_url(url)
    redirects: list[str] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)), follow_redirects=False, transport=transport) as c:
        for _ in range(max_redirects + 1):
            try:
                async with c.stream("GET", current, headers=headers) as r:
                    if r.status_code in (301, 302, 303, 307, 308):
                        loc = r.headers.get("location")
                        if not loc:
                            raise FetchError("http_" + str(r.status_code), "redirect without Location")
                        nxt = urljoin(current, loc)
                        try:
                            current = await validate_url(nxt)  # 리다이렉트 대상도 처음과 똑같이 검증한다
                        except FetchError as e:
                            raise FetchError("blocked_redirect", f"redirect target rejected: {e}") from e
                        redirects.append(current)
                        continue
                    if r.status_code >= 400:
                        raise FetchError(f"http_{r.status_code}", f"HTTP {r.status_code}")
                    ctype = r.headers.get("content-type", "").split(";")[0].strip().lower()
                    if accept_types and not any(ctype.startswith(t) for t in accept_types):
                        raise FetchError("unsupported_type", f"content-type {ctype or 'unknown'} is not supported")
                    declared = r.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > max_bytes * 4:
                        raise FetchError("too_large", f"declared size {declared} exceeds limit")
                    buf, truncated = bytearray(), False
                    async for chunk in r.aiter_bytes():
                        buf += chunk
                        if len(buf) > max_bytes:
                            truncated, buf = True, buf[:max_bytes]
                            break
                    return Fetched(url, current, r.status_code, ctype, bytes(buf), truncated, redirects, {k.lower(): v for k, v in r.headers.items()})
            except httpx.TimeoutException as e:
                raise FetchError("timeout", "timeout") from e
            except httpx.TransportError as e:
                raise FetchError("network", type(e).__name__) from e
    raise FetchError("too_many_redirects", f"more than {max_redirects} redirects")
