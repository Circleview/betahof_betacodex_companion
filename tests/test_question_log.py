import json
from datetime import datetime, timedelta, timezone

from app import question_log


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(question_log, "QUESTION_LOG_FILE", tmp_path / "question_log.json")


def test_log_question_appends_entry_with_text_and_timestamp(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    question_log.log_question("Was ist Beta-Kodex?")

    entries = question_log.list_entries()
    assert len(entries) == 1
    assert entries[0]["text"] == "Was ist Beta-Kodex?"
    assert entries[0]["timestamp"]


def test_list_entries_returns_newest_first(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    question_log.log_question("Erste Frage")
    question_log.log_question("Zweite Frage")

    entries = question_log.list_entries()

    assert [e["text"] for e in entries] == ["Zweite Frage", "Erste Frage"]


def test_list_entries_is_empty_without_prior_questions(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert question_log.list_entries() == []


def test_entries_have_unique_ids(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    question_log.log_question("Erste Frage")
    question_log.log_question("Zweite Frage")

    entries = question_log.list_entries()
    ids = [e["id"] for e in entries]
    assert all(ids)
    assert len(set(ids)) == 2


def test_delete_entry_removes_only_matching_entry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    question_log.log_question("Erste Frage")
    question_log.log_question("Zweite Frage")
    entries = question_log.list_entries()
    target_id = next(e["id"] for e in entries if e["text"] == "Erste Frage")

    result = question_log.delete_entry(target_id)

    assert result is True
    remaining = question_log.list_entries()
    assert [e["text"] for e in remaining] == ["Zweite Frage"]


def test_delete_entry_returns_false_for_unknown_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    question_log.log_question("Erste Frage")

    assert question_log.delete_entry("does-not-exist") is False
    assert len(question_log.list_entries()) == 1


def test_delete_entry_works_for_no_answer_and_feedback_events(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    no_answer_id = question_log.log_question("Frage ohne Antwort")
    question_log.add_event_type(no_answer_id, "no_answer")
    question_log.log_feedback("Frage mit Feedback", "Antwort", "good")
    entries = question_log.list_entries()
    feedback_id = next(e["id"] for e in entries if e["event_types"] == ["feedback"])

    assert question_log.delete_entry(no_answer_id) is True
    assert question_log.delete_entry(feedback_id) is True
    assert question_log.list_entries() == []


def test_add_event_type_merges_into_existing_entry_instead_of_duplicating(tmp_path, monkeypatch):
    """Regressionstest (Bug 2026-09-14, per Screenshot gemeldet): eine
    Frage, die sowohl die erste Frage einer Konversation ist als auch keine
    Antwort fand, tauchte bisher als ZWEI separate Log-Einträge mit
    identischem Text auf."""
    _isolate(tmp_path, monkeypatch)
    entry_id = question_log.log_question("Erste Frage ohne Antwort")

    result = question_log.add_event_type(entry_id, "no_answer")

    entries = question_log.list_entries()
    assert result is True
    assert len(entries) == 1
    assert set(entries[0]["event_types"]) == {"first_question", "no_answer"}


def test_add_event_type_is_idempotent(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    entry_id = question_log.log_question("Frage")

    question_log.add_event_type(entry_id, "no_answer")
    question_log.add_event_type(entry_id, "no_answer")

    entries = question_log.list_entries()
    assert entries[0]["event_types"] == ["first_question", "no_answer"]


def test_add_event_type_returns_false_for_unknown_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert question_log.add_event_type("does-not-exist", "no_answer") is False


def test_log_feedback_merges_into_matching_existing_entry(tmp_path, monkeypatch):
    """Feedback zu einer Antwort, die bereits (z.B. als erste Frage oder
    als "keine Antwort") geloggt wurde, soll denselben Eintrag ergänzen
    statt einen weiteren mit identischem Text/Antwort anzulegen."""
    _isolate(tmp_path, monkeypatch)
    question_log.log_question("Frage")
    question_log.set_answer(question_log.list_entries()[0]["id"], "Die Antwort.")

    question_log.log_feedback("Frage", "Die Antwort.", "bad")

    entries = question_log.list_entries()
    assert len(entries) == 1
    assert set(entries[0]["event_types"]) == {"first_question", "feedback"}
    assert entries[0]["feedback"] == "bad"


def test_log_feedback_creates_new_entry_without_a_match(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    question_log.log_feedback("Andere Frage", "Andere Antwort", "good")

    entries = question_log.list_entries()
    assert len(entries) == 1
    assert entries[0]["event_types"] == ["feedback"]


def test_list_entries_backfills_missing_id_and_persists_it(tmp_path, monkeypatch):
    """Ältere, vor Einführung der Löschfunktion gespeicherte Einträge haben
    noch keine id - list_entries() muss eine stabile id vergeben und
    persistieren, damit ein zweiter Aufruf dieselbe id liefert (sonst würde
    eine im Frontend angezeigte id beim nächsten Löschversuch nicht mehr
    passen)."""
    _isolate(tmp_path, monkeypatch)
    question_log.QUESTION_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    question_log.QUESTION_LOG_FILE.write_text(
        '[{"event_type": "first_question", "text": "Alte Frage", "timestamp": "2026-01-01T00:00:00+00:00"}]'
    )

    first = question_log.list_entries()
    second = question_log.list_entries()

    assert first[0]["id"]
    assert first[0]["id"] == second[0]["id"]


def test_purge_older_than_removes_only_expired_entries(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)

    def at(days_ago):
        return (now - timedelta(days=days_ago)).isoformat()

    question_log._save(
        [
            {"id": "old", "event_types": ["first_question"], "text": "alt", "timestamp": at(731)},
            {"id": "edge", "event_types": ["first_question"], "text": "fast alt", "timestamp": at(729)},
            {"id": "new", "event_types": ["first_question"], "text": "neu", "timestamp": at(1)},
        ]
    )

    assert question_log.purge_older_than(730) == 1
    assert sorted(e["id"] for e in question_log.list_entries()) == ["edge", "new"]
    assert question_log.purge_older_than(730) == 0


def test_log_creative_is_anonymous_marks_sections_and_merges_later_feedback(tmp_path, monkeypatch):
    monkeypatch.setattr(question_log, "QUESTION_LOG_FILE", tmp_path / "question_log.json")

    question_log.log_creative("Schreib über Beta.", "Text über Beta.", section=False)
    question_log.log_creative("Kürze den Abschnitt.", "## B\n\nKurz.", section=True)
    question_log.log_feedback("Schreib über Beta.", "Text über Beta.", "good", mode="creative")

    entries = question_log.list_entries()
    assert len(entries) == 2
    section_entry, draft_entry = entries  # neueste zuerst
    assert section_entry["event_types"] == ["creative"] and section_entry["section"] is True
    assert draft_entry["event_types"] == ["creative", "feedback"] and "section" not in draft_entry
    assert draft_entry["feedback"] == "good" and draft_entry["mode"] == "creative"
    assert not any(k in e for e in entries for k in ("email", "ip"))


CID = "3f2a9c1e-5b7d-4e8a-9c3b-1a2b3c4d5e6f"
CID2 = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def test_log_question_marks_first_or_follow_up_and_stores_conversation_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    question_log.log_question("Erste", CID)
    question_log.log_question("Folge", CID, first=False)
    question_log.log_question("Ohne ID", None, first=False)

    by_text = {e["text"]: e for e in question_log.list_entries()}
    assert (by_text["Erste"]["event_types"], by_text["Erste"]["conversation_id"]) == (["first_question"], CID)
    assert (by_text["Folge"]["event_types"], by_text["Folge"]["conversation_id"]) == (["follow_up"], CID)
    assert by_text["Ohne ID"]["event_types"] == ["follow_up"] and "conversation_id" not in by_text["Ohne ID"]


def test_log_feedback_with_id_matches_latest_entry_with_same_id_and_question_even_if_answer_differs(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    question_log.log_question("Frage", CID2)
    old_id = question_log.log_question("Frage", CID)
    new_id = question_log.log_question("Frage", CID)
    question_log.set_answer(new_id, "Kurzer Satz.")

    question_log.log_feedback("Frage", "Lange Erklärung.", "bad", conversation_id=CID)

    by_id = {e["id"]: e for e in question_log.list_entries()}
    assert by_id[new_id]["feedback"] == "bad"
    assert "feedback" not in by_id[old_id]
    assert len(by_id) == 3


def test_log_feedback_with_id_never_matches_by_id_alone(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    question_log.log_question("Erste", CID)

    question_log.log_feedback("Andere", "Antwort", "good", conversation_id=CID)

    entries = question_log.list_entries()
    assert len(entries) == 2
    assert next(e for e in entries if e["text"] == "Andere")["conversation_id"] == CID
    assert "feedback" not in next(e for e in entries if e["text"] == "Erste")


def test_delete_conversation_returns_count_and_keeps_other_entries(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    question_log.log_question("A1", CID)
    question_log.log_question("A2", CID, first=False)
    question_log.log_question("B1", CID2)

    assert question_log.delete_conversation(CID) == 2
    assert [e["text"] for e in question_log.list_entries()] == ["B1"]
    assert question_log.delete_conversation(CID) == 0


def test_broken_file_stays_byte_identical_on_every_write_path(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    question_log.QUESTION_LOG_FILE.write_bytes(b"[{kaputt")

    assert question_log.log_question("Frage", CID) is None
    question_log.set_answer("x", "a")
    assert question_log.add_event_type("x", "no_answer") is False
    question_log.log_feedback("F", "A", "good", conversation_id=CID)
    question_log.log_creative("I", "D", section=False)
    question_log.log_mcp("I", "D")
    assert question_log.delete_entry("x") is False
    assert question_log.delete_conversation(CID) == 0
    assert question_log.purge_older_than(1) == 0
    assert question_log.list_entries() == []

    assert question_log.QUESTION_LOG_FILE.read_bytes() == b"[{kaputt"


def test_log_file_is_written_compact(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    question_log.log_question("Frage", CID)

    raw = question_log.QUESTION_LOG_FILE.read_text()
    assert "\n" not in raw and json.loads(raw)[0]["text"] == "Frage"
