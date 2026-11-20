import json
import time

from netdoctor import cli
from netdoctor.core.models import ErrorCode, ProbeResult
from netdoctor.core.runner import run_all


def test_context_flows_from_adapter_to_parallel_probes():
    seen = {}

    def first(ctx):
        return ProbeResult("adapter", ok=True, data={"gateway": "192.168.0.1"})

    def second(ctx):
        seen.update(ctx)
        return ProbeResult("ping", ok=True)

    results = run_all(first=(("adapter", first),), parallel=(("ping", second),))
    assert seen["gateway"] == "192.168.0.1"
    assert [r.name for r in results] == ["adapter", "ping"]


def test_crashing_probe_becomes_unexpected_error():
    def broken(ctx):
        raise ZeroDivisionError

    results = run_all(first=(("adapter", broken),), parallel=())
    assert results[0].ok is False
    assert results[0].error == ErrorCode.UNEXPECTED


def test_hanging_probe_times_out():
    def slow(ctx):
        time.sleep(2)
        return ProbeResult("http", ok=True)

    start = time.monotonic()
    results = run_all(first=(), parallel=(("http", slow),), timeout=0.2)
    assert time.monotonic() - start < 1.5
    assert results[0].error == ErrorCode.TIMEOUT


def test_failed_adapter_does_not_feed_context():
    seen = {}

    def failed(ctx):
        return ProbeResult("adapter", ok=False, data={"gateway": "lixo"}, error="TIMEOUT")

    def second(ctx):
        seen.update(ctx)
        return ProbeResult("ping", ok=True)

    run_all(first=(("adapter", failed),), parallel=(("ping", second),))
    assert "gateway" not in seen


def _fake_results():
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
                "dns_servers": [],
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
                        "rtt_ms": {"min": 1.0, "avg": 1.0, "max": 1.0},
                        "error": None,
                    },
                ]
            },
        ),
        ProbeResult("dns", ok=False, error="TIMEOUT"),
    ]


def test_diagnose_json_is_valid(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run_all", lambda **kwargs: _fake_results())
    assert cli.main(["diagnose", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["tool"] == "netdoctor"
    assert [p["name"] for p in report["probes"]] == ["adapter", "ping", "dns"]


def test_diagnose_summary_and_output_file(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(cli, "run_all", lambda **kwargs: _fake_results())
    out_file = tmp_path / "relatorio.json"
    assert cli.main(["diagnose", "-o", str(out_file)]) == 0
    text = capsys.readouterr().out
    assert "[adapter] wifi" in text
    assert "[dns] não foi possível medir (TIMEOUT)" in text
    assert json.loads(out_file.read_text(encoding="utf-8"))["version"]
