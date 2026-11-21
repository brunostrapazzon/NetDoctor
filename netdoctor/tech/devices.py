"""Aparelhos vistos na rede local, pela tabela de vizinhos (ARP) do Windows.

Passivo: só lê o cache que o Windows já tem (`Get-NetNeighbor`), sem varrer a
rede nem mandar pacote para ninguém. Por isso mostra quem conversou com este
computador recentemente, não necessariamente todos os aparelhos da rede.

Usa PowerShell com saída JSON: o estado vem como número do enum, igual em
qualquer idioma do Windows (o `arp -a` traduz "dinâmico"/"dynamic").
MACs ficam só no relatório local; nunca vão para a IA.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import sys
from typing import Any

from netdoctor.core.models import ErrorCode, ProbeResult
from netdoctor.core.probes.adapter import _as_list
from netdoctor.core.proc import CommandError, CommandTimeout, run_command

NAME = "devices"
TIMEOUT_S = 15.0

# Enum NeighborState do Windows.
UNREACHABLE, INCOMPLETE, PROBE, DELAY, STALE, REACHABLE, PERMANENT = range(7)
_ALIVE = {PROBE, DELAY, STALE, REACHABLE}

_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$alias = $env:NETDOCTOR_IFACE
@(Get-NetNeighbor -AddressFamily IPv4 -InterfaceAlias $alias -ErrorAction SilentlyContinue |
  ForEach-Object { [ordered]@{ ip=$_.IPAddress; mac=$_.LinkLayerAddress; state=[int]$_.State } }) |
  ConvertTo-Json -Compress
"""


def _encoded_script() -> str:
    return base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")


def _normalize_mac(mac: str) -> str:
    return mac.replace("-", ":").lower()


def is_randomized_mac(mac: str) -> bool:
    """MAC "privado" (bit de administração local): comum em celulares modernos."""
    first = int(mac.replace("-", ":").split(":")[0], 16)
    return bool(first & 0b10)


def parse_neighbors(
    raw: Any, gateway: str | None = None, ipv4: str | None = None, prefix: int | None = None
) -> dict[str, Any]:
    network = None
    if ipv4 and prefix is not None:
        network = ipaddress.ip_network(f"{ipv4}/{prefix}", strict=False)

    devices = []
    for entry in _as_list(raw):
        ip = ipaddress.ip_address(entry["ip"])
        mac = entry.get("mac") or ""
        if entry.get("state") not in _ALIVE:
            continue
        if ip.is_multicast or ip == ipaddress.ip_address("255.255.255.255"):
            continue
        if network is not None and (ip not in network or ip == network.broadcast_address):
            continue
        if mac.replace("-", "").replace(":", "").strip("0").lower() in ("", "f" * 12):
            continue
        devices.append(
            {
                "ip": str(ip),
                "mac": _normalize_mac(mac),
                "gateway": str(ip) == gateway,
                "randomized_mac": is_randomized_mac(mac),
            }
        )
    devices.sort(key=lambda d: ipaddress.ip_address(d["ip"]))
    return {"count": len(devices), "devices": devices}


def run(ctx: dict[str, Any] | None = None) -> ProbeResult:
    ctx = ctx or {}
    if sys.platform != "win32":
        return ProbeResult(NAME, ok=False, error=ErrorCode.UNSUPPORTED_OS)
    if not ctx.get("interface"):
        return ProbeResult(NAME, ok=True, data={"skipped": "no_interface"})
    try:
        code, out = run_command(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", _encoded_script()],
            timeout=TIMEOUT_S,
            encoding="utf-8",
            env_extra={"NETDOCTOR_IFACE": ctx["interface"]},
        )
    except CommandTimeout:
        return ProbeResult(NAME, ok=False, error=ErrorCode.TIMEOUT)
    except CommandError:
        return ProbeResult(NAME, ok=False, error=ErrorCode.COMMAND_FAILED)
    if code != 0:
        return ProbeResult(NAME, ok=False, error=ErrorCode.COMMAND_FAILED)
    try:
        text = out.lstrip("﻿").strip()
        raw = json.loads(text) if text else []
        data = parse_neighbors(raw, ctx.get("gateway"), ctx.get("ipv4"), ctx.get("prefix"))
    except (ValueError, KeyError, TypeError):
        return ProbeResult(NAME, ok=False, error=ErrorCode.PARSE_ERROR)
    return ProbeResult(NAME, ok=True, data=data)
