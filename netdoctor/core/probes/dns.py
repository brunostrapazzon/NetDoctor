"""Resolução de nome no DNS configurado e em DNS públicos, com tempo de resposta.

Pergunta direto a cada servidor (dnspython) em vez de usar o resolvedor do
sistema. Assim dá para separar "o DNS do roteador/operadora falhou" de "a
internet caiu".
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import dns.exception
import dns.resolver

from netdoctor.core.models import ProbeResult

NAME = "dns"
TEST_NAME = "www.google.com"
LIFETIME_S = 2.5
MAX_CONFIGURED = 2
PUBLIC_SERVERS = ("1.1.1.1", "8.8.8.8")


def _error_code(exc: Exception) -> str:
    if isinstance(exc, dns.exception.Timeout):
        return "TIMEOUT"
    if isinstance(exc, dns.resolver.NXDOMAIN):
        return "NXDOMAIN"
    if isinstance(exc, dns.resolver.NoAnswer):
        return "NO_ANSWER"
    if isinstance(exc, dns.resolver.NoNameservers):
        return "SERVER_FAILED"
    return "UNEXPECTED"


def query_server(server: str, role: str, name: str = TEST_NAME) -> dict[str, Any]:
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [server]
    resolver.lifetime = LIFETIME_S
    start = time.perf_counter()
    try:
        answer = resolver.resolve(name, "A")
    except Exception as exc:  # qualquer falha vira fato, nunca exceção para o runner
        return {"server": server, "role": role, "ok": False, "ms": None, "error": _error_code(exc)}
    ms = round((time.perf_counter() - start) * 1000, 1)
    return {"server": server, "role": role, "ok": len(answer) > 0, "ms": ms, "error": None}


def run(ctx: dict[str, Any] | None = None) -> ProbeResult:
    ctx = ctx or {}
    configured = [s for s in ctx.get("dns_servers", []) if s][:MAX_CONFIGURED]
    jobs = [(s, "configured") for s in configured]
    jobs += [(s, "public") for s in PUBLIC_SERVERS if s not in configured]

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        servers = list(pool.map(lambda job: query_server(*job), jobs))

    return ProbeResult(
        NAME,
        ok=True,
        data={"test_name": TEST_NAME, "has_configured": bool(configured), "servers": servers},
    )
