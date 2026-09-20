import json

import pytest

from app import jsonstore


def test_load_returns_default_when_file_is_missing(tmp_path):
    assert jsonstore.load(tmp_path / "nope.json", {"a": 1}) == {"a": 1}


def test_save_then_load_roundtrip_creates_parent_dir_and_leaves_no_temp_file(tmp_path):
    path = tmp_path / "sub" / "data.json"
    jsonstore.save(path, {"ä": [1, 2]})

    assert jsonstore.load(path, {}) == {"ä": [1, 2]}
    assert "ä" in path.read_text()  # ensure_ascii=False
    assert [p.name for p in path.parent.iterdir()] == ["data.json"]


def test_corrupt_file_raises_by_default_but_returns_default_when_tolerant(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json")

    with pytest.raises(json.JSONDecodeError):
        jsonstore.load(path, {})
    assert jsonstore.load(path, {}, tolerant=True) == {}
