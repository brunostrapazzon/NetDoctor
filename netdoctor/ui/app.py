"""Janela do Modo Cliente: um clique, resultado em linguagem simples, uma ação.

A lógica fica em presenter.py (textos, cores) e worker.py (thread do
diagnóstico); aqui só existe Tk. O Tk só é tocado pela thread principal: o
worker escreve numa fila e a janela lê a fila a cada 100 ms com `after()`.

Três estados, sempre no mesmo cartão: esperando → testando (barra + etapas
marcadas ✔) → resultado (selo ✔/⚠/✖ + o que fazer).
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
    PALETTE,
    SPACE,
    badge_text,
    copy_summary,
    default_report_name,
    progress_fraction,
    progress_text,
    result_view,
    step_line,
)
from netdoctor.ui.worker import DiagnosisWorker

ICON_PATH = Path(__file__).with_name("netdoctor.ico")
POLL_MS = 100
COPIED_MS = 1600
PAD = SPACE["xl"]  # margem interna do cartão
WRAP = 460
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
        self.geometry("560x580")
        self.minsize(520, 500)
        self.worker = DiagnosisWorker()
        self.report: dict[str, Any] | None = None
        self._step_labels: dict[str, ctk.CTkLabel] = {}
        self._done_steps: set[str] = set()
        self._copied_job: str | None = None
        self.fonts = {
            "brand": ctk.CTkFont(size=22, weight="bold"),
            "subtitle": ctk.CTkFont(size=13),
            "title": ctk.CTkFont(size=19, weight="bold"),
            "body": ctk.CTkFont(size=14),
            "section": ctk.CTkFont(size=14, weight="bold"),
            "badge": ctk.CTkFont(size=13, weight="bold"),
            "button": ctk.CTkFont(size=14, weight="bold"),
            "small": ctk.CTkFont(size=12),
        }

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_body()
        self._build_footer()
        # Enter também diagnostica (o worker ignora um segundo início).
        self.bind("<Return>", lambda _e: self.start_diagnosis())
        self.bind("<KP_Enter>", lambda _e: self.start_diagnosis())
        self._show_welcome()

    # --- Montagem -------------------------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=SPACE["xl"], pady=(SPACE["xl"], SPACE["l"]))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="NetDoctor", font=self.fonts["brand"], text_color=PALETTE["text"]
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            header,
            text=p.SUBTITLE,
            font=self.fonts["subtitle"],
            text_color=PALETTE["muted"],
            height=18,
        ).grid(row=1, column=0, sticky="w")
        self.diagnose_btn = ctk.CTkButton(
            header,
            text=p.BUTTON_DIAGNOSE,
            width=180,
            height=42,
            corner_radius=10,
            font=self.fonts["button"],
            fg_color=PALETTE["accent"],
            hover_color=PALETTE["accent_hover"],
            text_color=PALETTE["accent_text"],
            text_color_disabled=PALETTE["accent_disabled_text"],
            command=self.start_diagnosis,
        )
        self.diagnose_btn.grid(row=0, column=1, rowspan=2, sticky="e")

    def _build_body(self) -> None:
        self.card = ctk.CTkFrame(
            self,
            corner_radius=12,
            fg_color=PALETTE["surface"],
            border_width=1,
            border_color=PALETTE["border"],
        )
        self.card.grid(row=1, column=0, sticky="nsew", padx=SPACE["xl"])
        self.card.grid_columnconfigure(0, weight=1)

        self.badge = ctk.CTkLabel(
            self.card, text="", font=self.fonts["badge"], corner_radius=10, height=26
        )
        self.title_label = ctk.CTkLabel(
            self.card,
            text="",
            font=self.fonts["title"],
            text_color=PALETTE["text"],
            wraplength=WRAP,
            justify="left",
            anchor="w",
        )
        self.body_label = ctk.CTkLabel(
            self.card,
            text="",
            font=self.fonts["body"],
            text_color=PALETTE["muted"],
            wraplength=WRAP,
            justify="left",
            anchor="w",
        )
        self.actions_title = ctk.CTkLabel(
            self.card,
            text=p.ACTIONS_TITLE,
            font=self.fonts["section"],
            text_color=PALETTE["text"],
            anchor="w",
        )
        self.actions_label = ctk.CTkLabel(
            self.card,
            text="",
            font=self.fonts["body"],
            text_color=PALETTE["text"],
            wraplength=WRAP,
            justify="left",
            anchor="w",
        )

        # Barra determinada: avança uma etapa por vez, sem fingir progresso.
        self.progress = ctk.CTkProgressBar(
            self.card,
            mode="determinate",
            height=6,
            fg_color=PALETTE["track"],
            progress_color=PALETTE["accent"],
        )
        self.steps_frame = ctk.CTkFrame(self.card, fg_color="transparent")
        for i, (name, label) in enumerate(STEPS):
            text, color = step_line(label, "pending")
            lbl = ctk.CTkLabel(
                self.steps_frame,
                text=text,
                text_color=color,
                font=self.fonts["body"],
                anchor="w",
                height=26,
            )
            lbl.grid(row=i, column=0, sticky="w")
            self._step_labels[name] = lbl

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=SPACE["xl"], pady=(SPACE["l"], SPACE["s"]))
        secondary = {
            "height": 36,
            "corner_radius": 8,
            "font": self.fonts["body"],
            "fg_color": "transparent",
            "hover_color": PALETTE["secondary_hover"],
            "border_width": 1,
            "border_color": PALETTE["border"],
            "text_color": PALETTE["text"],
            "text_color_disabled": PALETTE["muted"],
            "state": "disabled",
        }
        self.save_btn = ctk.CTkButton(
            footer, text=p.BUTTON_SAVE, width=150, command=self.save_report, **secondary
        )
        self.save_btn.grid(row=0, column=0, padx=(0, SPACE["s"]))
        self.copy_btn = ctk.CTkButton(
            footer, text=p.BUTTON_COPY, width=150, command=self.copy_to_clipboard, **secondary
        )
        self.copy_btn.grid(row=0, column=1)
        self.status_label = ctk.CTkLabel(
            self,
            text=f"v{__version__}",
            font=self.fonts["small"],
            text_color=PALETTE["muted"],
            anchor="w",
            justify="left",
            wraplength=WRAP + 40,
        )
        self.status_label.grid(row=3, column=0, sticky="ew", padx=SPACE["xl"], pady=(0, SPACE["l"]))

    # --- Estados da tela ---------------------------------------------------------------

    def _hide_result_parts(self) -> None:
        for widget in (
            self.badge,
            self.actions_title,
            self.actions_label,
            self.progress,
            self.steps_frame,
        ):
            widget.grid_forget()

    def _place_texts(self, with_badge: bool) -> None:
        if with_badge:
            self.badge.grid(row=0, column=0, sticky="w", padx=PAD, pady=(PAD, SPACE["m"]))
        title_top = 0 if with_badge else PAD
        self.title_label.grid(row=1, column=0, sticky="ew", padx=PAD, pady=(title_top, SPACE["s"]))
        self.body_label.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(0, SPACE["l"]))

    def _show_welcome(self) -> None:
        self._hide_result_parts()
        self.title_label.configure(text=p.WELCOME_TITLE)
        self.body_label.configure(text=p.WELCOME_BODY)
        self._place_texts(with_badge=False)

    def _show_running(self) -> None:
        self._hide_result_parts()
        self.title_label.configure(text=p.RUNNING_TITLE)
        self.body_label.configure(text=progress_text("start"))
        self._place_texts(with_badge=False)
        self._done_steps.clear()
        self.progress.set(0)
        self.progress.grid(row=3, column=0, sticky="ew", padx=PAD, pady=(0, SPACE["l"]))
        for name, label in STEPS:
            text, color = step_line(label, "pending")
            self._step_labels[name].configure(text=text, text_color=color)
        self.steps_frame.grid(row=4, column=0, sticky="w", padx=PAD, pady=(0, PAD))

    def _show_badge(self, text: str, color: tuple[str, str], tint: tuple[str, str]) -> None:
        self.badge.configure(text=text, text_color=color, fg_color=tint)
        self._place_texts(with_badge=True)

    def _show_result(self, report: dict[str, Any]) -> None:
        self.progress.set(1)
        self._hide_result_parts()
        view = result_view(report["explanation"])
        self.title_label.configure(text=view.title)
        self.body_label.configure(text=view.body)
        self._show_badge(badge_text(view), view.color, view.tint)
        self.actions_title.grid(row=3, column=0, sticky="ew", padx=PAD, pady=(0, SPACE["xs"]))
        self.actions_label.configure(text=view.actions)
        self.actions_label.grid(row=4, column=0, sticky="ew", padx=PAD, pady=(0, PAD))

    def _show_error(self) -> None:
        self._hide_result_parts()
        self.title_label.configure(text=p.ERROR_TITLE)
        self.body_label.configure(text=p.ERROR_BODY)
        icon, color = p.SEVERITY_STYLE["warning"]
        label = p.SEVERITY_LABEL["warning"]
        self._show_badge(f"{icon}  {label}", color, p.SEVERITY_TINT["warning"])

    def _set_status(self, text: str, tone: str = "muted") -> None:
        self.status_label.configure(text=text, text_color=PALETTE[tone])

    # --- Ações -----------------------------------------------------------------------

    def start_diagnosis(self) -> None:
        if not self.worker.start():
            return
        self.report = None
        self.diagnose_btn.configure(state="disabled", text=p.BUTTON_RUNNING)
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
                self._mark_step(event.payload, done=False)
            elif event.kind == "finished":
                self._mark_step(event.payload, done=True)
            elif event.kind == "done":
                self.report = event.payload
                self._show_result(event.payload)
                finished = True
            elif event.kind == "error":
                self._show_error()
                finished = True
        if finished:
            self.diagnose_btn.configure(state="normal", text=p.BUTTON_AGAIN)
            if self.report:
                self.save_btn.configure(state="normal")
                self.copy_btn.configure(state="normal")
        else:
            self.after(POLL_MS, self._poll)

    def _mark_step(self, name: str, done: bool) -> None:
        label = dict(STEPS).get(name)
        if label is None or name in self._done_steps:
            return
        if done:
            self._done_steps.add(name)
            self.progress.set(progress_fraction(len(self._done_steps), len(STEPS)))
        text, color = step_line(label, "done" if done else "running")
        self._step_labels[name].configure(text=text, text_color=color)

    def save_report(self) -> None:
        if not self.report:
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title=p.BUTTON_SAVE,
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
        self.copy_btn.configure(text=p.BUTTON_COPIED, text_color=PALETTE["ok"])
        self._copied_job = self.after(COPIED_MS, self._reset_copy_button)

    def _reset_copy_button(self) -> None:
        if self._copied_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._copied_job)
            self._copied_job = None
        self.copy_btn.configure(text=p.BUTTON_COPY, text_color=PALETTE["text"])


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
