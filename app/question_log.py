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
import uuid
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


def _append(entry: dict) -> str:
    """Gibt die vergebene id zurück - log_question() reicht sie weiter, damit
    app/main.py die Antwort nachträglich per set_answer() ergänzen kann,
    sobald sie feststeht (siehe dortiger Kommentar, warum das Loggen selbst
    schon VOR der Antwort-Erzeugung passiert)."""
    with _question_log_lock:
        entries = _load()
        entry_id = uuid.uuid4().hex
        entries.append({**entry, "id": entry_id, "timestamp": datetime.now(timezone.utc).isoformat()})
        _save(entries)
        return entry_id


def log_question(text: str) -> str:
    return _append({"event_type": "first_question", "text": text})


def set_answer(entry_id: str, answer: str) -> None:
    """Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): ergänzt einen
    first_question-Eintrag nachträglich um die Antwort. log_question() läuft
    bewusst schon VOR der eigentlichen RAG-Suche/Antwort-Erzeugung (siehe
    app/main.py: ask() - damit auch Fragen ohne Treffer für die
    Lücken-Analyse erfasst werden) - die Antwort steht deshalb erst hier,
    einen Schritt später, fest. Kein Fehler, falls die id inzwischen
    gelöscht wurde (z.B. durch die Löschfunktion, während die Antwort noch
    lief) - dann bleibt einfach nichts zu ergänzen."""
    with _question_log_lock:
        entries = _load()
        for entry in entries:
            if entry.get("id") == entry_id:
                entry["answer"] = answer
                _save(entries)
                return


def log_no_answer(question: str, answer: str) -> None:
    _append({"event_type": "no_answer", "text": question, "answer": answer})


def log_feedback(question: str, answer: str, feedback: str) -> None:
    _append({"event_type": "feedback", "text": question, "answer": answer, "feedback": feedback})


def list_entries() -> list[dict]:
    entries = _load()
    # Rückwärtskompatibel: vor der Einführung mehrerer Ereignistypen
    # gespeicherte Einträge haben noch kein event_type-Feld; vor der
    # Löschfunktion (Nutzerwunsch, Livegang-Vorbereitung 2026-09-10)
    # gespeicherte Einträge haben noch keine id - einmalig vergeben und
    # SOFORT persistieren, damit sie über mehrere list_entries()-Aufrufe
    # hinweg stabil bleibt (sonst würde ein zuvor angezeigtes id beim
    # nächsten Laden nicht mehr zum tatsächlichen Eintrag passen).
    changed = False
    for entry in entries:
        entry.setdefault("event_type", "first_question")
        if "id" not in entry:
            entry["id"] = uuid.uuid4().hex
            changed = True
    if changed:
        _save(entries)
    return sorted(entries, key=lambda e: e["timestamp"], reverse=True)


def delete_entry(entry_id: str) -> bool:
    """Löscht einen einzelnen Fragen-Log-Eintrag (jeden event_type - erste
    Frage, unbeantwortete Frage, Feedback) unwiderruflich. Gibt False
    zurück, wenn keine id passte (z.B. schon gelöscht/nie existiert), statt
    einen Fehler zu werfen - der Aufrufer entscheidet, ob das ein 404 wird."""
    with _question_log_lock:
        entries = _load()
        remaining = [e for e in entries if e.get("id") != entry_id]
        if len(remaining) == len(entries):
            return False
        _save(remaining)
        return True
