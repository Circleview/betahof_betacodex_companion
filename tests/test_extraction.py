from unittest.mock import MagicMock, patch

from app.extraction import (
    _parse_markdown_extraction,
    _split_authors,
    download_audio_bytes,
    download_pdf_bytes,
    extract_from_url,
    extract_pdf,
    looks_like_audio,
    looks_like_pdf,
)


def test_split_authors_handles_common_separators():
    assert _split_authors("Jane Doe; John Roe") == ["Jane Doe", "John Roe"]
    assert _split_authors("Jane Doe, John Roe") == ["Jane Doe", "John Roe"]
    assert _split_authors("Jane Doe and John Roe") == ["Jane Doe", "John Roe"]
    assert _split_authors("Jane Doe und John Roe") == ["Jane Doe", "John Roe"]
    assert _split_authors("Jane Doe & John Roe") == ["Jane Doe", "John Roe"]


def test_split_authors_trims_whitespace_and_drops_empty_parts():
    assert _split_authors("  Jane Doe ;; John Roe  ") == ["Jane Doe", "John Roe"]


def test_split_authors_handles_single_author():
    assert _split_authors("Jane Doe") == ["Jane Doe"]


def test_split_authors_handles_empty_string():
    assert _split_authors("") == []
    assert _split_authors("   ") == []


def test_parse_markdown_extraction_splits_multiple_authors():
    raw = (
        "---\n"
        "title: Ein Titel\n"
        "author: Anna Mueller; Ben Schmidt\n"
        "date: 2023-11-20\n"
        "---\n"
        "Text."
    )

    result = _parse_markdown_extraction(raw)

    assert result["authors"] == ["Anna Mueller", "Ben Schmidt"]


def test_parse_markdown_extraction_reads_frontmatter_and_body():
    raw = (
        "---\n"
        "title: Ein Titel: mit Doppelpunkt\n"
        "author: Anna Mueller\n"
        "date: 2023-11-20\n"
        "---\n"
        "# Ein Titel\n\nEin Absatz mit **fettem** Text."
    )

    result = _parse_markdown_extraction(raw)

    assert result["title"] == "Ein Titel: mit Doppelpunkt"
    assert result["authors"] == ["Anna Mueller"]
    assert result["date"] == "2023-11-20"
    assert result["text"] == "# Ein Titel\n\nEin Absatz mit **fettem** Text."


def test_parse_markdown_extraction_without_frontmatter_returns_raw_text():
    result = _parse_markdown_extraction("Nur Fließtext ohne Frontmatter.")

    assert result["title"] == ""
    assert result["authors"] == []
    assert result["date"] == ""
    assert result["text"] == "Nur Fließtext ohne Frontmatter."


