import socket
import ssl
import urllib.error

import pytest

from netdoctor.core.probes import http
from netdoctor.core.probes.http import FetchResult, interpret_https, interpret_ncsi


def test_ncsi_normal():
    data = interpret_ncsi(FetchResult(status=200, body="Microsoft Connect Test", ms=40.0))
    assert data["content_ok"] is True
    assert data["redirected"] is False


def test_ncsi_captive_portal_redirect():
    data = interpret_ncsi(FetchResult(status=302, location="http://login.hotel.example/portal?x=1"))
    assert data["content_ok"] is False
    assert data["redirected"] is True
    assert data["redirect_host"] == "login.hotel.example"


def test_ncsi_portal_serving_its_own_page():
    data = interpret_ncsi(FetchResult(status=200, body="<html>Faça login</html>"))
    assert data["content_ok"] is False
    assert data["redirected"] is False


def test_https_ok_and_failure():
    assert interpret_https(FetchResult(status=204))["ok"] is True
    failed = interpret_https(FetchResult(status=None, error="TLS_ERROR"))
    assert failed["ok"] is False
    assert failed["error"] == "TLS_ERROR"


@pytest.mark.parametrize(
    ("exc", "code"),
    [
        (urllib.error.URLError(ssl.SSLCertVerificationError("cert")), "TLS_ERROR"),
        (urllib.error.URLError(socket.gaierror(11001, "getaddrinfo")), "DNS_ERROR"),
        (urllib.error.URLError(TimeoutError()), "TIMEOUT"),
        (TimeoutError(), "TIMEOUT"),
        (urllib.error.URLError(ConnectionRefusedError()), "CONNECTION_ERROR"),
    ],
)
def test_fetch_classifies_errors(monkeypatch, exc, code):
    def boom(*args, **kwargs):
        raise exc

    monkeypatch.setattr(http._opener, "open", boom)
    assert http.fetch("https://example.invalid").error == code


def test_run_combines_both_checks(monkeypatch):
    responses = {
        http.NCSI_URL: FetchResult(status=200, body="Microsoft Connect Test"),
        http.HTTPS_URL: FetchResult(status=204),
    }
    monkeypatch.setattr(http, "fetch", lambda url, timeout=5.0: responses[url])
    result = http.run()
    assert result.data["ncsi"]["content_ok"] and result.data["https"]["ok"]
