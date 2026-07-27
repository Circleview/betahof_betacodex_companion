import json

from app import author_profiles, authors


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(author_profiles, "AUTHOR_PROFILES_FILE", tmp_path / "author_profiles.json")


def test_get_profile_returns_empty_defaults_for_unknown_author(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert author_profiles.get_profile("Unknown Person") == {
        "bio_de": "",
        "bio_en": "",
        "bio_ai_generated_de": False,
        "bio_ai_generated_en": False,
        "photo_url": "",
        "website": "",
        "social_links": [],
    }


def test_set_profile_creates_entry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    result = author_profiles.set_profile(
        "Elisabeth Sechser",
        bio_de="Kurze Vita.",
        bio_en="Short bio.",
        photo_url="https://example.org/foto.jpg",
        website="https://example.org",
        social_links=[{"platform": "LinkedIn", "url": "https://linkedin.com/in/es"}],
    )

    assert result == {
        "bio_de": "Kurze Vita.",
        "bio_en": "Short bio.",
        "bio_ai_generated_de": False,
        "bio_ai_generated_en": False,
        "photo_url": "https://example.org/foto.jpg",
        "website": "https://example.org",
        "social_links": [{"platform": "LinkedIn", "url": "https://linkedin.com/in/es"}],
    }
    assert author_profiles.get_profile("Elisabeth Sechser") == result


def test_set_profile_partial_update_preserves_other_fields(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Jane Doe", bio_de="Erste Vita.", website="https://jane.example")
    author_profiles.set_profile("Jane Doe", bio_de="Aktualisierte Vita.")

    result = author_profiles.get_profile("Jane Doe")
    assert result["bio_de"] == "Aktualisierte Vita."
    assert result["website"] == "https://jane.example"


def test_set_profile_languages_are_independent(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Jane Doe", bio_de="Deutsche Vita.")
    author_profiles.set_profile("Jane Doe", bio_en="English bio.")

    result = author_profiles.get_profile("Jane Doe")
    assert result["bio_de"] == "Deutsche Vita."
    assert result["bio_en"] == "English bio."


def test_set_profile_normalizes_name_casing_and_whitespace(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Niels Pfläging", bio_de="Vita.")

    assert author_profiles.get_profile("niels   pfläging")["bio_de"] == "Vita."


def test_set_profile_bio_ai_generated_true_when_explicitly_set(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    result = author_profiles.set_profile("Jane Doe", bio_de="KI-Vita.", bio_ai_generated_de=True)

    assert result["bio_ai_generated_de"] is True


def test_set_profile_clears_ai_flag_when_bio_text_changes(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Jane Doe", bio_de="KI-Vita.", bio_ai_generated_de=True)
    result = author_profiles.set_profile("Jane Doe", bio_de="Von Hand überarbeitete Vita.")

    assert result["bio_ai_generated_de"] is False


def test_set_profile_keeps_ai_flag_when_bio_text_unchanged(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Jane Doe", bio_de="KI-Vita.", bio_ai_generated_de=True)
    result = author_profiles.set_profile("Jane Doe", bio_de="KI-Vita.")

    assert result["bio_ai_generated_de"] is True


def test_set_profile_keeps_ai_flag_when_bio_not_touched(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.set_profile("Jane Doe", bio_de="KI-Vita.", bio_ai_generated_de=True)
    result = author_profiles.set_profile("Jane Doe", website="https://jane.example")

    assert result["bio_ai_generated_de"] is True
    assert result["bio_de"] == "KI-Vita."


def test_profile_survives_when_author_has_no_sources_left(tmp_path, monkeypatch):
    # Kernbeweis für die Entkopplung von app/authors.py: dort wird ein
    # Eintrag komplett gelöscht, sobald die letzte Quelle einer Person
    # entfernt wird - das darf das separat gespeicherte Profil nicht treffen.
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(authors, "AUTHORS_FILE", tmp_path / "authors.json")

    author_profiles.set_profile("Jane Doe", bio_de="Bleibt erhalten.")
    authors.register_author("Jane Doe", "source-1")
    authors.unregister_source("source-1")

    assert authors.list_authors() == []
    assert author_profiles.get_profile("Jane Doe")["bio_de"] == "Bleibt erhalten."


def test_rename_profile_moves_data_to_new_name(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    author_profiles.set_profile("Jane Doe", bio_de="Vita.", website="https://jane.example")

    author_profiles.rename_profile("Jane Doe", "Jane Smith")

    assert author_profiles.get_profile("Jane Doe") == {
        "bio_de": "",
        "bio_en": "",
        "bio_ai_generated_de": False,
        "bio_ai_generated_en": False,
        "photo_url": "",
        "website": "",
        "social_links": [],
    }
    result = author_profiles.get_profile("Jane Smith")
    assert result["bio_de"] == "Vita."
    assert result["website"] == "https://jane.example"


def test_rename_profile_is_noop_for_unknown_old_name(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    author_profiles.rename_profile("Unknown Person", "New Name")

    assert author_profiles.get_profile("New Name")["bio_de"] == ""


def test_rename_profile_is_noop_when_only_casing_changes(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    author_profiles.set_profile("Jane Doe", bio_de="Vita.")

    author_profiles.rename_profile("Jane Doe", "jane   doe")

    assert author_profiles.get_profile("Jane Doe")["bio_de"] == "Vita."


def test_rename_profile_does_not_overwrite_existing_target_profile(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    author_profiles.set_profile("Jane Doe", bio_de="Alte Vita.")
    author_profiles.set_profile("Jane Smith", bio_de="Vita von Smith.")

    author_profiles.rename_profile("Jane Doe", "Jane Smith")

    assert author_profiles.get_profile("Jane Smith")["bio_de"] == "Vita von Smith."
    assert author_profiles.get_profile("Jane Doe")["bio_de"] == ""


def test_get_profile_migrates_legacy_single_bio_field(tmp_path, monkeypatch):
    # Vor dem Umstieg auf bio_de/bio_en gab es ein einzelnes "bio"-Feld -
    # bestehende Daten müssen weiterhin lesbar sein, ohne Text zu verlieren
    # oder zu erraten, in welcher Sprache er verfasst wurde (DEFAULT_LANG ist
    # "de", der alte Text wird deshalb als bio_de übernommen).
    _isolate(tmp_path, monkeypatch)
    author_profiles.AUTHOR_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    author_profiles.AUTHOR_PROFILES_FILE.write_text(
        json.dumps(
            {
                "jane doe": {
                    "bio": "Alte einsprachige Vita.",
                    "bio_ai_generated": True,
                    "photo_url": "https://example.org/foto.jpg",
                    "website": "",
                    "social_links": [],
                }
            }
        )
    )

    result = author_profiles.get_profile("Jane Doe")

    assert result["bio_de"] == "Alte einsprachige Vita."
    assert result["bio_ai_generated_de"] is True
    assert result["bio_en"] == ""
    assert result["bio_ai_generated_en"] is False
    assert result["photo_url"] == "https://example.org/foto.jpg"


def test_set_profile_after_migration_persists_new_shape(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    author_profiles.AUTHOR_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    author_profiles.AUTHOR_PROFILES_FILE.write_text(
        json.dumps({"jane doe": {"bio": "Alte Vita.", "bio_ai_generated": False}})
    )

    author_profiles.set_profile("Jane Doe", bio_en="New bio.")

    saved = json.loads(author_profiles.AUTHOR_PROFILES_FILE.read_text())
    assert saved["jane doe"]["bio_de"] == "Alte Vita."
    assert saved["jane doe"]["bio_en"] == "New bio."
    assert "bio" not in saved["jane doe"]
