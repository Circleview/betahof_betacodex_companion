"""Speichert anonymisiert Ereignisse aus Konversation und Kreativ-Modus
(kein Bezug zu Nutzerkonto oder IP, nur Text + Zeitstempel):
- "first_question" (Backlog #97): die erste Frage jeder Konversation -
  Grundlage für eine Trend-/Lücken-Analyse.
- "follow_up" (Idee 56580b6e): jede weitere Frage derselben Konversation.
  Einträge einer Konversation tragen dieselbe zufällige "conversation_id"
  (ohne Verknüpfung mit IP-Adresse oder Konto).
- "no_answer" (Nutzerwunsch 2026-09-01): eine Frage, auf die der Companion
  laut eigener Systemanweisung explizit keine (oder nur teilweise eine)
  Antwort aus den Quellen geben konnte (siehe app/main.py: NO_ANSWER_PHRASES).
- "feedback" (Nutzerwunsch 2026-09-01): Daumen-hoch/-runter zu einer
  konkreten Antwort (siehe static/question.js: attachFeedbackButtons).

Alle drei teilen sich dieselbe Datei/denselben Namensraum, damit sich das
Fragen-Log (question-log.html) chronologisch gemischt und nach Ereignistyp
filterbar darstellen lässt. Ausschlüsse (System-Admin, Dev/Stabil) prüft
einheitlich app/main.py: _should_log_question_event()."""
import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import jsonstore

BASE_DIR = Path(__file__).resolve().parent.parent
QUESTION_LOG_FILE = BASE_DIR / "data" / "question_log.json"

logger = logging.getLogger(__name__)

# Eigener Lock, nach demselben Muster wie in app/audit.py.
_question_log_lock = threading.Lock()


def _load() -> list[dict]:
    # Bewusst NICHT tolerant: eine kaputte Datei als leer zu lesen hieße, dass
    # der nächste Schreibvorgang den ganzen Bestand überschreibt (jede Frage
    # wird jetzt geloggt). Die Schreibwege fangen den Fehler über _writable().
    return jsonstore.load(QUESTION_LOG_FILE, [])


def _save(entries: list[dict]) -> None:
    # ponytail: ganze Datei pro Schreibvorgang (kompakt, ohne Einrückung);
    # SQLite erst, wenn das Log spürbar langsam wird.
    jsonstore.save(QUESTION_LOG_FILE, entries, indent=None)


def _writable() -> list[dict] | None:
    """Für jeden Schreibweg (unter _question_log_lock): lädt den Bestand oder
    gibt None zurück, wenn die Datei nicht lesbar ist - dann wird der Vorgang
    übersprungen, die Datei bleibt unverändert, der Chat läuft weiter."""
    try:
        return _load()
    except Exception:
        logger.exception("Fragen-Log nicht lesbar - Schreibvorgang übersprungen")
        return None


def _append(entry: dict) -> str | None:
    """Gibt die vergebene id zurück - log_question() reicht sie weiter, damit
    app/main.py die Antwort nachträglich per set_answer() ergänzen kann,
    sobald sie feststeht (siehe dortiger Kommentar, warum das Loggen selbst
    schon VOR der Antwort-Erzeugung passiert)."""
    with _question_log_lock:
        entries = _writable()
        if entries is None:
            return None
        entry_id = uuid.uuid4().hex
        entries.append({**entry, "id": entry_id, "timestamp": datetime.now(timezone.utc).isoformat()})
        _save(entries)
        return entry_id


