import json
from unittest.mock import patch

from app.extraction import extract_from_url


def test_extract_from_url_returns_fields_on_success():
    fake_json = json.dumps(
        {
            "title": "Ein Artikel",
            "author": "Jane Doe",
            "date": "2023-01-01",
            "text": "Artikeltext hier.",
        }
    )
    with (
        patch("app.extraction.trafilatura.fetch_url", return_value="<html>...</html>"),
        patch("app.extraction.trafilatura.extract", return_value=fake_json),
    ):
        result = extract_from_url("https://example.org/artikel")

    assert result == {
        "title": "Ein Artikel",
        "author": "Jane Doe",
        "date": "2023-01-01",
        "text": "Artikeltext hier.",
        "extracted": True,
    }


def test_extract_from_url_handles_fetch_failure():
    with patch("app.extraction.trafilatura.fetch_url", return_value=None):
        result = extract_from_url("https://example.org/nicht-erreichbar")

    assert result["extracted"] is False
    assert result["text"] == ""


def test_extract_from_url_handles_empty_extraction():
    with (
        patch("app.extraction.trafilatura.fetch_url", return_value="<html></html>"),
        patch("app.extraction.trafilatura.extract", return_value=None),
    ):
        result = extract_from_url("https://example.org/leer")

    assert result["extracted"] is False


def test_extract_from_url_handles_missing_metadata_fields():
    fake_json = json.dumps({"text": "Nur Text, keine Metadaten."})
    with (
        patch("app.extraction.trafilatura.fetch_url", return_value="<html>...</html>"),
        patch("app.extraction.trafilatura.extract", return_value=fake_json),
    ):
        result = extract_from_url("https://example.org/ohne-metadaten")

    assert result["extracted"] is True
    assert result["title"] == ""
    assert result["author"] == ""
    assert result["date"] == ""


def test_extract_from_url_handles_fetch_exception():
    with patch("app.extraction.trafilatura.fetch_url", side_effect=RuntimeError("boom")):
        result = extract_from_url("not-a-valid-url")

    assert result["extracted"] is False
