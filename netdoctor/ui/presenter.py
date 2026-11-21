"""O que a tela mostra, sem depender de Tk (testável sem abrir janela).

Textos, ícones e cores ficam aqui. Toda cor é um par (tema claro, tema escuro),
no formato que o CustomTkinter aceita, e segue a mesma paleta do relatório HTML.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from netdoctor.explain.templates import AI_DISCLOSURE

Color = tuple[str, str]

# Paleta da janela: os mesmos tons do relatório HTML (html_report._CSS).
PALETTE: dict[str, Color] = {
    "window": ("#f4f5f7", "#0f1217"),
    "surface": ("#ffffff", "#171b23"),
    "border": ("#e1e4ea", "#2a303b"),
    "text": ("#151a23", "#e8ebf1"),
    "muted": ("#596273", "#9ca5b5"),
    "accent": ("#2459d4", "#3b6fe0"),
    "accent_hover": ("#1d48ad", "#2f5cc0"),
    "accent_text": ("#ffffff", "#ffffff"),
    "accent_disabled_text": ("#c8d5f4", "#a9bcea"),
    "track": ("#e4e7ec", "#2a303b"),
    "secondary_hover": ("#eef0f4", "#1f2430"),
    "ok": ("#16723a", "#6fdc98"),
    "ok_bg": ("#e5f5eb", "#16301f"),
    "warn": ("#8a5a00", "#f5c451"),
    "warn_bg": ("#fff4d6", "#352b14"),
    "crit": ("#b42318", "#ff8f85"),
    "crit_bg": ("#fdeceb", "#3b1d1b"),
}

# Escala de espaçamento (px). A janela só usa estes valores.
SPACE = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24}

PROGRESS_TEXT = {
    "start": "Preparando o diagnóstico…",
    "adapter": "Verificando a conexão do computador…",
    "wifi": "Medindo o sinal do Wi-Fi…",
    "ping": "Testando o roteador e a internet…",
    "dns": "Testando o acesso aos sites…",
    "http": "Testando o acesso aos sites…",
    "explain": "Escrevendo a explicação…",
}

# Textos fixos da janela (há teste que barra jargão neles).
WELCOME_TITLE = "Vamos testar sua internet?"
WELCOME_BODY = (
    "Clique em Diagnosticar. Em cerca de 10 segundos o NetDoctor mostra o que está "
    "acontecendo e o que fazer. Funciona mesmo sem internet."
)
RUNNING_TITLE = "Testando sua conexão…"
ERROR_TITLE = "Não foi possível terminar o teste."
ERROR_BODY = "Feche outros programas e clique em Diagnosticar de novo."
ACTIONS_TITLE = "O que fazer"
BUTTON_DIAGNOSE = "Diagnosticar"
BUTTON_RUNNING = "Testando…"
BUTTON_AGAIN = "Diagnosticar de novo"
BUTTON_SAVE = "Salvar relatório"
BUTTON_COPY = "Copiar resumo"
BUTTON_COPIED = "✔  Copiado"
COPIED_TEXT = "Resumo copiado. Cole na conversa com o suporte."
SAVE_FAILED_TEXT = "Não foi possível salvar nesse local. Tente outra pasta."
SUBTITLE = "Diagnóstico da internet, em português simples"

# Ícone + rótulo + cor + fundo por gravidade. O ícone e o rótulo garantem que
# a gravidade não dependa só da cor.
SEVERITY_STYLE = {
    "critical": ("✖", PALETTE["crit"]),
    "warning": ("⚠", PALETTE["warn"]),
    "info": ("✔", PALETTE["ok"]),
}
SEVERITY_LABEL = {"critical": "Problema", "warning": "Atenção", "info": "Normal"}
SEVERITY_TINT = {
    "critical": PALETTE["crit_bg"],
    "warning": PALETTE["warn_bg"],
    "info": PALETTE["ok_bg"],
}

StepState = Literal["pending", "running", "done"]
STEP_MARK: dict[str, tuple[str, Color]] = {
    "pending": ("○", PALETTE["muted"]),
    "running": ("…", PALETTE["text"]),
    "done": ("✔", PALETTE["ok"]),
}


@dataclass(frozen=True)
class ResultView:
    icon: str
    color: Color
    title: str
    body: str
    actions: str
    label: str
    tint: Color


def result_view(explanation: dict[str, Any]) -> ResultView:
    severity = explanation["severity"] if explanation["severity"] in SEVERITY_STYLE else "warning"
    icon, color = SEVERITY_STYLE[severity]
    body = [explanation["detail"], *explanation["numbers"]]
    if explanation["also"]:
        body.append("Também notamos: " + "; ".join(explanation["also"]) + ".")
    body += [f"Obs.: {n}" for n in explanation["notes"]]
    if explanation.get("source") == "llm":
        body.append(AI_DISCLOSURE)
    actions = "\n".join(f"{i}. {a}" for i, a in enumerate(explanation["actions"], 1))
    return ResultView(
        icon,
        color,
        explanation["headline"],
        "\n".join(body),
        actions,
        SEVERITY_LABEL[severity],
        SEVERITY_TINT[severity],
    )


def badge_text(view: ResultView) -> str:
    return f"{view.icon}  {view.label}"


def step_line(label: str, state: StepState) -> tuple[str, Color]:
    """Texto e cor de uma etapa da lista (○ esperando, … testando, ✔ concluída)."""
    mark, color = STEP_MARK[state]
    return f"{mark}  {label}", color


def progress_fraction(done: int, total: int) -> float:
    return 0.0 if total <= 0 else max(0.0, min(1.0, done / total))


def saved_text(path: str) -> str:
    return f"Relatório salvo em {path} (e uma cópia .json para o suporte)."


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
