import secrets
import time

# Nutzerwunsch (2026-08-30): Konversations-Übergabe vom Embed-Widget (oder
# vom Quellen-Ansicht-Link, siehe question.js:appendViewSourceLink) in einen
# neuen Tab mit der vollen Website - sessionStorage ist pro Tab (bewusst,
# siehe question.js:CONVERSATION_STORAGE_KEY) und zusätzlich pro
# Top-Level-Browsing-Context partitioniert, ein neuer Tab bekäme also so
# oder so leeren Storage. Einfacher In-Memory-Store wie app/ratelimit.py -
# ein Prozess reicht für diese Größenordnung, kein Redis nötig. Bewusst KEIN
# dauerhafter Speicher: Token verfallen nach TTL_SECONDS oder werden beim
# ersten (einzigen) Abruf sofort gelöscht - reine Übergabe, keine neue
# Konversations-Persistenz.
TTL_SECONDS = 300

_store: dict[str, tuple[float, list[dict]]] = {}


# Eigener Wrapper statt time.monotonic() direkt zu verwenden - Tests können
# so gezielt NUR diese Zeitquelle per monkeypatch vorstellen (Ablauf-Test),
# ohne das globale time-Modul für andere Tests (z.B. app/ratelimit.py) zu
# beeinflussen.
def _now() -> float:
    return time.monotonic()


def _cleanup_expired() -> None:
    now = _now()
    expired = [token for token, (expires_at, _) in _store.items() if expires_at < now]
    for token in expired:
        del _store[token]


def create(history: list[dict]) -> str:
    _cleanup_expired()
    token = secrets.token_urlsafe(24)
    _store[token] = (_now() + TTL_SECONDS, history)
    return token


def pop(token: str) -> list[dict] | None:
    """Liefert die Historie und löscht den Eintrag sofort (Einmal-Abruf) -
    None bei unbekanntem oder abgelaufenem Token."""
    _cleanup_expired()
    entry = _store.pop(token, None)
    if entry is None:
        return None
    return entry[1]
