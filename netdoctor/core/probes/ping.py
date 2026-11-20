"""Latência e perda até o gateway e até IPs públicos (1.1.1.1 e 8.8.8.8).

O parsing não depende do idioma: só linhas de resposta com sucesso têm "TTL=",
e o tempo aparece como "=12ms" ou "<1ms" (tempo=/time=) em qualquer idioma.
Linhas como "Host de destino inacessível" / "Destination host unreachable"
não têm "TTL=" e contam como perda.
"""

from __future__ import annotations

import re
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from netdoctor.core.models import ErrorCode, ProbeResult
from netdoctor.core.proc import CommandError, CommandTimeout, run_command

NAME = "ping"
COUNT = 4
REPLY_TIMEOUT_MS = 1000
PUBLIC_TARGETS = (("public_cloudflare", "1.1.1.1"), ("public_google", "8.8.8.8"))

_REPLY_RE = re.compile(r"([=<])\s*(\d+(?:[.,]\d+)?)\s*ms\b.*\bTTL=", re.IGNORECASE)


def parse_ping(text: str, sent: int) -> dict[str, Any]:
    """Extrai recebidos, perda (%) e RTT de uma saída do ping do Windows."""
    rtts: list[float] = []
    for line in text.splitlines():
        match = _REPLY_RE.search(line)
        if match:
            # "<1ms" vira 1.0: limite superior, conservador.
            rtts.append(float(match.group(2).replace(",", ".")))
    received = min(len(rtts), sent)
    loss_pct = round(100 * (sent - received) / sent, 1) if sent else 100.0
    rtt = (
        {
            "min": min(rtts),
            "avg": round(sum(rtts) / len(rtts), 1),
            "max": max(rtts),
        }
        if rtts
        else None
    )
    return {"sent": sent, "received": received, "loss_pct": loss_pct, "rtt_ms": rtt}


def _ping_target(role: str, host: str) -> dict[str, Any]:
    base = {"role": role, "host": host}
    timeout = COUNT * (REPLY_TIMEOUT_MS / 1000) + 5
    try:
        _, out = run_command(
            ["ping", "-n", str(COUNT), "-w", str(REPLY_TIMEOUT_MS), host], timeout=timeout
        )
    except CommandTimeout:
        return {**base, "error": ErrorCode.TIMEOUT.value}
    except CommandError:
        return {**base, "error": ErrorCode.COMMAND_FAILED.value}
    # O ping devolve código 1 quando há perda; isso é fato, não erro da probe.
    return {**base, **parse_ping(out, COUNT), "error": None}


def run(ctx: dict[str, Any] | None = None) -> ProbeResult:
    if sys.platform != "win32":
        return ProbeResult(NAME, ok=False, error=ErrorCode.UNSUPPORTED_OS)
    ctx = ctx or {}
    jobs: list[tuple[str, str]] = []
    if ctx.get("gateway"):
        jobs.append(("gateway", ctx["gateway"]))
    jobs.extend(PUBLIC_TARGETS)

    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        targets = list(pool.map(lambda job: _ping_target(*job), jobs))

    if not ctx.get("gateway"):
        targets.insert(0, {"role": "gateway", "host": None, "error": "NO_GATEWAY"})
    return ProbeResult(NAME, ok=True, data={"targets": targets})
