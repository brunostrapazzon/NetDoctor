"""O que a tela mostra, sem depender de Tk (testável sem abrir janela)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

PROGRESS_TEXT = {
    "start": "Preparando o diagnóstico…",
    "adapter": "Verificando a conexão do computador…",
    "wifi": "Medindo o sinal do Wi-Fi…",
    "ping": "Testando o roteador e a internet…",
    "dns": "Testando o acesso aos sites…",
    "http": "Testando o acesso aos sites…",
}

# Ícone + cor por gravidade. As cores são pares (tema claro, tema escuro).
SEVERITY_STYLE = {
    "critical": ("✖", ("#b42318", "#ff8a80")),
    "warning": ("⚠", ("#946200", "#ffd36b")),
    "info": ("✔", ("#1b7a3d", "#7ee2a0")),
}


@dataclass(frozen=True)
class ResultView:
    icon: str
    color: tuple[str, str]
    title: str
    body: str
    actions: str


def result_view(explanation: dict[str, Any]) -> ResultView:
    icon, color = SEVERITY_STYLE.get(explanation["severity"], SEVERITY_STYLE["warning"])
    body = [explanation["detail"], *explanation["numbers"]]
    if explanation["also"]:
        body.append("Também notamos: " + "; ".join(explanation["also"]) + ".")
    body += [f"Obs.: {n}" for n in explanation["notes"]]
    actions = "\n".join(f"{i}. {a}" for i, a in enumerate(explanation["actions"], 1))
    return ResultView(icon, color, explanation["headline"], "\n".join(body), actions)


def progress_text(step: str) -> str:
    return PROGRESS_TEXT.get(step, "Testando…")


def copy_summary(report: dict[str, Any]) -> str:
    """Resumo curto para colar no WhatsApp/e-mail do suporte.

    Só leva o texto da explicação, os códigos e a data. Nada de nome da rede,
    endereço ou nome do computador: isso fica no relatório salvo, que o
    usuário escolhe enviar.
    """
    ex = report["explanation"]
    codes = ", ".join(f["code"] for f in report["diagnosis"]["findings"])
    lines = [
        f"NetDoctor: {ex['headline']}",
        ex["detail"],
        *ex["numbers"],
        "",
        "O que fazer:",
        *(f"{i}. {a}" for i, a in enumerate(ex["actions"], 1)),
        "",
        f"Códigos: {codes} | {report['generated_at']} | v{report['version']}",
    ]
    return "\n".join(lines)


def default_report_name(when: datetime) -> str:
    return f"netdoctor-relatorio-{when:%Y%m%d-%H%M}.html"
