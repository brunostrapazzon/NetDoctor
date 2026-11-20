"""Relatório JSON: diagnóstico, explicação e fatos brutos de cada probe."""

from __future__ import annotations

import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netdoctor import __version__
from netdoctor.core.models import Diagnosis, ProbeResult
from netdoctor.explain.templates import Explanation


def build_report(
    results: list[ProbeResult],
    diagnosis: Diagnosis,
    explanation: Explanation,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    when = generated_at or datetime.now(UTC)
    return {
        "tool": "netdoctor",
        "version": __version__,
        "generated_at": when.isoformat(timespec="seconds"),
        "os": {"system": platform.system(), "release": platform.release()},
        "diagnosis": diagnosis.to_dict(),
        "explanation": explanation.to_dict(),
        "probes": [r.to_dict() for r in results],
    }


def to_json(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, indent=2)


def write_json(report: dict[str, Any], path: Path) -> Path:
    path.write_text(to_json(report), encoding="utf-8")
    return path
