"""Cada regra: dispara, limite do limiar, precedência na cadeia e probe sem medição.

Os cenários de ping usam as fixtures reais (PT e EN) passando por parse_ping,
para garantir que regra + parser funcionam juntos nos dois idiomas.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from netdoctor.core.models import ProbeResult
from netdoctor.core.probes.ping import parse_ping
from netdoctor.core.rules import Thresholds, diagnose, load_thresholds

FIXTURES = Path(__file__).parent / "fixtures" / "ping"
T = Thresholds(wifi_weak_signal_pct=50, gateway_high_loss_pct=20, gateway_high_avg_rtt_ms=50)
LANGS = ["pt", "en"]

# --- Construtores de resultados de probe -------------------------------------------


def adapter(connected=True, type_="wifi", ipv4="192.168.0.10", apipa=False, gateway="192.168.0.1"):
    return ProbeResult(
        "adapter",
        ok=True,
        data={
            "connected": connected,
            "interface": "Wi-Fi" if connected else None,
            "type": type_ if connected else None,
            "ipv4": ipv4 if connected else None,
            "prefix": 24,
            "apipa": apipa,
            "gateway": gateway if connected else None,
            "dns_servers": ["192.168.0.1"],
        },
    )


def target(role, host, lang="pt", fixture="ok", **override):
    text = (FIXTURES / f"{lang}_{fixture}.txt").read_text(encoding="utf-8")
    return {"role": role, "host": host, **parse_ping(text, sent=4), "error": None, **override}


def ping(gw="ok", public="ok", lang="pt", gw_override=None):
    gateway = (
        {"role": "gateway", "host": None, "error": "NO_GATEWAY"}
        if gw is None
        else target("gateway", "192.168.0.1", lang, gw, **(gw_override or {}))
    )
    return ProbeResult(
        "ping",
        ok=True,
        data={
            "targets": [
                gateway,
                target("public_cloudflare", "1.1.1.1", lang, public),
                target("public_google", "8.8.8.8", lang, public),
            ]
        },
    )


def dns(configured_ok=True, public_ok=True, configured=True):
    servers = []
    if configured:
        servers.append(
            {
                "server": "192.168.0.1",
                "role": "configured",
                "ok": configured_ok,
                "ms": 10.0 if configured_ok else None,
                "error": None if configured_ok else "TIMEOUT",
            }
        )
    for s in ("1.1.1.1", "8.8.8.8"):
        servers.append(
            {
                "server": s,
                "role": "public",
                "ok": public_ok,
                "ms": 20.0 if public_ok else None,
                "error": None if public_ok else "TIMEOUT",
            }
        )
    return ProbeResult(
        "dns", ok=True, data={"test_name": "x", "has_configured": configured, "servers": servers}
    )


def http(ncsi_status=200, content_ok=True, redirected=False, https_ok=True, https_error=None):
    return ProbeResult(
        "http",
        ok=True,
        data={
            "ncsi": {
                "status": ncsi_status,
                "error": None if ncsi_status else "DNS_ERROR",
                "content_ok": content_ok,
                "redirected": redirected,
                "redirect_host": "login.hotel.example" if redirected else None,
                "ms": 30.0,
            },
            "https": {
                "status": 204 if https_ok else None,
                "error": https_error,
                "ok": https_ok,
                "ms": 40.0,
            },
        },
    )


HTTP_DOWN = dict(ncsi_status=None, content_ok=False, https_ok=False, https_error="DNS_ERROR")


def wifi(signal):
    return ProbeResult("wifi", ok=True, data={"signal_pct": signal})


def failed(name):
    return ProbeResult(name, ok=False, error="TIMEOUT")


def healthy(lang="pt", **replace):
    parts = {
        "adapter": adapter(),
        "ping": ping(lang=lang),
        "dns": dns(),
        "http": http(),
        "wifi": wifi(80),
    }
    parts.update(replace)
    return [p for p in parts.values() if p is not None]


def run(results):
    return diagnose(results, T)


# --- Limiares -----------------------------------------------------------------------


def test_default_thresholds_file_loads():
    t = load_thresholds()
    assert t.wifi_weak_signal_pct == 50
    assert t.gateway_high_loss_pct == 20
    assert t.gateway_high_avg_rtt_ms == 50


def test_custom_thresholds_file(tmp_path):
    f = tmp_path / "t.toml"
    f.write_text(
        "[wifi]\nweak_signal_pct = 30\n[gateway]\nhigh_loss_pct = 50\nhigh_avg_rtt_ms = 10\n",
        encoding="utf-8",
    )
    assert load_thresholds(f).wifi_weak_signal_pct == 30


# --- ALL_OK / INCONCLUSIVE ------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_all_ok(lang):
    d = run(healthy(lang))
    assert d.codes() == ["ALL_OK"]
    assert d.primary.action == "CHECK_SITE_OR_APP"


@pytest.mark.parametrize("missing", ["adapter", "ping", "http"])
def test_unmeasured_core_probe_is_inconclusive_not_ok(missing):
    d = run(healthy(**{missing: failed(missing)}))
    assert d.codes() == ["INCONCLUSIVE"]


# --- NO_LINK --------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_no_link(lang):
    results = healthy(
        lang,
        adapter=adapter(connected=False),
        ping=ping(gw=None, public="timeout", lang=lang),
        http=http(**HTTP_DOWN),
        dns=dns(configured=False, public_ok=False),
    )
    d = run(results)
    assert d.primary.code == "NO_LINK"
    assert d.primary.severity == "critical"


def test_no_link_not_inferred_when_adapter_unmeasured():
    d = run(healthy(adapter=failed("adapter"), ping=ping(gw=None, public="timeout")))
    assert "NO_LINK" not in d.codes()


# --- NO_DHCP --------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_no_dhcp_apipa(lang):
    results = healthy(
        lang,
        adapter=adapter(ipv4="169.254.19.122", apipa=True, gateway=None),
        ping=ping(gw=None, public="timeout", lang=lang),
        http=http(**HTTP_DOWN),
    )
    d = run(results)
    assert d.primary.code == "NO_DHCP"
    assert d.primary.evidence == {"ipv4": "169.254.19.122", "apipa": True}
    assert d.primary.action == "RESTART_ROUTER"


def test_no_dhcp_without_any_ip():
    d = run(healthy(adapter=adapter(ipv4=None, gateway=None)))
    assert d.primary.code == "NO_DHCP"


def test_no_link_wins_over_no_dhcp():
    d = run(healthy(adapter=adapter(connected=False)))
    assert d.primary.code == "NO_LINK"
    assert "NO_DHCP" not in d.codes()


# --- GATEWAY_DOWN ---------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("fixture", ["timeout", "unreachable"])
def test_gateway_down(lang, fixture):
    results = healthy(
        lang, ping=ping(gw=fixture, public="timeout", lang=lang), http=http(**HTTP_DOWN)
    )
    d = run(results)
    assert d.primary.code == "GATEWAY_DOWN"
    assert d.primary.evidence["gateway_loss_pct"] == 100.0


def test_gateway_down_without_default_route():
    results = healthy(
        adapter=adapter(gateway=None), ping=ping(gw=None, public="timeout"), http=http(**HTTP_DOWN)
    )
    d = run(results)
    assert d.primary.code == "GATEWAY_DOWN"
    assert d.primary.evidence == {"reason": "no_default_route"}


@pytest.mark.parametrize("lang", LANGS)
def test_router_that_ignores_ping_is_not_gateway_down(lang):
    d = run(healthy(lang, ping=ping(gw="timeout", lang=lang)))
    assert "GATEWAY_DOWN" not in d.codes()
    assert d.primary.code == "ALL_OK"


def test_no_dhcp_wins_over_gateway_down():
    d = run(
        healthy(
            adapter=adapter(ipv4="169.254.1.1", apipa=True, gateway=None),
            ping=ping(gw=None, public="timeout"),
        )
    )
    assert d.codes()[0] == "NO_DHCP"
    assert "GATEWAY_DOWN" not in d.codes()


def test_gateway_down_with_weak_wifi_keeps_both():
    d = run(
        healthy(ping=ping(gw="timeout", public="timeout"), http=http(**HTTP_DOWN), wifi=wifi(20))
    )
    assert d.primary.code == "GATEWAY_DOWN"
    assert "WIFI_WEAK" in d.codes()


# --- ISP_DOWN -------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_isp_down(lang):
    results = healthy(lang, ping=ping(public="timeout", lang=lang), http=http(**HTTP_DOWN))
    d = run(results)
    assert d.primary.code == "ISP_DOWN"
    assert d.primary.evidence["public_loss_pct"] == [100.0, 100.0]
    assert d.primary.action == "CALL_ISP"


def test_isp_icmp_blocked_but_https_works_is_not_isp_down():
    d = run(healthy(ping=ping(public="timeout")))
    assert "ISP_DOWN" not in d.codes()


def test_portal_blocking_ping_is_captive_not_isp_down():
    results = healthy(
        ping=ping(public="timeout"),
        http=http(ncsi_status=302, content_ok=False, redirected=True, https_ok=False),
    )
    d = run(results)
    assert d.primary.code == "CAPTIVE_PORTAL"
    assert "ISP_DOWN" not in d.codes()


def test_isp_down_needs_http_measured():
    d = run(healthy(ping=ping(public="timeout"), http=failed("http")))
    assert "ISP_DOWN" not in d.codes()


def test_gateway_down_wins_over_isp_down():
    d = run(healthy(ping=ping(gw="timeout", public="timeout"), http=http(**HTTP_DOWN)))
    assert d.codes()[0] == "GATEWAY_DOWN"
    assert "ISP_DOWN" not in d.codes()


# --- DNS_FAIL -------------------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_dns_fail(lang):
    results = healthy(
        lang,
        dns=dns(configured_ok=False),
        http=http(ncsi_status=None, content_ok=False, https_ok=False, https_error="DNS_ERROR"),
    )
    d = run(results)
    assert d.primary.code == "DNS_FAIL"
    assert d.primary.evidence == {"reason": "configured_failed", "errors": ["TIMEOUT"]}
    assert d.primary.action == "CHANGE_DNS"


def test_dns_fail_when_no_dns_configured():
    d = run(healthy(dns=dns(configured=False)))
    assert d.primary.code == "DNS_FAIL"
    assert d.primary.evidence == {"reason": "no_dns_configured"}


def test_all_dns_failing_is_not_dns_fail():
    # Se nem o DNS público responde, não dá para culpar o DNS configurado.
    d = run(healthy(dns=dns(configured_ok=False, public_ok=False)))
    assert "DNS_FAIL" not in d.codes()


def test_isp_down_wins_over_dns_fail():
    results = healthy(
        ping=ping(public="timeout"),
        dns=dns(configured_ok=False),
        http=http(**HTTP_DOWN),
    )
    d = run(results)
    assert d.codes()[0] == "ISP_DOWN"
    assert "DNS_FAIL" not in d.codes()


def test_dns_unmeasured_does_not_fire():
    d = run(healthy(dns=failed("dns")))
    assert d.codes() == ["ALL_OK"]


# --- CAPTIVE_PORTAL -------------------------------------------------------------------


def test_captive_portal_redirect():
    d = run(healthy(http=http(ncsi_status=302, content_ok=False, redirected=True)))
    assert d.primary.code == "CAPTIVE_PORTAL"
    assert d.primary.evidence["redirect_host"] == "login.hotel.example"


def test_captive_portal_wrong_content():
    d = run(healthy(http=http(ncsi_status=200, content_ok=False)))
    assert d.primary.code == "CAPTIVE_PORTAL"


def test_captive_portal_tls_interception():
    d = run(healthy(http=http(https_ok=False, https_error="TLS_ERROR")))
    assert d.primary.code == "CAPTIVE_PORTAL"
    assert d.primary.evidence == {"https_error": "TLS_ERROR"}


def test_dns_fail_wins_over_captive_portal():
    results = healthy(
        dns=dns(configured_ok=False),
        http=http(ncsi_status=200, content_ok=False),
    )
    d = run(results)
    assert d.codes()[0] == "DNS_FAIL"
    assert "CAPTIVE_PORTAL" in d.codes()


# --- WIFI_WEAK ------------------------------------------------------------------------


@pytest.mark.parametrize(("signal", "fires"), [(49, True), (50, False), (51, False), (10, True)])
def test_wifi_weak_threshold_boundary(signal, fires):
    d = run(healthy(wifi=wifi(signal)))
    assert ("WIFI_WEAK" in d.codes()) is fires


def test_wifi_weak_evidence():
    d = run(healthy(wifi=wifi(30)))
    assert d.primary.code == "WIFI_WEAK"
    assert d.primary.severity == "warning"
    assert d.primary.evidence == {"signal_pct": 30, "threshold_pct": 50}


def test_wifi_weak_ignored_on_cable():
    d = run(healthy(adapter=adapter(type_="ethernet"), wifi=wifi(10)))
    assert "WIFI_WEAK" not in d.codes()


def test_wifi_unmeasured_does_not_fire():
    d = run(healthy(wifi=failed("wifi")))
    assert d.codes() == ["ALL_OK"]


def test_captive_portal_wins_over_wifi_weak():
    d = run(healthy(http=http(ncsi_status=302, content_ok=False, redirected=True), wifi=wifi(10)))
    assert d.codes() == ["CAPTIVE_PORTAL", "WIFI_WEAK"]


# --- LOCAL_INTERFERENCE ---------------------------------------------------------------


@pytest.mark.parametrize("lang", LANGS)
def test_local_interference_by_loss(lang):
    # Fixture real: 2 de 4 pacotes perdidos até o roteador (50%).
    d = run(healthy(lang, ping=ping(gw="partial_lt1ms", lang=lang)))
    assert d.primary.code == "LOCAL_INTERFERENCE"
    assert d.primary.evidence["gateway_loss_pct"] == 50.0


@pytest.mark.parametrize(("loss", "fires"), [(19.9, False), (20.0, True), (25.0, True)])
def test_local_interference_loss_boundary(loss, fires):
    d = run(healthy(ping=ping(gw_override={"loss_pct": loss})))
    assert ("LOCAL_INTERFERENCE" in d.codes()) is fires


@pytest.mark.parametrize(("avg", "fires"), [(49.9, False), (50.0, True), (120.0, True)])
def test_local_interference_latency_boundary(avg, fires):
    rtt = {"min": 1.0, "avg": avg, "max": avg}
    d = run(healthy(ping=ping(gw_override={"rtt_ms": rtt})))
    assert ("LOCAL_INTERFERENCE" in d.codes()) is fires


def test_wifi_weak_wins_over_local_interference():
    d = run(healthy(ping=ping(gw="partial_lt1ms"), wifi=wifi(20)))
    assert d.codes() == ["WIFI_WEAK", "LOCAL_INTERFERENCE"]


def test_local_interference_unmeasured_gateway_does_not_fire():
    d = run(healthy(ping=ping(gw=None)))
    assert "LOCAL_INTERFERENCE" not in d.codes()


# --- Relatório ------------------------------------------------------------------------


def test_diagnosis_to_dict():
    d = run(healthy(wifi=wifi(30)))
    out = d.to_dict()
    assert out["primary"] == "WIFI_WEAK"
    assert out["findings"][0]["severity"] == "warning"
