"""Análise do Modo Técnico, integração com pipeline, CLI, relatórios e privacidade."""

from __future__ import annotations

import json

import pytest

from netdoctor import cli
from netdoctor.core.models import ProbeResult
from netdoctor.core.runner import PARALLEL
from netdoctor.explain.llm import LLMConfig
from netdoctor.pipeline import run_pipeline
from netdoctor.report.html_report import render_html
from netdoctor.tech.analysis import (
    TECH_PROBES,
    TECH_TIMEOUT_S,
    TechThresholds,
    analyze,
    analyze_channel,
    analyze_route,
    load_tech_thresholds,
    suggest_channel,
)
from netdoctor.tech.hops import parse_tracert
from netdoctor.tech.neighbors import parse_networks

T = TechThresholds(
    strong_neighbor_pct=50,
    congested_neighbors=3,
    busy_utilization_pct=60,
    route_loss_pct=20,
    route_latency_jump_ms=60,
)
GW = "192.168.0.1"


def _ap(channel, signal, band="2.4 GHz", own=False, util=None):
    return {
        "own": own,
        "hidden": False,
        "signal_pct": signal,
        "channel": channel,
        "band": band,
        "radio": None,
        "stations": None,
        "utilization_pct": util,
    }


def _wifi(channel, band="2.4 GHz"):
    return {"connected": True, "channel": channel, "band": band}


def _codes(findings):
    return [f.code for f in findings]


def test_thresholds_load_from_package():
    assert load_tech_thresholds() == T


# --- Canais ------------------------------------------------------------------------


def test_channel_congested_with_suggestion(fixture_text):
    data = parse_networks(fixture_text("neighbors/pt_multi.txt"), "MinhaRede")
    out = analyze_channel(data, _wifi(6), T)
    assert _codes(out) == ["CHANNEL_CONGESTED", "CHANNEL_BUSY"]
    assert out[0].evidence["strong_overlapping"] == 3
    assert out[0].evidence["suggested_channel"] == 11
    assert out[0].action == "CHANGE_CHANNEL"
    assert out[1].evidence["utilization_pct"] == 70


def test_channel_5ghz_only_counts_same_channel(fixture_text):
    data = parse_networks(fixture_text("neighbors/pt_multi.txt"), "MinhaRede")
    out = analyze_channel(data, _wifi(36, "5 GHz"), T)
    assert _codes(out) == ["CHANNEL_OK"]
    assert out[0].evidence["visible_networks"] == 5


@pytest.mark.parametrize(("strong", "expected"), [(2, "CHANNEL_OK"), (3, "CHANNEL_CONGESTED")])
def test_congestion_threshold_boundary(strong, expected):
    aps = [_ap(6, 80, own=True)] + [_ap(6, 50) for _ in range(strong)] + [_ap(6, 49)]
    assert _codes(analyze_channel({"access_points": aps}, _wifi(6), T))[0] == expected


@pytest.mark.parametrize(("util", "busy"), [(59, False), (60, True), (None, False)])
def test_busy_threshold_boundary(util, busy):
    aps = [_ap(6, 80, own=True, util=util)]
    assert ("CHANNEL_BUSY" in _codes(analyze_channel({"access_points": aps}, _wifi(6), T))) is busy


def test_own_access_points_never_count_as_neighbors():
    aps = [_ap(6, 90, own=True) for _ in range(5)]
    assert _codes(analyze_channel({"access_points": aps}, _wifi(6), T)) == ["CHANNEL_OK"]


def test_no_suggestion_when_every_channel_is_worse_or_equal():
    aps = [_ap(ch, 80) for ch in (1, 1, 1, 6, 6, 6, 11, 11, 11)]
    assert suggest_channel(aps, True, 6, 50) is None
    out = analyze_channel({"access_points": aps}, _wifi(6), T)
    assert out[0].action == "CONSIDER_5GHZ_OR_CABLE"


def test_channel_not_analyzed_without_wifi_facts():
    assert analyze_channel({"access_points": [_ap(6, 90)]}, None, T) == []
    assert analyze_channel({"access_points": []}, {"connected": False}, T) == []


# --- Rota --------------------------------------------------------------------------


def _route(fixture_text, name):
    return _codes(analyze_route(parse_tracert(fixture_text(f"hops/{name}.txt")), GW, T))


def test_route_ok(fixture_text):
    assert _route(fixture_text, "pt_ok") == ["ROUTE_OK"]


def test_silent_intermediate_hop_is_not_a_problem(fixture_text):
    assert _route(fixture_text, "pt_silent_hop") == ["ROUTE_OK"]
    assert _route(fixture_text, "en_ok") == ["ROUTE_OK"]


def test_loss_starting_at_isp_and_persisting(fixture_text):
    out = analyze_route(parse_tracert(fixture_text("hops/pt_loss_isp.txt")), GW, T)
    assert _codes(out) == ["ROUTE_LOSS_ISP"]
    assert out[0].evidence == {"from_hop": 2, "destination_loss_pct": 33.3}


