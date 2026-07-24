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
        assert check_url("https://example.org") == {"reachable": True, "status_code": 200}


def test_check_url_unreachable_status():
    with patch("app.monitoring.urllib.request.urlopen", return_value=_cm_response(500)):
        assert check_url("https://example.org") == {"reachable": False, "status_code": 500}


def test_check_url_falls_back_to_get_when_head_not_allowed():
    error = urllib.error.HTTPError(
        url="https://example.org", code=405, msg="Method Not Allowed", hdrs=None, fp=None
    )
    with patch(
        "app.monitoring.urllib.request.urlopen", side_effect=[error, _cm_response(200)]
    ):
        assert check_url("https://example.org") == {"reachable": True, "status_code": 200}


def test_check_url_reports_http_error_status_for_non_405():
    error = urllib.error.HTTPError(
        url="https://example.org", code=404, msg="Not Found", hdrs=None, fp=None
    )
    with patch("app.monitoring.urllib.request.urlopen", side_effect=error):
        assert check_url("https://example.org") == {"reachable": False, "status_code": 404}


def test_check_url_handles_network_errors():
    with patch("app.monitoring.urllib.request.urlopen", side_effect=RuntimeError("boom")):
        assert check_url("https://example.org") == {"reachable": False, "status_code": None}
