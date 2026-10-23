import json
import socket
from unittest.mock import MagicMock, Mock

import pytest
import requests

from src import network_diagnostic as diagnostic


@pytest.fixture
def transport(monkeypatch):
    monkeypatch.setattr(diagnostic, "dns_status", lambda host, timeout: "resolved")
    monkeypatch.setattr(requests.utils, "get_environ_proxies", lambda url: {"https": "http://user:secret@proxy:8080"})
    # Context-manager mocks are explicit so cleanup can be verified.
    session = MagicMock()
    session.head.return_value.__enter__.return_value.status_code = 200
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(requests, "Session", factory)
    return session


@pytest.mark.parametrize("status,error", [(200, None), (301, "redirect"), (403, "http_error"), (405, "http_error"), (429, "http_error"), (503, "http_error")])
def test_head_status_and_safe_request(transport, status, error):
    transport.head.return_value.__enter__.return_value.status_code = status
    result = diagnostic.diagnose_endpoint(diagnostic.API_URL, 2)
    assert result["http_status"] == status
    assert result["error"] == error
    assert result["proxy_configured"] is True
    assert "secret" not in json.dumps(result)
    transport.head.assert_called_once_with(diagnostic.API_URL, timeout=(2, 2), allow_redirects=False, stream=True)
    transport.head.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize("exception,error", [
    (requests.exceptions.ProxyError, "proxy_error"),
    (requests.exceptions.SSLError, "tls_error"),
    (requests.Timeout, "timeout"),
    (requests.ConnectionError, "connection_error"),
    (requests.RequestException, "request_error"),
    (OSError, "local_configuration_error"),
])
def test_errors_are_classified_and_sanitized(transport, exception, error):
    transport.head.side_effect = exception("secret proxy credentials")
    result = diagnostic.diagnose_endpoint(diagnostic.FPDS_URL)
    assert result["error"] == error
    assert result["http_status"] is None
    assert "secret" not in json.dumps(result)


def test_direct_mode_and_failed_local_dns_do_not_disable_proxy_routing(transport, monkeypatch):
    monkeypatch.setattr(requests.utils, "get_environ_proxies", lambda url: {})
    monkeypatch.setattr(diagnostic, "dns_status", lambda host, timeout: "dns_error")
    result = diagnostic.diagnose_endpoint(diagnostic.API_URL)
    assert result["proxy_configured"] is False
    assert result["dns"] == "dns_error"
    assert result["http_status"] == 200


def test_dns_success_failure_and_timeout(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [])
    assert diagnostic.dns_status("example.test", 1) == "resolved"
    def fail(*args, **kwargs):
        raise socket.gaierror("sensitive resolver detail")
    monkeypatch.setattr(socket, "getaddrinfo", fail)
    assert diagnostic.dns_status("example.test", 1) == "dns_error"
    monkeypatch.setattr(diagnostic.threading.Thread, "start", lambda self: None)
    assert diagnostic.dns_status("example.test", 0.001) == "timeout"


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeouts_do_not_make_requests(timeout, transport):
    with pytest.raises(ValueError):
        diagnostic.diagnose_endpoint(diagnostic.API_URL, timeout)
    with pytest.raises(SystemExit) as exc:
        diagnostic.main(["--timeout", str(timeout)])
    assert exc.value.code == 2
    transport.head.assert_not_called()


def test_only_official_endpoints(transport):
    with pytest.raises(ValueError):
        diagnostic.diagnose_endpoint("https://example.test")
    transport.head.assert_not_called()


@pytest.mark.parametrize("error,exit_code", [(None, 0), ("http_error", 1)])
def test_cli_reports_both_endpoints(monkeypatch, capsys, error, exit_code):
    probe = Mock(side_effect=[{"error": error}, {"error": None}])
    monkeypatch.setattr(diagnostic, "diagnose_endpoint", probe)
    assert diagnostic.main(["--timeout", "2"]) == exit_code
    assert len(json.loads(capsys.readouterr().out)) == 2
    assert [call.args for call in probe.call_args_list] == [(diagnostic.API_URL, 2), (diagnostic.FPDS_URL, 2)]