def test_latency_jump_at_isp(fixture_text):
    out = analyze_route(parse_tracert(fixture_text("hops/en_latency_isp.txt")), GW, T)
    assert _codes(out) == ["ROUTE_LATENCY_ISP"]
    assert out[0].evidence["from_hop"] == 2


def test_incomplete_route_is_only_informative(fixture_text):
    out = analyze_route(parse_tracert(fixture_text("hops/en_incomplete.txt")), GW, T)
    assert _codes(out) == ["ROUTE_INCOMPLETE"]
    assert out[0].severity == "info"
    assert out[0].evidence["last_responding_hop"] == 2


def _hop(n, ip, loss, avg):
    return {"hop": n, "ip": ip, "rtt_ms": [], "loss_pct": loss, "avg_ms": avg}


def test_loss_that_disappears_later_is_ignored():
    data = {
        "target": "1.1.1.1",
        "reached": True,
        "hops": [_hop(1, GW, 0, 1), _hop(2, "10.0.0.1", 66.7, 5), _hop(3, "1.1.1.1", 0, 20)],
    }
    assert _codes(analyze_route(data, GW, T)) == ["ROUTE_OK"]


def test_loss_from_router_is_local():
    data = {
        "target": "1.1.1.1",
        "reached": True,
        "hops": [_hop(1, GW, 33.3, 1), _hop(2, "10.0.0.1", 33.3, 5), _hop(3, "1.1.1.1", 66.7, 20)],
    }
    out = analyze_route(data, GW, T)
    assert _codes(out) == ["ROUTE_LOSS_LOCAL"]
    assert out[0].action == "CHECK_LOCAL_NETWORK"


@pytest.mark.parametrize(("dest_ms", "flag"), [(60.9, False), (61.0, True)])
def test_latency_threshold_boundary(dest_ms, flag):
    data = {
        "target": "1.1.1.1",
        "reached": True,
        "hops": [_hop(1, GW, 0, 1.0), _hop(2, "1.1.1.1", 0, dest_ms)],
    }
    assert ("ROUTE_LATENCY_ISP" in _codes(analyze_route(data, GW, T))) is flag


# --- analyze() ---------------------------------------------------------------------


def _tech_results(fixture_text, **override):
    results = {
        "adapter": ProbeResult(
            "adapter",
            ok=True,
            data={
                "connected": True,
                "interface": "Wi-Fi",
                "type": "wifi",
                "ipv4": "192.168.0.10",
                "prefix": 24,
                "apipa": False,
                "gateway": GW,
                "dns_servers": [GW],
            },
        ),
        "wifi": ProbeResult(
            "wifi",
            ok=True,
            data={
                "error": None,
                "connected": True,
                "interfaces": 1,
                "ssid": "MinhaRede",
                "signal_pct": 90,
                "rssi_dbm": -50,
                "channel": 6,
                "band": "2.4 GHz",
                "radio": "802.11n",
            },
        ),
        "ping": ProbeResult(
            "ping",
            ok=True,
            data={
                "targets": [
                    {
                        "role": role,
                        "host": host,
                        "sent": 4,
                        "received": 4,
                        "loss_pct": 0.0,
                        "rtt_ms": {"min": 1.0, "avg": 2.0, "max": 3.0},
                    }
                    for role, host in (
                        ("gateway", GW),
                        ("public_cloudflare", "1.1.1.1"),
                        ("public_google", "8.8.8.8"),
                    )
                ]
            },
        ),
        "dns": ProbeResult(
            "dns",
            ok=True,
            data={
                "test_name": "www.google.com",
                "has_configured": True,
                "servers": [
                    {"server": GW, "role": "configured", "ok": True, "ms": 5.0, "error": None},
                    {"server": "1.1.1.1", "role": "public", "ok": True, "ms": 9.0, "error": None},
                ],
            },
        ),
        "http": ProbeResult(
            "http",
            ok=True,
            data={
                "ncsi": {
                    "status": 200,
                    "error": None,
                    "content_ok": True,
                    "redirected": False,
                    "redirect_host": None,
                    "ms": 10.0,
                },
                "https": {"status": 204, "error": None, "ok": True, "ms": 20.0},
            },
        ),
        "neighbors": ProbeResult(
            "neighbors",
            ok=True,
            data=parse_networks(fixture_text("neighbors/pt_multi.txt"), "MinhaRede"),
        ),
        "devices": ProbeResult(
            "devices",
            ok=True,
            data={
                "count": 2,
                "devices": [
                    {
                        "ip": GW,
                        "mac": "00:00:5e:00:53:01",
                        "gateway": True,
                        "randomized_mac": False,
                    },
                    {
                        "ip": "192.168.0.53",
                        "mac": "da:11:22:33:44:55",
                        "gateway": False,
                        "randomized_mac": True,
                    },
                ],
            },
        ),
        "hops": ProbeResult(
            "hops", ok=True, data=parse_tracert(fixture_text("hops/pt_loss_isp.txt"))
        ),
    }
    results.update(override)
    return list(results.values())


