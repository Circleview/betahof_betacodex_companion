"""Persönliche MCP-Schlüssel (Nutzerwunsch 2026-09-24): Zugriff auf den
Kreativ-Modus per MCP (app/mcp_server.py) für einen kleinen, widerrufbaren
Kreis. Jeder Schlüssel gehört zu einem Konto mit der Rolle MCP-Nutzung
(users.MCP_NUTZER), ein Konto kann mehrere haben (z.B. "Laptop",
"Claude Code"). Wird dem Konto die Rolle entzogen oder das Konto gelöscht,
funktioniert keiner seiner Schlüssel mehr - geprüft bei JEDEM Aufruf.

Gespeichert wird nur ein SHA-256-Hash; der Klartext-Schlüssel wird genau
einmal beim Anlegen angezeigt. Ein Hash ohne Salt reicht hier: die
Schlüssel sind 256 Bit zufällig, nicht von Menschen gewählt.

Limits je Schlüssel (änderbar durch User-Admins): Aufrufe pro Tag und Kosten
pro Monat in EUR - gemessen über app/usage.py."""
import hashlib
import hmac
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app import jsonstore, usage, users

BASE_DIR = Path(__file__).resolve().parent.parent
MCP_KEYS_FILE = BASE_DIR / "data" / "mcp_keys.json"

KEY_PREFIX = "bcx_"
DEFAULT_DAILY_CALL_LIMIT = 30
DEFAULT_MONTHLY_EUR_LIMIT = 5.0
MAX_LABEL_CHARS = 60

_lock = threading.Lock()


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _load() -> dict:
    return jsonstore.load(MCP_KEYS_FILE, {})


def _public(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k != "key_hash"}


def create_key(email: str, label: str) -> tuple[dict, str]:
    plaintext = KEY_PREFIX + secrets.token_urlsafe(32)
    entry = {
        "id": uuid.uuid4().hex,
        "email": email.strip().lower(),
        "label": (label or "").strip()[:MAX_LABEL_CHARS] or "MCP",
        "key_hash": _hash(plaintext),
        "key_hint": plaintext[: len(KEY_PREFIX) + 4],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "revoked_at": None,
        "last_used_at": None,
        "daily_call_limit": DEFAULT_DAILY_CALL_LIMIT,
        "monthly_eur_limit": DEFAULT_MONTHLY_EUR_LIMIT,
    }
    with _lock:
        keys = _load()
        keys[entry["id"]] = entry
        jsonstore.save(MCP_KEYS_FILE, keys)
    return _public(entry), plaintext


def list_keys(email: str | None = None) -> list[dict]:
    keys = [_public(k) for k in _load().values() if email is None or k["email"] == email.strip().lower()]
    return sorted(keys, key=lambda k: k["created_at"])


def get_key(key_id: str) -> dict | None:
    entry = _load().get(key_id)
    return _public(entry) if entry else None


def _update(key_id: str, **fields) -> dict | None:
    with _lock:
        keys = _load()
        entry = keys.get(key_id)
        if entry is None:
            return None
        entry.update(fields)
        jsonstore.save(MCP_KEYS_FILE, keys)
        return _public(entry)


def revoke_key(key_id: str) -> dict | None:
    return _update(key_id, revoked_at=datetime.now(timezone.utc).isoformat())


def set_limits(key_id: str, daily_call_limit: int, monthly_eur_limit: float) -> dict | None:
    return _update(key_id, daily_call_limit=daily_call_limit, monthly_eur_limit=monthly_eur_limit)


def authenticate(plaintext: str | None) -> dict | None:
    """Gültiger, nicht widerrufener Schlüssel eines Kontos, das (noch) die
    Rolle MCP-Nutzung hat - sonst None."""
    if not plaintext or not plaintext.startswith(KEY_PREFIX):
        return None
    wanted = _hash(plaintext)
    for entry in _load().values():
        if hmac.compare_digest(entry["key_hash"], wanted):
            if entry["revoked_at"] or not users.has_role(entry["email"], users.MCP_NUTZER):
                return None
            return _update(entry["id"], last_used_at=datetime.now(timezone.utc).isoformat())
    return None


def limit_exceeded(key: dict) -> str | None:
    """"daily" / "monthly", wenn ein Limit erreicht ist, sonst None."""
    stats = usage.key_stats(key["id"])
    if stats["calls_today"] >= key["daily_call_limit"]:
        return "daily"
    if stats["month_eur"] >= key["monthly_eur_limit"]:
        return "monthly"
    return None


def with_stats(key: dict, month: str | None = None) -> dict:
    return {**key, **usage.key_stats(key["id"], month=month)}
