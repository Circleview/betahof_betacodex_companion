import json
from pathlib import Path

from app import i18n

FRONTEND_I18N_DIR = Path(__file__).resolve().parent.parent / "static" / "i18n"


def test_get_message_returns_german_by_default():
    assert i18n.get_message("text_empty") == "Text darf nicht leer sein."


def test_get_message_returns_english():
    assert i18n.get_message("text_empty", "en") == "Text must not be empty."


def test_get_message_falls_back_to_german_for_unknown_lang():
    assert i18n.get_message("text_empty", "fr") == i18n.get_message("text_empty", "de")


def test_get_message_formats_placeholders():
    result = i18n.get_message("role_required", "de", role="quellen_pfleger", user="anon")
    assert result == "Diese Aktion erfordert die Rolle 'quellen_pfleger' (aktuell: 'anon')."


def test_de_and_en_backend_message_keys_match():
    assert set(i18n.MESSAGES["de"].keys()) == set(i18n.MESSAGES["en"].keys())


def test_frontend_locale_files_have_matching_keys():
    de = json.loads((FRONTEND_I18N_DIR / "de.json").read_text())
    en = json.loads((FRONTEND_I18N_DIR / "en.json").read_text())
    assert set(de.keys()) == set(en.keys())
