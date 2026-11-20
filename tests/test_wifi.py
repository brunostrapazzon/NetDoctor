import pytest

from netdoctor.core.models import ErrorCode
from netdoctor.core.probes import wifi
from netdoctor.core.probes.wifi import LOCATION_PERMISSION, NO_WIFI_INTERFACE, parse_interfaces
from netdoctor.core.proc import CommandTimeout, decode_output

LANGS = ["pt", "en"]


@pytest.mark.parametrize("lang", LANGS)
def test_connected(fixture_text, lang):
    data = parse_interfaces(fixture_text(f"wifi/{lang}_connected.txt"))
    assert data == {
        "error": None,
        "connected": True,
        "interfaces": 1,
        "ssid": "MinhaRede_5G",
        "signal_pct": 100,
        "rssi_dbm": -43,
        "channel": 36,
        "band": "5 GHz",
        "radio": "802.11ac",
    }


@pytest.mark.parametrize("lang", LANGS)
def test_weak_signal_values(fixture_text, lang):
    data = parse_interfaces(fixture_text(f"wifi/{lang}_connected_weak.txt"))
    assert data["signal_pct"] == 38
    assert data["rssi_dbm"] == -81


@pytest.mark.parametrize("lang", LANGS)
def test_disconnected(fixture_text, lang):
    data = parse_interfaces(fixture_text(f"wifi/{lang}_disconnected.txt"))
    assert data["connected"] is False
    assert data["signal_pct"] is None
    assert data["ssid"] is None


@pytest.mark.parametrize("lang", LANGS)
def test_no_wireless_interface(fixture_text, lang):
    assert parse_interfaces(fixture_text(f"wifi/{lang}_no_interface.txt")) == {
        "error": NO_WIFI_INTERFACE
    }


@pytest.mark.parametrize("lang", LANGS)
def test_location_permission(fixture_text, lang):
    assert parse_interfaces(fixture_text(f"wifi/{lang}_location.txt")) == {
        "error": LOCATION_PERMISSION
    }


def test_picks_the_connected_interface(fixture_text):
    data = parse_interfaces(fixture_text("wifi/en_two_interfaces.txt"))
    assert data["interfaces"] == 2
    assert data["signal_pct"] == 62
    assert data["channel"] == 6
    assert data["band"] == "2.4 GHz"


def test_ssid_label_does_not_match_bssid_value(fixture_text):
    data = parse_interfaces(fixture_text("wifi/pt_connected.txt"))
    assert data["ssid"] != "11:22:33:44:55:66"


def test_crlf_and_odd_spacing():
    text = "    Name : Wi-Fi\r\n    State   :   connected\r\n    Signal:  71 %\r\n"
    data = parse_interfaces(text)
    assert data["connected"] and data["signal_pct"] == 71


def test_netsh_utf8_output_is_decoded():
    # Captura real: o netsh do Windows 11 escreve UTF-8 quando redirecionado.
    raw = "    Tipo de rádio             : 802.11ac\n".encode()
    assert "rádio" in decode_output(raw)


def test_cp850_output_still_decoded(monkeypatch):
    raw = "Estatísticas do Ping".encode("cp850")
    monkeypatch.setattr("netdoctor.core.proc._default_encoding", lambda: "cp850")
    assert decode_output(raw) == "Estatísticas do Ping"


def test_location_permission_is_unknown_not_weak(monkeypatch, fixture_text):
    monkeypatch.setattr(wifi.sys, "platform", "win32")
    monkeypatch.setattr(
        wifi, "run_command", lambda *a, **k: (1, fixture_text("wifi/pt_location.txt"))
    )
    result = wifi.run({"type": "wifi"})
    assert result.ok is False
    assert result.error == LOCATION_PERMISSION


def test_cable_connection_skips_netsh(monkeypatch):
    monkeypatch.setattr(wifi.sys, "platform", "win32")

    def must_not_run(*a, **k):
        raise AssertionError("netsh não deveria rodar com cabo")

    monkeypatch.setattr(wifi, "run_command", must_not_run)
    result = wifi.run({"type": "ethernet"})
    assert result.ok and result.data == {"skipped": "not_wifi"}


def test_timeout(monkeypatch):
    monkeypatch.setattr(wifi.sys, "platform", "win32")

    def slow(*a, **k):
        raise CommandTimeout("x")

    monkeypatch.setattr(wifi, "run_command", slow)
    assert wifi.run({"type": "wifi"}).error == ErrorCode.TIMEOUT
