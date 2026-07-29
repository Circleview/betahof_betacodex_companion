"""Speichert anonymisiert die erste Frage jeder Konversation (Backlog #97) -
kein Bezug zu Nutzerkonto oder IP, nur Text + Zeitstempel. Grundlage für eine
spätere Trend-/Lücken-Analyse (z.B. eine Themen-Cloud), siehe app/main.py
ask() für die Ausschlüsse (System-Admin, Dev/Stabil)."""
import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
QUESTION_LOG_FILE = BASE_DIR / "data" / "question_log.json"

# Eigener Lock, nach demselben Muster wie in app/audit.py.
_question_log_lock = threading.Lock()


def _load() -> list[dict]:
    if not QUESTION_LOG_FILE.exists():
        return []
    try:
        return json.loads(QUESTION_LOG_FILE.read_text())
    except Exception:
        return []


def _save(entries: list[dict]) -> None:
    QUESTION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = QUESTION_LOG_FILE.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(entries, ensure_ascii=False, indent=2))
    tmp.replace(QUESTION_LOG_FILE)


def log_question(text: str) -> None:
    with _question_log_lock:
        entries = _load()
        entries.append({"text": text, "timestamp": datetime.now(timezone.utc).isoformat()})
        _save(entries)


def list_entries() -> list[dict]:
    return sorted(_load(), key=lambda e: e["timestamp"], reverse=True)
