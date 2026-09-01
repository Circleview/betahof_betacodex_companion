"""Speichert anonymisiert drei Arten von Ereignissen aus der Konversation
(kein Bezug zu Nutzerkonto oder IP, nur Text + Zeitstempel):
- "first_question" (Backlog #97): die erste Frage jeder Konversation -
  Grundlage für eine Trend-/Lücken-Analyse.
- "no_answer" (Nutzerwunsch 2026-09-01): eine Frage, auf die der Companion
  laut eigener Systemanweisung explizit keine (oder nur teilweise eine)
  Antwort aus den Quellen geben konnte (siehe app/main.py: NO_ANSWER_PHRASES).
- "feedback" (Nutzerwunsch 2026-09-01): Daumen-hoch/-runter zu einer
  konkreten Antwort (siehe static/question.js: attachFeedbackButtons).

Alle drei teilen sich dieselbe Datei/denselben Namensraum, damit sich das
Fragen-Log (question-log.html) chronologisch gemischt und nach Ereignistyp
filterbar darstellen lässt. Ausschlüsse (System-Admin, Dev/Stabil) prüft
einheitlich app/main.py: _should_log_question_event()."""
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


def _append(entry: dict) -> None:
    with _question_log_lock:
        entries = _load()
        entries.append({**entry, "timestamp": datetime.now(timezone.utc).isoformat()})
        _save(entries)


def log_question(text: str) -> None:
    _append({"event_type": "first_question", "text": text})


def log_no_answer(question: str, answer: str) -> None:
    _append({"event_type": "no_answer", "text": question, "answer": answer})


def log_feedback(question: str, answer: str, feedback: str) -> None:
    _append({"event_type": "feedback", "text": question, "answer": answer, "feedback": feedback})


def list_entries() -> list[dict]:
    entries = _load()
    # Rückwärtskompatibel: vor der Einführung mehrerer Ereignistypen
    # gespeicherte Einträge haben noch kein event_type-Feld.
    for entry in entries:
        entry.setdefault("event_type", "first_question")
    return sorted(entries, key=lambda e: e["timestamp"], reverse=True)
