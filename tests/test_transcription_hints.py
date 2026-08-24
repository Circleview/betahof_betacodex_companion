from app import transcription_hints


def test_get_hints_returns_german_vocabulary():
    assert "Beta-Kodex" in transcription_hints.get_hints("de")


def test_get_hints_returns_english_vocabulary():
    assert "BetaCodex" in transcription_hints.get_hints("en")


def test_get_hints_returns_empty_for_unknown_lang():
    assert transcription_hints.get_hints("fr") == []


def test_get_hints_returns_empty_when_file_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(transcription_hints, "HINTS_FILE", tmp_path / "does-not-exist.json")
    assert transcription_hints.get_hints("de") == []


def test_get_hints_returns_empty_on_invalid_json(monkeypatch, tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("not valid json")
    monkeypatch.setattr(transcription_hints, "HINTS_FILE", broken)
    assert transcription_hints.get_hints("de") == []
