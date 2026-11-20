"""IA opcional: privacidade do payload, fallback em qualquer falha e configuração."""

from __future__ import annotations

import json
import socket
import urllib.error

import pytest

from netdoctor.core.models import Diagnosis, Finding, ProbeResult, Severity
from netdoctor.explain import llm
from netdoctor.explain.llm import (
    LLMConfig,
    build_llm_payload,
    build_request,
    enhance,
    load_config,
    parse_env_file,
    parse_response,
)
from netdoctor.explain.templates import explain
from netdoctor.pipeline import run_pipeline

SECRETS = (
    "MinhaRede",
    "aa:bb:cc:dd:ee:ff",
    "11:22:33:44:55:66",
    "203.0.113.10",
    "192.168.0.10",
    "169.254.19.122",
    "DESKTOP-TESTE",
    "login.hotel.example",
    "Wi-Fi",
    "Realtek",
)

GROQ = LLMConfig("groq", "modelo-teste", "https://api.groq.com/openai/v1", "chave-falsa", 1.0)
OLLAMA = LLMConfig("ollama", "llama", "http://localhost:11434/v1", None, 1.0)


def _diag(code="ALL_OK", evidence=None, extra=()):
    findings = [Finding(code, Severity.WARNING, "X", evidence or {})]
    findings += [Finding(c, Severity.WARNING, "Y", e) for c, e in extra]
    return Diagnosis(findings)


def _reply(headline="Seu Wi-Fi está fraco aqui.", actions=("Chegue perto do roteador.",)):
    content = json.dumps({"headline": headline, "actions": list(actions)}, ensure_ascii=False)
    return json.dumps({"choices": [{"message": {"content": content}}]}).encode()


def _transport(raw=None, exc=None, calls=None):
    def send(url, headers, body, timeout):
        if calls is not None:
            calls.append({"url": url, "headers": headers, "body": json.loads(body), "t": timeout})
        if exc:
            raise exc
        return raw

    return send


# --- Privacidade -------------------------------------------------------------------


def _everything_filled_results():
    """Resultados com todos os identificadores possíveis preenchidos."""
    return [
        ProbeResult(
            "adapter",
            ok=True,
            data={
                "connected": True,
                "interface": "Wi-Fi",
                "type": "wifi",
                "ipv4": "169.254.19.122",
                "prefix": 16,
                "apipa": True,
                "gateway": None,
                "dns_servers": ["203.0.113.10"],
                "hostname": "DESKTOP-TESTE",
                "mac": "aa:bb:cc:dd:ee:ff",
            },
        ),
        ProbeResult(
            "wifi",
            ok=True,
            data={
                "connected": True,
                "ssid": "MinhaRede",
                "bssid": "11:22:33:44:55:66",
                "signal_pct": 20,
                "rssi_dbm": -90,
                "channel": 6,
                "band": "2.4 GHz",
                "radio": "802.11n",
                "description": "Realtek",
            },
        ),
        ProbeResult(
            "http",
            ok=True,
            data={
                "ncsi": {
                    "status": 302,
                    "error": None,
                    "content_ok": False,
                    "redirected": True,
                    "redirect_host": "login.hotel.example",
                    "ms": 10.0,
                },
                "https": {"status": None, "error": "TLS_ERROR", "ok": False, "ms": None},
            },
        ),
    ]


def test_llm_payload_has_no_identifiers():
    # Evidências com identificadores de propósito (ipv4 no NO_DHCP, redirect_host no portal).
    diagnosis = _diag(
        "NO_DHCP",
        {"ipv4": "169.254.19.122", "apipa": True},
        extra=[
            ("CAPTIVE_PORTAL", {"ncsi_status": 302, "redirect_host": "login.hotel.example"}),
            ("WIFI_WEAK", {"signal_pct": 20, "threshold_pct": 50, "ssid": "MinhaRede"}),
        ],
    )
    text = json.dumps(build_llm_payload(diagnosis, "wifi"), ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in text, secret
    assert '"signal_pct": 20' in text
    assert '"apipa": true' in text


def test_request_body_from_real_pipeline_has_no_identifiers():
    calls = []
    run_pipeline(
        runner=lambda **k: _everything_filled_results(),
        llm_config=OLLAMA,  # local: chamado mesmo com achado "sem internet"
        transport=_transport(_reply(), calls=calls),
    )
    assert len(calls) == 1
    sent = json.dumps(calls[0]["body"], ensure_ascii=False)
    for secret in SECRETS:
        assert secret not in sent, secret


def test_unknown_connection_type_is_dropped():
    assert build_llm_payload(_diag(), "Realtek USB")["connection_type"] is None


# --- Sucesso ------------------------------------------------------------------------


def test_enhance_replaces_headline_and_actions():
    d = _diag("WIFI_WEAK", {"signal_pct": 30, "threshold_pct": 50})
    base = explain(d)
    out = enhance(base, d, "wifi", GROQ, transport=_transport(_reply()))
    assert out.source == "llm"
    assert out.headline == "Seu Wi-Fi está fraco aqui."
    assert out.actions == ["Chegue perto do roteador."]
    assert out.detail == base.detail  # detalhe e números continuam do template
    assert out.numbers == base.numbers
    assert "Texto reescrito por IA" in out.as_text()


def test_request_shape():
    url, headers, body = build_request(GROQ, {"x": 1})
    assert url == "https://api.groq.com/openai/v1/chat/completions"
    assert headers["Authorization"] == "Bearer chave-falsa"
    data = json.loads(body)
    assert data["model"] == "modelo-teste"
    assert data["response_format"] == {"type": "json_object"}
    assert data["messages"][0]["role"] == "system"
    assert "não invente causas" in data["messages"][0]["content"]


def test_ollama_sends_no_authorization_header():
    _, headers, _ = build_request(OLLAMA, {})
    assert "Authorization" not in headers


# --- Fallback -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        urllib.error.HTTPError("u", 401, "Unauthorized", {}, None),
        urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None),
        urllib.error.URLError(socket.gaierror(11001, "getaddrinfo")),
        TimeoutError(),
        ConnectionResetError(),
        RuntimeError("inesperado"),
    ],
)
def test_any_transport_failure_falls_back_to_template(exc):
    d = _diag()
    base = explain(d)
    assert enhance(base, d, "wifi", GROQ, transport=_transport(exc=exc)) == base


