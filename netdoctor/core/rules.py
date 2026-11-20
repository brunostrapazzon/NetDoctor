"""Motor de regras: fatos das probes → achados (Finding).

Determinístico e sem rede. A ordem da cadeia importa: o primeiro ponto de
falha é a causa provável e vira o achado principal.

    NO_LINK → NO_DHCP → GATEWAY_DOWN → ISP_DOWN → DNS_FAIL → CAPTIVE_PORTAL
    → WIFI_WEAK → LOCAL_INTERFERENCE → ALL_OK (ou INCONCLUSIVE)

Regra de ouro: probe que não conseguiu medir (ok=False) é fato desconhecido,
nunca fato negativo. Nenhuma regra dispara por falta de dado.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from netdoctor.core.models import Diagnosis, Finding, ProbeResult, Severity

# --- Limiares --------------------------------------------------------------------


@dataclass(frozen=True)
class Thresholds:
    wifi_weak_signal_pct: float
    gateway_high_loss_pct: float
    gateway_high_avg_rtt_ms: float


def load_thresholds(path: Path | None = None) -> Thresholds:
    if path is None:
        text = resources.files("netdoctor.core").joinpath("thresholds.toml").read_text("utf-8")
    else:
        text = path.read_text("utf-8")
    raw = tomllib.loads(text)
    return Thresholds(
        wifi_weak_signal_pct=raw["wifi"]["weak_signal_pct"],
        gateway_high_loss_pct=raw["gateway"]["high_loss_pct"],
        gateway_high_avg_rtt_ms=raw["gateway"]["high_avg_rtt_ms"],
    )


# --- Fatos -----------------------------------------------------------------------


@dataclass(frozen=True)
class Facts:
    """Dados de cada probe que conseguiu medir. `None` = desconhecido."""

    adapter: dict[str, Any] | None = None
    ping: dict[str, dict[str, Any]] | None = None  # por papel: gateway, public_*
    dns: dict[str, Any] | None = None
    http: dict[str, Any] | None = None
    wifi: dict[str, Any] | None = None

    @classmethod
    def from_results(cls, results: list[ProbeResult]) -> Facts:
        ok = {r.name: r.data for r in results if r.ok}
        ping = ok.get("ping")
        return cls(
            adapter=ok.get("adapter"),
            ping={t["role"]: t for t in ping["targets"]} if ping else None,
            dns=ok.get("dns"),
            http=ok.get("http"),
            wifi=ok.get("wifi"),
        )

    # Helpers: devolvem None quando o fato não foi medido.

    def target(self, role: str) -> dict[str, Any] | None:
        if not self.ping:
            return None
        t = self.ping.get(role)
        return t if t and not t.get("error") else None

    def public_targets(self) -> list[dict[str, Any]]:
        if not self.ping:
            return []
        return [t for r, t in self.ping.items() if r.startswith("public") and not t.get("error")]

    def link_ok(self) -> bool:
        a = self.adapter
        return bool(a and a["connected"] and a["ipv4"] and not a["apipa"])

    def gateway_responds(self) -> bool:
        gw = self.target("gateway")
        return bool(gw and gw["received"] > 0)

    def internet_by_ping(self) -> bool:
        return any(t["received"] > 0 for t in self.public_targets())

    def https_ok(self) -> bool:
        return bool(self.http and self.http["https"]["ok"])


Rule = Callable[[Facts, Thresholds], Finding | None]

# --- Regras (na ordem da cadeia) ---------------------------------------------------


def no_link(f: Facts, t: Thresholds) -> Finding | None:
    if f.adapter is not None and not f.adapter["connected"]:
        return Finding("NO_LINK", Severity.CRITICAL, "CHECK_CABLE_OR_WIFI")
    return None


def no_dhcp(f: Facts, t: Thresholds) -> Finding | None:
    a = f.adapter
    if a and a["connected"] and (a["apipa"] or not a["ipv4"]):
        return Finding(
            "NO_DHCP",
            Severity.CRITICAL,
            "RESTART_ROUTER",
            {"ipv4": a["ipv4"], "apipa": a["apipa"]},
        )
    return None


def gateway_down(f: Facts, t: Thresholds) -> Finding | None:
    if not f.link_ok():
        return None
    if f.adapter["gateway"] is None:
        # IP válido mas sem rota padrão: o roteador não está entregando a saída.
        return Finding(
            "GATEWAY_DOWN", Severity.CRITICAL, "RESTART_ROUTER", {"reason": "no_default_route"}
        )
    gw = f.target("gateway")
    # Alguns roteadores não respondem a ping. Se a internet responde, o roteador está vivo.
    if gw and gw["received"] == 0 and not (f.internet_by_ping() or f.https_ok()):
        return Finding(
            "GATEWAY_DOWN",
            Severity.CRITICAL,
            "RESTART_ROUTER",
            {"reason": "no_reply", "gateway_loss_pct": gw["loss_pct"]},
        )
    return None


def isp_down(f: Facts, t: Thresholds) -> Finding | None:
    publics = f.public_targets()
    if not (f.gateway_responds() and publics and f.http):
        return None
    if f.internet_by_ping() or f.https_ok():
        return None
    # Se o teste do Windows recebeu qualquer resposta HTTP, há saída para a
    # internet (ex.: portal cativo que bloqueia ping). Não é a operadora.
    if f.http["ncsi"]["status"] is not None:
        return None
    return Finding(
        "ISP_DOWN",
        Severity.CRITICAL,
        "CALL_ISP",
        {
            "public_loss_pct": [p["loss_pct"] for p in publics],
            "https_error": f.http["https"]["error"],
        },
    )


def dns_fail(f: Facts, t: Thresholds) -> Finding | None:
    if not (f.dns and f.internet_by_ping()):
        return None
    servers = f.dns["servers"]
    configured = [s for s in servers if s["role"] == "configured"]
    public_ok = any(s["ok"] for s in servers if s["role"] == "public")
    if not public_ok:
        return None
    if not configured:
        return Finding("DNS_FAIL", Severity.CRITICAL, "CHANGE_DNS", {"reason": "no_dns_configured"})
    if all(not s["ok"] for s in configured):
        return Finding(
            "DNS_FAIL",
            Severity.CRITICAL,
            "CHANGE_DNS",
            {"reason": "configured_failed", "errors": [s["error"] for s in configured]},
        )
    return None


def captive_portal(f: Facts, t: Thresholds) -> Finding | None:
    if not f.http:
        return None
    ncsi, https = f.http["ncsi"], f.http["https"]
    if ncsi["status"] is None:
        return None  # sem resposta nenhuma: não é portal (as regras anteriores cobrem)
    if ncsi["redirected"] or not ncsi["content_ok"]:
        return Finding(
            "CAPTIVE_PORTAL",
            Severity.CRITICAL,
            "OPEN_LOGIN_PAGE",
            {"ncsi_status": ncsi["status"], "redirect_host": ncsi["redirect_host"]},
        )
    if https["error"] == "TLS_ERROR":
        return Finding(
            "CAPTIVE_PORTAL", Severity.CRITICAL, "OPEN_LOGIN_PAGE", {"https_error": "TLS_ERROR"}
        )
    return None


def wifi_weak(f: Facts, t: Thresholds) -> Finding | None:
    a, w = f.adapter, f.wifi
    if not (a and a["type"] == "wifi" and w and w.get("signal_pct") is not None):
        return None
    if w["signal_pct"] < t.wifi_weak_signal_pct:
        return Finding(
            "WIFI_WEAK",
            Severity.WARNING,
            "MOVE_CLOSER_OR_USE_CABLE",
            {"signal_pct": w["signal_pct"], "threshold_pct": t.wifi_weak_signal_pct},
        )
    return None


def local_interference(f: Facts, t: Thresholds) -> Finding | None:
    gw = f.target("gateway")
    if not (gw and gw["received"] > 0):
        return None
    avg = gw["rtt_ms"]["avg"] if gw["rtt_ms"] else None
    high_loss = gw["loss_pct"] >= t.gateway_high_loss_pct
    high_rtt = avg is not None and avg >= t.gateway_high_avg_rtt_ms
    if high_loss or high_rtt:
        return Finding(
            "LOCAL_INTERFERENCE",
            Severity.WARNING,
            "RESTART_ROUTER_REDUCE_LOAD",
            {"gateway_loss_pct": gw["loss_pct"], "gateway_avg_rtt_ms": avg},
        )
    return None


CHAIN: tuple[Rule, ...] = (
    no_link,
    no_dhcp,
    gateway_down,
    isp_down,
    dns_fail,
    captive_portal,
    wifi_weak,
    local_interference,
)


def _measured_enough(f: Facts) -> bool:
    """Para afirmar ALL_OK é preciso ter medido conexão, rede e web."""
    return f.adapter is not None and f.ping is not None and f.http is not None


def evaluate(facts: Facts, thresholds: Thresholds | None = None) -> Diagnosis:
    thresholds = thresholds or load_thresholds()
    findings = [finding for rule in CHAIN if (finding := rule(facts, thresholds))]
    if not findings:
        if _measured_enough(facts):
            findings = [Finding("ALL_OK", Severity.INFO, "CHECK_SITE_OR_APP")]
        else:
            findings = [Finding("INCONCLUSIVE", Severity.WARNING, "RUN_AGAIN")]
    return Diagnosis(findings)


def diagnose(results: list[ProbeResult], thresholds: Thresholds | None = None) -> Diagnosis:
    return evaluate(Facts.from_results(results), thresholds)
