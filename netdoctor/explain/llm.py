"""Explicação via LLM: opcional, com fallback silencioso para os templates.

Princípios (ver NETDOCTOR_SPEC.md e a skill netdoctor-milestone):
- A IA **não decide** nada. Recebe o diagnóstico já decidido e o texto do
  template, e só reescreve em linguagem simples.
- **Privacidade por allowlist:** o payload é montado só a partir de códigos,
  gravidade, tipo de conexão e de uma lista fechada de campos numéricos ou
  enumerados da evidência. Nunca recebe SSID, MAC, IP, hostname ou nome de
  adaptador, porque esses campos não estão na lista.
- **Nunca quebra:** sem configuração, sem internet, timeout, HTTP de erro ou
  resposta fora do formato → devolve o template. O usuário nunca vê erro de IA.

Provedores com API compatível com OpenAI (`POST {base_url}/chat/completions`):
Groq, OpenAI e Ollama local. Feito com urllib para não acrescentar dependência
ao .exe.
"""

from __future__ import annotations

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from netdoctor.core.models import Diagnosis
from netdoctor.explain.templates import TEMPLATES, Explanation

DEFAULT_BASE_URLS = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
}
DEFAULT_TIMEOUT_S = 8.0
MAX_TEXT = 220

# Achados em que a internet não está disponível: não adianta chamar um
# provedor na nuvem (só esperaria o timeout). Um provedor local continua ok.
OFFLINE_CODES = frozenset(
    {"NO_LINK", "NO_DHCP", "GATEWAY_DOWN", "ISP_DOWN", "DNS_FAIL", "CAPTIVE_PORTAL"}
)

# Únicos campos de evidência que podem sair da máquina. Valores numéricos ou
# códigos fixos do próprio NetDoctor; nenhum identificador de rede ou máquina.
EVIDENCE_ALLOWLIST = frozenset(
    {
        "signal_pct",
        "threshold_pct",
        "gateway_loss_pct",
        "gateway_avg_rtt_ms",
        "public_loss_pct",
        "reason",
        "errors",
        "https_error",
        "ncsi_status",
        "apipa",
    }
)

SYSTEM_PROMPT = (
    "Você explica problemas de internet para pessoas leigas, em português do Brasil. "
    "O diagnóstico JÁ FOI DECIDIDO por regras técnicas e está correto: não mude a causa, "
    "não invente causas novas, não cite marcas, valores ou passos que não estejam nos dados. "
    "Reescreva o texto-base de forma clara, curta e gentil, sem jargão técnico "
    "(não use palavras como gateway, DNS, DHCP, IP, ping, latência). "
    'Responda APENAS com JSON no formato {"headline": "uma frase com a causa", '
    '"actions": ["ação 1", "ação 2"]}, com 1 a 3 ações curtas e práticas.'
)


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    base_url: str
    api_key: str | None
    timeout: float = DEFAULT_TIMEOUT_S

    @property
    def is_local(self) -> bool:
        host = urlsplit(self.base_url).hostname or ""
        return host in {"localhost", "127.0.0.1", "::1"}


# --- Configuração -------------------------------------------------------------------


