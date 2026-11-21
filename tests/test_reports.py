import json
from datetime import UTC, datetime

from netdoctor.core.models import ProbeResult
from netdoctor.core.rules import diagnose
from netdoctor.explain.templates import explain
from netdoctor.report.html_report import render_html, write_html
from netdoctor.report.json_report import build_report, to_json, write_json


def _results(ssid="MinhaRede"):
    return [
        ProbeResult(
            "adapter",
            ok=True,
            data={
                "connected": True,
                "interface": "Wi-Fi",
                "type": "wifi",
                "ipv4": "192.168.0.10",
                "prefix": 24,
                "apipa": False,
                "gateway": "192.168.0.1",
                "dns_servers": ["192.168.0.1"],
            },
        ),
        ProbeResult(
            "wifi",
            ok=True,
            data={
                "error": None,
                "connected": True,
                "interfaces": 1,
                "ssid": ssid,
                "signal_pct": 30,
                "rssi_dbm": -85,
                "channel": 6,
                "band": "2.4 GHz",
                "radio": "802.11n",
            },
        ),
        ProbeResult(
            "ping",
            ok=True,
            data={
                "targets": [
                    {
                        "role": "gateway",
                        "host": "192.168.0.1",
                        "sent": 4,
                        "received": 4,
                        "loss_pct": 0.0,
                        "rtt_ms": {"min": 1.0, "avg": 2.0, "max": 3.0},
                        "error": None,
                    },
                    {
                        "role": "public_cloudflare",
                        "host": "1.1.1.1",
                        "sent": 4,
                        "received": 4,
                        "loss_pct": 0.0,
                        "rtt_ms": {"min": 18.0, "avg": 19.0, "max": 21.0},
                        "error": None,
                    },
                ]
            },
        ),
        ProbeResult(
            "dns",
            ok=True,
            data={
                "test_name": "www.google.com",
                "has_configured": True,
                "servers": [
                    {
                        "server": "192.168.0.1",
                        "role": "configured",
                        "ok": True,
                        "ms": 9.0,
                        "error": None,
                    }
                ],
            },
        ),
        ProbeResult(
            "http",
            ok=True,
            data={
                "ncsi": {
                    "status": 200,
                    "error": None,
                    "content_ok": True,
                    "redirected": False,
                    "redirect_host": None,
                    "ms": 30.0,
                },
                "https": {"status": 204, "error": None, "ok": True, "ms": 40.0},
            },
        ),
    ]


def _report(results):
    diagnosis = diagnose(results)
    when = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)
    return build_report(results, diagnosis, explain(diagnosis, results), generated_at=when)


def test_json_report_roundtrip(tmp_path):
    report = _report(_results())
    path = write_json(report, tmp_path / "r.json")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["diagnosis"]["primary"] == "WIFI_WEAK"
    assert loaded["explanation"]["headline"] == "Seu Wi-Fi está fraco neste lugar."
    assert loaded["generated_at"] == "2026-11-20T12:00:00+00:00"
    assert [p["name"] for p in loaded["probes"]] == ["adapter", "wifi", "ping", "dns", "http"]
    assert "está" in to_json(report)  # acentos legíveis, sem á


def test_html_is_self_contained(tmp_path):
    html = render_html(_report(_results()))
    assert html.startswith("<!doctype html>")
    assert "Seu Wi-Fi está fraco neste lugar." in html
    assert "Força do sinal: 30%" in html
    assert "WIFI_WEAK" in html
    # Nada externo: abre offline e não vaza nada ao abrir.
    for needle in ("<script src", "<link ", "http://", "https://", "@import", "url("):
        assert needle not in html.split("<pre>")[0], needle
    path = write_html(_report(_results()), tmp_path / "r.html")
    assert path.read_text(encoding="utf-8") == html


def test_html_escapes_hostile_ssid():
    html = render_html(_report(_results(ssid='<script>alert("x")</script>')))
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_html_shows_failed_probe():
    results = _results()
    results[3] = ProbeResult("dns", ok=False, error="TIMEOUT")
    html = render_html(_report(results))
    assert "Não foi possível medir" in html


def test_html_is_accessible_and_readable_on_phones():
    html = render_html(_report(_results()))
    assert 'name="viewport"' in html
    assert "prefers-color-scheme:dark" in html
    assert "prefers-reduced-motion" in html  # a única transição respeita o pedido do sistema
    assert "transition:all" not in html
    assert ":focus-visible" in html
    assert '<th scope="col">Gravidade</th>' in html
    assert 'role="region" aria-label="Achados" tabindex="0"' in html  # tabela rola pelo teclado
    # Gravidade com ícone e texto, não só cor.
    assert '<span aria-hidden="true">⚠</span>Atenção' in html
    # Sumário com âncoras para cada seção que existe.
    for anchor in ("resultado", "achados", "probe-wifi", "probe-http", "dados"):
        assert f'href="#{anchor}"' in html and f'id="{anchor}"' in html
    assert 'href="#laudo"' not in html  # sem Modo Técnico, sem laudo
    assert '<time datetime="2026-11-20T12:00:00+00:00">20/11/2026 às 12:00 (UTC)</time>' in html


def test_html_numbers_are_right_aligned():
    html = render_html(_report(_results()))
    assert '<th scope="col" class="num">Média (ms)</th>' in html
    assert '<td class="num">19.0</td>' in html


def test_html_evidence_is_escaped():
    report = _report(_results())
    report["diagnosis"]["findings"][0]["evidence"] = {"<b>": "<i>x</i>"}
    html = render_html(report)
    assert "<b>" not in html.split("<pre")[0]
    assert "<code>&lt;b&gt;: &lt;i&gt;x&lt;/i&gt;</code>" in html
