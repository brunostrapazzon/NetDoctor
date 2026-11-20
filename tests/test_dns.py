import dns.exception
import dns.resolver
import pytest

from netdoctor.core.probes import dns as dns_probe


class _FakeResolver:
    behaviour: dict = {}

    def __init__(self, configure=False):
        self.nameservers = []
        self.lifetime = None

    def resolve(self, name, rdtype):
        outcome = self.behaviour[self.nameservers[0]]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def fake_resolver(monkeypatch):
    monkeypatch.setattr(dns_probe.dns.resolver, "Resolver", _FakeResolver)
    return _FakeResolver


def test_configured_fails_public_ok(fake_resolver):
    fake_resolver.behaviour = {
        "192.168.0.1": dns.exception.Timeout(),
        "1.1.1.1": ["142.250.0.1"],
        "8.8.8.8": ["142.250.0.1"],
    }
    result = dns_probe.run({"dns_servers": ["192.168.0.1"]})
    by_server = {s["server"]: s for s in result.data["servers"]}
    assert by_server["192.168.0.1"] == {
        "server": "192.168.0.1",
        "role": "configured",
        "ok": False,
        "ms": None,
        "error": "TIMEOUT",
    }
    assert by_server["1.1.1.1"]["ok"] and by_server["1.1.1.1"]["role"] == "public"
    assert result.data["has_configured"] is True


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (dns.resolver.NXDOMAIN(), "NXDOMAIN"),
        (dns.resolver.NoAnswer(), "NO_ANSWER"),
        (dns.resolver.NoNameservers(), "SERVER_FAILED"),
        (dns.resolver.LifetimeTimeout(timeout=2.5, errors=[]), "TIMEOUT"),
        (RuntimeError("?"), "UNEXPECTED"),
    ],
)
def test_error_codes(fake_resolver, exc, code):
    fake_resolver.behaviour = {"203.0.113.53": exc}
    assert dns_probe.query_server("203.0.113.53", "configured")["error"] == code


def test_public_server_configured_is_not_duplicated(fake_resolver):
    fake_resolver.behaviour = {"8.8.8.8": ["x"], "1.1.1.1": ["x"]}
    result = dns_probe.run({"dns_servers": ["8.8.8.8"]})
    servers = [(s["server"], s["role"]) for s in result.data["servers"]]
    assert servers == [("8.8.8.8", "configured"), ("1.1.1.1", "public")]


def test_no_configured_dns(fake_resolver):
    fake_resolver.behaviour = {"8.8.8.8": ["x"], "1.1.1.1": ["x"]}
    result = dns_probe.run({})
    assert result.data["has_configured"] is False
    assert {s["role"] for s in result.data["servers"]} == {"public"}
