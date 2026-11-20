"""Adaptador ativo: tipo (Wi-Fi/cabo), IPv4, gateway e DNS configurado.

Usa cmdlets do PowerShell com saída JSON em vez de fazer parsing do `ipconfig`.
Os valores de Status e MediaType vêm de enums, então não mudam com o idioma do
Windows. Nenhum dos cmdlets exige administrador.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import sys
from typing import Any

from netdoctor.core.models import ErrorCode, ProbeResult
from netdoctor.core.proc import CommandError, CommandTimeout, run_command

NAME = "adapter"
TIMEOUT_S = 15.0  # o PowerShell pode levar ~3 s só para carregar os módulos de rede

_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$soft = @{ ErrorAction = 'SilentlyContinue' }
$out = [ordered]@{
  adapters = @(Get-NetAdapter | ForEach-Object { [ordered]@{
    name=$_.Name; index=[int]$_.InterfaceIndex; status=[string]$_.Status;
    media=[string]$_.MediaType; hardware=[bool]$_.HardwareInterface; virtual=[bool]$_.Virtual } })
  addresses = @(Get-NetIPAddress -AddressFamily IPv4 @soft | ForEach-Object {
    [ordered]@{ index=[int]$_.InterfaceIndex; ip=$_.IPAddress; prefix=[int]$_.PrefixLength } })
  routes = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' @soft | ForEach-Object {
    [ordered]@{ index=[int]$_.InterfaceIndex; gateway=$_.NextHop;
                metric=[int]($_.RouteMetric + $_.InterfaceMetric) } })
  dns = @(Get-DnsClientServerAddress -AddressFamily IPv4 @soft | ForEach-Object {
    [ordered]@{ index=[int]$_.InterfaceIndex; servers=@($_.ServerAddresses) } })
}
$out | ConvertTo-Json -Depth 5 -Compress
"""


def _encoded_script() -> str:
    return base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")


def _media_type(media: str) -> str:
    if "802.11" in media:
        return "wifi"
    if "802.3" in media:
        return "ethernet"
    return "other"


def _is_apipa(ip: str) -> bool:
    return ipaddress.ip_address(ip).is_link_local


def _as_list(value: Any) -> list[Any]:
    # O ConvertTo-Json do PowerShell 5.1 pode transformar lista de 1 item em objeto
    # ou em string solta.
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _normalize(raw: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out = {key: _as_list(raw.get(key)) for key in ("adapters", "addresses", "routes", "dns")}
    for entry in out["dns"]:
        entry["servers"] = _as_list(entry.get("servers"))
    return out


def select_active(raw: dict[str, Any]) -> dict[str, Any]:
    """Escolhe o adaptador que leva à internet a partir dos dados brutos.

    Ordem de preferência:
    1. Adaptador "Up" com rota padrão (menor métrica). Isso inclui VPN.
    2. Adaptador físico "Up" sem rota padrão (ex.: sem DHCP, IP 169.254.x.x).
    3. Nenhum: o computador não está conectado.
    Adaptadores virtuais sem rota padrão (VirtualBox, Hyper-V) são ignorados.
    """
    raw = _normalize(raw)
    adapters = {a["index"]: a for a in raw.get("adapters", []) if a.get("status") == "Up"}

    addresses: dict[int, list[dict[str, Any]]] = {}
    for addr in raw.get("addresses", []):
        if addr["index"] in adapters and not addr["ip"].startswith("127."):
            addresses.setdefault(addr["index"], []).append(addr)

    dns: dict[int, list[str]] = {
        d["index"]: list(d.get("servers") or []) for d in raw.get("dns", [])
    }

    routes = sorted(
        (r for r in raw.get("routes", []) if r["index"] in adapters),
        key=lambda r: r.get("metric", 0),
    )

    chosen: dict[str, Any] | None = None
    gateway: str | None = None
    if routes:
        chosen = adapters[routes[0]["index"]]
        gateway = routes[0]["gateway"]
    else:
        physical = [a for a in adapters.values() if a.get("hardware") and not a.get("virtual")]
        physical.sort(key=lambda a: a["index"] not in addresses)  # com IP primeiro
        chosen = physical[0] if physical else None

    if chosen is None:
        return {
            "connected": False,
            "interface": None,
            "type": None,
            "ipv4": None,
            "prefix": None,
            "apipa": False,
            "gateway": None,
            "dns_servers": [],
        }

    own = addresses.get(chosen["index"], [])
    own.sort(key=lambda a: _is_apipa(a["ip"]))  # endereço válido antes de 169.254
    first = own[0] if own else None
    return {
        "connected": True,
        "interface": chosen["name"],
        "type": _media_type(chosen.get("media", "")),
        "ipv4": first["ip"] if first else None,
        "prefix": first["prefix"] if first else None,
        "apipa": bool(first) and _is_apipa(first["ip"]),
        "gateway": gateway,
        "dns_servers": dns.get(chosen["index"], []),
    }


def run(ctx: dict[str, Any] | None = None) -> ProbeResult:
    if sys.platform != "win32":
        return ProbeResult(NAME, ok=False, error=ErrorCode.UNSUPPORTED_OS)
    try:
        code, out = run_command(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", _encoded_script()],
            timeout=TIMEOUT_S,
            encoding="utf-8",
        )
    except CommandTimeout:
        return ProbeResult(NAME, ok=False, error=ErrorCode.TIMEOUT)
    except CommandError:
        return ProbeResult(NAME, ok=False, error=ErrorCode.COMMAND_FAILED)
    if code != 0:
        return ProbeResult(NAME, ok=False, error=ErrorCode.COMMAND_FAILED)
    try:
        raw = json.loads(out.lstrip("﻿"))
        data = select_active(raw)
    except (ValueError, KeyError, TypeError):
        return ProbeResult(NAME, ok=False, error=ErrorCode.PARSE_ERROR)
    return ProbeResult(NAME, ok=True, data=data)
