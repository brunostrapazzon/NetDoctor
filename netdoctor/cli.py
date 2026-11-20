"""Linha de comando: `netdoctor diagnose [--json] [-o ARQUIVO.json] [--html ARQUIVO.html]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from netdoctor import __version__
from netdoctor.core.models import Diagnosis, ProbeResult
from netdoctor.core.runner import run_all
from netdoctor.pipeline import AUTO, run_pipeline
from netdoctor.report.html_report import write_html
from netdoctor.report.json_report import to_json, write_json

_PROGRESS = {
    "adapter": "Verificando a conexão do computador…",
    "wifi": "Medindo o sinal do Wi-Fi…",
    "ping": "Testando o roteador e a internet…",
    "dns": "Testando a tradução de nomes (DNS)…",
    "http": "Testando o acesso a sites…",
    "explain": "Escrevendo a explicação…",
}


def format_diagnosis(diagnosis: Diagnosis) -> str:
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
    """Resumo técnico dos fatos, para quem dá suporte."""
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
        elif r.name == "wifi":
            if d.get("skipped"):
                lines.append("[wifi] não se aplica (conexão por cabo)")
            elif d["connected"]:
                lines.append(
                    f"[wifi] sinal {d['signal_pct']}% ({d['rssi_dbm']} dBm) | canal {d['channel']}"
                    f" | {d['band']} | {d['radio']}"
                )
            else:
                lines.append("[wifi] desconectado")
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
    outcome = run_pipeline(
        on_progress=None if args.json else _progress,
        runner=run_all,
        llm_config=None if args.no_ai else AUTO,
    )
    results, diagnosis, explanation, report = (
        outcome.results,
        outcome.diagnosis,
        outcome.explanation,
        outcome.report,
    )

    saved = []
    if args.output:
        saved.append(write_json(report, Path(args.output)))
    if args.html:
        saved.append(write_html(report, Path(args.html)))

    if args.json:
        print(to_json(report))
        return 0

    print(explanation.as_text())
    print("\n--- Detalhes técnicos ---")
    print(format_diagnosis(diagnosis))
    print(format_summary(results))
    for path in saved:
        print(f"\nRelatório salvo em {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="netdoctor", description="Diagnóstico de internet.")
    parser.add_argument("--version", action="version", version=f"netdoctor {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    diag = sub.add_parser("diagnose", help="Testa a conexão e mostra o resultado.")
    diag.add_argument("--json", action="store_true", help="Saída em JSON.")
    diag.add_argument("--output", "-o", metavar="ARQUIVO", help="Salva o relatório JSON.")
    diag.add_argument("--html", metavar="ARQUIVO", help="Salva o relatório técnico HTML.")
    diag.add_argument(
        "--sem-ia",
        dest="no_ai",
        action="store_true",
        help="Não usa IA mesmo se configurada (só explicações offline).",
    )
    diag.set_defaults(func=cmd_diagnose)
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdout()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
