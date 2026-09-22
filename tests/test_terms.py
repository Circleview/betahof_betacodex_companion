from app import terms


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(terms, "TERMS_FILE", tmp_path / "terms.json")


def test_register_term_creates_entry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    terms.register_term("Dezentralisierung", "source-1", "de")

    assert terms.list_terms() == [
        {
            "term": "Dezentralisierung",
            "source_count": 1,
            "source_ids": ["source-1"],
            "langs": ["de"],
        }
    ]


def test_register_term_merges_same_term_different_casing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    terms.register_term("Dezentralisierung", "source-1", "de")
    terms.register_term("dezentralisierung", "source-2", "de")

    result = terms.list_terms()
    assert len(result) == 1
    assert result[0]["source_count"] == 2
    assert set(result[0]["source_ids"]) == {"source-1", "source-2"}


def test_register_term_keeps_first_seen_spelling(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    terms.register_term("BetaCodex", "source-1", "de")
    terms.register_term("betacodex", "source-2", "de")

    assert terms.list_terms()[0]["term"] == "BetaCodex"


def test_register_term_ignores_empty_term(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    terms.register_term("", "source-1", "de")
    terms.register_term("   ", "source-2", "de")

    assert terms.list_terms() == []


def test_register_term_tracks_every_language_it_was_seen_in(tmp_path, monkeypatch):
    # Nutzerwunsch (2026-09-22): Tag-Vorschläge (static/import.js) sollen nur
    # Begriffe der gerade angezeigten Sprache zeigen - dafür muss jeder
    # Begriff wissen, in welcher(n) Sprache(n) er tatsächlich vorkam.
    _isolate(tmp_path, monkeypatch)

    terms.register_term("Agency", "source-1", "de")
    terms.register_term("Agency", "source-2", "en")
    # Erneutes Registrieren derselben Sprache darf sie nicht doppelt eintragen.
    terms.register_term("Agency", "source-3", "de")

    result = terms.list_terms()
    assert len(result) == 1
    assert set(result[0]["langs"]) == {"de", "en"}


def test_unregister_source_removes_from_all_terms(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    terms.register_term("Marktdynamik", "source-1", "de")
    terms.register_term("Selbstorganisation", "source-1", "de")
    terms.register_term("Marktdynamik", "source-2", "de")

    terms.unregister_source("source-1")

    result = {t["term"]: t["source_ids"] for t in terms.list_terms()}
    assert result == {"Marktdynamik": ["source-2"]}


def test_list_terms_sorted_alphabetically(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    terms.register_term("Zelle", "s1", "de")
    terms.register_term("Anders Unternehmen", "s2", "de")

    result = terms.list_terms()
    assert [t["term"] for t in result] == ["Anders Unternehmen", "Zelle"]
