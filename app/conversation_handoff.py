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

# Idee 2070893d: globale Obergrenze (Summe der Roh-Bytes aller offenen Einträge),
# damit viele große Handoffs den Speicher des Prozesses nicht füllen.
MAX_TOTAL_BYTES = 50_000_000


class StoreFull(Exception):
    pass


# token -> (Ablauf, Historie, conversation_id, Rohgröße in Bytes)
_store: dict[str, tuple[float, list[dict], str | None, int]] = {}


# Eigener Wrapper statt time.monotonic() direkt zu verwenden - Tests können
# so gezielt NUR diese Zeitquelle per monkeypatch vorstellen (Ablauf-Test),
# ohne das globale time-Modul für andere Tests (z.B. app/ratelimit.py) zu
# beeinflussen.
def _now() -> float:
    return time.monotonic()


def _cleanup_expired() -> None:
    now = _now()
    expired = [token for token, (expires_at, _, _cid, _size) in _store.items() if expires_at < now]
    for token in expired:
        del _store[token]


def create(history: list[dict], conversation_id: str | None = None, size: int = 0) -> str:
    _cleanup_expired()
    if sum(entry[3] for entry in _store.values()) + size > MAX_TOTAL_BYTES:
        raise StoreFull
    token = secrets.token_urlsafe(24)
    _store[token] = (_now() + TTL_SECONDS, history, conversation_id, size)
    return token


def pop(token: str) -> tuple[list[dict], str | None] | None:
    """Liefert (Historie, conversation_id) und löscht den Eintrag sofort
    (Einmal-Abruf) - None bei unbekanntem oder abgelaufenem Token. Die ID
    reist mit, damit die Zielseite im Fragen-Log denselben Chat fortsetzt."""
    _cleanup_expired()
    entry = _store.pop(token, None)
    if entry is None:
        return None
    return entry[1], entry[2]
