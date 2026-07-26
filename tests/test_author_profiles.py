from app import author_profiles, authors


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(author_profiles, "AUTHOR_PROFILES_FILE", tmp_path / "author_profiles.json")


def test_get_profile_returns_empty_defaults_for_unknown_author(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert author_profiles.get_profile("Unknown Person") == {
        "bio": "",
        "photo_url": "",
        "website": "",
        "social_links": [],
        "bio_ai_generated": False,
    }


def test_set_profile_creates_entry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    result = author_profiles.set_profile(
        "Elisabeth Sechser",
        bio="Kurze Vita.",
        photo_url="https://example.org/foto.jpg",
        website="https://example.org",
        social_links=[{"platform": "LinkedIn", "url": "https://linkedin.com/in/es"}],
    )

    assert result == {
        "bio": "Kurze Vita.",
        "photo_url": "https://example.org/foto.jpg",
        "website": "https://example.org",
        "social_links": [{"platform": "LinkedIn", "url": "https://linkedin.com/in/es"}],
        "bio_ai_generated": False,
    }
    assert author_profiles.get_profile("Elisabeth Sechser") == result


def test_set_profile_partial_update_preserves_other_fields(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Jane Doe", bio="Erste Vita.", website="https://jane.example")
    author_profiles.set_profile("Jane Doe", bio="Aktualisierte Vita.")

    result = author_profiles.get_profile("Jane Doe")
    assert result["bio"] == "Aktualisierte Vita."
    assert result["website"] == "https://jane.example"


def test_set_profile_normalizes_name_casing_and_whitespace(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Niels Pfläging", bio="Vita.")

    assert author_profiles.get_profile("niels   pfläging")["bio"] == "Vita."


def test_set_profile_bio_ai_generated_true_when_explicitly_set(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    result = author_profiles.set_profile("Jane Doe", bio="KI-Vita.", bio_ai_generated=True)

    assert result["bio_ai_generated"] is True


def test_set_profile_clears_ai_flag_when_bio_text_changes(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Jane Doe", bio="KI-Vita.", bio_ai_generated=True)
    result = author_profiles.set_profile("Jane Doe", bio="Von Hand überarbeitete Vita.")

    assert result["bio_ai_generated"] is False


def test_set_profile_keeps_ai_flag_when_bio_text_unchanged(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Jane Doe", bio="KI-Vita.", bio_ai_generated=True)
    result = author_profiles.set_profile("Jane Doe", bio="KI-Vita.")

    assert result["bio_ai_generated"] is True


def test_set_profile_keeps_ai_flag_when_bio_not_touched(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Jane Doe", bio="KI-Vita.", bio_ai_generated=True)
    result = author_profiles.set_profile("Jane Doe", website="https://jane.example")

    assert result["bio_ai_generated"] is True
    assert result["bio"] == "KI-Vita."


def test_profile_survives_when_author_has_no_sources_left(tmp_path, monkeypatch):
    # Kernbeweis für die Entkopplung von app/authors.py: dort wird ein
    # Eintrag komplett gelöscht, sobald die letzte Quelle einer Person
    # entfernt wird - das darf das separat gespeicherte Profil nicht treffen.
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(authors, "AUTHORS_FILE", tmp_path / "authors.json")

    author_profiles.set_profile("Jane Doe", bio="Bleibt erhalten.")
    authors.register_author("Jane Doe", "source-1")
    authors.unregister_source("source-1")

    assert authors.list_authors() == []
    assert author_profiles.get_profile("Jane Doe")["bio"] == "Bleibt erhalten."


def test_rename_profile_moves_data_to_new_name(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    author_profiles.set_profile("Jane Doe", bio="Vita.", website="https://jane.example")

    author_profiles.rename_profile("Jane Doe", "Jane Smith")

    assert author_profiles.get_profile("Jane Doe") == {
        "bio": "",
        "photo_url": "",
        "website": "",
        "social_links": [],
        "bio_ai_generated": False,
    }
    result = author_profiles.get_profile("Jane Smith")
    assert result["bio"] == "Vita."
    assert result["website"] == "https://jane.example"


def test_rename_profile_is_noop_for_unknown_old_name(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.rename_profile("Unknown Person", "New Name")

    assert author_profiles.get_profile("New Name")["bio"] == ""


def test_rename_profile_is_noop_when_only_casing_changes(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    author_profiles.set_profile("Jane Doe", bio="Vita.")

    author_profiles.rename_profile("Jane Doe", "jane   doe")

    assert author_profiles.get_profile("Jane Doe")["bio"] == "Vita."


def test_rename_profile_does_not_overwrite_existing_target_profile(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    author_profiles.set_profile("Jane Doe", bio="Alte Vita.")
    author_profiles.set_profile("Jane Smith", bio="Vita von Smith.")

    author_profiles.rename_profile("Jane Doe", "Jane Smith")

    assert author_profiles.get_profile("Jane Smith")["bio"] == "Vita von Smith."
    assert author_profiles.get_profile("Jane Doe")["bio"] == ""