def test_analyze_collects_everything_with_text(fixture_text):
    tech = analyze(_tech_results(fixture_text), T)
    codes = [f["code"] for f in tech["findings"]]
    assert codes == ["CHANNEL_CONGESTED", "CHANNEL_BUSY", "ROUTE_LOSS_ISP", "DEVICES_SEEN"]
    texts = {f["code"]: (f["text"], f["action_text"]) for f in tech["findings"]}
    assert texts["CHANNEL_CONGESTED"][1] == "Trocar o canal do roteador para 11."
    assert "salto 2" in texts["ROUTE_LOSS_ISP"][0]
    assert texts["DEVICES_SEEN"][0].startswith("2 aparelho(s)")
    assert "1 com MAC aleatório" in texts["DEVICES_SEEN"][0]
    assert tech["notes"] == []


def test_failed_tech_probe_becomes_note_not_finding(fixture_text):
    results = _tech_results(
        fixture_text,
        hops=ProbeResult("hops", ok=False, error="TIMEOUT"),
        neighbors=ProbeResult("neighbors", ok=False, error="LOCATION_PERMISSION"),
    )
    tech = analyze(results, T)
    assert [f["code"] for f in tech["findings"]] == ["DEVICES_SEEN"]
    assert tech["notes"] == [
        "Redes vizinhas: não foi possível medir (LOCATION_PERMISSION).",
        "Saltos (tracert): não foi possível medir (TIMEOUT).",
    ]


def test_skipped_neighbors_on_cable(fixture_text):
    results = _tech_results(
        fixture_text, neighbors=ProbeResult("neighbors", ok=True, data={"skipped": "not_wifi"})
    )
    codes = [f["code"] for f in analyze(results, T)["findings"]]
    assert not any(c.startswith("CHANNEL") for c in codes)


# --- Pipeline, CLI, relatórios -----------------------------------------------------


def test_pipeline_tech_runs_extra_probes_and_keeps_client_diagnosis(fixture_text):
    seen = {}

    def runner(**kwargs):
        seen.update(kwargs)
        return _tech_results(fixture_text)

    out = run_pipeline(runner=runner, llm_config=None, tech=True)
    assert seen["parallel"] == PARALLEL + TECH_PROBES
    assert seen["timeout"] == TECH_TIMEOUT_S
    assert out.diagnosis.primary.code == "ALL_OK"  # o Modo Técnico não muda o diagnóstico
    assert [f["code"] for f in out.report["tech"]["findings"]][0] == "CHANNEL_CONGESTED"


def test_pipeline_client_mode_has_no_tech_section(fixture_text):
    out = run_pipeline(runner=lambda **k: _tech_results(fixture_text), llm_config=None)
    assert "tech" not in out.report


def test_tech_mode_sends_nothing_technical_to_ai(fixture_text):
    calls = []

    def transport(url, headers, body, timeout):
        calls.append(body.decode() if isinstance(body, bytes) else body)
        raise TimeoutError

    run_pipeline(
        runner=lambda **k: _tech_results(fixture_text),
        llm_config=LLMConfig("ollama", "m", "http://localhost:11434/v1", None, 1.0),
        transport=transport,
        tech=True,
    )
    assert len(calls) == 1
    for secret in ("00:00:5e", "da:11:22", "100.64.0.1", "203.0.113.1", "CHANNEL", "MinhaRede"):
        assert secret not in calls[0]


def test_cli_tech_json(monkeypatch, capsys, fixture_text):
    monkeypatch.setattr(cli, "run_all", lambda **kwargs: _tech_results(fixture_text))
    assert cli.main(["tech", "--json", "--sem-ia"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tech"]["findings"][0]["code"] == "CHANNEL_CONGESTED"


def test_cli_tech_text_and_html(monkeypatch, capsys, tmp_path, fixture_text):
    monkeypatch.setattr(cli, "run_all", lambda **kwargs: _tech_results(fixture_text))
    path = tmp_path / "laudo.html"
    assert cli.main(["tech", "--sem-ia", "--html", str(path)]) == 0
    out = capsys.readouterr().out
    assert "--- Laudo técnico ---" in out
    assert "-> Trocar o canal do roteador para 11." in out
    assert "[hops] 5 saltos até 1.1.1.1 (chegou)" in out
    assert "[neighbors] 7 pontos de acesso visíveis (2 da própria rede)" in out
    html = path.read_text(encoding="utf-8")
    assert "<h1>NetDoctor — Laudo técnico</h1>" in html
    assert "Caminho até a internet (tracert)" in html
    assert "Vizinho" not in html  # nomes das redes vizinhas nunca são guardados
    assert "aparelhos conectados (MAC)" in html


def test_client_html_unchanged_title(fixture_text):
    out = run_pipeline(runner=lambda **k: _tech_results(fixture_text)[:5], llm_config=None)
    assert "<h1>NetDoctor — Relatório técnico</h1>" in render_html(out.report)
