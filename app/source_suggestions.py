"""Nutzerwunsch: der Companion soll proaktiv im offenen Web nach neuen,
thematisch/autorenmäßig passenden Text-Quellen suchen (app/source_discovery.py)
und sie als kleine Vorschlagsliste ablegen, aus der Quellen-Pfleger:innen
einzelne annehmen oder ablehnen. "Annehmen" legt HIER bewusst keine Quelle
an - das läuft komplett über das bestehende "Quelle per URL"-Formular
(static/import.js), diese Zeile kennt nur den eigenen Status
(pending/accepted/rejected). Getrennt von app/web_candidates.py, da dortige
Kandidaten an einen bereits freigegebenen allowlist_entry_id gebunden sind -
hier geht es um komplett neue, unbekannte Domains/Autor:innen."""
import json
import os
import random
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
SOURCE_SUGGESTIONS_FILE = BASE_DIR / "data" / "source_suggestions.json"
SOURCE_SUGGESTION_WEIGHTS_FILE = BASE_DIR / "data" / "source_suggestion_weights.json"

# Ab diesem (negativen) Gewichtungs-Score wird eine Domain/Autor:in nicht
# mehr vorgeschlagen - bewusst erst nach mehreren Ablehnungen, nicht schon
# nach der ersten (siehe app/main.py _run_source_suggestion_discovery_once).
BLOCK_THRESHOLD = -3

_lock = threading.Lock()


def _load() -> dict:
    if not SOURCE_SUGGESTIONS_FILE.exists():
        return {}
    try:
        return json.loads(SOURCE_SUGGESTIONS_FILE.read_text())
    except Exception:
        return {}


def _save(suggestions: dict) -> None:
    SOURCE_SUGGESTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SOURCE_SUGGESTIONS_FILE.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(suggestions, ensure_ascii=False, indent=2))
    tmp.replace(SOURCE_SUGGESTIONS_FILE)


def _load_weights() -> dict:
    # "last_author_index" tauchte in älteren Dateien auf (Rundenlauf-Ansatz,
    # per Nutzerfeedback 2026-08-23 durch echte Zufallsauswahl ersetzt, siehe
    # pick_next_authors) - ein evtl. noch vorhandener Altwert wird einfach
    # ignoriert, kein Migrationscode nötig.
    if not SOURCE_SUGGESTION_WEIGHTS_FILE.exists():
        return {"authors": {}, "domains": {}}
    try:
        data = json.loads(SOURCE_SUGGESTION_WEIGHTS_FILE.read_text())
    except Exception:
        return {"authors": {}, "domains": {}}
    data.setdefault("authors", {})
    data.setdefault("domains", {})
    return data


def _save_weights(weights: dict) -> None:
    SOURCE_SUGGESTION_WEIGHTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SOURCE_SUGGESTION_WEIGHTS_FILE.with_suffix(
        f".json.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    tmp.write_text(json.dumps(weights, ensure_ascii=False, indent=2))
    tmp.replace(SOURCE_SUGGESTION_WEIGHTS_FILE)


def domain_of(url: str) -> str:
    return (urlparse(url).netloc or "").lower().removeprefix("www.")


def list_suggestions(status: str | None = "pending") -> dict:
    all_suggestions = _load()
    if status is None:
        return all_suggestions
    return {sid: s for sid, s in all_suggestions.items() if s.get("status") == status}


def get_suggestion(suggestion_id: str) -> dict | None:
    return _load().get(suggestion_id)


def known_urls() -> set[str]:
    return {s["url"] for s in _load().values() if s.get("url")}


def add_suggestion(candidate: dict, discovered_at: str) -> str:
    """Legt einen neu entdeckten Kandidaten als pending Vorschlag an.
    Aufrufer (app/main.py) ist dafür verantwortlich, vorher gegen
    known_urls() UND die bestehenden Quellen zu deduplizieren - hier wird
    nicht erneut geprüft, um denselben Lock nicht doppelt zu nehmen."""
    with _lock:
        all_suggestions = _load()
        suggestion_id = str(uuid.uuid4())
        all_suggestions[suggestion_id] = {
            "url": candidate["url"],
            "title": candidate["title"],
            "reason": candidate.get("reason", ""),
            "discovered_via": candidate["discovered_via"],
            "author_hint": candidate.get("author_hint"),
            "status": "pending",
            "discovered_at": discovered_at,
        }
        _save(all_suggestions)
        return suggestion_id


def set_status(suggestion_id: str, status: str) -> dict | None:
    with _lock:
        all_suggestions = _load()
        suggestion = all_suggestions.get(suggestion_id)
        if suggestion is None:
            return None
        suggestion["status"] = status
        _save(all_suggestions)
        return {"id": suggestion_id, **suggestion}


def blocked_domains() -> set[str]:
    weights = _load_weights()
    return {domain for domain, score in weights["domains"].items() if score <= BLOCK_THRESHOLD}


def blocked_authors() -> set[str]:
    weights = _load_weights()
    return {author for author, score in weights["authors"].items() if score <= BLOCK_THRESHOLD}


def adjust_weight(*, author_hint: str | None, url: str, delta: int) -> None:
    """delta=+1 bei Annahme, -1 bei Ablehnung (und jeweils umgekehrt beim
    Rückgängigmachen, siehe app/main.py _revert_source_suggestion_changes)."""
    with _lock:
        weights = _load_weights()
        if author_hint:
            weights["authors"][author_hint] = weights["authors"].get(author_hint, 0) + delta
        domain = domain_of(url)
        if domain:
            weights["domains"][domain] = weights["domains"].get(domain, 0) + delta
        _save_weights(weights)


def pick_next_authors(all_author_names: list[str], n: int) -> list[str]:
    """Nutzerfeedback (2026-08-23): ein Rundenlauf in alphabetischer
    Reihenfolge (authors.list_authors() ist nach Namen sortiert) fragte
    praktisch immer zuerst dieselben, alphabetisch frühen Autor:innen ab -
    bei Autor:innen mit sehr vielen Veröffentlichungen (z.B. Alfie Kohn)
    kann eine EINZELNE Anfrage schon die gesamte Warteschlange füllen, ohne
    dass sich die Quellenlage in der Breite verbessert. Wählt stattdessen
    rein zufällig aus den (nicht gesperrten) bekannten Autor:innen - über
    mehrere Wochen kommen so alle ungefähr gleich oft dran, ohne die
    alphabetische Schieflage. Bereits gesperrte Autor:innen
    (blocked_authors()) werden ausgeschlossen."""
    if not all_author_names:
        return []
    blocked = blocked_authors()
    candidates = [name for name in all_author_names if name not in blocked]
    if not candidates:
        return []
    return random.sample(candidates, min(n, len(candidates)))
