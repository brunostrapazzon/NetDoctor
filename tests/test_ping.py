import pytest

from netdoctor.core.probes import ping
from netdoctor.core.probes.ping import parse_ping


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_all_replies(fixture_text, lang):
    result = parse_ping(fixture_text(f"ping/{lang}_ok.txt"), sent=4)
    assert result == {
        "sent": 4,
        "received": 4,
        "loss_pct": 0.0,
        "rtt_ms": {"min": 18.0, "avg": 19.0, "max": 21.0},
    }


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_all_timeouts(fixture_text, lang):
    result = parse_ping(fixture_text(f"ping/{lang}_timeout.txt"), sent=4)
    assert result["received"] == 0
    assert result["loss_pct"] == 100.0
    assert result["rtt_ms"] is None


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_partial_loss_and_sub_millisecond(fixture_text, lang):
    result = parse_ping(fixture_text(f"ping/{lang}_partial_lt1ms.txt"), sent=4)
    assert result["received"] == 2
    assert result["loss_pct"] == 50.0
    assert result["rtt_ms"] == {"min": 1.0, "avg": 2.0, "max": 3.0}


@pytest.mark.parametrize("lang", ["pt", "en"])
def test_destination_unreachable_counts_as_loss(fixture_text, lang):
    # O Windows conta "host inacessível" como recebido; para nós é perda total.
    result = parse_ping(fixture_text(f"ping/{lang}_unreachable.txt"), sent=4)
    assert result["received"] == 0
    assert result["loss_pct"] == 100.0


def test_decimal_comma():
    result = parse_ping("Resposta de 10.0.0.1: bytes=32 tempo=1,5ms TTL=64", sent=1)
    assert result["rtt_ms"]["avg"] == 1.5


def test_empty_output_is_total_loss():
    assert parse_ping("", sent=4)["loss_pct"] == 100.0


def test_run_without_gateway_reports_it(monkeypatch):
    monkeypatch.setattr(ping.sys, "platform", "win32")
    monkeypatch.setattr(
        ping, "_ping_target", lambda role, host: {"role": role, "host": host, "error": None}
    )
    result = ping.run({"gateway": None})
    assert result.ok
    roles = [t["role"] for t in result.data["targets"]]
    assert roles == ["gateway", "public_cloudflare", "public_google"]
    assert result.data["targets"][0]["error"] == "NO_GATEWAY"


def test_run_pings_gateway_first(monkeypatch):
    monkeypatch.setattr(ping.sys, "platform", "win32")
    seen = []

    def fake(role, host):
        seen.append(host)
        return {"role": role, "host": host, "error": None}

    monkeypatch.setattr(ping, "_ping_target", fake)
    result = ping.run({"gateway": "192.168.0.1"})
    assert result.data["targets"][0]["host"] == "192.168.0.1"
    assert set(seen) == {"192.168.0.1", "1.1.1.1", "8.8.8.8"}
