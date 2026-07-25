import json
from unittest.mock import MagicMock, patch

from app import captcha


def test_verify_turnstile_token_passes_when_no_secret_configured(monkeypatch):
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)

    assert captcha.verify_turnstile_token("") is True
    assert captcha.verify_turnstile_token("some-token") is True


def test_verify_turnstile_token_rejects_empty_token_when_configured(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")

    assert captcha.verify_turnstile_token("") is False


def _fake_response(payload):
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    return resp


def test_verify_turnstile_token_returns_true_on_success(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")
    with patch(
        "app.captcha.urllib.request.urlopen",
        return_value=_fake_response({"success": True}),
    ):
        assert captcha.verify_turnstile_token("valid-token", "1.2.3.4") is True


def test_verify_turnstile_token_returns_false_on_rejected_response(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")
    with patch(
        "app.captcha.urllib.request.urlopen",
        return_value=_fake_response({"success": False, "error-codes": ["invalid-input-response"]}),
    ):
        assert captcha.verify_turnstile_token("invalid-token") is False


def test_verify_turnstile_token_returns_false_on_network_error(monkeypatch):
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "test-secret")
    with patch("app.captcha.urllib.request.urlopen", side_effect=RuntimeError("boom")):
        assert captcha.verify_turnstile_token("some-token") is False
