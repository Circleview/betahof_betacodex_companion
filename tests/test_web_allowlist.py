from app import web_allowlist, web_index


def test_add_entry_sets_reviewed_at_to_added_at(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")

    entry = web_allowlist.add_entry(
        url_prefix="https://beispiel.org/blog",
        label="Beispiel-Blog",
        reason="BetaCodex-nahe Redaktion.",
        added_by="admin@test.local",
        added_at="2026-01-01T00:00:00+00:00",
        max_pages=30,
    )

    assert entry["reviewed_at"] == "2026-01-01T00:00:00+00:00"
    assert entry["max_pages"] == 30
    assert "id" in entry


def test_list_entries_returns_all_added_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")

    web_allowlist.add_entry(
        url_prefix="https://a.org", label="A", reason="R", added_by="x", added_at="2026-01-01T00:00:00+00:00"
    )
    web_allowlist.add_entry(
        url_prefix="https://b.org", label="B", reason="R", added_by="x", added_at="2026-01-01T00:00:00+00:00"
    )

    entries = web_allowlist.list_entries()

    assert len(entries) == 2
    assert {e["url_prefix"] for e in entries.values()} == {"https://a.org", "https://b.org"}


def test_get_entry_returns_none_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    assert web_allowlist.get_entry("unknown") is None


def test_delete_entry_removes_it_and_returns_true(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://a.org", label="A", reason="R", added_by="x", added_at="2026-01-01T00:00:00+00:00"
    )

    deleted = web_allowlist.delete_entry(entry["id"])

    assert deleted is True
    assert web_allowlist.list_entries() == {}


def test_delete_entry_returns_false_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    assert web_allowlist.delete_entry("unknown") is False


def test_mark_reviewed_updates_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://a.org", label="A", reason="R", added_by="x", added_at="2020-01-01T00:00:00+00:00"
    )

    updated = web_allowlist.mark_reviewed(entry["id"], "2026-01-01T00:00:00+00:00")

    assert updated["reviewed_at"] == "2026-01-01T00:00:00+00:00"


def test_mark_reviewed_returns_none_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    assert web_allowlist.mark_reviewed("unknown", "2026-01-01T00:00:00+00:00") is None


def test_set_indexing_status_updates_status(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://a.org", label="A", reason="R", added_by="x", added_at="2020-01-01T00:00:00+00:00"
    )

    running = web_allowlist.set_indexing_status(entry["id"], "running")
    assert running["indexing_status"] == "running"

    done = web_allowlist.set_indexing_status(entry["id"], None)
    assert done["indexing_status"] is None


def test_set_indexing_status_returns_none_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    assert web_allowlist.set_indexing_status("unknown", "running") is None


def test_add_entry_defaults_selection_mode_to_negativ(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://a.org", label="A", reason="R", added_by="x", added_at="2020-01-01T00:00:00+00:00"
    )
    assert entry["selection_mode"] == "negativ"


def test_set_selection_mode_updates_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://a.org", label="A", reason="R", added_by="x", added_at="2020-01-01T00:00:00+00:00"
    )

    updated = web_allowlist.set_selection_mode(entry["id"], "positiv")

    assert updated["selection_mode"] == "positiv"


def test_set_selection_mode_returns_none_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    assert web_allowlist.set_selection_mode("unknown", "positiv") is None


def test_web_index_upsert_page_stores_date_and_defaults_excluded_to_false(tmp_path, monkeypatch):
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id="entry-a",
        url="https://a.org/1",
        title="A1",
        date="2026-01-01",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=2,
    )

    page = web_index.get_page("page-1")

    assert page["date"] == "2026-01-01"
    assert page["excluded"] is False


def test_web_index_set_excluded_toggles_flag(tmp_path, monkeypatch):
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id="entry-a",
        url="https://a.org/1",
        title="A1",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=2,
    )

    excluded = web_index.set_excluded("page-1", True)
    assert excluded["excluded"] is True

    included = web_index.set_excluded("page-1", False)
    assert included["excluded"] is False


def test_web_index_set_excluded_returns_none_for_unknown_page(tmp_path, monkeypatch):
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    assert web_index.set_excluded("unknown", True) is None


def test_web_index_excluded_page_ids_returns_only_excluded(tmp_path, monkeypatch):
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id="entry-a",
        url="https://a.org/1",
        title="A1",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )
    web_index.upsert_page(
        "page-2",
        allowlist_entry_id="entry-a",
        url="https://a.org/2",
        title="A2",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )
    web_index.set_excluded("page-2", True)

    assert web_index.excluded_page_ids() == {"page-2"}


def test_web_index_active_page_count_for_entry_excludes_excluded_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id="entry-a",
        url="https://a.org/1",
        title="A1",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )
    web_index.upsert_page(
        "page-2",
        allowlist_entry_id="entry-a",
        url="https://a.org/2",
        title="A2",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )
    web_index.set_excluded("page-2", True)

    assert web_index.active_page_count_for_entry("entry-a") == 1


def test_web_index_pages_for_entry_filters_by_allowlist_entry_id(tmp_path, monkeypatch):
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id="entry-a",
        url="https://a.org/1",
        title="A1",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=2,
    )
    web_index.upsert_page(
        "page-2",
        allowlist_entry_id="entry-b",
        url="https://b.org/1",
        title="B1",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )

    pages = web_index.pages_for_entry("entry-a")

    assert list(pages.keys()) == ["page-1"]


def test_web_index_delete_pages_for_entry_removes_only_matching_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id="entry-a",
        url="https://a.org/1",
        title="A1",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=2,
    )
    web_index.upsert_page(
        "page-2",
        allowlist_entry_id="entry-b",
        url="https://b.org/1",
        title="B1",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )

    removed_ids = web_index.delete_pages_for_entry("entry-a")

    assert removed_ids == ["page-1"]
    assert web_index.get_page("page-1") is None
    assert web_index.get_page("page-2") is not None
