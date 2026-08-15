from app import web_candidates


def test_upsert_candidates_adds_new_pending_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")

    web_candidates.upsert_candidates(
        "entry-1",
        [{"url": "https://a.org/1", "title": "A1", "snippet": "Text.", "relevance_score": 0.5}],
    )

    candidates = web_candidates.candidates_for_entry("entry-1")
    assert len(candidates) == 1
    candidate = list(candidates.values())[0]
    assert candidate["url"] == "https://a.org/1"
    assert candidate["status"] == "pending"


def test_upsert_candidates_updates_score_of_existing_pending_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    web_candidates.upsert_candidates(
        "entry-1",
        [{"url": "https://a.org/1", "title": "A1", "snippet": "Alt.", "relevance_score": 0.3}],
    )

    web_candidates.upsert_candidates(
        "entry-1",
        [{"url": "https://a.org/1", "title": "A1 neu", "snippet": "Neu.", "relevance_score": 0.9}],
    )

    candidates = web_candidates.candidates_for_entry("entry-1")
    assert len(candidates) == 1
    candidate = list(candidates.values())[0]
    assert candidate["relevance_score"] == 0.9
    assert candidate["title"] == "A1 neu"


def test_upsert_candidates_does_not_resurrect_rejected_candidate(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    web_candidates.upsert_candidates(
        "entry-1",
        [{"url": "https://a.org/1", "title": "A1", "snippet": "Text.", "relevance_score": 0.3}],
    )
    candidate_id = next(iter(web_candidates.candidates_for_entry("entry-1")))
    web_candidates.set_status(candidate_id, "rejected")

    web_candidates.upsert_candidates(
        "entry-1",
        [{"url": "https://a.org/1", "title": "A1", "snippet": "Text.", "relevance_score": 0.9}],
    )

    assert web_candidates.candidates_for_entry("entry-1", status="pending") == {}
    assert web_candidates.get_candidate(candidate_id)["status"] == "rejected"


def test_candidates_for_entry_filters_by_entry_and_status(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    web_candidates.upsert_candidates(
        "entry-1", [{"url": "https://a.org/1", "title": "A1", "snippet": "T", "relevance_score": 0.5}]
    )
    web_candidates.upsert_candidates(
        "entry-2", [{"url": "https://b.org/1", "title": "B1", "snippet": "T", "relevance_score": 0.5}]
    )

    entry_1_candidates = web_candidates.candidates_for_entry("entry-1")

    assert len(entry_1_candidates) == 1
    assert list(entry_1_candidates.values())[0]["url"] == "https://a.org/1"


def test_candidates_for_entry_status_none_returns_all_statuses(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    web_candidates.upsert_candidates(
        "entry-1", [{"url": "https://a.org/1", "title": "A1", "snippet": "T", "relevance_score": 0.5}]
    )
    candidate_id = next(iter(web_candidates.candidates_for_entry("entry-1")))
    web_candidates.set_status(candidate_id, "rejected")

    assert len(web_candidates.candidates_for_entry("entry-1", status=None)) == 1
    assert web_candidates.candidates_for_entry("entry-1", status="pending") == {}


def test_get_candidate_returns_none_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    assert web_candidates.get_candidate("unknown") is None


def test_set_status_returns_none_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    assert web_candidates.set_status("unknown", "approved") is None


def test_delete_candidate_removes_it_and_returns_true(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    web_candidates.upsert_candidates(
        "entry-1", [{"url": "https://a.org/1", "title": "A1", "snippet": "T", "relevance_score": 0.5}]
    )
    candidate_id = next(iter(web_candidates.candidates_for_entry("entry-1")))

    assert web_candidates.delete_candidate(candidate_id) is True
    assert web_candidates.get_candidate(candidate_id) is None


def test_delete_candidate_returns_false_for_unknown_id(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    assert web_candidates.delete_candidate("unknown") is False


def test_delete_candidates_for_entry_removes_only_matching_entries(tmp_path, monkeypatch):
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    web_candidates.upsert_candidates(
        "entry-1", [{"url": "https://a.org/1", "title": "A1", "snippet": "T", "relevance_score": 0.5}]
    )
    web_candidates.upsert_candidates(
        "entry-2", [{"url": "https://b.org/1", "title": "B1", "snippet": "T", "relevance_score": 0.5}]
    )

    web_candidates.delete_candidates_for_entry("entry-1")

    assert web_candidates.candidates_for_entry("entry-1", status=None) == {}
    assert len(web_candidates.candidates_for_entry("entry-2", status=None)) == 1
