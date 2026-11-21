"""O que a tela mostra, sem depender de Tk (testável sem abrir janela).

Textos, cores e o estado de cada etapa ficam aqui. Toda cor é um par
(tema claro, tema escuro), no formato que o CustomTkinter aceita.

Direção visual: utilitário do Windows, não página de produto. Fonte do
sistema (Segoe UI), cores do sistema do Windows 11, cantos pequenos, nenhum
emoji ou símbolo decorativo. A gravidade aparece como uma faixa de cor ao lado
do resultado mais uma palavra ("Problema", "Atenção", "Normal"), então nunca
depende só da cor.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from netdoctor.explain.templates import AI_DISCLOSURE

Color = tuple[str, str]

FONT_FAMILY = "Segoe UI"
FONT_FAMILY_STRONG = "Segoe UI Semibold"

# Cores do sistema do Windows 11 (neutros, destaque e estados).
PALETTE: dict[str, Color] = {
    "window": ("#f3f3f3", "#202020"),
    "rule": ("#e0e0e0", "#383838"),
    "text": ("#1b1b1b", "#f3f3f3"),
    "muted": ("#616161", "#a8a8a8"),
    "accent": ("#005fb8", "#60cdff"),
    "accent_hover": ("#1a6fc0", "#5ab8e6"),
    "accent_text": ("#ffffff", "#000000"),
    "accent_disabled": ("#bfbfbf", "#4a4a4a"),
    "accent_disabled_text": ("#f3f3f3", "#9a9a9a"),
    "button": ("#fbfbfb", "#2d2d2d"),
    "button_hover": ("#f0f0f0", "#353535"),
    "button_border": ("#d1d1d1", "#424242"),
    "track": ("#e0e0e0", "#383838"),
    "ok": ("#0f7b0f", "#6ccb5f"),
    "warn": ("#9d5d00", "#fce100"),
    "crit": ("#c42b1c", "#ff99a4"),
}

# Escala de espaçamento (px). A janela só usa estes valores.
SPACE = {"xs": 4, "s": 8, "m": 12, "l": 16, "xl": 24}

PROGRESS_TEXT = {
    "start": "Preparando…",
    "adapter": "Verificando a conexão do computador…",
    "wifi": "Medindo o sinal do Wi-Fi…",
    "ping": "Testando o roteador e a internet…",
    "dns": "Testando o acesso aos sites…",
    "http": "Testando o acesso aos sites…",
    "explain": "Escrevendo a explicação…",
}

# Textos fixos da janela (há teste que barra jargão neles). Diretos, sem
# perguntas retóricas nem slogan.
WELCOME_TITLE = "Teste da conexão"
WELCOME_BODY = "Clique em Diagnosticar. O teste leva uns 10 segundos e funciona mesmo sem internet."
RUNNING_TITLE = "Testando a conexão"
ERROR_TITLE = "O teste não terminou."
ERROR_BODY = "Feche outros programas e clique em Diagnosticar de novo."
ACTIONS_TITLE = "O que fazer"
BUTTON_DIAGNOSE = "Diagnosticar"
BUTTON_RUNNING = "Testando…"
BUTTON_AGAIN = "Testar de novo"
BUTTON_SAVE = "Salvar relatório…"
BUTTON_COPY = "Copiar resumo"
BUTTON_COPIED = "Copiado"
COPIED_TEXT = "Resumo copiado. Cole na conversa com o suporte."
SAVE_FAILED_TEXT = "Não foi possível salvar nesse local. Tente outra pasta."

SEVERITY_LABEL = {"critical": "Problema", "warning": "Atenção", "info": "Normal"}
SEVERITY_COLOR: dict[str, Color] = {
    "critical": PALETTE["crit"],
    "warning": PALETTE["warn"],
    "info": PALETTE["ok"],
}

StepState = Literal["pending", "running", "ok", "skipped", "failed"]
STEP_STATUS: dict[str, tuple[str, Color]] = {
    "pending": ("", PALETTE["muted"]),
    "running": ("testando…", PALETTE["muted"]),
    "ok": ("ok", PALETTE["ok"]),
    "skipped": ("não se aplica", PALETTE["muted"]),
    "failed": ("não mediu", PALETTE["warn"]),
}


@dataclass(frozen=True)
class ResultView:
    severity: str
    label: str
    color: Color
    title: str
    body: str
    actions: str


def result_view(explanation: dict[str, Any]) -> ResultView:
    severity = explanation["severity"] if explanation["severity"] in SEVERITY_LABEL else "warning"
    body = [explanation["detail"], *explanation["numbers"]]
    if explanation["also"]:
        body.append("Também notamos: " + "; ".join(explanation["also"]) + ".")
    body += [f"Obs.: {n}" for n in explanation["notes"]]
    if explanation.get("source") == "llm":
        body.append(AI_DISCLOSURE)
    actions = "\n".join(f"{i}.  {a}" for i, a in enumerate(explanation["actions"], 1))
    return ResultView(
        severity=severity,
        label=SEVERITY_LABEL[severity],
        color=SEVERITY_COLOR[severity],
        title=explanation["headline"],
        body="\n".join(body),
        actions=actions,
    )


def step_state(probe: Any) -> StepState:
    """Estado final de uma etapa a partir do ProbeResult dela."""
    if not probe.ok:
        return "failed"
    if (probe.data or {}).get("skipped"):
        return "skipped"
    return "ok"


def step_status(state: StepState) -> tuple[str, Color]:
    """Texto e cor da coluna de status de uma etapa."""
    return STEP_STATUS[state]


def progress_fraction(done: int, total: int) -> float:
    return 0.0 if total <= 0 else max(0.0, min(1.0, done / total))


def saved_text(path: str) -> str:
    return f"Salvo em {path} (com uma cópia .json para o suporte)."


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
