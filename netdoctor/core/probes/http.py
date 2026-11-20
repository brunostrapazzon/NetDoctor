"""Consegue abrir a web? Detecta portal cativo e bloqueio de HTTPS.

1. NCSI: o mesmo teste que o Windows usa. HTTP simples que deve devolver
   exatamente "Microsoft Connect Test". Um redirecionamento ou outro conteúdo
   indica portal cativo (rede de hotel, aeroporto...).
2. HTTPS: um pedido a um endpoint que devolve 204. Falha de TLS costuma
   indicar portal ou interceptação.
Redirecionamentos não são seguidos de propósito.
"""

from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from netdoctor.core.models import ProbeResult

NAME = "http"
NCSI_URL = "http://www.msftconnecttest.com/connecttest.txt"
NCSI_BODY = "Microsoft Connect Test"
HTTPS_URL = "https://www.google.com/generate_204"
TIMEOUT_S = 5.0
_MAX_BODY = 2048


@dataclass
class FetchResult:
    status: int | None
    body: str = ""
    location: str | None = None
    error: str | None = None
    ms: float | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _classify(exc: BaseException) -> str:
    reason = getattr(exc, "reason", exc)
    if isinstance(reason, ssl.SSLError):
        return "TLS_ERROR"
    if isinstance(reason, socket.gaierror):
        return "DNS_ERROR"
    if isinstance(reason, TimeoutError | socket.timeout):
        return "TIMEOUT"
    if isinstance(reason, ConnectionError | OSError):
        return "CONNECTION_ERROR"
    return "UNEXPECTED"


def fetch(url: str, timeout: float = TIMEOUT_S) -> FetchResult:
    start = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": "NetDoctor"})
    try:
        with _opener.open(request, timeout=timeout) as resp:
            body = resp.read(_MAX_BODY).decode("utf-8", errors="replace")
            status = resp.status
            location = resp.headers.get("Location")
    except urllib.error.HTTPError as exc:  # 3xx/4xx/5xx sem seguir redirecionamento
        status, body, location = exc.code, "", exc.headers.get("Location")
    except Exception as exc:
        return FetchResult(status=None, error=_classify(exc))
    ms = round((time.perf_counter() - start) * 1000, 1)
    return FetchResult(status=status, body=body, location=location, ms=ms)


def interpret_ncsi(result: FetchResult) -> dict[str, Any]:
    redirect_host = urlsplit(result.location).hostname if result.location else None
    return {
        "status": result.status,
        "error": result.error,
        "content_ok": result.status == 200 and result.body.strip() == NCSI_BODY,
        "redirected": result.status is not None and 300 <= result.status < 400,
        "redirect_host": redirect_host,
        "ms": result.ms,
    }


def interpret_https(result: FetchResult) -> dict[str, Any]:
    return {
        "status": result.status,
        "error": result.error,
        "ok": result.status == 204,
        "ms": result.ms,
    }


def run(ctx: dict[str, Any] | None = None) -> ProbeResult:
    ncsi = interpret_ncsi(fetch(NCSI_URL))
    https = interpret_https(fetch(HTTPS_URL))
    return ProbeResult(NAME, ok=True, data={"ncsi": ncsi, "https": https})
