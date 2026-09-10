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
    question_log.log_no_answer("Frage ohne Antwort", "Keine Antwort möglich.")
    question_log.log_feedback("Frage mit Feedback", "Antwort", "good")
    entries = question_log.list_entries()
    no_answer_id = next(e["id"] for e in entries if e["event_type"] == "no_answer")
    feedback_id = next(e["id"] for e in entries if e["event_type"] == "feedback")

    assert question_log.delete_entry(no_answer_id) is True
    assert question_log.delete_entry(feedback_id) is True
    assert question_log.list_entries() == []


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
