import re

import pytest

from netdoctor.core.models import Diagnosis, Finding, ProbeResult, Severity
from netdoctor.core.rules import CHAIN
from netdoctor.explain.templates import TEMPLATES, explain

ALL_CODES = [
    "NO_LINK",
    "NO_DHCP",
    "GATEWAY_DOWN",
    "ISP_DOWN",
    "DNS_FAIL",
    "CAPTIVE_PORTAL",
    "WIFI_WEAK",
    "LOCAL_INTERFERENCE",
    "ALL_OK",
    "INCONCLUSIVE",
]
JARGON = re.compile(
    r"\b(gateway|dns|dhcp|ip|ping|lat[eê]ncia|icmp|tcp|udp|ssid|https?|apipa|isp)\b",
    re.IGNORECASE,
)


def test_every_code_has_template():
    assert set(TEMPLATES) == set(ALL_CODES)
    assert len(CHAIN) == len(ALL_CODES) - 2  # ALL_OK e INCONCLUSIVE não são regras


@pytest.mark.parametrize("code", ALL_CODES)
def test_template_shape(code):
    tpl = TEMPLATES[code]
    assert tpl.headline.endswith(".")
    assert 1 <= len(tpl.actions) <= 3
    assert tpl.short and not tpl.short.endswith(".")


@pytest.mark.parametrize("code", ALL_CODES)
def test_no_jargon_for_laypeople(code):
    tpl = TEMPLATES[code]
    for text in (tpl.headline, tpl.detail, tpl.short, *tpl.actions):
        assert not JARGON.search(text), f"{code}: jargão em {text!r}"


def _diag(*codes, evidence=None):
    return Diagnosis(
        [
            Finding(c, Severity.WARNING, "X", (evidence or {}) if i == 0 else {})
            for i, c in enumerate(codes)
        ]
    )


def test_secondary_findings_become_also():
    ex = explain(_diag("GATEWAY_DOWN", "WIFI_WEAK"))
    assert ex.headline == TEMPLATES["GATEWAY_DOWN"].headline
    assert ex.also == ["Wi-Fi fraco neste lugar"]
    assert "Também notamos: Wi-Fi fraco neste lugar." in ex.as_text()


def test_wifi_weak_shows_signal_number():
    ex = explain(_diag("WIFI_WEAK", evidence={"signal_pct": 38, "threshold_pct": 50}))
    assert ex.numbers == ["Força do sinal: 38% (o ideal é acima de 50%)."]


def test_local_interference_numbers():
    ex = explain(
        _diag("LOCAL_INTERFERENCE", evidence={"gateway_loss_pct": 50.0, "gateway_avg_rtt_ms": 2.0})
    )
    assert ex.numbers == [
        "50% das tentativas até o roteador se perderam.",
        "Tempo de resposta do roteador: 2 ms.",
    ]


def test_location_permission_note():
    results = [ProbeResult("wifi", ok=False, error="LOCATION_PERMISSION")]
    ex = explain(_diag("ALL_OK"), results)
    assert len(ex.notes) == 1
    assert "Localização" in ex.notes[0]


def test_other_probe_errors_add_no_note():
    ex = explain(_diag("ALL_OK"), [ProbeResult("wifi", ok=False, error="TIMEOUT")])
    assert ex.notes == []


def test_as_text_numbers_actions():
    text = explain(_diag("ISP_DOWN")).as_text()
    assert "O que fazer:" in text
    assert "  1. Ligue para o suporte da operadora" in text
