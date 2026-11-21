"""Janela do Modo Cliente: um clique, resultado em linguagem simples, uma ação.

A lógica fica em presenter.py (textos, cores, estado das etapas) e worker.py
(thread do diagnóstico); aqui só existe Tk. O Tk só é tocado pela thread
principal: o worker escreve numa fila e a janela lê a fila a cada 100 ms com
`after()`.

Layout de caixa de diálogo do Windows: título no topo, conteúdo direto no
fundo da janela (sem cartão), linha fina, e os botões embaixo com o principal
à direita. Três estados no mesmo lugar: esperando → testando (barra + lista de
etapas com o status de cada uma) → resultado (faixa de cor + palavra da
gravidade, explicação e o que fazer).
"""

from __future__ import annotations

import contextlib
import os
import sys
from datetime import datetime
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from netdoctor import __version__
from netdoctor.report.html_report import write_html
from netdoctor.report.json_report import write_json
from netdoctor.ui import presenter as p
from netdoctor.ui.presenter import (
    FONT_FAMILY,
    FONT_FAMILY_STRONG,
    PALETTE,
    SPACE,
    copy_summary,
    default_report_name,
    progress_fraction,
    progress_text,
    result_view,
    step_state,
    step_status,
)
from netdoctor.ui.worker import DiagnosisWorker

ICON_PATH = Path(__file__).with_name("netdoctor.ico")
POLL_MS = 100
COPIED_MS = 1600
MARGIN = SPACE["xl"]
WRAP = 470
STRIPE = 4  # largura da faixa de cor da gravidade
STEPS = (
    ("adapter", "Conexão do computador"),
    ("wifi", "Sinal do Wi-Fi"),
    ("ping", "Roteador e internet"),
    ("dns", "Nomes dos sites"),
    ("http", "Acesso aos sites"),
)


class ClientApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__(fg_color=PALETTE["window"])
        self.title("NetDoctor")
        # Chamar iconbitmap aqui impede o CTk de trocar pelo ícone dele (after 200 ms).
        with contextlib.suppress(Exception):
            self.iconbitmap(str(ICON_PATH))
        self.geometry("560x540")
        self.minsize(520, 480)
        self.worker = DiagnosisWorker()
        self.report: dict[str, Any] | None = None
        self._step_status: dict[str, ctk.CTkLabel] = {}
        self._done_steps: set[str] = set()
        self._copied_job: str | None = None
        # O tema padrão do CustomTkinter usa Roboto; no Windows a fonte do sistema é Segoe UI.
        self.fonts = {
            "brand": ctk.CTkFont(family=FONT_FAMILY_STRONG, size=20),
            "title": ctk.CTkFont(family=FONT_FAMILY_STRONG, size=18),
            "label": ctk.CTkFont(family=FONT_FAMILY_STRONG, size=13),
            "section": ctk.CTkFont(family=FONT_FAMILY_STRONG, size=14),
            "body": ctk.CTkFont(family=FONT_FAMILY, size=14),
            "button": ctk.CTkFont(family=FONT_FAMILY, size=14),
            "small": ctk.CTkFont(family=FONT_FAMILY, size=12),
        }

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._rule(row=1)
        self._build_body()
        self._rule(row=3)
        self._build_footer()
        # Enter aciona o botão principal, como numa caixa de diálogo do Windows.
        self.bind("<Return>", lambda _e: self.start_diagnosis())
        self.bind("<KP_Enter>", lambda _e: self.start_diagnosis())
        self._show_welcome()

    # --- Montagem -------------------------------------------------------------------

    def _label(self, parent: Any, font: str, color: str = "text", **kw: Any) -> ctk.CTkLabel:
        return ctk.CTkLabel(
            parent,
            text="",
            font=self.fonts[font],
            text_color=PALETTE[color],
            justify="left",
            anchor="w",
            **kw,
        )

    def _rule(self, row: int) -> None:
        ctk.CTkFrame(self, height=1, corner_radius=0, fg_color=PALETTE["rule"]).grid(
            row=row, column=0, sticky="ew"
        )

    def _build_header(self) -> None:
        brand = self._label(self, "brand")
        brand.configure(text="NetDoctor")
        brand.grid(row=0, column=0, sticky="w", padx=MARGIN, pady=(SPACE["l"], SPACE["m"]))

    def _build_body(self) -> None:
        body = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        body.grid(row=2, column=0, sticky="nsew", padx=MARGIN, pady=MARGIN)
        body.grid_columnconfigure(1, weight=1)

        # Faixa de cor da gravidade, só no resultado.
        # height=1: só a largura importa; a altura vem do sticky="ns".
        self.stripe = ctk.CTkFrame(body, width=STRIPE, height=1, corner_radius=0)
        self.text_col = ctk.CTkFrame(body, fg_color="transparent", corner_radius=0)
        self.text_col.grid(row=0, column=1, sticky="nsew")
        self.text_col.grid_columnconfigure(0, weight=1)

        self.severity_label = self._label(self.text_col, "label")
        self.title_label = self._label(self.text_col, "title", wraplength=WRAP)
        self.body_label = self._label(self.text_col, "body", "muted", wraplength=WRAP)
        self.actions_title = self._label(self.text_col, "section")
        self.actions_title.configure(text=p.ACTIONS_TITLE)
        self.actions_label = self._label(self.text_col, "body", wraplength=WRAP)

        self.progress = ctk.CTkProgressBar(
            self.text_col,
            mode="determinate",
            height=4,
            corner_radius=2,
            fg_color=PALETTE["track"],
            progress_color=PALETTE["accent"],
        )
        self.steps_frame = ctk.CTkFrame(self.text_col, fg_color="transparent", corner_radius=0)
        self.steps_frame.grid_columnconfigure(0, weight=1)
        for i, (name, label) in enumerate(STEPS):
            row_label = self._label(self.steps_frame, "body", height=28)
            row_label.configure(text=label)
            row_label.grid(row=i, column=0, sticky="w")
            status = self._label(self.steps_frame, "body", "muted", height=28)
            status.configure(anchor="e")
            status.grid(row=i, column=1, sticky="e")
            self._step_status[name] = status

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent", corner_radius=0)
        footer.grid(row=4, column=0, sticky="ew", padx=MARGIN, pady=SPACE["l"])
        footer.grid_columnconfigure(0, weight=1)

        self.status_label = self._label(footer, "small", "muted", wraplength=220)
        self.status_label.configure(text=f"Versão {__version__}")
        self.status_label.grid(row=0, column=0, sticky="w", padx=(0, SPACE["m"]))

        common = {"height": 32, "corner_radius": 4, "font": self.fonts["button"]}
        secondary = {
            **common,
            "fg_color": PALETTE["button"],
            "hover_color": PALETTE["button_hover"],
            "border_width": 1,
            "border_color": PALETTE["button_border"],
            "text_color": PALETTE["text"],
            "text_color_disabled": PALETTE["muted"],
            "state": "disabled",
        }
        self.save_btn = ctk.CTkButton(
            footer, text=p.BUTTON_SAVE, width=136, command=self.save_report, **secondary
        )
        self.save_btn.grid(row=0, column=1, padx=(0, SPACE["s"]))
        self.copy_btn = ctk.CTkButton(
            footer, text=p.BUTTON_COPY, width=120, command=self.copy_to_clipboard, **secondary
        )
        self.copy_btn.grid(row=0, column=2, padx=(0, SPACE["s"]))
        self.diagnose_btn = ctk.CTkButton(
            footer,
            text=p.BUTTON_DIAGNOSE,
            width=120,
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            text_color=PALETTE["accent_text"],
            text_color_disabled=PALETTE["accent_disabled_text"],
            command=self.start_diagnosis,
            **common,
        )
        self.diagnose_btn.grid(row=0, column=3)

    # --- Estados da tela ---------------------------------------------------------------

    def _clear(self) -> None:
        for widget in (
            self.stripe,
            self.severity_label,
            self.actions_title,
            self.actions_label,
            self.progress,
            self.steps_frame,
        ):
            widget.grid_forget()

    def _place_texts(self, severity: tuple[str, tuple[str, str]] | None = None) -> None:
        """Título e corpo; com `severity` (palavra, cor), mostra também a faixa e a palavra."""
        if severity:
            word, color = severity
            self.stripe.configure(fg_color=color)
            self.stripe.grid(row=0, column=0, sticky="ns", padx=(0, SPACE["l"]))
            self.severity_label.configure(text=word, text_color=color)
            self.severity_label.grid(row=0, column=0, sticky="w", pady=(0, SPACE["xs"]))
        self.title_label.grid(row=1, column=0, sticky="ew", pady=(0, SPACE["s"]))
        self.body_label.grid(row=2, column=0, sticky="ew", pady=(0, SPACE["l"]))

    def _show_welcome(self) -> None:
        self._clear()
        self.title_label.configure(text=p.WELCOME_TITLE)
        self.body_label.configure(text=p.WELCOME_BODY)
        self._place_texts()

    def _show_running(self) -> None:
        self._clear()
        self.title_label.configure(text=p.RUNNING_TITLE)
        self.body_label.configure(text=progress_text("start"))
        self._place_texts()
        self._done_steps.clear()
        self.progress.set(0)
        self.progress.grid(row=3, column=0, sticky="ew", pady=(0, SPACE["m"]))
        for name, _label in STEPS:
            self._set_step(name, "pending")
        self.steps_frame.grid(row=4, column=0, sticky="ew")

    def _show_result(self, report: dict[str, Any]) -> None:
        self.progress.set(1)
        self._clear()
        view = result_view(report["explanation"])
        self.title_label.configure(text=view.title)
        self.body_label.configure(text=view.body)
        self._place_texts((view.label, view.color))
        self.actions_title.grid(row=3, column=0, sticky="ew", pady=(0, SPACE["xs"]))
        self.actions_label.configure(text=view.actions)
        self.actions_label.grid(row=4, column=0, sticky="ew")

    def _show_error(self) -> None:
        self._clear()
        self.title_label.configure(text=p.ERROR_TITLE)
        self.body_label.configure(text=p.ERROR_BODY)
        self._place_texts((p.SEVERITY_LABEL["warning"], p.SEVERITY_COLOR["warning"]))

    def _set_status(self, text: str, tone: str = "muted") -> None:
        self.status_label.configure(text=text, text_color=PALETTE[tone])

    def _set_step(self, name: str, state: p.StepState) -> None:
        text, color = step_status(state)
        self._step_status[name].configure(text=text, text_color=color)

    # --- Ações -----------------------------------------------------------------------

    def start_diagnosis(self) -> None:
        if not self.worker.start():
            return
        self.report = None
        self.diagnose_btn.configure(
            state="disabled", text=p.BUTTON_RUNNING, fg_color=PALETTE["accent_disabled"]
        )
        self.save_btn.configure(state="disabled")
        self._reset_copy_button()
        self.copy_btn.configure(state="disabled")
        self._set_status("")
        self._show_running()
        self.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        finished = False
        for event in self.worker.drain():
            if event.kind == "progress":
                self.body_label.configure(text=progress_text(event.payload))
                if event.payload in dict(STEPS) and event.payload not in self._done_steps:
                    self._set_step(event.payload, "running")
            elif event.kind == "finished":
                self._finish_step(event.payload)
            elif event.kind == "done":
                self.report = event.payload
                self._show_result(event.payload)
                finished = True
            elif event.kind == "error":
                self._show_error()
                finished = True
        if finished:
            self.diagnose_btn.configure(
                state="normal", text=p.BUTTON_AGAIN, fg_color=PALETTE["accent"]
            )
            if self.report:
                self.save_btn.configure(state="normal")
                self.copy_btn.configure(state="normal")
            self._set_status(f"Versão {__version__}")
        else:
            self.after(POLL_MS, self._poll)

    def _finish_step(self, probe: Any) -> None:
        name = probe.name
        if name not in dict(STEPS) or name in self._done_steps:
            return
        self._done_steps.add(name)
        self.progress.set(progress_fraction(len(self._done_steps), len(STEPS)))
        self._set_step(name, step_state(probe))

    def save_report(self) -> None:
        if not self.report:
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title=p.BUTTON_SAVE.rstrip("…"),
            defaultextension=".html",
            initialfile=default_report_name(datetime.now()),
            filetypes=[("Relatório (HTML)", "*.html")],
        )
        if not path:
            return
        html_path = Path(path)
        try:
            write_html(self.report, html_path)
            write_json(self.report, html_path.with_suffix(".json"))
        except OSError:
            self._set_status(p.SAVE_FAILED_TEXT, "warn")
            return
        self._set_status(p.saved_text(str(html_path)), "ok")

    def copy_to_clipboard(self) -> None:
        if not self.report:
            return
        self.clipboard_clear()
        self.clipboard_append(copy_summary(self.report))
        self._set_status(p.COPIED_TEXT, "ok")
        # Confirmação no próprio botão por um instante, depois volta ao normal.
        self._reset_copy_button()
        self.copy_btn.configure(text=p.BUTTON_COPIED)
        self._copied_job = self.after(COPIED_MS, self._reset_copy_button)

    def _reset_copy_button(self) -> None:
        if self._copied_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._copied_job)
            self._copied_job = None
        self.copy_btn.configure(text=p.BUTTON_COPY)


def _ensure_std_streams() -> None:
    # No .exe sem console (PyInstaller --windowed / pythonw) stdout e stderr são None.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")  # noqa: SIM115


def main() -> int:
    _ensure_std_streams()
    ctk.set_appearance_mode("system")
    ClientApp().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
