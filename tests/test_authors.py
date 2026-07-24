from app import authors


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(authors, "AUTHORS_FILE", tmp_path / "authors.json")


def test_register_author_creates_entry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    authors.register_author("Niels Pfläging", "source-1")

    assert authors.list_authors() == [
        {"name": "Niels Pfläging", "source_count": 1, "source_ids": ["source-1"]}
    ]


def test_register_author_merges_same_author_different_casing_and_whitespace(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    authors.register_author("Niels Pfläging", "source-1")
    authors.register_author("niels   pfläging", "source-2")

    result = authors.list_authors()
    assert len(result) == 1
    assert result[0]["source_count"] == 2
    assert set(result[0]["source_ids"]) == {"source-1", "source-2"}


def test_register_author_keeps_first_seen_spelling(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    authors.register_author("Niels Pfläging", "source-1")
    authors.register_author("niels   pfläging", "source-2")

    assert authors.list_authors()[0]["name"] == "Niels Pfläging"


def test_register_author_ignores_empty_name(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    authors.register_author("", "source-1")
    authors.register_author("   ", "source-2")

    assert authors.list_authors() == []


def test_register_author_does_not_duplicate_same_source(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    authors.register_author("Jane Doe", "source-1")
    authors.register_author("Jane Doe", "source-1")

    assert authors.list_authors()[0]["source_count"] == 1


def test_unregister_source_removes_source_from_author(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    authors.register_author("Jane Doe", "source-1")
    authors.register_author("Jane Doe", "source-2")

    authors.unregister_source("source-1")

    result = authors.list_authors()
    assert result[0]["source_ids"] == ["source-2"]


def test_unregister_source_removes_author_entirely_when_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    authors.register_author("Jane Doe", "source-1")
    authors.unregister_source("source-1")

    assert authors.list_authors() == []


def test_unregister_source_is_noop_for_unknown_source(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    authors.register_author("Jane Doe", "source-1")
    authors.unregister_source("unknown-source")

    assert authors.list_authors()[0]["source_ids"] == ["source-1"]


def test_list_authors_sorted_alphabetically(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    authors.register_author("Zora Zeisig", "s1")
    authors.register_author("Anna Adler", "s2")
    authors.register_author("moritz mueller", "s3")

    result = authors.list_authors()
    assert [a["name"] for a in result] == ["Anna Adler", "moritz mueller", "Zora Zeisig"]
