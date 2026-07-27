import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import extraction
from app.extraction import (
    _extract_youtube,
    _parse_markdown_extraction,
    _split_authors,
    _transcribe_chunk,
    download_audio_bytes,
    download_pdf_bytes,
    extract_from_url,
    extract_pdf,
    looks_like_audio,
    looks_like_pdf,
    split_audio_file,
    transcribe_audio,
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


def test_extract_from_url_routes_audio_to_manual_fallback_without_downloading():
    # Transkription kann Minuten dauern und darf deshalb NICHT bei der
    # Vorschau (extract_from_url) passieren, sondern erst als Hintergrund-
    # Job nach dem Anlegen der Quelle (app/main.py:
    # _process_audio_transcription) - hier darf also gar nicht erst
    # heruntergeladen/transkribiert werden.
    with patch("app.extraction.download_audio_bytes") as mock_download, \
         patch("app.extraction.transcribe_audio") as mock_transcribe:
        result = extract_from_url("https://example.org/podcast/folge-42-ueber-dezentralisierung.mp3")

    mock_download.assert_not_called()
    mock_transcribe.assert_not_called()
    assert result["extracted"] is False
    assert result["text"] == ""
    assert result["title"] == "Folge 42 ueber dezentralisierung"


def _fake_transcript_segment(start, text):
    segment = MagicMock()
    segment.start = start
    segment.text = text
    return segment


def test_extract_youtube_returns_flowing_text_without_timestamps():
    segments = [
        _fake_transcript_segment(0.0, "Hallo und willkommen"),
        _fake_transcript_segment(3.5, "zu diesem Video."),
        _fake_transcript_segment(7.0, "Heute geht es um Beta."),
    ]
    fake_api = MagicMock()
    fake_api.fetch.return_value = segments
    with (
        patch("app.extraction.YouTubeTranscriptApi", return_value=fake_api),
        patch(
            "app.extraction._fetch_youtube_metadata",
            return_value={"title": "Ein Video", "date": "2024-01-01"},
        ),
    ):
        result = _extract_youtube("https://www.youtube.com/watch?v=abc123")

    assert result["extracted"] is True
    assert result["title"] == "Ein Video"
    assert result["date"] == "2024-01-01"
    assert result["authors"] == []
    assert result["text"] == "Hallo und willkommen zu diesem Video. Heute geht es um Beta."
    assert "[" not in result["text"]


def test_extract_youtube_falls_back_to_transcript_list_when_fetch_fails():
    transcript = MagicMock()
    transcript.fetch.return_value = [_fake_transcript_segment(0.0, "Fallback-Text.")]
    fake_api = MagicMock()
    fake_api.fetch.side_effect = Exception("keine deutsche/englische Spur verfügbar")
    fake_api.list.return_value = [transcript]
    with (
        patch("app.extraction.YouTubeTranscriptApi", return_value=fake_api),
        patch(
            "app.extraction._fetch_youtube_metadata",
            return_value={"title": "", "date": ""},
        ),
    ):
        result = _extract_youtube("https://youtu.be/abc123")

    assert result["extracted"] is True
    assert result["text"] == "Fallback-Text."


def test_extract_youtube_handles_missing_video_id():
    result = _extract_youtube("https://www.youtube.com/")

    assert result["extracted"] is False
    assert result["text"] == ""


def test_extract_youtube_handles_transcript_fetch_failure():
    fake_api = MagicMock()
    fake_api.fetch.side_effect = Exception("boom")
    fake_api.list.side_effect = Exception("boom")
    with patch("app.extraction.YouTubeTranscriptApi", return_value=fake_api):
        result = _extract_youtube("https://www.youtube.com/watch?v=abc123")

    assert result["extracted"] is False


def _fake_diarized_result(pairs):
    segments = []
    for speaker, text in pairs:
        segment = MagicMock()
        segment.speaker = speaker
        segment.text = text
        segments.append(segment)
    result = MagicMock()
    result.segments = segments
    return result


def test_transcribe_chunk_uses_diarize_model_and_formats_speakers():
    client = MagicMock()
    client.audio.transcriptions.create.return_value = _fake_diarized_result(
        [("A", "Hallo zusammen."), ("B", "Hallo, schön hier zu sein."), ("A", "Wie geht's dir?")]
    )
    with patch.object(extraction, "_get_openai_client", return_value=client):
        text = _transcribe_chunk(b"fake-mp3-bytes", "episode.mp3")

    assert text == "Sprecher 1: Hallo zusammen.\n\nSprecher 2: Hallo, schön hier zu sein.\n\nSprecher 1: Wie geht's dir?"
    kwargs = client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-transcribe-diarize"
    assert kwargs["response_format"] == "diarized_json"
    assert kwargs["chunking_strategy"] == "auto"


def test_transcribe_chunk_falls_back_to_whisper_for_flac():
    client = MagicMock()
    client.audio.transcriptions.create.return_value = "Ein einfaches Transkript."
    with patch.object(extraction, "_get_openai_client", return_value=client):
        text = _transcribe_chunk(b"fake-flac-bytes", "aufnahme.flac")

    assert text == "Ein einfaches Transkript."
    kwargs = client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["model"] == "whisper-1"
    assert kwargs["response_format"] == "text"


def test_transcribe_chunk_returns_empty_string_on_error():
    client = MagicMock()
    client.audio.transcriptions.create.side_effect = RuntimeError("boom")
    with patch.object(extraction, "_get_openai_client", return_value=client):
        text = _transcribe_chunk(b"fake-bytes", "episode.mp3")

    assert text == ""


def test_split_audio_file_returns_original_path_when_under_limit(tmp_path):
    audio_path = tmp_path / "small.mp3"
    audio_path.write_bytes(b"x" * 100)

    with patch("app.extraction.subprocess.run") as mock_run:
        result = split_audio_file(audio_path, max_bytes=1000)

    assert result == [audio_path]
    mock_run.assert_not_called()


def test_split_audio_file_splits_when_over_limit(tmp_path):
    audio_path = tmp_path / "big.mp3"
    audio_path.write_bytes(b"x" * 2000)
    split_dir = tmp_path / "split"
    split_dir.mkdir()

    def fake_run(cmd, **kwargs):
        (split_dir / "chunk_000.mp3").write_bytes(b"a")
        (split_dir / "chunk_001.mp3").write_bytes(b"b")
        return MagicMock()

    with patch("app.extraction._audio_duration_seconds", return_value=120.0), \
         patch("app.extraction.tempfile.mkdtemp", return_value=str(split_dir)), \
         patch("app.extraction.subprocess.run", side_effect=fake_run) as mock_run:
        result = split_audio_file(audio_path, max_bytes=1000)

    assert mock_run.called
    assert sorted(p.name for p in result) == ["chunk_000.mp3", "chunk_001.mp3"]


def test_split_audio_file_returns_original_on_ffmpeg_failure(tmp_path):
    audio_path = tmp_path / "big.mp3"
    audio_path.write_bytes(b"x" * 2000)

    with patch("app.extraction._audio_duration_seconds", return_value=120.0), \
         patch("app.extraction.subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
        result = split_audio_file(audio_path, max_bytes=1000)

    assert result == [audio_path]


def test_split_audio_file_returns_original_when_duration_unknown(tmp_path):
    audio_path = tmp_path / "big.mp3"
    audio_path.write_bytes(b"x" * 2000)

    with patch("app.extraction._audio_duration_seconds", return_value=None):
        result = split_audio_file(audio_path, max_bytes=1000)

    assert result == [audio_path]


def test_transcribe_audio_returns_single_chunk_text_unchanged(tmp_path):
    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"fake-bytes")

    with patch.object(extraction, "split_audio_file", return_value=[audio_path]), \
         patch.object(extraction, "_transcribe_chunk", return_value="Nur ein Teil."):
        text = transcribe_audio(audio_path)

    assert text == "Nur ein Teil."


def test_transcribe_audio_concatenates_multiple_segments_with_part_markers(tmp_path):
    split_dir = tmp_path / "split"
    split_dir.mkdir()
    chunk_a = split_dir / "chunk_000.mp3"
    chunk_b = split_dir / "chunk_001.mp3"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")

    with patch.object(extraction, "split_audio_file", return_value=[chunk_a, chunk_b]), \
         patch.object(extraction, "_transcribe_chunk", side_effect=["Text A", "Text B"]):
        text = transcribe_audio(tmp_path / "original.mp3")

    assert text == "--- Teil 1 ---\n\nText A\n\n--- Teil 2 ---\n\nText B"
    assert not split_dir.exists()
