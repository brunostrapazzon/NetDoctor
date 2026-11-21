"""Execução de comandos do sistema de forma segura para CLI e para o .exe sem console."""

from __future__ import annotations

import locale
import os
import subprocess
import sys


class CommandTimeout(Exception):
    pass


class CommandError(Exception):
    pass


def _default_encoding() -> str:
    # ping/ipconfig escrevem na code page OEM do console (ex.: 850 em pt-BR).
    return "oem" if sys.platform == "win32" else locale.getpreferredencoding(False)


def decode_output(raw: bytes, encoding: str | None = None) -> str:
    """Decodifica a saída de um comando.

    Sem `encoding` explícito, tenta UTF-8 estrito e cai para a code page OEM.
    Motivo: no Windows 11 o `netsh` escreve UTF-8 quando a saída é redirecionada,
    enquanto o `ping` escreve cp850. Texto cp850 com acento quase nunca é UTF-8
    válido, então a tentativa é segura.
    """
    if encoding:
        return raw.decode(encoding, errors="replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode(_default_encoding(), errors="replace")


def run_command(
    args: list[str],
    timeout: float,
    encoding: str | None = None,
    env_extra: dict[str, str] | None = None,
) -> tuple[int, str]:
    """Roda `args` e devolve (returncode, stdout decodificado).

    Todas as streams são redirecionadas porque, no .exe `--windowed` do
    PyInstaller, sys.stdin/stdout/stderr são None. CREATE_NO_WINDOW evita
    que uma janela de console pisque na interface gráfica.

    `env_extra` passa valores ao comando por variável de ambiente, nunca
    colados no texto do comando (evita injeção em scripts do PowerShell).
    """
    kwargs: dict = {}
    if env_extra:
        kwargs["env"] = {**os.environ, **env_extra}
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
    return completed.returncode, decode_output(completed.stdout, encoding)
