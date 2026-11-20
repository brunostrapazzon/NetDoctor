"""Linha de comando: `netdoctor diagnose [--json] [--output ARQUIVO]`."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netdoctor import __version__
from netdoctor.core.models import Diagnosis, ProbeResult
from netdoctor.core.rules import diagnose
from netdoctor.core.runner import run_all

_PROGRESS = {
    "adapter": "Verificando a conexão do computador…",
    "ping": "Testando o roteador e a internet…",
    "dns": "Testando a tradução de nomes (DNS)…",
    "http": "Testando o acesso a sites…",
}


def build_report(results: list[ProbeResult], diagnosis: Diagnosis) -> dict[str, Any]:
    return {
        "tool": "netdoctor",
        "version": __version__,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "os": {"system": platform.system(), "release": platform.release()},
        "diagnosis": diagnosis.to_dict(),
        "probes": [r.to_dict() for r in results],
    }


def format_diagnosis(diagnosis: Diagnosis) -> str:
    """Códigos técnicos. O texto para leigos (templates pt-BR) chega no Marco 3."""
    p = diagnosis.primary
    lines = [f"Diagnóstico: {p.code} ({p.severity}) -> ação {p.action}"]
    for extra in diagnosis.findings[1:]:
        lines.append(f"  também: {extra.code} ({extra.severity}) -> ação {extra.action}")
    return "\n".join(lines)


def _fmt_ping(target: dict[str, Any]) -> str:
    if target.get("error"):
        return f"{target['role']}: não medido ({target['error']})"
    rtt = target.get("rtt_ms")
    avg = f", média {rtt['avg']} ms" if rtt else ""
    return f"{target['role']}: perda {target['loss_pct']}%{avg}"


def format_summary(results: list[ProbeResult]) -> str:
    """Resumo técnico dos fatos. A explicação para leigos chega no Marco 3."""
    lines = []
    for r in results:
        if not r.ok:
            lines.append(f"[{r.name}] não foi possível medir ({r.error})")
            continue
        d = r.data
        if r.name == "adapter":
            if d["connected"]:
                apipa = " (sem DHCP)" if d["apipa"] else ""
                lines.append(
                    f"[adapter] {d['type']} | IP {d['ipv4']}{apipa} | gateway {d['gateway']}"
                )
            else:
                lines.append("[adapter] nenhum adaptador conectado")
        elif r.name == "ping":
            lines.append("[ping] " + " | ".join(_fmt_ping(t) for t in d["targets"]))
        elif r.name == "dns":
            parts = [
                f"{s['role']} {s['server']}: " + (f"ok {s['ms']} ms" if s["ok"] else s["error"])
                for s in d["servers"]
            ]
            lines.append("[dns] " + " | ".join(parts))
        elif r.name == "http":
            ncsi, https = d["ncsi"], d["https"]
            lines.append(
                f"[http] teste Windows: {'ok' if ncsi['content_ok'] else 'falhou'}"
                f" | HTTPS: {'ok' if https['ok'] else https['error'] or https['status']}"
            )
    return "\n".join(lines)


def _configure_stdout() -> None:
    # No console pt-BR (code page 850) caracteres fora da tabela não podem quebrar a saída.
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")


def _progress(name: str) -> None:
    if sys.stderr is not None:
        print(_PROGRESS.get(name, name), file=sys.stderr, flush=True)


def cmd_diagnose(args: argparse.Namespace) -> int:
    results = run_all(on_progress=None if args.json else _progress)
    diagnosis = diagnose(results)
    report = build_report(results, diagnosis)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    if args.json:
        print(text)
    else:
        print(format_diagnosis(diagnosis))
        print()
        print(format_summary(results))
        if args.output:
            print(f"\nRelatório salvo em {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="netdoctor", description="Diagnóstico de internet.")
    parser.add_argument("--version", action="version", version=f"netdoctor {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    diag = sub.add_parser("diagnose", help="Testa a conexão e mostra o resultado.")
    diag.add_argument("--json", action="store_true", help="Saída em JSON.")
    diag.add_argument("--output", "-o", metavar="ARQUIVO", help="Salva o relatório JSON.")
    diag.set_defaults(func=cmd_diagnose)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
