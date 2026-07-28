"""Protokolliert Änderungen, die Quellen-Pfleger:innen ausführen (Backlog
#98) - Grundlage für den in Backlog #99 geplanten Feed, in dem andere
Quellen-Pfleger:innen die Änderungen ihrer Kolleg:innen nachvollziehen
können.
"""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUDIT_LOG_FILE = BASE_DIR / "data" / "audit_log.json"

# Eigener Lock, nach demselben Muster wie _sources_write_lock in app/main.py
# (siehe dortigen Kommentar zum Datenverlust-Vorfall 2026-07-28): schützt den
# read-modify-write-Zyklus dieser Datei, _save() nutzt zusätzlich einen
# eindeutigen Temp-Dateinamen je Prozess/Thread statt eines gemeinsamen.
_audit_log_lock = threading.Lock()


def _load() -> list[dict]:
    if not AUDIT_LOG_FILE.exists():
        return []
    try:
        return json.loads(AUDIT_LOG_FILE.read_text())
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUDIT_LOG_FILE.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2))
    tmp.replace(AUDIT_LOG_FILE)


def log_action(actor_email: str, action: str, target_label: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "actor_email": actor_email,
        "action": action,
        "target_label": target_label,
    }
    with _audit_log_lock:
        entries = _load()
        entries.append(entry)
        _save(entries)


def list_entries(limit: int = 500) -> list[dict]:
    entries = _load()
    return list(reversed(entries))[:limit]