def test_extract_from_url_returns_fields_on_success():
    fake_markdown = (
        "---\n"
        "title: Ein Artikel\n"
        "author: Jane Doe\n"
        "date: 2023-01-01\n"
        "---\n"
        "# Ein Artikel\n\n"
        "Artikeltext mit **fettem** Begriff hier.\n\n"
        "## Zwischenueberschrift\n\n"
        "Noch ein Absatz."
    )
    with (
        patch("app.extraction.trafilatura.fetch_url", return_value="<html>...</html>"),
        patch("app.extraction.trafilatura.extract", return_value=fake_markdown),
    ):
        result = extract_from_url("https://example.org/artikel")

    assert result == {
        "title": "Ein Artikel",
        "authors": ["Jane Doe"],
        "date": "2023-01-01",
        "text": (
            "# Ein Artikel\n\n"
            "Artikeltext mit **fettem** Begriff hier.\n\n"
            "## Zwischenueberschrift\n\n"
            "Noch ein Absatz."
        ),
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
    with (
        patch("app.extraction.trafilatura.fetch_url", return_value="<html>...</html>"),
        patch(
            "app.extraction.trafilatura.extract",
            return_value="Nur Text, keine Metadaten.",
        ),
    ):
        result = extract_from_url("https://example.org/ohne-metadaten")

    assert result["extracted"] is True
    assert result["title"] == ""
    assert result["authors"] == []
    assert result["date"] == ""
    assert result["text"] == "Nur Text, keine Metadaten."


def test_extract_from_url_handles_fetch_exception():
    with patch("app.extraction.trafilatura.fetch_url", side_effect=RuntimeError("boom")):
        result = extract_from_url("not-a-valid-url")

    assert result["extracted"] is False


def _fake_pdf_reader(title="", author="", creation_date=None, pages_text=None):
    reader = MagicMock()
    meta = MagicMock()
    meta.title = title
    meta.author = author
    meta.get.return_value = creation_date
    reader.metadata = meta
    pages = []
    for text in pages_text or []:
        page = MagicMock()
        page.extract_text.return_value = text
        pages.append(page)
    reader.pages = pages
    return reader


def test_extract_pdf_returns_metadata_and_text():
    reader = _fake_pdf_reader(
        title="Ein PDF",
        author="Jane Doe",
        creation_date="D:20230115120000+02'00'",
        pages_text=["Seite eins.", "Seite zwei."],
    )
    with patch("app.extraction.PdfReader", return_value=reader):
        result = extract_pdf(b"fake-bytes")

    assert result == {
        "title": "Ein PDF",
        "authors": ["Jane Doe"],
        "date": "2023-01-15",
        "text": "Seite eins.\nSeite zwei.",
        "extracted": True,
    }


def test_extract_pdf_handles_missing_metadata():
    reader = _fake_pdf_reader(pages_text=["Nur Text."])
    with patch("app.extraction.PdfReader", return_value=reader):
        result = extract_pdf(b"fake-bytes")

    assert result["title"] == ""
    assert result["authors"] == []
    assert result["date"] == ""
    assert result["extracted"] is True


def test_extract_pdf_handles_reader_exception():
    with patch("app.extraction.PdfReader", side_effect=RuntimeError("boom")):
        result = extract_pdf(b"not-a-pdf")

    assert result["extracted"] is False


def test_extract_pdf_handles_no_extractable_text():
    reader = _fake_pdf_reader(pages_text=["", ""])
    with patch("app.extraction.PdfReader", return_value=reader):
        result = extract_pdf(b"fake-bytes")

    assert result["extracted"] is False


def test_looks_like_pdf_detects_extension():
    assert looks_like_pdf("https://example.org/paper.pdf") is True
    assert looks_like_pdf("https://example.org/paper.pdf?x=1") is True


def test_looks_like_pdf_checks_content_type_when_no_extension():
    resp = MagicMock()
    resp.headers = {"Content-Type": "application/pdf; charset=binary"}
    resp.__enter__.return_value = resp
    with patch("app.extraction.urllib.request.urlopen", return_value=resp):
        assert looks_like_pdf("https://example.org/download?id=42") is True


def test_looks_like_pdf_false_for_html_content_type():
    resp = MagicMock()
    resp.headers = {"Content-Type": "text/html"}
    resp.__enter__.return_value = resp
    with patch("app.extraction.urllib.request.urlopen", return_value=resp):
        assert looks_like_pdf("https://example.org/artikel") is False


def test_looks_like_pdf_returns_false_on_network_error():
    with patch("app.extraction.urllib.request.urlopen", side_effect=RuntimeError("boom")):
        assert looks_like_pdf("https://example.org/nope") is False


def test_download_pdf_bytes_returns_content():
    resp = MagicMock()
    resp.read.return_value = b"%PDF-1.4..."
    resp.__enter__.return_value = resp
    with patch("app.extraction.urllib.request.urlopen", return_value=resp):
        assert download_pdf_bytes("https://example.org/paper.pdf") == b"%PDF-1.4..."


def test_download_pdf_bytes_returns_none_on_error():
    with patch("app.extraction.urllib.request.urlopen", side_effect=RuntimeError("boom")):
        assert download_pdf_bytes("https://example.org/paper.pdf") is None


def test_extract_from_url_routes_pdf_to_pdf_extractor():
    reader = _fake_pdf_reader(title="PDF-Titel", pages_text=["Inhalt."])
    with (
        patch("app.extraction.looks_like_pdf", return_value=True),
        patch("app.extraction.download_pdf_bytes", return_value=b"%PDF-1.4..."),
        patch("app.extraction.PdfReader", return_value=reader),
    ):
        result = extract_from_url("https://example.org/paper.pdf")

    assert result["extracted"] is True
    assert result["title"] == "PDF-Titel"


def test_extract_from_url_reports_failure_when_pdf_download_fails():
    with (
        patch("app.extraction.looks_like_pdf", return_value=True),
        patch("app.extraction.download_pdf_bytes", return_value=None),
    ):
        result = extract_from_url("https://example.org/paper.pdf")

    assert result["extracted"] is False


def test_looks_like_audio_detects_extension():
    assert looks_like_audio("https://example.org/episode.mp3") is True
    assert looks_like_audio("https://example.org/episode.mp3?x=1") is True


def test_looks_like_audio_checks_content_type_when_no_extension():
    resp = MagicMock()
    resp.headers = {"Content-Type": "audio/mpeg"}
    resp.__enter__.return_value = resp
    with patch("app.extraction.urllib.request.urlopen", return_value=resp):
        assert looks_like_audio("https://example.org/download?id=42") is True


def test_looks_like_audio_false_for_html_content_type():
    resp = MagicMock()
    resp.headers = {"Content-Type": "text/html"}
    resp.__enter__.return_value = resp
    with patch("app.extraction.urllib.request.urlopen", return_value=resp):
        assert looks_like_audio("https://example.org/artikel") is False


def test_download_audio_bytes_returns_content():
    resp = MagicMock()
    resp.read.return_value = b"ID3-fake-mp3-data"
    resp.__enter__.return_value = resp
    with patch("app.extraction.urllib.request.urlopen", return_value=resp):
        assert download_audio_bytes("https://example.org/episode.mp3") == b"ID3-fake-mp3-data"


def test_download_audio_bytes_returns_none_on_error():
    with patch("app.extraction.urllib.request.urlopen", side_effect=RuntimeError("boom")):
        assert download_audio_bytes("https://example.org/episode.mp3") is None


def test_extract_from_url_routes_audio_to_manual_fallback():
    result = extract_from_url("https://example.org/podcast/folge-42-ueber-dezentralisierung.mp3")

    assert result["extracted"] is False
    assert result["text"] == ""
    assert result["title"] == "Folge 42 ueber dezentralisierung"
