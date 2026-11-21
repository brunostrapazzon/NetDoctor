"""`run()` das probes técnicas com o comando simulado (sem rede, sem Windows real)."""

from __future__ import annotations

import base64
import json
import sys

import pytest

from netdoctor.core.proc import CommandTimeout
from netdoctor.tech import devices, hops, neighbors

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="probes só rodam no Windows")


def test_neighbors_skipped_on_cable():
    assert neighbors.run({"type": "ethernet"}).data == {"skipped": "not_wifi"}


def test_neighbors_marks_own_network_from_interfaces(monkeypatch, fixture_text):
    outputs = {
        "interfaces": fixture_text("wifi/pt_connected.txt"),
        # O fixture de wifi está conectado em "MinhaRede_5G".
        "networks": fixture_text("neighbors/pt_multi.txt").replace(
            "SSID 1 : MinhaRede", "SSID 1 : MinhaRede_5G"
        ),
    }

    def fake(args, timeout, encoding=None):
        return 0, outputs[args[3]]

    monkeypatch.setattr(neighbors, "run_command", fake)
    result = neighbors.run({"type": "wifi"})
    assert result.ok
    assert sum(ap["own"] for ap in result.data["access_points"]) == 2


def test_neighbors_location_error(monkeypatch, fixture_text):
    text = fixture_text("wifi/en_location.txt")
    monkeypatch.setattr(neighbors, "run_command", lambda *a, **k: (1, text))
    result = neighbors.run({"type": "wifi"})
    assert not result.ok and result.error == "LOCATION_PERMISSION"


def test_devices_passes_interface_by_environment(monkeypatch, fixture_text):
    seen = {}

    def fake(args, timeout, encoding=None, env_extra=None):
        seen["args"], seen["env"] = args, env_extra
        return 0, fixture_text("devices/neighbors.json")

    monkeypatch.setattr(devices, "run_command", fake)
    ctx = {"interface": "Wi-Fi'; Remove-Item x", "gateway": "192.168.0.1"}
    ctx |= {"ipv4": "192.168.0.10", "prefix": 24}
    result = devices.run(ctx)
    assert result.ok and result.data["count"] == 4
    assert seen["env"] == {"NETDOCTOR_IFACE": "Wi-Fi'; Remove-Item x"}
    script = base64.b64decode(seen["args"][-1]).decode("utf-16-le")
    assert "Remove-Item" not in script  # o nome nunca é colado no script


def test_devices_empty_output_means_no_devices(monkeypatch):
    monkeypatch.setattr(devices, "run_command", lambda *a, **k: (0, ""))
    assert devices.run({"interface": "Wi-Fi"}).data == {"count": 0, "devices": []}


def test_devices_skipped_without_interface():
    assert devices.run({}).data == {"skipped": "no_interface"}


def test_devices_bad_json(monkeypatch):
    monkeypatch.setattr(devices, "run_command", lambda *a, **k: (0, "{nao json"))
    assert devices.run({"interface": "Wi-Fi"}).error == "PARSE_ERROR"


def test_hops_uses_no_name_resolution(monkeypatch, fixture_text):
    seen = {}

    def fake(args, timeout, encoding=None):
        seen["args"] = args
        return 0, fixture_text("hops/pt_ok.txt")

    monkeypatch.setattr(hops, "run_command", fake)
    result = hops.run({"connected": True})
    assert result.ok and result.data["reached"]
    assert "-d" in seen["args"]


def test_hops_timeout(monkeypatch):
    def fake(*a, **k):
        raise CommandTimeout("x")

    monkeypatch.setattr(hops, "run_command", fake)
    assert hops.run({}).error == "TIMEOUT"


def test_hops_skipped_without_link():
    assert hops.run({"connected": False}).data == {"skipped": "no_link"}


def test_hops_unparseable(monkeypatch):
    monkeypatch.setattr(hops, "run_command", lambda *a, **k: (1, "erro"))
    assert hops.run({}).error == "PARSE_ERROR"


def test_devices_fixture_is_valid_json(fixture_text):
    assert isinstance(json.loads(fixture_text("devices/neighbors.json")), list)
