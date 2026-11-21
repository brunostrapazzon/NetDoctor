"""Lógica da interface sem abrir janela: textos, resumo copiado e thread do diagnóstico."""

import re
import time
from datetime import datetime

from netdoctor.core.models import ProbeResult
from netdoctor.core.runner import run_all
from netdoctor.pipeline import run_pipeline
from netdoctor.ui import presenter
from netdoctor.ui.presenter import (
    PALETTE,
    SEVERITY_COLOR,
    copy_summary,
    default_report_name,
    progress_fraction,
    progress_text,
    result_view,
    step_state,
    step_status,
)
from netdoctor.ui.worker import DiagnosisWorker

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
    assert (view.severity, view.label, view.color) == ("warning", "Atenção", PALETTE["warn"])
    assert view.title == "Seu Wi-Fi está fraco neste lugar."
    assert "Força do sinal: 38%" in view.body
    assert "Também notamos: conexão instável até o roteador." in view.body
    assert view.actions == "1.  Aproxime-se do roteador.\n2.  Use cabo."


def test_severity_is_word_and_color_never_color_alone():
    labels = {
        sev: result_view({**EXPLANATION, "severity": sev}).label
        for sev in ("critical", "warning", "info")
    }
    assert labels == {"critical": "Problema", "warning": "Atenção", "info": "Normal"}
    unknown = result_view({**EXPLANATION, "severity": "???"})
    assert (unknown.label, unknown.color) == ("Atenção", SEVERITY_COLOR["warning"])


def test_window_texts_have_no_decorative_symbols():
    # Direção visual: utilitário do Windows, sem emoji nem símbolos decorativos.
    symbols = re.compile("[☀-➿■-◿\U0001f300-\U0001faff]")
    texts = [v for k, v in vars(presenter).items() if k.isupper() and isinstance(v, str)]
    texts += [text for text, _ in presenter.STEP_STATUS.values()]
    for sev in ("critical", "warning", "info"):
        view = result_view({**EXPLANATION, "severity": sev})
        texts += [view.label, view.actions]
    for text in texts:
        assert not symbols.search(text), text


def test_every_color_has_light_and_dark_variant():
    hex_color = re.compile(r"^#[0-9a-f]{6}$")
    for name, pair in PALETTE.items():
        assert len(pair) == 2 and all(hex_color.match(c) for c in pair), name
        assert pair[0] != pair[1] or name.endswith("text"), name


def test_step_state_from_probe_result():
    assert step_state(ProbeResult("ping", ok=True, data={"targets": []})) == "ok"
    assert step_state(ProbeResult("wifi", ok=True, data={"skipped": "not_wifi"})) == "skipped"
    assert step_state(ProbeResult("dns", ok=False, error="TIMEOUT")) == "failed"


def test_step_status_text_and_color():
    assert step_status("pending") == ("", PALETTE["muted"])
    assert step_status("running")[0] == "testando…"
    assert step_status("ok") == ("ok", PALETTE["ok"])
    assert step_status("skipped") == ("não se aplica", PALETTE["muted"])
    assert step_status("failed") == ("não mediu", PALETTE["warn"])


def test_progress_fraction_is_clamped():
    assert progress_fraction(2, 5) == 0.4
    assert progress_fraction(7, 5) == 1.0
    assert progress_fraction(1, 0) == 0.0


def test_window_microcopy_has_no_jargon():
    jargon = re.compile(
        r"(gateway|dns|dhcp|ip|ping|lat[eê]ncia|icmp|tcp|udp|ssid|https?|apipa|isp)",
        re.IGNORECASE,
    )
    texts = [v for k, v in vars(presenter).items() if k.isupper() and isinstance(v, str)]
    texts += list(presenter.PROGRESS_TEXT.values()) + [presenter.saved_text("C:/x.html")]
    assert len(texts) > 15
    for text in texts:
        assert not jargon.search(text), text


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
    report = run_pipeline(steps.append, runner=_fake_runner, llm_config=None).report
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
    worker = DiagnosisWorker(runner=_fake_runner, llm_config=None)
    assert worker.start()
    events = _wait_for(worker, "done")
    kinds = [e.kind for e in events]
    assert kinds[0] == "progress"
    assert "finished" in kinds
    finished = [e.payload for e in events if e.kind == "finished"]
    assert [(r.name, r.ok) for r in finished] == [("adapter", False), ("ping", False)]
    assert kinds[-1] == "done"
    assert events[-1].payload["diagnosis"]["primary"] == "INCONCLUSIVE"


def test_worker_reports_error_instead_of_hanging():
    def broken(**kwargs):
        raise RuntimeError("boom")

    worker = DiagnosisWorker(runner=broken, llm_config=None)
    worker.start()
    events = _wait_for(worker, "error")
    assert events[-1].payload == "RuntimeError"


def test_worker_refuses_second_start_while_running():
    def slow(**kwargs):
        time.sleep(0.3)
        return []

    worker = DiagnosisWorker(runner=slow, llm_config=None)
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
