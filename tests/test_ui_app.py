"""A janela de verdade (`ui/app.py`) com widgets falsos: nada é desenhado na tela.

Os widgets falsos aceitam só os parâmetros que o widget real do CustomTkinter
aceita (lidos da assinatura do `__init__` instalado), então um parâmetro
errado quebra o teste em vez de quebrar a janela do usuário.
"""

from __future__ import annotations

import importlib
import inspect
import sys
import types

import customtkinter as real_ctk
import pytest

from netdoctor.core.models import ProbeResult
from netdoctor.ui.worker import Event

# Parâmetros que o CTk repassa ao widget Tk de baixo (**kwargs) e que usamos.
TK_PASSTHROUGH = {"justify"}


def _allowed(real_cls: type) -> set[str]:
    params = set(inspect.signature(real_cls.__init__).parameters) - {"self", "kwargs", "args"}
    return params | TK_PASSTHROUGH


class FakeWidget:
    real: type = object

    def __init__(self, master=None, **kw):
        self._check(kw)
        self.kw = dict(kw)
        self.gridded = False

    def _check(self, kw):
        bad = set(kw) - _allowed(self.real) - {"state"}
        assert not bad, f"{self.real.__name__} não aceita {bad}"

    def configure(self, **kw):
        self._check(kw)
        self.kw.update(kw)

    def cget(self, key):
        return self.kw.get(key)

    def grid(self, **kw):
        self.gridded = True

    def grid_forget(self):
        self.gridded = False

    def grid_columnconfigure(self, *a, **k):
        pass

    def grid_rowconfigure(self, *a, **k):
        pass

    def set(self, value):
        self.kw["value"] = value


def _fake(real_cls):
    return type(real_cls.__name__, (FakeWidget,), {"real": real_cls})


class FakeCTk(FakeWidget):
    real = real_ctk.CTk

    def __init__(self, **kw):
        super().__init__(None, **kw)
        self.after_calls = []
        self.clipboard = ""

    def title(self, *_):
        pass

    def iconbitmap(self, *_):
        pass

    def geometry(self, *_):
        pass

    def minsize(self, *_):
        pass

    def bind(self, *_):
        pass

    def after(self, ms, fn):
        self.after_calls.append(fn)
        return f"job{len(self.after_calls)}"

    def after_cancel(self, _):
        pass

    def clipboard_clear(self):
        self.clipboard = ""

    def clipboard_append(self, text):
        self.clipboard += text


class FakeFont:
    def __init__(self, **kw):
        assert set(kw) <= set(inspect.signature(real_ctk.CTkFont.__init__).parameters)
        self.kw = kw


class FakeWorker:
    def __init__(self):
        self.queue = []

    def start(self):
        return True

    def drain(self):
        out, self.queue = self.queue, []
        return out


@pytest.fixture
def app_module(monkeypatch):
    fake = types.SimpleNamespace(
        CTk=FakeCTk,
        CTkFrame=_fake(real_ctk.CTkFrame),
        CTkLabel=_fake(real_ctk.CTkLabel),
        CTkButton=_fake(real_ctk.CTkButton),
        CTkProgressBar=_fake(real_ctk.CTkProgressBar),
        CTkFont=FakeFont,
        set_appearance_mode=lambda *_: None,
    )
    monkeypatch.setitem(sys.modules, "customtkinter", fake)
    monkeypatch.delitem(sys.modules, "netdoctor.ui.app", raising=False)
    module = importlib.import_module("netdoctor.ui.app")
    monkeypatch.setattr(module, "DiagnosisWorker", FakeWorker)
    yield module
    sys.modules.pop("netdoctor.ui.app", None)


REPORT = {
    "version": "0.1.0",
    "generated_at": "2026-11-20T12:00:00+00:00",
    "diagnosis": {"primary": "WIFI_WEAK", "findings": [{"code": "WIFI_WEAK"}]},
    "explanation": {
        "code": "WIFI_WEAK",
        "severity": "warning",
        "headline": "Seu Wi-Fi está fraco neste lugar.",
        "detail": "O sinal chega fraco ao computador.",
        "actions": ["Aproxime-se do roteador."],
        "also": [],
        "notes": [],
        "numbers": [],
        "source": "template",
    },
    "probes": [],
}


def test_window_goes_through_every_state(app_module):
    p = app_module.p
    w = app_module.ClientApp()
    assert w.title_label.kw["text"] == p.WELCOME_TITLE
    assert not w.stripe.gridded and not w.severity_label.gridded
    assert w.fonts["body"].kw["family"] == "Segoe UI"

    w.start_diagnosis()
    assert w.diagnose_btn.kw["state"] == "disabled"
    assert w.steps_frame.gridded and w.progress.gridded

    w.worker.queue = [
        Event("progress", "adapter"),
        Event("finished", ProbeResult("adapter", ok=True, data={"connected": True})),
        Event("progress", "wifi"),
        Event("finished", ProbeResult("wifi", ok=True, data={"skipped": "not_wifi"})),
        Event("progress", "ping"),
        Event("finished", ProbeResult("ping", ok=False, error="TIMEOUT")),
        Event("progress", "dns"),
    ]
    w._poll()
    assert w._step_status["adapter"].kw["text"] == "ok"
    assert w._step_status["wifi"].kw["text"] == "não se aplica"
    assert w._step_status["ping"].kw["text"] == "não mediu"
    assert w._step_status["dns"].kw["text"] == "testando…"
    assert w._step_status["http"].kw["text"] == ""
    assert w.progress.kw["value"] == 0.6

    w.worker.queue = [Event("done", REPORT)]
    w._poll()
    assert w.stripe.gridded and w.stripe.kw["fg_color"] == p.PALETTE["warn"]
    assert w.severity_label.kw["text"] == "Atenção"
    assert w.title_label.kw["text"] == "Seu Wi-Fi está fraco neste lugar."
    assert w.actions_label.kw["text"] == "1.  Aproxime-se do roteador."
    assert not w.steps_frame.gridded
    assert w.diagnose_btn.kw["text"] == p.BUTTON_AGAIN
    assert w.save_btn.kw["state"] == "normal" and w.copy_btn.kw["state"] == "normal"

    w.copy_to_clipboard()
    assert w.clipboard.startswith("NetDoctor: Seu Wi-Fi está fraco")
    assert w.copy_btn.kw["text"] == p.BUTTON_COPIED
    w._reset_copy_button()
    assert w.copy_btn.kw["text"] == p.BUTTON_COPY


def test_error_state_shows_word_and_stripe(app_module):
    w = app_module.ClientApp()
    w.start_diagnosis()
    w.worker.queue = [Event("error", "RuntimeError")]
    w._poll()
    assert w.title_label.kw["text"] == app_module.p.ERROR_TITLE
    assert w.severity_label.kw["text"] == "Atenção" and w.stripe.gridded
    assert w.save_btn.kw["state"] == "disabled"
