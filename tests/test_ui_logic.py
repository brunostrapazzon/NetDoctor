"""Lógica da interface sem abrir janela: textos, resumo copiado e thread do diagnóstico."""

import time
from datetime import datetime

from netdoctor.core.models import ProbeResult
from netdoctor.core.runner import run_all
from netdoctor.ui.presenter import copy_summary, default_report_name, progress_text, result_view
from netdoctor.ui.worker import DiagnosisWorker, run_pipeline

EXPLANATION = {
    "code": "WIFI_WEAK",
    "severity": "warning",
    "headline": "Seu Wi-Fi está fraco neste lugar.",
    "detail": "O sinal chega fraco ao computador.",
    "actions": ["Aproxime-se do roteador.", "Use cabo."],
    "also": ["conexão instável até o roteador"],
    "notes": [],
    "numbers": ["Força do sinal: 38% (o ideal é acima de 50%)."],
    "source": "template",
}
REPORT = {
    "version": "0.1.0",
    "generated_at": "2026-11-20T12:00:00+00:00",
    "diagnosis": {
        "primary": "WIFI_WEAK",
        "findings": [{"code": "WIFI_WEAK"}, {"code": "LOCAL_INTERFERENCE"}],
    },
    "explanation": EXPLANATION,
    "probes": [
        {"name": "wifi", "data": {"ssid": "MinhaRede"}},
        {"name": "adapter", "data": {"ipv4": "192.168.0.10", "gateway": "192.168.0.1"}},
    ],
}


def test_result_view_warning():
    view = result_view(EXPLANATION)
    assert view.icon == "⚠"
    assert view.title == "Seu Wi-Fi está fraco neste lugar."
    assert "Força do sinal: 38%" in view.body
    assert "Também notamos: conexão instável até o roteador." in view.body
    assert view.actions == "1. Aproxime-se do roteador.\n2. Use cabo."


def test_result_view_ok_and_critical_icons():
    assert result_view({**EXPLANATION, "severity": "info"}).icon == "✔"
    assert result_view({**EXPLANATION, "severity": "critical"}).icon == "✖"


def test_copy_summary_has_codes_but_no_network_identifiers():
    text = copy_summary(REPORT)
    assert text.startswith("NetDoctor: Seu Wi-Fi está fraco neste lugar.")
    assert "Códigos: WIFI_WEAK, LOCAL_INTERFERENCE" in text
    for secret in ("MinhaRede", "192.168.0.10", "192.168.0.1"):
        assert secret not in text


def test_progress_text_known_and_unknown():
    assert progress_text("ping") == "Testando o roteador e a internet…"
    assert progress_text("???") == "Testando…"


def test_default_report_name():
    assert (
        default_report_name(datetime(2026, 11, 20, 9, 5))
        == "netdoctor-relatorio-20261120-0905.html"
    )


def _fake_runner(on_progress=None, on_done=None):
    results = []
    for name in ("adapter", "ping"):
        if on_progress:
            on_progress(name)
        r = ProbeResult(name, ok=False, error="TIMEOUT")
        results.append(r)
        if on_done:
            on_done(r)
    return results


def test_pipeline_builds_full_report():
    steps = []
    report = run_pipeline(steps.append, runner=_fake_runner)
    assert steps == ["adapter", "ping"]
    assert report["diagnosis"]["primary"] == "INCONCLUSIVE"
    assert report["explanation"]["headline"]


def _wait_for(worker, kind, timeout=3.0):
    events = []
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        events += worker.drain()
        if any(e.kind == kind for e in events):
            return events
        time.sleep(0.01)
    raise AssertionError(f"evento {kind} não chegou: {events}")


def test_worker_emits_progress_finished_and_done():
    worker = DiagnosisWorker(runner=_fake_runner)
    assert worker.start()
    events = _wait_for(worker, "done")
    kinds = [e.kind for e in events]
    assert kinds[0] == "progress"
    assert "finished" in kinds
    assert kinds[-1] == "done"
    assert events[-1].payload["diagnosis"]["primary"] == "INCONCLUSIVE"


def test_worker_reports_error_instead_of_hanging():
    def broken(**kwargs):
        raise RuntimeError("boom")

    worker = DiagnosisWorker(runner=broken)
    worker.start()
    events = _wait_for(worker, "error")
    assert events[-1].payload == "RuntimeError"


def test_worker_refuses_second_start_while_running():
    def slow(**kwargs):
        time.sleep(0.3)
        return []

    worker = DiagnosisWorker(runner=slow)
    assert worker.start()
    assert worker.start() is False


def test_runner_calls_on_done_for_each_probe():
    done = []

    def probe(name):
        return lambda ctx: ProbeResult(name, ok=True)

    run_all(
        first=(("adapter", probe("adapter")),),
        parallel=(("ping", probe("ping")), ("dns", probe("dns"))),
        on_done=lambda r: done.append(r.name),
    )
    time.sleep(0.05)
    assert sorted(done) == ["adapter", "dns", "ping"]
