"""Execução de comandos do sistema de forma segura para CLI e para o .exe sem console."""

from __future__ import annotations

import locale
import subprocess
import sys


class CommandTimeout(Exception):
    pass


class CommandError(Exception):
    pass


def _default_encoding() -> str:
    # ping/ipconfig escrevem na code page OEM do console (ex.: 850 em pt-BR).
    return "oem" if sys.platform == "win32" else locale.getpreferredencoding(False)


def run_command(args: list[str], timeout: float, encoding: str | None = None) -> tuple[int, str]:
    """Roda `args` e devolve (returncode, stdout decodificado).

    Todas as streams são redirecionadas porque, no .exe `--windowed` do
    PyInstaller, sys.stdin/stdout/stderr são None. CREATE_NO_WINDOW evita
    que uma janela de console pisque na interface gráfica.
    """
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    try:
        completed = subprocess.run(
            args,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
            check=False,
            **kwargs,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandTimeout(f"{args[0]} excedeu {timeout}s") from exc
    except OSError as exc:
        raise CommandError(f"{args[0]}: {exc}") from exc
    text = completed.stdout.decode(encoding or _default_encoding(), errors="replace")
    return completed.returncode, text
