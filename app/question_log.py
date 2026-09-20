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
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import jsonstore

BASE_DIR = Path(__file__).resolve().parent.parent
QUESTION_LOG_FILE = BASE_DIR / "data" / "question_log.json"

# Eigener Lock, nach demselben Muster wie in app/audit.py.
_question_log_lock = threading.Lock()


def _load() -> list[dict]:
    return jsonstore.load(QUESTION_LOG_FILE, [], tolerant=True)


def _save(entries: list[dict]) -> None:
    jsonstore.save(QUESTION_LOG_FILE, entries)


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
    return _append({"event_types": ["first_question"], "text": text})


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


def add_event_type(entry_id: str, event_type: str) -> bool:
    """Ergänzt einen bestehenden Eintrag um einen weiteren event_type, statt
    für dieselbe Frage einen komplett separaten Eintrag anzulegen (Bug
    2026-09-14, per Screenshot gemeldet: eine Frage, die sowohl "erste
    Frage" als auch z.B. "keine Antwort gefunden" war, tauchte bisher
    zweimal im Log auf, jeweils nur mit einem Label). Wird von app/main.py
    für "no_answer" genutzt, wenn dieselbe Anfrage bereits einen
    first_question-Eintrag hat (first_question_log_id bekannt - kein
    Text-Abgleich nötig, da beide Ereignisse aus demselben ask()-Aufruf
    stammen). Gibt False zurück, wenn die id nicht (mehr) existiert (z.B.
    zwischenzeitlich gelöscht)."""
    with _question_log_lock:
        entries = _load()
        for entry in entries:
            if entry.get("id") == entry_id:
                event_types = entry.setdefault("event_types", [])
                if event_type not in event_types:
                    event_types.append(event_type)
                    _save(entries)
                return True
        return False


def log_no_answer(question: str, answer: str) -> None:
    """Nur für den Fall, dass KEIN first_question-Eintrag für dieselbe
    Anfrage existiert (z.B. eine spätere Folgefrage in der Konversation,
    nicht die erste) - sonst siehe add_event_type()."""
    _append({"event_types": ["no_answer"], "text": question, "answer": answer})


def log_feedback(question: str, answer: str, feedback: str, mode: str = "conversation") -> None:
    """Feedback kommt über einen eigenen, späteren Request ohne Bezug zu
    einer evtl. schon geloggten id (siehe /api/answer-feedback) - anders als
    bei add_event_type() oben deshalb ein Abgleich über den exakten Frage-
    UND Antworttext: eine identische Kombination ist praktisch immer
    derselbe reale Konversations-Turn (Antworten sind frei generierter
    Text, eine zufällige Kollision ist nicht realistisch). Findet sich ein
    Treffer (neuester zuerst), wird "feedback" dort ergänzt statt eines
    separaten Eintrags - sonst (z.B. Feedback zu einer nicht geloggten
    Folgefrage) wie bisher ein eigener Eintrag. Feedback aus dem Kreativ-Modus
    (mode="creative", text = Anweisung, answer = erzeugter Text) bekommt das
    zusätzliche Feld "mode", damit das Fragen-Log es kennzeichnen kann."""
    extra = {} if mode == "conversation" else {"mode": mode}
    with _question_log_lock:
        entries = _load()
        for entry in reversed(entries):
            if entry.get("text") == question and entry.get("answer") == answer:
                event_types = entry.setdefault("event_types", [])
                if "feedback" not in event_types:
                    event_types.append("feedback")
                entry["feedback"] = feedback
                entry.update(extra)
                _save(entries)
                return
    _append({"event_types": ["feedback"], "text": question, "answer": answer, "feedback": feedback, **extra})


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
        # Migration (2026-09-14): vor der Mehrfach-Label-Fähigkeit gespeicherte
        # Einträge haben noch das alte einzelne "event_type"-Feld statt der
        # neuen "event_types"-Liste.
        if "event_types" not in entry:
            entry["event_types"] = [entry.pop("event_type", "first_question")]
            changed = True
        if "id" not in entry:
            entry["id"] = uuid.uuid4().hex
            changed = True
    if changed:
        _save(entries)
    return sorted(entries, key=lambda e: e["timestamp"], reverse=True)


def get_entry(entry_id: str) -> dict | None:
    return next((e for e in list_entries() if e["id"] == entry_id), None)


def purge_older_than(days: int) -> int:
    """Löscht alle Einträge, die älter als `days` Tage sind (Aufbewahrungsfrist,
    siehe app/main.py: QUESTION_LOG_RETENTION_DAYS), und gibt die Anzahl der
    gelöschten Einträge zurück. Jeder Eintrag hat einen Zeitstempel (siehe
    _append)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with _question_log_lock:
        entries = _load()
        kept = [e for e in entries if datetime.fromisoformat(e["timestamp"]) >= cutoff]
        if len(kept) != len(entries):
            _save(kept)
        return len(entries) - len(kept)


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