@pytest.mark.parametrize(
    "raw",
    [
        b"nao e json",
        b"{}",
        json.dumps({"choices": [{"message": {"content": "texto solto"}}]}).encode(),
        _reply(headline=""),
        _reply(actions=()),
        _reply(actions=("a", "b", "c", "d")),
        _reply(headline="x" * 500),
        _reply(actions=("y" * 500,)),
        json.dumps(
            {"choices": [{"message": {"content": '{"headline": 1, "actions": []}'}}]}
        ).encode(),
    ],
)
def test_invalid_responses_fall_back(raw):
    d = _diag()
    base = explain(d)
    assert enhance(base, d, "wifi", GROQ, transport=_transport(raw)) == base


def test_parse_response_trims_and_drops_empty_actions():
    assert parse_response(_reply("  Oi.  ", ("  a  ", "", "b"))) == ("Oi.", ["a", "b"])


def test_no_config_never_calls():
    calls = []
    d = _diag()
    base = explain(d)
    assert enhance(base, d, "wifi", None, transport=_transport(_reply(), calls=calls)) == base
    assert calls == []


@pytest.mark.parametrize("code", sorted(llm.OFFLINE_CODES))
def test_cloud_provider_skipped_when_internet_is_down(code):
    calls = []
    d = _diag(code)
    base = explain(d)
    assert enhance(base, d, "wifi", GROQ, transport=_transport(_reply(), calls=calls)) == base
    assert calls == []


def test_local_provider_used_even_without_internet():
    d = _diag("ISP_DOWN")
    out = enhance(explain(d), d, "wifi", OLLAMA, transport=_transport(_reply()))
    assert out.source == "llm"


# --- Configuração -----------------------------------------------------------------------


def test_parse_env_file():
    text = """
    # comentário
    NETDOCTOR_LLM_PROVIDER=groq
    export NETDOCTOR_LLM_MODEL="modelo x"
    NETDOCTOR_LLM_API_KEY='abc'
    NETDOCTOR_LLM_TIMEOUT=5 # comentário no fim
    linha sem igual
    """
    assert parse_env_file(text) == {
        "NETDOCTOR_LLM_PROVIDER": "groq",
        "NETDOCTOR_LLM_MODEL": "modelo x",
        "NETDOCTOR_LLM_API_KEY": "abc",
        "NETDOCTOR_LLM_TIMEOUT": "5",
    }


@pytest.mark.real_llm_config
def test_load_config_from_env_file_with_env_override(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "NETDOCTOR_LLM_PROVIDER=groq\nNETDOCTOR_LLM_MODEL=a\nNETDOCTOR_LLM_API_KEY=k\n",
        encoding="utf-8",
    )
    cfg = load_config(environ={"NETDOCTOR_LLM_MODEL": "b"}, env_files=[env])
    assert cfg == LLMConfig("groq", "b", "https://api.groq.com/openai/v1", "k", 8.0)


@pytest.mark.real_llm_config
@pytest.mark.parametrize(
    "environ",
    [
        {},
        {"NETDOCTOR_LLM_PROVIDER": "none", "NETDOCTOR_LLM_MODEL": "m"},
        {"NETDOCTOR_LLM_PROVIDER": "groq", "NETDOCTOR_LLM_MODEL": "m"},  # sem chave
        {"NETDOCTOR_LLM_PROVIDER": "groq", "NETDOCTOR_LLM_API_KEY": "k"},  # sem modelo
        {
            "NETDOCTOR_LLM_PROVIDER": "desconhecido",
            "NETDOCTOR_LLM_MODEL": "m",
            "NETDOCTOR_LLM_API_KEY": "k",
        },
    ],
)
def test_incomplete_config_disables_ai(environ):
    assert load_config(environ=environ, env_files=[]) is None


@pytest.mark.real_llm_config
def test_ollama_needs_no_key_and_custom_timeout():
    cfg = load_config(
        environ={
            "NETDOCTOR_LLM_PROVIDER": "ollama",
            "NETDOCTOR_LLM_MODEL": "llama",
            "NETDOCTOR_LLM_TIMEOUT": "abc",
        },
        env_files=[],
    )
    assert cfg.base_url == "http://localhost:11434/v1"
    assert cfg.api_key is None and cfg.is_local and cfg.timeout == 8.0


@pytest.mark.real_llm_config
def test_missing_env_file_is_ignored(tmp_path):
    assert load_config(environ={}, env_files=[tmp_path / "nao-existe"]) is None


def test_env_example_is_safe_default():
    from pathlib import Path

    text = (Path(__file__).parent.parent / ".env.example").read_text(encoding="utf-8")
    values = parse_env_file(text)
    assert values["NETDOCTOR_LLM_PROVIDER"] == "none"
    assert values["NETDOCTOR_LLM_API_KEY"] == ""
