"""Fluxo completo, igual para CLI e interface:
probes → regras → explicação (template, IA opcional) → relatório.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from netdoctor.core.models import Diagnosis, ProbeResult
from netdoctor.core.rules import diagnose
from netdoctor.core.runner import run_all
from netdoctor.explain import llm
from netdoctor.explain.templates import Explanation, explain
from netdoctor.report.json_report import build_report

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
) -> PipelineResult:
    results = runner(on_progress=on_progress, on_done=on_done)
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

    report = build_report(results, diagnosis, explanation)
    return PipelineResult(results, diagnosis, explanation, report)
