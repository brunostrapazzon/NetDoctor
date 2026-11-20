"""Sinal Wi-Fi (%), RSSI, canal, banda e padrão via `netsh wlan show interfaces`.

É o único dado sem alternativa estável e sem administrador fora do `netsh`.
Os rótulos mudam com o idioma do Windows, então a leitura usa uma tabela de
rótulos PT/EN normalizados (sem acento, minúsculos, espaços simples).

Windows 11 24H2+: sem permissão de Localização, o `netsh wlan` nega acesso às
informações de WLAN. Não existe texto oficial documentado da mensagem, então a
detecção é por palavras-chave nos dois idiomas → error="LOCATION_PERMISSION".
"""

from __future__ import annotations

import re
import sys
import unicodedata
from typing import Any

from netdoctor.core.models import ErrorCode, ProbeResult
from netdoctor.core.proc import CommandError, CommandTimeout, run_command

NAME = "wifi"
TIMEOUT_S = 10.0

LOCATION_PERMISSION = "LOCATION_PERMISSION"
NO_WIFI_INTERFACE = "NO_WIFI_INTERFACE"

# Rótulo normalizado → campo. Comparação exata, então "ssid" não casa com "ap bssid".
LABELS: dict[str, str] = {
    "name": "name",
    "nome": "name",
    "state": "state",
    "estado": "state",
    "ssid": "ssid",
    "band": "band",
    "banda": "band",
    "channel": "channel",
    "canal": "channel",
    "radio type": "radio",
    "tipo de radio": "radio",
    "signal": "signal",
    "sinal": "signal",
    "rssi": "rssi",
}

_CONNECTED = {"connected", "conectado"}
_LOCATION_HINTS = (("location", "permission"), ("localizacao", "permiss"))


def _normalize(text: str) -> str:
    no_accents = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", no_accents).strip().lower()


def _int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"-?\d+", value)
    return int(match.group()) if match else None


def _parse_blocks(text: str) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")  # BSSID/MAC têm ":" no valor
        if not sep:
            continue
        field = LABELS.get(_normalize(key))
        if field is None:
            continue
        if field == "name" and current:
            blocks.append(current)
            current = {}
        current.setdefault(field, value.strip())
    if current:
        blocks.append(current)
    return blocks


def parse_interfaces(text: str) -> dict[str, Any]:
    """Interpreta a saída do `netsh wlan show interfaces`.

    Devolve `{"error": ...}` quando não há dado de Wi-Fi para ler, ou os campos
    da interface conectada (ou da primeira, se nenhuma estiver conectada).
    """
    normalized = _normalize(text)
    if any(all(word in normalized for word in hint) for hint in _LOCATION_HINTS):
        return {"error": LOCATION_PERMISSION}

    blocks = [b for b in _parse_blocks(text) if "state" in b]
    if not blocks:
        return {"error": NO_WIFI_INTERFACE}

    connected = [b for b in blocks if _normalize(b["state"]) in _CONNECTED]
    chosen = connected[0] if connected else blocks[0]
    is_connected = bool(connected)
    return {
        "error": None,
        "connected": is_connected,
        "interfaces": len(blocks),
        "ssid": chosen.get("ssid") if is_connected else None,  # sensível: só relatório local
        "signal_pct": _int(chosen.get("signal")) if is_connected else None,
        "rssi_dbm": _int(chosen.get("rssi")) if is_connected else None,
        "channel": _int(chosen.get("channel")) if is_connected else None,
        "band": chosen.get("band") if is_connected else None,
        "radio": chosen.get("radio") if is_connected else None,
    }


def run(ctx: dict[str, Any] | None = None) -> ProbeResult:
    ctx = ctx or {}
    if sys.platform != "win32":
        return ProbeResult(NAME, ok=False, error=ErrorCode.UNSUPPORTED_OS)
    if ctx.get("type") not in (None, "wifi"):
        # Conectado por cabo: Wi-Fi não é relevante para o diagnóstico.
        return ProbeResult(NAME, ok=True, data={"skipped": "not_wifi"})
    try:
        _, out = run_command(["netsh", "wlan", "show", "interfaces"], timeout=TIMEOUT_S)
    except CommandTimeout:
        return ProbeResult(NAME, ok=False, error=ErrorCode.TIMEOUT)
    except CommandError:
        return ProbeResult(NAME, ok=False, error=ErrorCode.COMMAND_FAILED)
    data = parse_interfaces(out)
    if data["error"]:
        # Não conseguiu ler o sinal: é fato desconhecido, não "sinal fraco".
        return ProbeResult(NAME, ok=False, data={}, error=data["error"])
    return ProbeResult(NAME, ok=True, data=data)
