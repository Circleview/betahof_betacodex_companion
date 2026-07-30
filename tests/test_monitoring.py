import socket
import ssl
import urllib.error
from unittest.mock import MagicMock, patch

from app.monitoring import check_url


def _cm_response(status):
    resp = MagicMock()
    resp.status = status
    resp.__enter__.return_value = resp
    return resp


def test_check_url_reachable():
    with patch("app.monitoring.urllib.request.urlopen", return_value=_cm_response(200)):
        assert check_url("https://example.org") == {
            "reachable": True,
            "status_code": 200,
            "reason_code": None,
        }


def test_check_url_unreachable_status():
    with patch("app.monitoring.urllib.request.urlopen", return_value=_cm_response(500)):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": 500,
            "reason_code": "http_error",
        }


def test_check_url_falls_back_to_get_when_head_not_allowed():
    error = urllib.error.HTTPError(
        url="https://example.org", code=405, msg="Method Not Allowed", hdrs=None, fp=None
    )
    with patch(
        "app.monitoring.urllib.request.urlopen", side_effect=[error, _cm_response(200)]
    ):
        assert check_url("https://example.org") == {
            "reachable": True,
            "status_code": 200,
            "reason_code": None,
        }


def test_check_url_reports_http_error_status_for_non_405():
    error = urllib.error.HTTPError(
        url="https://example.org", code=404, msg="Not Found", hdrs=None, fp=None
    )
    with patch("app.monitoring.urllib.request.urlopen", side_effect=error):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": 404,
            "reason_code": "http_error",
        }


def test_check_url_treats_403_as_reachable():
    # Manche Seiten (z. B. academia.edu) blockieren automatisierte HEAD-Anfragen
    # pauschal mit 403, obwohl die Seite im Browser normal erreichbar ist.
    error = urllib.error.HTTPError(
        url="https://example.org", code=403, msg="Forbidden", hdrs=None, fp=None
    )
    with patch("app.monitoring.urllib.request.urlopen", side_effect=error):
        assert check_url("https://example.org") == {
            "reachable": True,
            "status_code": 403,
            "reason_code": None,
        }


def test_check_url_treats_403_as_reachable_after_405_fallback():
    error_405 = urllib.error.HTTPError(
        url="https://example.org", code=405, msg="Method Not Allowed", hdrs=None, fp=None
    )
    error_403 = urllib.error.HTTPError(
        url="https://example.org", code=403, msg="Forbidden", hdrs=None, fp=None
    )
    with patch(
        "app.monitoring.urllib.request.urlopen", side_effect=[error_405, error_403]
    ):
        assert check_url("https://example.org") == {
            "reachable": True,
            "status_code": 403,
            "reason_code": None,
        }


def test_check_url_treats_429_as_reachable():
    # LinkedIn (hinter Cloudflare) blockiert automatisierte Anfragen mit 429 +
    # Bot-Challenge-Seite, obwohl der Artikel selbst existiert und im Browser
    # normal erreichbar ist.
    error = urllib.error.HTTPError(
        url="https://example.org", code=429, msg="Too Many Requests", hdrs=None, fp=None
    )
    with patch("app.monitoring.urllib.request.urlopen", side_effect=error):
        assert check_url("https://example.org") == {
            "reachable": True,
            "status_code": 429,
            "reason_code": None,
        }


def test_check_url_handles_network_errors():
    with patch("app.monitoring.urllib.request.urlopen", side_effect=RuntimeError("boom")):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": None,
            "reason_code": "unknown_error",
        }


# Backlog #163: konkreter Fehlergrund statt nur "nicht erreichbar" -
# urllib wickelt Verbindungsfehler in URLError.reason ein, siehe
# app/monitoring.py:_classify_url_error.
def test_check_url_reports_timeout_reason_code():
    with patch(
        "app.monitoring.urllib.request.urlopen", side_effect=socket.timeout("timed out")
    ):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": None,
            "reason_code": "timeout",
        }


def test_check_url_reports_timeout_reason_code_when_wrapped_in_url_error():
    error = urllib.error.URLError(socket.timeout("timed out"))
    with patch("app.monitoring.urllib.request.urlopen", side_effect=error):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": None,
            "reason_code": "timeout",
        }


def test_check_url_reports_dns_error_reason_code():
    error = urllib.error.URLError(socket.gaierror("Name or service not known"))
    with patch("app.monitoring.urllib.request.urlopen", side_effect=error):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": None,
            "reason_code": "dns_error",
        }


def test_check_url_reports_ssl_error_reason_code():
    error = urllib.error.URLError(ssl.SSLError("certificate verify failed"))
    with patch("app.monitoring.urllib.request.urlopen", side_effect=error):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": None,
            "reason_code": "ssl_error",
        }


def test_check_url_reports_connection_error_reason_code():
    error = urllib.error.URLError(ConnectionRefusedError("Connection refused"))
    with patch("app.monitoring.urllib.request.urlopen", side_effect=error):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": None,
            "reason_code": "connection_error",
        }


def test_check_url_reports_unknown_error_reason_code_for_unclassified_url_error():
    error = urllib.error.URLError("something else entirely")
    with patch("app.monitoring.urllib.request.urlopen", side_effect=error):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": None,
            "reason_code": "unknown_error",
        }


def test_check_url_reports_reason_code_for_url_error_after_405_fallback():
    error_405 = urllib.error.HTTPError(
        url="https://example.org", code=405, msg="Method Not Allowed", hdrs=None, fp=None
    )
    error_dns = urllib.error.URLError(socket.gaierror("Name or service not known"))
    with patch(
        "app.monitoring.urllib.request.urlopen", side_effect=[error_405, error_dns]
    ):
        assert check_url("https://example.org") == {
            "reachable": False,
            "status_code": None,
            "reason_code": "dns_error",
        }
