"""Registry der von Quellen-Pfleger:innen freigegebenen externen Domains/
Pfade (Backlog: LLM/Internet-Fallback bei dünner Quellenlage) - jeder
Eintrag erlaubt app/web_crawler.py, Unterseiten innerhalb von url_prefix
periodisch zu indizieren und in app/main.py:ask() als ergänzende Quelle
heranzuziehen. Bewusst getrennt von sources.json: das sind keine manuell
kuratierten Einzel-Quellen, sondern ganze (Teil-)Websites, deren einzelne
Unterseiten app/web_index.py verwaltet."""
import json
import os
import threading
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_ALLOWLIST_FILE = BASE_DIR / "data" / "web_allowlist.json"

DEFAULT_MAX_PAGES = 50

# Eigener Lock, nach demselben Muster wie in app/audit.py/app/question_log.py.
_web_allowlist_lock = threading.Lock()


def _load() -> dict:
    if not WEB_ALLOWLIST_FILE.exists():
        return {}
    try:
        return json.loads(WEB_ALLOWLIST_FILE.read_text())
    except Exception:
        return {}


def _save(entries: dict) -> None:
    WEB_ALLOWLIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WEB_ALLOWLIST_FILE.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2))
    tmp.replace(WEB_ALLOWLIST_FILE)


def list_entries() -> dict:
    return _load()


def get_entry(entry_id: str) -> dict | None:
    entry = _load().get(entry_id)
    return {"id": entry_id, **entry} if entry is not None else None


def add_entry(
    *, url_prefix: str, label: str, reason: str, added_by: str, added_at: str, max_pages: int = DEFAULT_MAX_PAGES
) -> dict:
    with _web_allowlist_lock:
        entries = _load()
        entry_id = str(uuid.uuid4())
        entry = {
            "url_prefix": url_prefix,
            "label": label,
            "reason": reason,
            "added_by": added_by,
            "added_at": added_at,
            # Das Anlegen selbst zählt als erste Prüfung - sonst stünde ein
            # gerade erst von Menschenhand freigegebener Eintrag sofort als
            # "prüfungsfällig" da.
            "reviewed_at": added_at,
            "max_pages": max_pages,
            # Nutzerwunsch (Positivselektion, siehe app/web_crawler.py):
            # "negativ" (Standard) = wie gewohnt automatisch indizieren und
            # bei Bedarf einzelne Seiten ausschließen; "positiv" = das
            # System hat zu wenige eindeutig zuordenbare Seiten gefunden und
            # legt stattdessen bewertete Vorschläge zur manuellen Aufnahme
            # ab (siehe app/web_candidates.py). Wird von index_entry() bei
            # jedem Lauf neu gesetzt, nicht von Hand gepflegt.
            "selection_mode": "negativ",
        }
        entries[entry_id] = entry
        _save(entries)
        return {"id": entry_id, **entry}


def delete_entry(entry_id: str) -> bool:
    with _web_allowlist_lock:
        entries = _load()
        if entry_id not in entries:
            return False
        del entries[entry_id]
        _save(entries)
        return True


def mark_reviewed(entry_id: str, reviewed_at: str) -> dict | None:
    with _web_allowlist_lock:
        entries = _load()
        entry = entries.get(entry_id)
        if entry is None:
            return None
        entry["reviewed_at"] = reviewed_at
        _save(entries)
        return {"id": entry_id, **entry}


def set_selection_mode(entry_id: str, mode: str) -> dict | None:
    with _web_allowlist_lock:
        entries = _load()
        entry = entries.get(entry_id)
        if entry is None:
            return None
        entry["selection_mode"] = mode
        _save(entries)
        return {"id": entry_id, **entry}


def set_indexing_status(entry_id: str, status: str | None) -> dict | None:
    """Nutzerwunsch: Fortschrittsring am Globus-Icon (siehe import.js), damit
    Quellen-Pfleger:innen sehen, wann eine neu freigegebene Website fertig
    indiziert ist - status ist "running" während app/web_crawler.py läuft,
    danach wieder None (fertig) oder "error" (siehe main.py:
    _index_new_web_allowlist_entry/_run_web_allowlist_crawl_once)."""
    with _web_allowlist_lock:
        entries = _load()
        entry = entries.get(entry_id)
        if entry is None:
            return None
        entry["indexing_status"] = status
        _save(entries)
        return {"id": entry_id, **entry}
