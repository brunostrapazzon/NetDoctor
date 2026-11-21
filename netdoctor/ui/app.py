"""Janela do Modo Cliente: um clique, resultado em linguagem simples, uma ação.

A lógica fica em presenter.py (texto) e worker.py (thread do diagnóstico);
aqui só existe Tk. O Tk só é tocado pela thread principal: o worker escreve
numa fila e a janela lê a fila a cada 100 ms com `after()`.
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
from netdoctor.ui.presenter import copy_summary, default_report_name, progress_text, result_view
from netdoctor.ui.worker import DiagnosisWorker

ICON_PATH = Path(__file__).with_name("netdoctor.ico")
POLL_MS = 100
WRAP = 470
STEPS = (
    ("adapter", "Conexão do computador"),
    ("wifi", "Sinal do Wi-Fi"),
    ("ping", "Roteador e internet"),
    ("dns", "Nomes dos sites"),
    ("http", "Acesso aos sites"),
)
WELCOME_TITLE = "Vamos testar sua internet?"
WELCOME_BODY = (
    "Clique em Diagnosticar. Em cerca de 10 segundos o NetDoctor mostra o que está "
    "acontecendo e o que fazer. Funciona mesmo sem internet."
)


class ClientApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("NetDoctor")
        # Chamar iconbitmap aqui impede o CTk de trocar pelo ícone dele (after 200 ms).
        with contextlib.suppress(Exception):
            self.iconbitmap(str(ICON_PATH))
        self.geometry("560x520")
        self.minsize(500, 460)
        self.worker = DiagnosisWorker()
        self.report: dict[str, Any] | None = None
        self._step_labels: dict[str, ctk.CTkLabel] = {}

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self._build_body()
        self._build_footer()
        self._show_welcome()

    # --- Montagem -------------------------------------------------------------------

    def _build_header(self) -> None:
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=20, pady=(18, 8))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="NetDoctor", font=ctk.CTkFont(size=22, weight="bold")).grid(
            row=0, column=0, sticky="w"
        )
        self.diagnose_btn = ctk.CTkButton(
            header, text="Diagnosticar", width=150, height=36, command=self.start_diagnosis
        )
        self.diagnose_btn.grid(row=0, column=1, sticky="e")

    def _build_body(self) -> None:
        self.card = ctk.CTkFrame(self, corner_radius=12)
        self.card.grid(row=1, column=0, sticky="nsew", padx=20, pady=8)
        self.card.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            self.card,
            text="",
            font=ctk.CTkFont(size=19, weight="bold"),
            wraplength=WRAP,
            justify="left",
            anchor="w",
        )
        self.title_label.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 6))

        self.body_label = ctk.CTkLabel(
            self.card, text="", wraplength=WRAP, justify="left", anchor="w"
        )
        self.body_label.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))

        self.actions_title = ctk.CTkLabel(
            self.card, text="O que fazer:", font=ctk.CTkFont(weight="bold"), anchor="w"
        )
        self.actions_label = ctk.CTkLabel(
            self.card, text="", wraplength=WRAP, justify="left", anchor="w"
        )

        self.progress = ctk.CTkProgressBar(self.card, mode="indeterminate")
        self.steps_frame = ctk.CTkFrame(self.card, fg_color="transparent")
        for i, (name, label) in enumerate(STEPS):
            lbl = ctk.CTkLabel(self.steps_frame, text=f"○  {label}", anchor="w")
            lbl.grid(row=i, column=0, sticky="w", pady=1)
            self._step_labels[name] = lbl

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.grid(row=2, column=0, sticky="ew", padx=20, pady=(8, 4))
        self.save_btn = ctk.CTkButton(
            footer, text="Salvar relatório", command=self.save_report, state="disabled"
        )
        self.save_btn.grid(row=0, column=0, padx=(0, 8))
        self.copy_btn = ctk.CTkButton(
            footer,
            text="Copiar resumo",
            command=self.copy_to_clipboard,
            state="disabled",
            fg_color="transparent",
            border_width=1,
            text_color=("#1d2330", "#e6e9ef"),
        )
        self.copy_btn.grid(row=0, column=1)
        self.status_label = ctk.CTkLabel(
            self, text=f"v{__version__}", text_color="gray", anchor="w", wraplength=WRAP + 40
        )
        self.status_label.grid(row=3, column=0, sticky="ew", padx=20, pady=(0, 12))

    # --- Estados da tela ---------------------------------------------------------------

    def _hide_result_parts(self) -> None:
        for widget in (self.actions_title, self.actions_label, self.progress, self.steps_frame):
            widget.grid_forget()

    def _show_welcome(self) -> None:
        self._hide_result_parts()
        self.title_label.configure(text=WELCOME_TITLE, text_color=("#1d2330", "#e6e9ef"))
        self.body_label.configure(text=WELCOME_BODY)

    def _show_running(self) -> None:
        self._hide_result_parts()
        self.title_label.configure(text="Testando sua conexão…", text_color=("#1d2330", "#e6e9ef"))
        self.body_label.configure(text=progress_text("start"))
        self.progress.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 12))
        self.progress.start()
        for name, label in STEPS:
            self._step_labels[name].configure(text=f"○  {label}", text_color="gray")
        self.steps_frame.grid(row=3, column=0, sticky="w", padx=18, pady=(0, 18))

    def _show_result(self, report: dict[str, Any]) -> None:
        self.progress.stop()
        self._hide_result_parts()
        view = result_view(report["explanation"])
        self.title_label.configure(text=f"{view.icon}  {view.title}", text_color=view.color)
        self.body_label.configure(text=view.body)
        self.actions_title.grid(row=2, column=0, sticky="ew", padx=18, pady=(4, 2))
        self.actions_label.configure(text=view.actions)
        self.actions_label.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 18))

    def _show_error(self) -> None:
        self.progress.stop()
        self._hide_result_parts()
        self.title_label.configure(
            text="⚠  Não foi possível terminar o teste.", text_color=("#946200", "#ffd36b")
        )
        self.body_label.configure(text="Feche outros programas e clique em Diagnosticar de novo.")

    # --- Ações -----------------------------------------------------------------------

    def start_diagnosis(self) -> None:
        if not self.worker.start():
            return
        self.report = None
        self.diagnose_btn.configure(state="disabled", text="Testando…")
        self.save_btn.configure(state="disabled")
        self.copy_btn.configure(state="disabled")
        self.status_label.configure(text="")
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
            self.diagnose_btn.configure(state="normal", text="Diagnosticar de novo")
            if self.report:
                self.save_btn.configure(state="normal")
                self.copy_btn.configure(state="normal")
        else:
            self.after(POLL_MS, self._poll)

    def _mark_step(self, name: str, done: bool) -> None:
        label = dict(STEPS).get(name)
        if label is None:
            return
        if done:
            self._step_labels[name].configure(text=f"✔  {label}", text_color=("#1d2330", "#e6e9ef"))
        else:
            self._step_labels[name].configure(text=f"…  {label}")

    def save_report(self) -> None:
        if not self.report:
            return
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Salvar relatório",
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
            self.status_label.configure(
                text="Não foi possível salvar nesse local. Tente outra pasta."
            )
            return
        self.status_label.configure(
            text=f"Relatório salvo em {html_path} (e uma cópia .json para o suporte)."
        )

    def copy_to_clipboard(self) -> None:
        if not self.report:
            return
        self.clipboard_clear()
        self.clipboard_append(copy_summary(self.report))
        self.status_label.configure(text="Resumo copiado. Cole na conversa com o suporte.")


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
