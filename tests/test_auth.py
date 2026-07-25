from app import auth


def _isolate(monkeypatch):
    monkeypatch.setattr(auth, "_consumed_jti", {})


def test_session_token_roundtrip():
    token = auth.create_session_token("lena@test.local")
    assert auth.verify_session_token(token) == "lena@test.local"


def test_session_token_rejects_tampered_signature():
    token = auth.create_session_token("lena@test.local")
    body, _, signature = token.partition(".")
    tampered = f"{body}.{'0' * len(signature)}"

    assert auth.verify_session_token(tampered) is None


def test_session_token_rejects_expired_token(monkeypatch):
    import time

    monkeypatch.setattr(time, "time", lambda: 1_000_000.0)
    token = auth.create_session_token("lena@test.local")

    monkeypatch.setattr(time, "time", lambda: 1_000_000.0 + auth.SESSION_MAX_AGE_SECONDS + 1)
    assert auth.verify_session_token(token) is None


def test_verify_session_token_handles_missing_or_malformed_input():
    assert auth.verify_session_token(None) is None
    assert auth.verify_session_token("") is None
    assert auth.verify_session_token("not-a-valid-token") is None


def test_magic_link_token_roundtrip(monkeypatch):
    _isolate(monkeypatch)
    token = auth.create_magic_link_token("lena@test.local", auth.LOGIN_LINK_MAX_AGE_SECONDS)

    assert auth.verify_magic_link_token(token) == "lena@test.local"


def test_magic_link_token_cannot_be_reused(monkeypatch):
    _isolate(monkeypatch)
    token = auth.create_magic_link_token("lena@test.local", auth.LOGIN_LINK_MAX_AGE_SECONDS)

    assert auth.verify_magic_link_token(token) == "lena@test.local"
    assert auth.verify_magic_link_token(token) is None


def test_magic_link_token_rejects_expired_token(monkeypatch):
    _isolate(monkeypatch)
    import time

    monkeypatch.setattr(time, "time", lambda: 1_000_000.0)
    token = auth.create_magic_link_token("lena@test.local", 60)

    monkeypatch.setattr(time, "time", lambda: 1_000_000.0 + 61)
    assert auth.verify_magic_link_token(token) is None


def test_magic_link_token_rejects_tampered_signature(monkeypatch):
    _isolate(monkeypatch)
    token = auth.create_magic_link_token("lena@test.local", auth.LOGIN_LINK_MAX_AGE_SECONDS)
    body, _, signature = token.partition(".")
    tampered = f"{body}.{'0' * len(signature)}"

    assert auth.verify_magic_link_token(tampered) is None
