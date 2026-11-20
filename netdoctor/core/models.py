"""Estruturas de dados compartilhadas entre probes, regras e relatórios."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    """Por que uma probe não conseguiu coletar o fato (não é um diagnóstico)."""

    TIMEOUT = "TIMEOUT"
    COMMAND_FAILED = "COMMAND_FAILED"
    PARSE_ERROR = "PARSE_ERROR"
    UNSUPPORTED_OS = "UNSUPPORTED_OS"
    UNEXPECTED = "UNEXPECTED"


# Campos que identificam a rede ou a máquina. Ficam no relatório local,
# mas nunca podem ir para a IA (ver explain/llm.py no Marco 5).
SENSITIVE_FIELDS = frozenset({"interface", "ipv4", "gateway", "dns_servers", "server", "host"})


@dataclass
class ProbeResult:
    """Fatos brutos de uma probe. `ok=False` significa "não deu para medir"."""

    name: str
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