def log_question(text: str, conversation_id: str | None = None, first: bool = True) -> str | None:
    """first=False: Folgefrage ("follow_up") statt "first_question"."""
    entry = {"event_types": ["first_question" if first else "follow_up"], "text": text}
    if conversation_id:
        entry["conversation_id"] = conversation_id
    return _append(entry)


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
        entries = _writable()
        if entries is None:
            return
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
    first_question-Eintrag hat (log_id bekannt - kein
    Text-Abgleich nötig, da beide Ereignisse aus demselben ask()-Aufruf
    stammen). Gibt False zurück, wenn die id nicht (mehr) existiert (z.B.
    zwischenzeitlich gelöscht)."""
    with _question_log_lock:
        entries = _writable()
        if entries is None:
            return False
        for entry in entries:
            if entry.get("id") == entry_id:
                event_types = entry.setdefault("event_types", [])
                if event_type not in event_types:
                    event_types.append(event_type)
                    _save(entries)
                return True
        return False


def log_feedback(
    question: str, answer: str, feedback: str, mode: str = "conversation", conversation_id: str | None = None
) -> None:
    """Feedback kommt über einen eigenen, späteren Request ohne Bezug zu
    einer evtl. schon geloggten id (siehe /api/answer-feedback). Abgleich:
    1. Mit conversation_id: neuester Eintrag mit gleicher ID UND gleichem
       Fragetext (die ID allein reicht nie - sonst landete das Feedback bei
       einer anderen Frage des Chats). Die Antwort zählt hier nicht: bei
       einer Absage steht im Log der kurze Satz, das Frontend schickt die
       lange Erklärung.
    2. Sonst (und ohne Treffer) wie bisher über den exakten Frage- UND
       Antworttext: eine identische Kombination ist praktisch immer
       derselbe reale Konversations-Turn (Antworten sind frei generierter
       Text, eine zufällige Kollision ist nicht realistisch).
    Bei einem Treffer wird "feedback" dort ergänzt statt eines separaten
    Eintrags - sonst ein eigener Eintrag (mit conversation_id, falls
    bekannt). Feedback aus dem Kreativ-Modus (mode="creative", text =
    Anweisung, answer = erzeugter Text) bekommt das zusätzliche Feld "mode",
    damit das Fragen-Log es kennzeichnen kann."""
    extra = {} if mode == "conversation" else {"mode": mode}
    with _question_log_lock:
        entries = _writable()
        if entries is None:
            return
        match = None
        if conversation_id:
            match = next(
                (e for e in reversed(entries) if e.get("conversation_id") == conversation_id and e.get("text") == question),
                None,
            )
        if match is None:
            match = next(
                (e for e in reversed(entries) if e.get("text") == question and e.get("answer") == answer), None
            )
        if match is not None:
            event_types = match.setdefault("event_types", [])
            if "feedback" not in event_types:
                event_types.append("feedback")
            match["feedback"] = feedback
            match.update(extra)
            _save(entries)
            return
    new_entry = {"event_types": ["feedback"], "text": question, "answer": answer, "feedback": feedback, **extra}
    if conversation_id:
        new_entry["conversation_id"] = conversation_id
    _append(new_entry)


def log_creative(instruction: str, document: str, section: bool) -> None:
    """2026-09-24: jede Anfrage im Kreativ-Modus der Oberfläche - Anweisung
    + erzeugter Text (bei section=True nur der überarbeitete Abschnitt),
    anonym. Gleiche Kürzung wie beim Feedback (app/main.py:
    ANSWER_FEEDBACK_MAX_*), damit späteres Daumen-Feedback per exaktem
    Text-Abgleich (log_feedback) in DIESEN Eintrag wandert."""
    entry = {"event_types": ["creative"], "text": instruction[:2000], "answer": document[:20000], "mode": "creative"}
    if section:
        entry["section"] = True
    _append(entry)


def log_mcp(instruction: str, document: str) -> None:
    """2026-09-24: Aufruf des Kreativ-Modus über MCP (app/mcp_server.py) -
    wie Kreativ-Feedback Anweisung + erzeugter Text, aber bewusst OHNE Konto:
    das Fragen-Log bleibt anonym, die Zuordnung zum Schlüssel steht nur im
    Verbrauchsprotokoll (app/usage.py)."""
    _append({"event_types": ["mcp"], "text": instruction[:2000], "answer": document[:20000], "mode": "mcp"})


def list_entries() -> list[dict]:
    # Nicht lesbare Datei: leere Liste, nichts speichern (Datei bleibt).
    with _question_log_lock:
        entries = _writable()
        if entries is None:
            return []
        # Rückwärtskompatibel: vor der Einführung mehrerer Ereignistypen
        # gespeicherte Einträge haben noch kein event_type-Feld; vor der
        # Löschfunktion (Nutzerwunsch, Livegang-Vorbereitung 2026-09-10)
        # gespeicherte Einträge haben noch keine id - einmalig vergeben und
        # SOFORT persistieren, damit sie über mehrere list_entries()-Aufrufe
        # hinweg stabil bleibt (sonst würde ein zuvor angezeigtes id beim
        # nächsten Laden nicht mehr zum tatsächlichen Eintrag passen). Die
        # Migration läuft unter dem Lock, damit sie keinen parallelen
        # Schreibvorgang (z.B. set_answer) überschreibt.
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
        entries = _writable()
        if entries is None:
            return 0
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
        entries = _writable()
        if entries is None:
            return False
        remaining = [e for e in entries if e.get("id") != entry_id]
        if len(remaining) == len(entries):
            return False
        _save(remaining)
        return True


def delete_conversation(conversation_id: str) -> int:
    """Löscht alle Einträge einer Konversation (Idee 56580b6e) und gibt die
    Anzahl zurück - 0 bei unbekannter ID (der Aufrufer macht daraus ein 404)."""
    with _question_log_lock:
        entries = _writable()
        if entries is None:
            return 0
        remaining = [e for e in entries if e.get("conversation_id") != conversation_id]
        removed = len(entries) - len(remaining)
        if removed:
            _save(remaining)
        return removed