def parse_env_file(text: str) -> dict[str, str]:
    """Leitor mínimo de .env: `CHAVE=valor`, comentários com #, aspas opcionais."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        out[key] = value
    return out


def env_file_candidates() -> list[Path]:
    """.env na pasta atual e em %APPDATA%\\NetDoctor (onde o .exe procura)."""
    paths = [Path.cwd() / ".env"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(Path(appdata) / "NetDoctor" / ".env")
    return paths


def load_config(
    environ: dict[str, str] | None = None, env_files: list[Path] | None = None
) -> LLMConfig | None:
    """Variáveis de ambiente têm prioridade sobre o .env. None = IA desligada."""
    values: dict[str, str] = {}
    for path in reversed(env_files if env_files is not None else env_file_candidates()):
        try:
            values.update(parse_env_file(path.read_text(encoding="utf-8")))
        except OSError:
            continue
    env = os.environ if environ is None else environ
    values.update({k: v for k, v in env.items() if k.startswith("NETDOCTOR_LLM_")})

    provider = values.get("NETDOCTOR_LLM_PROVIDER", "").strip().lower()
    model = values.get("NETDOCTOR_LLM_MODEL", "").strip()
    if not provider or provider == "none" or not model:
        return None
    base_url = values.get("NETDOCTOR_LLM_BASE_URL", "").strip() or DEFAULT_BASE_URLS.get(provider)
    if not base_url:
        return None
    api_key = values.get("NETDOCTOR_LLM_API_KEY", "").strip() or None
    if api_key is None and provider != "ollama":
        return None
    try:
        timeout = float(values.get("NETDOCTOR_LLM_TIMEOUT", DEFAULT_TIMEOUT_S))
    except ValueError:
        timeout = DEFAULT_TIMEOUT_S
    return LLMConfig(provider, model, base_url.rstrip("/"), api_key, timeout)


# --- Payload ----------------------------------------------------------------------


def build_llm_payload(diagnosis: Diagnosis, connection_type: str | None) -> dict[str, Any]:
    """O que vai para a IA. Só allowlist: nada de identificador de rede ou máquina."""
    primary = diagnosis.primary
    tpl = TEMPLATES[primary.code]
    return {
        "connection_type": connection_type if connection_type in ("wifi", "ethernet") else None,
        "findings": [
            {
                "code": f.code,
                "severity": str(f.severity),
                "evidence": {k: v for k, v in f.evidence.items() if k in EVIDENCE_ALLOWLIST},
            }
            for f in diagnosis.findings
        ],
        "base_text": {"headline": tpl.headline, "detail": tpl.detail, "actions": list(tpl.actions)},
    }


# --- Chamada -----------------------------------------------------------------------

Transport = Callable[[str, dict[str, str], bytes, float], bytes]


def _http_post(url: str, headers: dict[str, str], body: bytes, timeout: float) -> bytes:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as resp:
        return resp.read()


def build_request(config: LLMConfig, payload: dict[str, Any]) -> tuple[str, dict[str, str], bytes]:
    headers = {"Content-Type": "application/json", "User-Agent": "NetDoctor"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    body = {
        "model": config.model,
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
    }
    return (
        f"{config.base_url}/chat/completions",
        headers,
        json.dumps(body, ensure_ascii=False).encode("utf-8"),
    )


def parse_response(raw: bytes) -> tuple[str, list[str]] | None:
    """Valida a resposta. Qualquer coisa fora do formato → None (usa o template)."""
    try:
        content = json.loads(raw)["choices"][0]["message"]["content"]
        data = json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError):
        return None
    headline = data.get("headline") if isinstance(data, dict) else None
    actions = data.get("actions") if isinstance(data, dict) else None
    if not isinstance(headline, str) or not isinstance(actions, list):
        return None
    headline = headline.strip()
    actions = [a.strip() for a in actions if isinstance(a, str) and a.strip()]
    if not headline or len(headline) > MAX_TEXT or not 1 <= len(actions) <= 3:
        return None
    if any(len(a) > MAX_TEXT for a in actions):
        return None
    return headline, actions


def enhance(
    explanation: Explanation,
    diagnosis: Diagnosis,
    connection_type: str | None = None,
    config: LLMConfig | None = None,
    transport: Transport = _http_post,
) -> Explanation:
    """Tenta reescrever com IA. Em qualquer problema devolve `explanation` intacta."""
    if config is None:
        return explanation
    if diagnosis.primary.code in OFFLINE_CODES and not config.is_local:
        return explanation
    url, headers, body = build_request(config, build_llm_payload(diagnosis, connection_type))
    try:
        raw = transport(url, headers, body, config.timeout)
    except Exception:  # HTTP 4xx/5xx, timeout, sem rede, TLS...: nunca chega ao usuário
        return explanation
    parsed = parse_response(raw)
    if parsed is None:
        return explanation
    headline, actions = parsed
    return replace(explanation, headline=headline, actions=actions, source="llm")
