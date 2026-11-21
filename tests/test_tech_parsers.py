"""Parsers do Modo Técnico: netsh networks (PT/EN), tracert (PT/EN) e Get-NetNeighbor."""

from __future__ import annotations

import json

import pytest

from netdoctor.core.probes import wifi
from netdoctor.tech.devices import is_randomized_mac, parse_neighbors
from netdoctor.tech.hops import parse_tracert
from netdoctor.tech.neighbors import parse_networks

# --- Redes vizinhas ----------------------------------------------------------------


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_networks_multi(fixture_text, lang):
    data = parse_networks(fixture_text(f"neighbors/{lang}_multi.txt"), own_ssid="MinhaRede")
    aps = data["access_points"]
    assert data["error"] is None
    assert len(aps) == 7
    own = [(ap["band"], ap["channel"]) for ap in aps if ap["own"]]
    assert own == [("5 GHz", 36), ("2.4 GHz", 6)]  # as duas bandas da própria rede
    assert sum(ap["hidden"] for ap in aps) == 1
    assert aps[1]["utilization_pct"] == 70 and aps[1]["stations"] == 5
    assert aps[2] == {
        "own": False,
        "hidden": False,
        "signal_pct": 70,
        "channel": 6,
        "band": "2.4 GHz",
        "radio": "802.11n",
        "stations": None,
        "utilization_pct": None,
    }


def test_networks_pt_and_en_are_equal(fixture_text):
    pt = parse_networks(fixture_text("neighbors/pt_multi.txt"), "MinhaRede")
    en = parse_networks(fixture_text("neighbors/en_multi.txt"), "MinhaRede")
    assert pt == en


def test_networks_single_real_capture(fixture_text):
    aps = parse_networks(fixture_text("neighbors/pt_single.txt"), "MinhaRede")["access_points"]
    assert len(aps) == 1
    assert aps[0]["own"] and aps[0]["channel"] == 36 and aps[0]["utilization_pct"] == 0


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_neighbor_names_and_bssids_are_not_kept(fixture_text, lang):
    data = parse_networks(fixture_text(f"neighbors/{lang}_multi.txt"), "MinhaRede")
    text = json.dumps(data)
    for secret in ("MinhaRede", "Vizinho", "aa:bb:cc", "11:22:33"):
        assert secret not in text


def test_without_own_ssid_nothing_is_marked_own(fixture_text):
    aps = parse_networks(fixture_text("neighbors/pt_multi.txt"))["access_points"]
    assert not any(ap["own"] for ap in aps)


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_networks_location_permission(fixture_text, lang):
    data = parse_networks(fixture_text(f"wifi/{lang}_location.txt"))
    assert data == {"error": wifi.LOCATION_PERMISSION}


# --- Saltos ------------------------------------------------------------------------


def test_tracert_pt_real_capture(fixture_text):
    data = parse_tracert(fixture_text("hops/pt_ok.txt"))
    assert data["reached"] is True
    assert [h["hop"] for h in data["hops"]] == list(range(1, 9))
    first, last = data["hops"][0], data["hops"][-1]
    assert first == {
        "hop": 1,
        "ip": "192.168.0.1",
        "rtt_ms": [1.0, 1.0, 1.0],
        "loss_pct": 0.0,
        "avg_ms": 1.0,
    }
    assert last["ip"] == "1.1.1.1" and last["avg_ms"] == 18.3


def test_tracert_silent_hop_pt_and_en_are_equal(fixture_text):
    pt = parse_tracert(fixture_text("hops/pt_silent_hop.txt"))
    en = parse_tracert(fixture_text("hops/en_ok.txt"))
    assert pt == en
    silent = pt["hops"][2]
    assert silent == {
        "hop": 3,
        "ip": None,
        "rtt_ms": [None, None, None],
        "loss_pct": 100.0,
        "avg_ms": None,
    }


def test_tracert_partial_loss(fixture_text):
    hops = parse_tracert(fixture_text("hops/pt_loss_isp.txt"))["hops"]
    assert hops[1]["rtt_ms"] == [9.0, None, 8.0]
    assert hops[1]["loss_pct"] == 33.3
    assert hops[3]["loss_pct"] == 66.7 and hops[3]["ip"] == "198.51.100.1"


def test_tracert_incomplete(fixture_text):
    data = parse_tracert(fixture_text("hops/en_incomplete.txt"))
    assert data["reached"] is False
    assert len(data["hops"]) == 5


def test_tracert_less_than_one_ms_counts_as_one(fixture_text):
    assert parse_tracert(fixture_text("hops/en_ok.txt"))["hops"][0]["rtt_ms"] == [1.0] * 3


def test_tracert_garbage():
    assert parse_tracert("nada aqui\n") == {"target": "1.1.1.1", "reached": False, "hops": []}


# --- Aparelhos ---------------------------------------------------------------------


def _devices(fixture_text, name="devices/neighbors.json", **kw):
    return parse_neighbors(json.loads(fixture_text(name)), **kw)


def test_devices_filters_multicast_broadcast_and_dead_entries(fixture_text):
    data = _devices(fixture_text, gateway="192.168.0.1", ipv4="192.168.0.10", prefix=24)
    assert data["count"] == 4
    assert [d["ip"] for d in data["devices"]] == [
        "192.168.0.1",
        "192.168.0.41",
        "192.168.0.48",
        "192.168.0.53",
    ]
    assert data["devices"][0] == {
        "ip": "192.168.0.1",
        "mac": "00:00:5e:00:53:01",
        "gateway": True,
        "randomized_mac": False,
    }
    assert data["devices"][-1]["randomized_mac"] is True


def test_devices_without_subnet_still_drops_global_broadcast(fixture_text):
    ips = [d["ip"] for d in _devices(fixture_text)["devices"]]
    assert "255.255.255.255" not in ips and "224.0.0.251" not in ips


def test_devices_single_object_from_powershell_51(fixture_text):
    data = _devices(fixture_text, "devices/single_object.json", gateway="192.168.0.1")
    assert data["count"] == 1 and data["devices"][0]["gateway"]


def test_devices_empty():
    assert parse_neighbors([]) == {"count": 0, "devices": []}


@pytest.mark.parametrize(
    ("mac", "expected"),
    [("00-00-5E-00-53-01", False), ("DA-11-22-33-44-55", True), ("02:00:00:00:00:01", True)],
)
def test_randomized_mac(mac, expected):
    assert is_randomized_mac(mac) is expected
