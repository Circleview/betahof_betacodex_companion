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
