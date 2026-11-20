"""Roda o diagnóstico fora da thread da interface.

O Tk só pode ser tocado pela thread principal. O worker escreve eventos numa
fila e a janela lê a fila com `after()`, sem travar.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from netdoctor.core.models import ProbeResult
from netdoctor.core.runner import run_all
from netdoctor.pipeline import AUTO, run_pipeline


@dataclass(frozen=True)
class Event:
    kind: str  # "progress" (probe começou) | "finished" (probe terminou) | "done" | "error"
    payload: Any = None


class DiagnosisWorker:
    def __init__(
        self,
        runner: Callable[..., list[ProbeResult]] = run_all,
        llm_config: Any = AUTO,
    ) -> None:
        self.events: queue.Queue[Event] = queue.Queue()
        self._runner = runner
        self._llm_config = llm_config
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if self.running:
            return False
        self._thread = threading.Thread(target=self._run, daemon=True, name="netdoctor-diag")
        self._thread.start()
        return True

    def _run(self) -> None:
        self.events.put(Event("progress", "start"))
        try:
            result = run_pipeline(
                lambda step: self.events.put(Event("progress", step)),
                lambda probe: self.events.put(Event("finished", probe.name)),
                runner=self._runner,
                llm_config=self._llm_config,
            )
        except Exception as exc:  # a janela nunca pode ficar travada em "testando"
            self.events.put(Event("error", type(exc).__name__))
        else:
            self.events.put(Event("done", result.report))

    def drain(self) -> list[Event]:
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out
