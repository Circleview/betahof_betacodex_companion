import json

from app import audit


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_LOG_FILE", tmp_path / "audit_log.json")


def test_log_change_creates_revertible_entry_with_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    entry = audit.log_change(
        "lena@test.local", "source_updated", "source", "src-1", "Titel", {"title": {"old": "Alt", "new": "Neu"}}
    )

    assert entry["id"]
    assert entry["revertible"] is True
    assert entry["reverted_at"] is None
    assert entry["changes"] == {"title": {"old": "Alt", "new": "Neu"}}


def test_log_action_creates_non_revertible_entry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    entry = audit.log_action("lena@test.local", "source_created", "source", "src-1", "Titel")

    assert entry["revertible"] is False
    assert entry["changes"] is None


def test_list_entries_returns_newest_first(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    audit.log_action("lena@test.local", "source_created", "source", "src-1", "Erste")
    audit.log_action("lena@test.local", "source_created", "source", "src-2", "Zweite")

    entries = audit.list_entries()

    assert [e["target_label"] for e in entries] == ["Zweite", "Erste"]


def test_get_entry_finds_by_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    created = audit.log_change(
        "lena@test.local", "source_updated", "source", "src-1", "Titel", {"title": {"old": "Alt", "new": "Neu"}}
    )

    found = audit.get_entry(created["id"])

    assert found is not None
    assert found["target_label"] == "Titel"


def test_get_entry_returns_none_for_unknown_id(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert audit.get_entry("does-not-exist") is None


def test_mark_reverted_sets_timestamp(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    created = audit.log_change(
        "lena@test.local", "source_updated", "source", "src-1", "Titel", {"title": {"old": "Alt", "new": "Neu"}}
    )

    audit.mark_reverted(created["id"])

    assert audit.get_entry(created["id"])["reverted_at"] is not None


def test_legacy_entry_without_new_fields_gets_safe_defaults(tmp_path, monkeypatch):
    # Bestandsschutz: vor Backlog #99 geschriebene Einträge kennen weder id
    # noch changes/revertible - list_entries() darf daran nicht scheitern
    # und muss sie als nicht rückgängig machbar behandeln.
    log_file = tmp_path / "audit_log.json"
    monkeypatch.setattr(audit, "AUDIT_LOG_FILE", log_file)
    log_file.write_text(
        json.dumps(
            [{"timestamp": "2026-01-01T00:00:00+00:00", "actor_email": "lena@test.local",
              "action": "source_created", "target_label": "Alte Quelle"}]
        )
    )

    entries = audit.list_entries()

    assert len(entries) == 1
    assert entries[0]["id"]
    assert entries[0]["revertible"] is False
    assert entries[0]["changes"] is None
