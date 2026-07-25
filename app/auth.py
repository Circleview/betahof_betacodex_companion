import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import uuid

SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 3600
LOGIN_LINK_MAX_AGE_SECONDS = 15 * 60
INVITE_LINK_MAX_AGE_SECONDS = 7 * 24 * 3600

# Ohne konfiguriertes SESSION_SECRET_KEY (z.B. lokale Entwicklung) wird
# einmalig ein zufälliger Schlüssel fürs laufende Prozess erzeugt - Sessions
# und offene Magic-Links überleben dann keinen Neustart, die App bleibt aber
# ohne Konfiguration nutzbar (analog zum Turnstile-Verhalten ohne Secret).
_FALLBACK_SECRET = secrets.token_hex(32)

# Bereits verbrauchte Magic-Link-jtis (Einweg-Schutz) - klein und
# selbst-verfallend, kein Session-Speicher, analog zu ratelimit._request_log.
_consumed_jti: dict[str, float] = {}


def _get_secret() -> str:
    return os.environ.get("SESSION_SECRET_KEY") or _FALLBACK_SECRET


def _sign(payload: dict) -> str:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body_b64 = base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")
    signature = hmac.new(_get_secret().encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body_b64}.{signature}"


def _verify(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body_b64, _, signature = token.partition(".")
    expected = hmac.new(_get_secret().encode("utf-8"), body_b64.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    try:
        padding = "=" * (-len(body_b64) % 4)
        body = base64.urlsafe_b64decode(body_b64 + padding)
        payload = json.loads(body)
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload


def create_session_token(email: str) -> str:
    return _sign({"email": email, "exp": time.time() + SESSION_MAX_AGE_SECONDS})


def verify_session_token(token: str | None) -> str | None:
    payload = _verify(token)
    if not payload:
        return None
    return payload.get("email")


def _prune_consumed_jti() -> None:
    now = time.time()
    expired = [jti for jti, exp in _consumed_jti.items() if exp < now]
    for jti in expired:
        del _consumed_jti[jti]


def create_magic_link_token(email: str, max_age_seconds: int) -> str:
    return _sign({"email": email, "jti": uuid.uuid4().hex, "exp": time.time() + max_age_seconds})


def verify_magic_link_token(token: str) -> str | None:
    payload = _verify(token)
    if not payload:
        return None
    jti = payload.get("jti")
    if not jti:
        return None
    _prune_consumed_jti()
    if jti in _consumed_jti:
        return None
    _consumed_jti[jti] = payload.get("exp", time.time())
    return payload.get("email")
