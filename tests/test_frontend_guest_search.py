"""Idee 669405f0 (P2): Gäste laden nie Volltext, suchen serverseitig, 429 zeigt Hinweis."""
import json
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "static"
IMPORT_JS = "\n".join(p.read_text() for p in [STATIC / "import.js", *sorted(STATIC.glob("import-*.js"))])
EXPLORE_JS = (STATIC / "explore.js").read_text()


def _fn(src: str, name: str) -> str:
    m = re.search(rf"(?:async )?function {name}\(.*?\n}}\n", src, re.S)
    assert m, name
    return m.group(0)


def test_full_text_only_for_logged_in_users():
    body = _fn(IMPORT_JS, "loadSources")
    assert "include_text=false" in body
    assert re.search(r"if \(currentUserEmail\(\)\)\s*\{?\s*fullTextReady = loadFullSourceText\(\)", body)
    assert body.count("loadFullSourceText()") == 1


def test_load_sources_checks_res_ok_and_429():
    body = _fn(IMPORT_JS, "loadSources")
    assert "res.ok" in body and "429" in body and "showTooManyRequests()" in body
    assert "import.tooManyRequests" in _fn(IMPORT_JS, "showTooManyRequests")


def test_guest_search_uses_server_endpoint():
    body = _fn(IMPORT_JS, "applySearchFilter")
    assert "/api/sources/search" in IMPORT_JS
    assert "currentUserEmail()" in body
    assert "setTimeout" in IMPORT_JS and "300" in IMPORT_JS
    assert "429" in IMPORT_JS


def test_explore_handles_429():
    assert re.search(r"status === 429[^;]*explore\.tooManyRequests|explore\.tooManyRequests", _fn(EXPLORE_JS, "loadGraph"))
    assert "429" in _fn(EXPLORE_JS, "loadGraph")


def test_i18n_keys_in_both_languages():
    for lang in ("de", "en"):
        d = json.loads((STATIC / "i18n" / f"{lang}.json").read_text())
        assert d["import.tooManyRequests"] and d["explore.tooManyRequests"]


def test_guest_search_discards_stale_answers_and_shows_error():
    body = _fn(IMPORT_JS, "applyGuestSearch")
    assert "++guestSearchSeq" in body
    assert body.count("seq !== guestSearchSeq") >= 2
    assert "showSearchFailed()" in body
    assert "import.searchFailed" in _fn(IMPORT_JS, "showSearchFailed")


def test_search_field_has_maxlength():
    html = (STATIC / "import.html").read_text()
    assert re.search(r'id="search-input"[^>]*maxlength="200"', html)


def test_other_public_fetches_check_res_ok_and_429():
    for name in ("loadAuthors", "loadTermOverview", "applyAuthorFilter", "applyTermFilter"):
        body = _fn(IMPORT_JS, name)
        assert "res.ok" in body or "Res.ok" in body, name
        assert "showTooManyRequests()" in body, name


def test_search_failed_key_in_both_languages():
    for lang in ("de", "en"):
        assert json.loads((STATIC / "i18n" / f"{lang}.json").read_text())["import.searchFailed"]
