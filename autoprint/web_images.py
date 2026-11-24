"""Картинки из ответа нейросети — копиями в урок (без Qt; вызывается в фоновом потоке).

Ссылка «![кот](https://…/cat.jpg)» из ответа своего чата скачивается в data/media, чтобы на уроке картинка не
зависела от интернета. Скачивается только из интернета: адрес хоста и каждого перенаправления — не частный,
не loopback, не link-local, не зарезервированный (ссылка из ответа нейросети не должна ходить по локальной
сети учителя). Только PNG, JPEG, GIF, WebP, BMP (не SVG), не больше 10 МБ и 15 с на картинку, не больше 40
на урок. Ссылка не на интернет — блок становится местом «Нужна картинка: <подпись>»; не скачалось по сети,
размеру или типу — ссылка остаётся (покажется из интернета).
"""
from __future__ import annotations

import ipaddress
import socket
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from . import storage
from .storage import BLOCK_IMAGE, Template

MAX_BYTES = 10 * 1024 * 1024
TIMEOUT = 15
LIMIT = 40
TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp", "image/bmp": ".bmp"}
USER_AGENT = "AutoPrintCode"


class _Local(Exception):
    """Адрес — не интернет (или перенаправили туда)."""


def _bad_ip(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if a.version == 6 and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    return a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified


def is_local_url(url: str) -> bool:
    """Без DNS: не http(s), localhost, *.local, буквальный частный / loopback / link-local IP. Такой адрес не
    скачивается и не отдаётся странице урока."""
    try:
        parts = urlsplit((url or "").strip())
        host = (parts.hostname or "").lower().rstrip(".")
    except ValueError:
        return True
    if parts.scheme.lower() not in ("http", "https") or not host:
        return True
    if host == "localhost" or host.endswith((".localhost", ".local")):
        return True
    return _bad_ip(host)


def _resolve(host: str) -> list[str]:
    return sorted({ai[4][0] for ai in socket.getaddrinfo(host, None)})


def _public(url: str, resolve) -> bool:
    """Адрес в интернете: схема http(s) и все IP хоста — публичные. OSError — имя не нашлось (сеть)."""
    if is_local_url(url):
        return False
    ips = resolve(urlsplit(url).hostname)
    return bool(ips) and not any(_bad_ip(ip) for ip in ips)


class _CheckedRedirects(urllib.request.HTTPRedirectHandler):
    """Перенаправление в локальную сеть — отказ (до запроса туда)."""

    def __init__(self, resolve) -> None:
        super().__init__()
        self._resolve = resolve

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _public(newurl, self._resolve):
            raise _Local(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _default_opener(resolve):
    def open_(url: str, timeout: float):
        op = urllib.request.build_opener(_CheckedRedirects(resolve))
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
        return op.open(req, timeout=timeout)
    return open_


def _download(url: str, opener, resolve) -> str:
    """→ ссылка на копию в data/media. _Local — адрес не интернет; иное исключение — не скачалось."""
    resp = opener(url, TIMEOUT)
    try:
        final = resp.geturl() or url
        if final != url and not _public(final, resolve):
            raise _Local(final)
        ctype = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        ext = TYPES.get(ctype)
        if ext is None:
            raise ValueError(f"не картинка ({ctype or 'без типа'})")
        length = resp.headers.get("Content-Length")
        if length and str(length).isdigit() and int(length) > MAX_BYTES:
            raise ValueError("больше 10 МБ")
        data = bytearray()
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_BYTES:
                raise ValueError("больше 10 МБ")
    finally:
        try:
            resp.close()
        except Exception:   # noqa: BLE001 — закрыть не вышло — не важно
            pass
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / f"web{ext}"
        p.write_bytes(bytes(data))
        return storage.import_media(p)


def fetch_images(t: Template, *, cancel=None, progress=None, opener=None, resolve=None, limit: int = LIMIT) -> list[str]:
    """Картинки урока t по ссылкам (http, https и любые «схема://») → копии в data/media; меняет t. → замечания.
    cancel — threading.Event («Пропустить», «Закрыть»): что успели — скачано, остальное остаётся ссылками.
    progress(сделано, всего) — после каждой картинки."""
    resolve = resolve or _resolve
    opener = opener or _default_opener(resolve)
    blocks = [b for b in t.blocks if b.type == BLOCK_IMAGE and "://" in (b.text or "")]
    todo = blocks[:limit]
    local = 0
    for i, b in enumerate(todo):
        if cancel is not None and cancel.is_set():
            break
        url = b.text.strip()
        try:
            if not _public(url, resolve):
                raise _Local(url)
            b.text = _download(url, opener, resolve)
        except _Local:
            b.text = ""                      # место «Нужна картинка: <подпись>»
            local += 1
        except Exception:   # noqa: BLE001 — сеть, тип, размер: ссылка остаётся
            pass
        if progress is not None:
            progress(i + 1, len(todo))
    notes = []
    left = sum(1 for b in blocks if "://" in (b.text or ""))
    if left:
        notes.append(f"Не скачалось: {left} — эти картинки покажутся из интернета.")
    if local:
        notes.append(f"Ссылки не из интернета: {local} — вместо них места «Нужна картинка».")
    return notes
