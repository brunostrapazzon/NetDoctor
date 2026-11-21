"""Redes Wi-Fi vizinhas: canal, banda e sinal, para medir congestionamento de canal.

Usa `netsh wlan show networks mode=bssid`, que só lê a lista que o Windows já
tem (não força varredura e não se conecta a nada).

Privacidade: o nome (SSID) e o BSSID das redes vizinhas são de terceiros e
**não são guardados**. O SSID só é usado aqui dentro para marcar quais pontos
de acesso são da própria rede (inclusive outros nós de mesh e a outra banda) e
depois é descartado.
"""

from __future__ import annotations

import re
import sys
from typing import Any

from netdoctor.core.models import ErrorCode, ProbeResult
from netdoctor.core.probes import wifi
from netdoctor.core.probes.wifi import _int, _normalize, location_denied
from netdoctor.core.proc import CommandError, CommandTimeout, run_command

NAME = "neighbors"
TIMEOUT_S = 10.0

_SSID_RE = re.compile(r"^ssid \d+$")
_BSSID_RE = re.compile(r"^bssid \d+$")
_PCT_RE = re.compile(r"\((\d+)\s*%\)")

AP_LABELS: dict[str, str] = {
    "signal": "signal",
    "sinal": "signal",
    "radio type": "radio",
    "tipo de radio": "radio",
    "band": "band",
    "banda": "band",
    "channel": "channel",
    "canal": "channel",
    "connected stations": "stations",
    "estacoes conectadas": "stations",
    "channel utilization": "utilization",
    "utilizacao do canal": "utilization",
}


def parse_networks(text: str, own_ssid: str | None = None) -> dict[str, Any]:
    """Lista de pontos de acesso visíveis, sem SSID nem BSSID.

    `own` marca os pontos de acesso cujo SSID é igual ao da rede conectada.
    """
    if location_denied(text):
        return {"error": wifi.LOCATION_PERMISSION}

    aps: list[dict[str, Any]] = []
    ssid: str | None = None
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        key, sep, value = line.partition(":")  # BSSID tem ":" no valor
        if not sep:
            continue
        k = _normalize(key)
        value = value.strip()
        if _SSID_RE.match(k):
            ssid = value
            continue
        if _BSSID_RE.match(k):
            current = {
                "own": bool(own_ssid) and ssid == own_ssid,
                "hidden": not ssid,
                "signal_pct": None,
                "channel": None,
                "band": None,
                "radio": None,
                "stations": None,
                "utilization_pct": None,
            }
            aps.append(current)
            continue
        field = AP_LABELS.get(k)
        if current is None or field is None:
            continue
        if field == "signal":
            current["signal_pct"] = _int(value)
        elif field == "channel":
            current["channel"] = _int(value)
        elif field == "stations":
            current["stations"] = _int(value)
        elif field == "utilization":
            match = _PCT_RE.search(value)
            current["utilization_pct"] = int(match.group(1)) if match else None
        else:
            current[field] = value or None
    return {"error": None, "access_points": aps}


def run(ctx: dict[str, Any] | None = None) -> ProbeResult:
    ctx = ctx or {}
    if sys.platform != "win32":
        return ProbeResult(NAME, ok=False, error=ErrorCode.UNSUPPORTED_OS)
    if ctx.get("type") not in (None, "wifi"):
        return ProbeResult(NAME, ok=True, data={"skipped": "not_wifi"})
    try:
        _, iface = run_command(["netsh", "wlan", "show", "interfaces"], timeout=TIMEOUT_S)
        _, out = run_command(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=TIMEOUT_S)
    except CommandTimeout:
        return ProbeResult(NAME, ok=False, error=ErrorCode.TIMEOUT)
    except CommandError:
        return ProbeResult(NAME, ok=False, error=ErrorCode.COMMAND_FAILED)
    own = wifi.parse_interfaces(iface)
    data = parse_networks(out, own.get("ssid"))
    if data["error"]:
        return ProbeResult(NAME, ok=False, data={}, error=data["error"])
    return ProbeResult(NAME, ok=True, data=data)
