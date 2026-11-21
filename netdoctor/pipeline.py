"""Fluxo completo, igual para CLI e interface:
probes → regras → explicação (template, IA opcional) → relatório.

Com `tech=True` (Modo Técnico) roda também vizinhos, dispositivos e saltos e
acrescenta a análise técnica ao relatório. O diagnóstico do cliente não muda.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from netdoctor.core.models import Diagnosis, ProbeResult
from netdoctor.core.rules import diagnose
from netdoctor.core.runner import PARALLEL, run_all
from netdoctor.explain import llm
from netdoctor.explain.templates import Explanation, explain
from netdoctor.report.json_report import build_report
from netdoctor.tech.analysis import TECH_PROBES, TECH_TIMEOUT_S, analyze

AUTO = object()  # carrega a configuração da IA do ambiente/.env


@dataclass
class PipelineResult:
    results: list[ProbeResult]
    diagnosis: Diagnosis
    explanation: Explanation
    report: dict[str, Any]


def _connection_type(results: list[ProbeResult]) -> str | None:
    for r in results:
        if r.name == "adapter" and r.ok:
            return r.data.get("type")
    return None


def run_pipeline(
    on_progress: Callable[[str], None] | None = None,
    on_done: Callable[[ProbeResult], None] | None = None,
    runner: Callable[..., list[ProbeResult]] = run_all,
    llm_config: Any = AUTO,
    transport: llm.Transport | None = None,
    tech: bool = False,
) -> PipelineResult:
    extra = {"parallel": PARALLEL + TECH_PROBES, "timeout": TECH_TIMEOUT_S} if tech else {}
    results = runner(on_progress=on_progress, on_done=on_done, **extra)
    diagnosis = diagnose(results)
    explanation = explain(diagnosis, results)

    config = llm.load_config() if llm_config is AUTO else llm_config
    if config is not None:
        if on_progress:
            on_progress("explain")
        kwargs = {"transport": transport} if transport else {}
        explanation = llm.enhance(
            explanation, diagnosis, _connection_type(results), config, **kwargs
        )

    # A IA recebe só o diagnóstico do cliente; nada do Modo Técnico vai para ela.
    report = build_report(results, diagnosis, explanation, tech=analyze(results) if tech else None)
    return PipelineResult(results, diagnosis, explanation, report)
