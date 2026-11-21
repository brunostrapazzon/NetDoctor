"""Análise do Modo Técnico: fatos das probes técnicas → achados para o laudo.

Determinística, como `core/rules.py`, mas é uma lista de observações para o
técnico, não uma cadeia com causa principal. Os textos podem usar termos
técnicos (canal, salto, ARP): o leitor é quem dá suporte, não o cliente.
O diagnóstico do Modo Cliente não muda com o Modo Técnico.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from netdoctor.core.models import Finding, ProbeResult, Severity
from netdoctor.core.probes import wifi
from netdoctor.tech import devices, hops, neighbors

TECH_PROBES = (
    (neighbors.NAME, neighbors.run),
    (devices.NAME, devices.run),
    (hops.NAME, hops.run),
)
# O tracert domina o tempo (pior caso ~32 s).
TECH_TIMEOUT_S = hops.TIMEOUT_S + 5

# Canais de 20 MHz em 2,4 GHz só não se sobrepõem a 5 canais de distância.
CHANNELS_24 = (1, 6, 11)
# 5 GHz sem DFS permitidos no Brasil (Anatel): UNII-1 e UNII-3.
CHANNELS_5 = (36, 40, 44, 48, 149, 153, 157, 161)


@dataclass(frozen=True)
class TechThresholds:
    strong_neighbor_pct: float
    congested_neighbors: int
    busy_utilization_pct: float
    route_loss_pct: float
    route_latency_jump_ms: float


def load_tech_thresholds(path: Path | None = None) -> TechThresholds:
    if path is None:
        text = resources.files("netdoctor.core").joinpath("thresholds.toml").read_text("utf-8")
    else:
        text = path.read_text("utf-8")
    return TechThresholds(**tomllib.loads(text)["tech"])


# --- Canais ----------------------------------------------------------------------


def is_24ghz(band: str | None, channel: int | None) -> bool:
    if band:
        return band.strip().startswith("2")
    return channel is not None and channel <= 14


def overlaps(own: int, other: int, band_24: bool) -> bool:
    return abs(own - other) < 5 if band_24 else own == other


def _overlapping(aps: list[dict[str, Any]], channel: int, band_24: bool) -> list[dict[str, Any]]:
    return [
        ap
        for ap in aps
        if ap["channel"] is not None
        and is_24ghz(ap["band"], ap["channel"]) == band_24
        and overlaps(channel, ap["channel"], band_24)
    ]


def _score(aps: list[dict[str, Any]], channel: int, band_24: bool, strong: float):
    """(vizinhos fortes, soma dos sinais): menor é melhor."""
    near = _overlapping(aps, channel, band_24)
    return (
        sum(1 for ap in near if (ap["signal_pct"] or 0) >= strong),
        sum(ap["signal_pct"] or 0 for ap in near),
    )


def suggest_channel(
    aps: list[dict[str, Any]], band_24: bool, current: int, strong: float
) -> int | None:
    """Canal com menos disputa entre os recomendados; None se o atual já é o melhor."""
    others = [ap for ap in aps if not ap["own"]]
    candidates = CHANNELS_24 if band_24 else CHANNELS_5
    best = min(candidates, key=lambda ch: _score(others, ch, band_24, strong))
    if _score(others, best, band_24, strong) >= _score(others, current, band_24, strong):
        return None
    return best


def analyze_channel(
    neighbors_data: dict[str, Any], wifi_data: dict[str, Any] | None, t: TechThresholds
) -> list[Finding]:
    if not wifi_data or not wifi_data.get("connected") or wifi_data.get("channel") is None:
        return []
    channel, band = wifi_data["channel"], wifi_data.get("band")
    band_24 = is_24ghz(band, channel)
    aps = neighbors_data["access_points"]
    others = [ap for ap in aps if not ap["own"]]
    strong = _score(others, channel, band_24, t.strong_neighbor_pct)[0]
    own_ap = next((ap for ap in aps if ap["own"] and ap["channel"] == channel), None)
    utilization = own_ap["utilization_pct"] if own_ap else None
    evidence = {
        "channel": channel,
        "band": band,
        "visible_networks": len(others),
        "strong_overlapping": strong,
        "utilization_pct": utilization,
    }

    out = []
    if strong >= t.congested_neighbors:
        suggestion = suggest_channel(aps, band_24, channel, t.strong_neighbor_pct)
        out.append(
            Finding(
                "CHANNEL_CONGESTED",
                Severity.WARNING,
                "CHANGE_CHANNEL" if suggestion else "CONSIDER_5GHZ_OR_CABLE",
                {**evidence, "suggested_channel": suggestion},
            )
        )
    if utilization is not None and utilization >= t.busy_utilization_pct:
        out.append(Finding("CHANNEL_BUSY", Severity.WARNING, "REDUCE_LOAD_OR_CHANGE", evidence))
    if not out:
        out.append(Finding("CHANNEL_OK", Severity.INFO, "NONE", evidence))
    return out


# --- Rota ------------------------------------------------------------------------


def _persistent_from(responding: list[dict[str, Any]], test) -> int | None:
    """Índice do primeiro salto a partir do qual `test` vale até o destino."""
    start = None
    for i in range(len(responding) - 1, -1, -1):
        if test(responding[i]):
            start = i
        else:
            break
    return start


def analyze_route(hops_data: dict[str, Any], gateway: str | None, t: TechThresholds):
    hop_list = hops_data["hops"]
    responding = [h for h in hop_list if h["ip"]]
    if not hops_data["reached"]:
        last = responding[-1]["hop"] if responding else None
        return [
            Finding(
                "ROUTE_INCOMPLETE",
                Severity.INFO,
                "COMPARE_WITH_PING",
                {"target": hops_data["target"], "last_responding_hop": last},
            )
        ]

    router = next((h for h in responding if gateway and h["ip"] == gateway), None)
    base_ms = router["avg_ms"] if router else 0.0
    dest = responding[-1]
    out = []

    i = _persistent_from(responding, lambda h: h["loss_pct"] >= t.route_loss_pct)
    if i is not None:
        start = responding[i]
        local = start is router or start["hop"] == 1
        out.append(
            Finding(
                "ROUTE_LOSS_LOCAL" if local else "ROUTE_LOSS_ISP",
                Severity.WARNING,
                "CHECK_LOCAL_NETWORK" if local else "CONTACT_ISP",
                {"from_hop": start["hop"], "destination_loss_pct": dest["loss_pct"]},
            )
        )

    beyond = responding[responding.index(router) + 1 :] if router else responding[1:]
    j = _persistent_from(
        beyond,
        lambda h: h["avg_ms"] is not None and h["avg_ms"] - base_ms >= t.route_latency_jump_ms,
    )
    if j is not None:
        out.append(
            Finding(
                "ROUTE_LATENCY_ISP",
                Severity.WARNING,
                "CONTACT_ISP",
                {
                    "from_hop": beyond[j]["hop"],
                    "router_ms": base_ms,
                    "destination_ms": dest["avg_ms"],
                },
            )
        )
    if not out:
        out.append(
            Finding(
                "ROUTE_OK",
                Severity.INFO,
                "NONE",
                {"hops": len(hop_list), "destination_ms": dest["avg_ms"]},
            )
        )
    return out


# --- Dispositivos ----------------------------------------------------------------


def analyze_devices(devices_data: dict[str, Any]) -> list[Finding]:
    items = devices_data["devices"]
    return [
        Finding(
            "DEVICES_SEEN",
            Severity.INFO,
            "NONE",
            {
                "count": devices_data["count"],
                "randomized_mac": sum(1 for d in items if d["randomized_mac"]),
            },
        )
    ]


# --- Laudo -----------------------------------------------------------------------

TECH_TEXT: dict[str, str] = {
    "CHANNEL_OK": "Canal {channel} ({band}) sem disputa relevante: "
    "{strong_overlapping} rede(s) vizinha(s) forte(s) sobreposta(s).",
    "CHANNEL_CONGESTED": "Canal {channel} ({band}) congestionado: {strong_overlapping} redes "
    "vizinhas fortes no mesmo canal ou sobrepostas.",
    "CHANNEL_BUSY": "O roteador informa utilização de {utilization_pct}% no canal {channel}.",
    "ROUTE_OK": "Rota até o destino em {hops} saltos, sem perda persistente nem salto de "
    "latência ({destination_ms} ms no destino).",
    "ROUTE_LOSS_LOCAL": "Perda a partir do salto {from_hop} (rede local) que continua até o "
    "destino ({destination_loss_pct}% no destino).",
    "ROUTE_LOSS_ISP": "Perda a partir do salto {from_hop} (rede da operadora) que continua "
    "até o destino ({destination_loss_pct}% no destino).",
    "ROUTE_LATENCY_ISP": "Latência sobe a partir do salto {from_hop} e se mantém: roteador "
    "{router_ms} ms, destino {destination_ms} ms.",
    "ROUTE_INCOMPLETE": "O tracert não chegou a {target} (último salto que respondeu: "
    "{last_responding_hop}). Pode ser filtro de ICMP no caminho; compare com o ping.",
    "DEVICES_SEEN": "{count} aparelho(s) na tabela ARP deste computador ({randomized_mac} com "
    "MAC aleatório). É uma contagem mínima: só aparece quem conversou com este PC há pouco.",
}

ACTION_TEXT: dict[str, str] = {
    "CHANGE_CHANNEL": "Trocar o canal do roteador para {suggested_channel}.",
    "CONSIDER_5GHZ_OR_CABLE": "Todos os canais estão disputados: preferir 5 GHz ou cabo.",
    "REDUCE_LOAD_OR_CHANGE": "Reduzir aparelhos na mesma banda ou trocar de canal.",
    "CHECK_LOCAL_NETWORK": "Verificar Wi-Fi/cabo e o roteador (a perda começa na rede local).",
    "CONTACT_ISP": "Abrir chamado na operadora com este laudo (o problema começa fora da casa).",
    "COMPARE_WITH_PING": "Se o ping para a internet está ok, ignorar.",
    "NONE": "",
}

NOT_MEASURED_TEXT: dict[str, str] = {
    "neighbors": "Redes vizinhas: não foi possível medir ({error}).",
    "devices": "Aparelhos na rede: não foi possível medir ({error}).",
    "hops": "Saltos (tracert): não foi possível medir ({error}).",
}


def finding_text(f: Finding) -> tuple[str, str]:
    values = {k: ("—" if v is None else v) for k, v in f.evidence.items()}
    return TECH_TEXT[f.code].format(**values), ACTION_TEXT[f.action].format(**values)


def analyze(results: list[ProbeResult], thresholds: TechThresholds | None = None) -> dict:
    """Achados técnicos + texto do laudo, prontos para o relatório."""
    t = thresholds or load_tech_thresholds()
    by_name = {r.name: r for r in results}
    ok = {r.name: r.data for r in results if r.ok}
    adapter = ok.get("adapter") or {}

    findings: list[Finding] = []
    notes: list[str] = []
    n = ok.get(neighbors.NAME)
    if n and not n.get("skipped"):
        findings += analyze_channel(n, ok.get(wifi.NAME), t)
    h = ok.get(hops.NAME)
    if h and not h.get("skipped"):
        findings += analyze_route(h, adapter.get("gateway"), t)
    d = ok.get(devices.NAME)
    if d and not d.get("skipped"):
        findings += analyze_devices(d)

    for name, text in NOT_MEASURED_TEXT.items():
        r = by_name.get(name)
        if r is not None and not r.ok:
            notes.append(text.format(error=r.error))

    return {
        "findings": [
            {**asdict(f), "text": finding_text(f)[0], "action_text": finding_text(f)[1]}
            for f in findings
        ],
        "notes": notes,
    }
