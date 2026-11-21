"""Latência e perda por salto até 1.1.1.1 (`tracert`).

`-d` desliga a resolução de nomes: mais rápido e não registra hostnames.
O parsing não depende do idioma: cada linha de salto começa com o número do
salto, tem três colunas "N ms" / "<1 ms" / "*" e, se alguém respondeu, um IP.
O texto do timeout ("Request timed out." / "Esgotado o tempo limite do
pedido.") e o cabeçalho são ignorados.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from netdoctor.core.models import ErrorCode, ProbeResult
from netdoctor.core.proc import CommandError, CommandTimeout, run_command

NAME = "hops"
TARGET = "1.1.1.1"
MAX_HOPS = 15
WAIT_MS = 500
# Pior caso: todos os saltos sem resposta = 15 × 3 × 0,5 s.
TIMEOUT_S = MAX_HOPS * 3 * WAIT_MS / 1000 + 10

_HOP_RE = re.compile(r"^\s*(\d+)\s+(.*)$")
_RTT_RE = re.compile(r"(<)?\s*(\d+)\s*ms\b|\*", re.IGNORECASE)
_IP_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def parse_tracert(text: str, target: str = TARGET) -> dict[str, Any]:
    hops = []
    for line in text.splitlines():
        match = _HOP_RE.match(line)
        if not match:
            continue
        rest = match.group(2)
        probes = _RTT_RE.findall(rest)[:3]
        if len(probes) < 3:
            continue
        rtts: list[float | None] = []
        for less, value in probes:
            if not value:
                rtts.append(None)  # "*"
            else:
                # "<1 ms" vira 1.0: limite superior, conservador (igual ao ping).
                rtts.append(float(value) if not less else 1.0)
        ips = _IP_RE.findall(rest)
        replies = [r for r in rtts if r is not None]
        hops.append(
            {
                "hop": int(match.group(1)),
                "ip": ips[-1] if ips and replies else None,
                "rtt_ms": rtts,
                "loss_pct": round(100 * (3 - len(replies)) / 3, 1),
                "avg_ms": round(sum(replies) / len(replies), 1) if replies else None,
            }
        )
    reached = bool(hops) and hops[-1]["ip"] == target
    return {"target": target, "reached": reached, "hops": hops}


def run(ctx: dict[str, Any] | None = None) -> ProbeResult:
    ctx = ctx or {}
    if sys.platform != "win32":
        return ProbeResult(NAME, ok=False, error=ErrorCode.UNSUPPORTED_OS)
    if ctx.get("connected") is False:
        return ProbeResult(NAME, ok=True, data={"skipped": "no_link"})
    args = ["tracert", "-d", "-h", str(MAX_HOPS), "-w", str(WAIT_MS), TARGET]
    try:
        _, out = run_command(args, timeout=TIMEOUT_S)
    except CommandTimeout:
        return ProbeResult(NAME, ok=False, error=ErrorCode.TIMEOUT)
    except CommandError:
        return ProbeResult(NAME, ok=False, error=ErrorCode.COMMAND_FAILED)
    data = parse_tracert(out)
    if not data["hops"]:
        return ProbeResult(NAME, ok=False, error=ErrorCode.PARSE_ERROR)
    return ProbeResult(NAME, ok=True, data=data)
