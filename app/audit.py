"""Protokolliert Änderungen, die Quellen-Pfleger:innen ausführen (Backlog
#98), inklusive der dafür nötigen alten Feldwerte (Backlog #99) - so kann
eine einzelne Änderung gezielt rückgängig gemacht werden (siehe
POST /api/audit-log/{id}/revert in app/main.py), ohne eine vollständige
Versionskontrolle einführen zu müssen. Jeder Eintrag, der Felder ändert,
speichert NUR die tatsächlich geänderten Felder als {"feld": {"old": ...,
"new": ...}} - ein Revert liest genau diesen einen Eintrag und stellt nur
diese Felder wieder her, andere seither geänderte Felder bleiben unberührt.
"""
import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIT_LOG_FILE = BASE_DIR / "data" / "audit_log.json"

# Eigener Lock, nach demselben Muster wie _sources_write_lock in app/main.py
# (siehe dortigen Kommentar zum Datenverlust-Vorfall 2026-07-28): schützt den
# read-modify-write-Zyklus dieser Datei, _save() nutzt zusätzlich einen
# eindeutigen Temp-Dateinamen je Prozess/Thread statt eines gemeinsamen.
_audit_log_lock = threading.Lock()


def _load_raw() -> list[dict]:
    if not AUDIT_LOG_FILE.exists():
        return []
    try:
        return json.loads(AUDIT_LOG_FILE.read_text())
    except Exception:
        return []


def _normalize(entry: dict) -> dict:
    # Bestandsschutz für vor Backlog #99 geschriebene Einträge, denen die
    # neuen Felder komplett fehlen - id wird dann bei jedem Laden neu
    # vergeben (nicht stabil, aber unschädlich: revertible bleibt False,
    # der Rückgängig-Button erscheint für solche Einträge nie).
    entry.setdefault("id", uuid.uuid4().hex)
    entry.setdefault("entity_type", None)
    entry.setdefault("entity_id", None)
    entry.setdefault("changes", None)
    entry.setdefault("revertible", False)
    entry.setdefault("reverted_at", None)
    return entry


def _load() -> list[dict]:
    return [_normalize(entry) for entry in _load_raw()]


def _save(entries: list[dict]) -> None:
    AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUDIT_LOG_FILE.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2))
    tmp.replace(AUDIT_LOG_FILE)


def _append(entry: dict) -> dict:
    entry["id"] = uuid.uuid4().hex
    entry["timestamp"] = datetime.now(timezone.utc).isoformat()
    with _audit_log_lock:
        entries = _load_raw()
        entries.append(entry)
        _save(entries)
    return entry


def log_action(actor_email: str, action: str, entity_type: str, entity_id: str, target_label: str) -> dict:
    """Für Ereignisse ohne sinnvollen Rückgängig-Zustand - entweder weil sie
    kein bestehendes Feld überschreiben (z.B. eine Anlage - siehe Backlog
    #99: bewusst NICHT rückgängig machbar, dafür bleibt der normale
    Löschen-Weg zuständig) oder weil es schlicht keinen vorherigen Wert gab
    (z.B. die einmalige KI-Vita-Erstellung für eine brandneue Person)."""
    return _append(
        {
            "actor_email": actor_email,
            "action": action,
            "target_label": target_label,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "changes": None,
            "revertible": False,
            "reverted_at": None,
        }
    )


def log_change(
    actor_email: str, action: str, entity_type: str, entity_id: str, target_label: str, changes: dict
) -> dict:
    """Protokolliert eine feld-bezogene Änderung (Backlog #99) - changes ist
    ein {"feld": {"old": ..., "new": ...}}-Dict NUR für tatsächlich
    geänderte Felder. Grundlage für POST /api/audit-log/{id}/revert
    (app/main.py): schreibt gezielt die "old"-Werte der hier
    festgehaltenen Felder zurück."""
    return _append(
        {
            "actor_email": actor_email,
            "action": action,
            "target_label": target_label,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "changes": changes,
            "revertible": bool(changes),
            "reverted_at": None,
        }
    )


def list_entries(limit: int = 500) -> list[dict]:
    entries = _load()
    return list(reversed(entries))[:limit]


def get_entry(entry_id: str) -> dict | None:
    for entry in _load():
        if entry.get("id") == entry_id:
            return entry
    return None


def mark_reverted(entry_id: str) -> None:
    with _audit_log_lock:
        entries = _load_raw()
        for entry in entries:
            if entry.get("id") == entry_id:
                entry["reverted_at"] = datetime.now(timezone.utc).isoformat()
                break
        _save(entries)
