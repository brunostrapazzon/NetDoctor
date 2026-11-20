import json

from netdoctor.core.models import ErrorCode
from netdoctor.core.probes import adapter
from netdoctor.core.probes.adapter import select_active
from netdoctor.core.proc import CommandTimeout


def _load(fixture_text, name):
    return json.loads(fixture_text(f"adapter/{name}.json"))


def test_wifi_wins_over_virtualbox(fixture_text):
    data = select_active(_load(fixture_text, "wifi_with_virtualbox"))
    assert data == {
        "connected": True,
        "interface": "Wi-Fi",
        "type": "wifi",
        "ipv4": "192.168.0.10",
        "prefix": 24,
        "apipa": False,
        "gateway": "192.168.0.1",
        "dns_servers": ["203.0.113.53", "203.0.113.54"],
    }


def test_cable_without_dhcp_is_apipa(fixture_text):
    data = select_active(_load(fixture_text, "ethernet_apipa"))
    assert data["connected"] is True
    assert data["type"] == "ethernet"
    assert data["apipa"] is True
    assert data["gateway"] is None


def test_only_virtual_adapter_up_means_no_link(fixture_text):
    data = select_active(_load(fixture_text, "no_link_virtual_only"))
    assert data["connected"] is False
    assert data["interface"] is None


def test_powershell_collapsed_single_items(fixture_text):
    data = select_active(_load(fixture_text, "single_adapter_object"))
    assert data["interface"] == "Wi-Fi"
    assert data["gateway"] == "192.168.0.1"
    assert data["dns_servers"] == ["192.168.0.1"]


def test_lowest_metric_route_wins():
    raw = {
        "adapters": [
            {
                "name": "VPN",
                "index": 30,
                "status": "Up",
                "media": "",
                "hardware": False,
                "virtual": True,
            },
            {
                "name": "Wi-Fi",
                "index": 15,
                "status": "Up",
                "media": "Native 802.11",
                "hardware": True,
                "virtual": False,
            },
        ],
        "addresses": [
            {"index": 30, "ip": "10.8.0.2", "prefix": 24},
            {"index": 15, "ip": "192.168.0.10", "prefix": 24},
        ],
        "routes": [
            {"index": 15, "gateway": "192.168.0.1", "metric": 50},
            {"index": 30, "gateway": "10.8.0.1", "metric": 5},
        ],
        "dns": [],
    }
    data = select_active(raw)
    assert data["interface"] == "VPN"
    assert data["type"] == "other"


def test_timeout_is_reported_not_raised(monkeypatch):
    monkeypatch.setattr(adapter.sys, "platform", "win32")

    def boom(*args, **kwargs):
        raise CommandTimeout("lento")

    monkeypatch.setattr(adapter, "run_command", boom)
    result = adapter.run()
    assert result.ok is False
    assert result.error == ErrorCode.TIMEOUT


def test_invalid_json_is_parse_error(monkeypatch):
    monkeypatch.setattr(adapter.sys, "platform", "win32")
    monkeypatch.setattr(adapter, "run_command", lambda *a, **k: (0, "não é json"))
    result = adapter.run()
    assert result.error == ErrorCode.PARSE_ERROR


def test_bom_is_tolerated(monkeypatch, fixture_text):
    monkeypatch.setattr(adapter.sys, "platform", "win32")
    body = "﻿" + fixture_text("adapter/wifi_with_virtualbox.json")
    monkeypatch.setattr(adapter, "run_command", lambda *a, **k: (0, body))
    assert adapter.run().ok
