import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import openai

from app import extraction
from app.extraction import (
    _extract_youtube,
    _parse_markdown_extraction,
    _split_authors,
    _transcribe_chunk_once,
    _transcribe_chunk_with_retries,
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


def test_extract_pdf_handles_unresolved_creation_date():
    # Regressionstest: bei PDFs mit beschädigter Xref-Tabelle (reales
    # Beispiel: betacodex.org-Whitepaper mit vielen "Ignoring wrong pointing
    # object"-Warnungen von pypdf) liefert meta.get("/CreationDate")
    # gelegentlich ein IndirectObject statt eines Strings - das crashte
    # _parse_pdf_date mit TypeError und riss den gesamten Extraktions-Request
    # mit sich, obwohl der eigentliche Seitentext problemlos lesbar war.
    reader = _fake_pdf_reader(
        title="Ein PDF", author="Jane Doe", creation_date=object(), pages_text=["Seite eins."]
    )
    with patch("app.extraction.PdfReader", return_value=reader):
        result = extract_pdf(b"fake-bytes")

    assert result["extracted"] is True
    assert result["date"] == ""
    assert result["text"] == "Seite eins."


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


def _fake_anthropic_message(text):
    block = MagicMock()
    block.text = text
    message = MagicMock()
    message.content = [block]
    return message


def test_render_pdf_pages_to_images_returns_one_png_per_page():
    import fitz

    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    data = doc.tobytes()
    doc.close()

    images = extraction._render_pdf_pages_to_images(data)

    assert len(images) == 2
    assert all(img.startswith(b"\x89PNG") for img in images)


def test_ocr_page_returns_transcribed_text():
    client = MagicMock()
    client.messages.create.return_value = _fake_anthropic_message("Erkannter Seitentext.")
    with patch.object(extraction, "_get_anthropic_client", return_value=client):
        text = extraction._ocr_page(b"fake-png-bytes")

    assert text == "Erkannter Seitentext."
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["model"] == extraction._OCR_MODEL_NAME
    content_block = kwargs["messages"][0]["content"][0]
    assert content_block["type"] == "image"


def test_ocr_page_returns_empty_string_on_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    with patch.object(extraction, "_get_anthropic_client", return_value=client):
        text = extraction._ocr_page(b"fake-png-bytes")

    assert text == ""


def test_ocr_pdf_with_ai_concatenates_page_texts():
    with (
        patch.object(extraction, "_render_pdf_pages_to_images", return_value=[b"page1", b"page2"]),
        patch.object(extraction, "_ocr_page", side_effect=["Seite eins.", "Seite zwei."]),
    ):
        text = extraction.ocr_pdf_with_ai(b"fake-pdf-bytes")

    assert text == "Seite eins.\n\nSeite zwei."


def test_ocr_pdf_with_ai_skips_pages_without_text():
    with (
        patch.object(extraction, "_render_pdf_pages_to_images", return_value=[b"page1", b"page2"]),
        patch.object(extraction, "_ocr_page", side_effect=["Seite eins.", ""]),
    ):
        text = extraction.ocr_pdf_with_ai(b"fake-pdf-bytes")

    assert text == "Seite eins."


def test_ocr_pdf_with_ai_returns_empty_string_when_rendering_fails():
    with patch.object(extraction, "_render_pdf_pages_to_images", side_effect=RuntimeError("boom")):
        text = extraction.ocr_pdf_with_ai(b"not-a-pdf")

    assert text == ""


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
    with (
        patch("app.extraction.YouTubeTranscriptApi", return_value=fake_api),
        patch("app.extraction._fetch_youtube_metadata", return_value={"title": "", "date": ""}),
    ):
        result = _extract_youtube("https://www.youtube.com/watch?v=abc123")

    assert result["extracted"] is False


def test_extract_youtube_still_fills_metadata_when_transcript_is_blocked():
    """Regression-Schutz (2026-08-03): auf Produktion (Cloud-IP) blockiert
    YouTube automatisierte Transkript-Anfragen (RequestBlocked) - Titel und
    Datum kommen aus einer davon unabhaengigen Anfrage und sollen trotzdem
    ankommen, statt durch den fruehen Abbruch verloren zu gehen."""
    fake_api = MagicMock()
    fake_api.fetch.side_effect = Exception("RequestBlocked: YouTube is blocking requests from your IP")
    fake_api.list.side_effect = Exception("RequestBlocked: YouTube is blocking requests from your IP")
    with (
        patch("app.extraction.YouTubeTranscriptApi", return_value=fake_api),
        patch(
            "app.extraction._fetch_youtube_metadata",
            return_value={"title": "Ein Video", "date": "2024-01-01"},
        ),
    ):
        result = _extract_youtube("https://www.youtube.com/watch?v=abc123")

    assert result["extracted"] is False
    assert result["text"] == ""
    assert result["title"] == "Ein Video"
    assert result["date"] == "2024-01-01"


def _fake_rate_limit_error() -> openai.RateLimitError:
    response = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions"))
    return openai.RateLimitError("zu viele Anfragen", response=response, body=None)


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
        text = _transcribe_chunk_once(b"fake-mp3-bytes", "episode.mp3")

    assert text == "Sprecher 1: Hallo zusammen.\n\nSprecher 2: Hallo, schön hier zu sein.\n\nSprecher 1: Wie geht's dir?"
    kwargs = client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-transcribe-diarize"
    assert kwargs["response_format"] == "diarized_json"
    assert kwargs["chunking_strategy"] == "auto"


def test_transcribe_chunk_falls_back_to_whisper_for_flac():
    client = MagicMock()
    client.audio.transcriptions.create.return_value = "Ein einfaches Transkript."
    with patch.object(extraction, "_get_openai_client", return_value=client):
        text = _transcribe_chunk_once(b"fake-flac-bytes", "aufnahme.flac")

    assert text == "Ein einfaches Transkript."
    kwargs = client.audio.transcriptions.create.call_args.kwargs
    assert kwargs["model"] == "whisper-1"
    assert kwargs["response_format"] == "text"


def test_transcribe_chunk_once_raises_on_error_instead_of_swallowing():
    # Bug vom 2026-07-29: _transcribe_chunk verschluckte jeden Fehler und
    # lieferte "" zurück - dadurch verschwand ein gescheiterter Abschnitt
    # einfach spurlos aus dem Ergebnis, statt die Verarbeitung als
    # gescheitert zu markieren. _transcribe_chunk_once lässt Exceptions
    # deshalb jetzt bewusst durch - die Fehlerbehandlung/-klassifikation
    # übernimmt _transcribe_chunk_with_retries.
    client = MagicMock()
    client.audio.transcriptions.create.side_effect = RuntimeError("boom")
    with patch.object(extraction, "_get_openai_client", return_value=client):
        try:
            _transcribe_chunk_once(b"fake-bytes", "episode.mp3")
            assert False, "sollte RuntimeError weiterreichen"
        except RuntimeError as exc:
            assert str(exc) == "boom"


def test_transcribe_chunk_with_retries_gives_up_immediately_on_non_retryable_error(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(extraction.time, "sleep", lambda s: sleep_calls.append(s))
    with patch.object(extraction, "_transcribe_chunk_once", side_effect=RuntimeError("kaputte Datei")):
        text, detail = _transcribe_chunk_with_retries(b"data", "episode.mp3", duration_seconds=60)

    assert text == ""
    assert "RuntimeError" in detail and "kaputte Datei" in detail
    assert sleep_calls == []  # kein Wiederholungsversuch bei nicht-vorübergehendem Fehler


def test_transcribe_chunk_with_retries_retries_and_succeeds_on_rate_limit(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr(extraction.time, "sleep", lambda s: sleep_calls.append(s))
    rate_limit_error = _fake_rate_limit_error()
    with patch.object(
        extraction, "_transcribe_chunk_once", side_effect=[rate_limit_error, "Erfolgreich beim 2. Versuch."]
    ):
        # duration_seconds=None: dieser Test prüft gezielt die Wiederholung
        # bei Fehlern, nicht die separate Plausibilitätsprüfung der
        # Textlänge (siehe test_..._treats_suspiciously_short_result...).
        text, detail = _transcribe_chunk_with_retries(b"data", "episode.mp3", duration_seconds=None)

    assert text == "Erfolgreich beim 2. Versuch."
    assert detail is None
    assert sleep_calls == [extraction._SEGMENT_RETRY_DELAYS_SECONDS[0]]


def test_transcribe_chunk_with_retries_gives_up_after_exhausting_retryable_attempts(monkeypatch):
    monkeypatch.setattr(extraction.time, "sleep", lambda s: None)
    rate_limit_error = _fake_rate_limit_error()
    with patch.object(extraction, "_transcribe_chunk_once", side_effect=rate_limit_error):
        text, detail = _transcribe_chunk_with_retries(b"data", "episode.mp3", duration_seconds=60)

    assert text == ""
    assert "RateLimitError" in detail


def test_transcribe_chunk_with_retries_treats_suspiciously_short_result_as_failure(monkeypatch):
    # Der eigentliche Auslöser der Umstrukturierung (2026-07-29): OpenAI
    # kann ohne jede Fehlermeldung ein fast leeres Ergebnis liefern - ohne
    # diese Prüfung würde das stillschweigend als Erfolg durchgehen.
    monkeypatch.setattr(extraction.time, "sleep", lambda s: None)
    with patch.object(extraction, "_transcribe_chunk_once", return_value="Nur ein paar Wörter."):
        text, detail = _transcribe_chunk_with_retries(b"data", "episode.mp3", duration_seconds=20 * 60)

    assert text == ""
    assert "auffällig kurz" in detail


def test_transcribe_chunk_with_retries_accepts_short_result_without_known_duration(monkeypatch):
    # Ohne Dauer (z.B. ffprobe konnte sie nicht ermitteln) lässt sich keine
    # Plausibilitätsgrenze berechnen - dann lieber kein falscher Alarm.
    with patch.object(extraction, "_transcribe_chunk_once", return_value="Kurz."):
        text, detail = _transcribe_chunk_with_retries(b"data", "episode.mp3", duration_seconds=None)

    assert text == "Kurz."
    assert detail is None


def test_split_audio_file_returns_original_path_when_under_limit(tmp_path):
    audio_path = tmp_path / "small.mp3"
    audio_path.write_bytes(b"x" * 100)

    # _audio_duration_seconds wird jetzt auch für Dateien unter dem
    # Größenlimit aufgerufen (siehe MAX_DIARIZE_DURATION_SECONDS) - hier
    # direkt gemockt, damit die anschließende subprocess.run-Prüfung
    # eindeutig nur den (nicht stattfindenden) eigentlichen Aufteilungs-Aufruf
    # betrifft, nicht den Dauer-Check selbst.
    with (
        patch("app.extraction._audio_duration_seconds", return_value=60.0),
        patch("app.extraction.subprocess.run") as mock_run,
    ):
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


def test_split_audio_file_splits_on_duration_even_when_under_size_limit(tmp_path):
    # Regressionstest: gpt-4o-transcribe-diarize lehnt Dateien über
    # MAX_DIARIZE_DURATION_SECONDS unabhängig von der Byte-Größe ab - eine
    # reale, nur 20MB große, aber 24,5-minütige Episode blieb bisher
    # unter AUDIO_UPLOAD_MAX_BYTES und wurde deshalb NIE aufgeteilt, obwohl
    # die Transkription am separaten Dauerlimit scheiterte.
    audio_path = tmp_path / "long-but-small.mp3"
    audio_path.write_bytes(b"x" * 100)
    split_dir = tmp_path / "split"
    split_dir.mkdir()

    def fake_run(cmd, **kwargs):
        (split_dir / "chunk_000.mp3").write_bytes(b"a")
        (split_dir / "chunk_001.mp3").write_bytes(b"b")
        return MagicMock()

    with (
        patch("app.extraction._audio_duration_seconds", return_value=1468.0),
        patch("app.extraction.tempfile.mkdtemp", return_value=str(split_dir)),
        patch("app.extraction.subprocess.run", side_effect=fake_run) as mock_run,
    ):
        result = split_audio_file(audio_path, max_bytes=extraction.AUDIO_UPLOAD_MAX_BYTES)

    assert mock_run.called
    assert sorted(p.name for p in result) == ["chunk_000.mp3", "chunk_001.mp3"]


def test_split_audio_file_ignores_duration_limit_for_non_diarize_extension(tmp_path):
    # .flac läuft über whisper-1 (siehe _DIARIZE_EXTENSIONS), das keine
    # gesonderte Dauergrenze hat - eine lange, aber kleine .flac-Datei soll
    # deshalb NICHT allein wegen der Dauer aufgeteilt werden.
    audio_path = tmp_path / "long-but-small.flac"
    audio_path.write_bytes(b"x" * 100)

    with (
        patch("app.extraction._audio_duration_seconds", return_value=1468.0),
        patch("app.extraction.subprocess.run") as mock_run,
    ):
        result = split_audio_file(audio_path, max_bytes=extraction.AUDIO_UPLOAD_MAX_BYTES)

    assert result == [audio_path]
    mock_run.assert_not_called()


def test_find_binary_prefers_shutil_which(monkeypatch):
    monkeypatch.setattr(extraction.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert extraction._find_binary("ffmpeg", ["/opt/homebrew/bin/ffmpeg"]) == "/usr/bin/ffmpeg"


def test_find_binary_falls_back_to_known_install_paths(monkeypatch, tmp_path):
    # Regressionstest: ffmpeg/ffprobe waren über Homebrew installiert, aber
    # /opt/homebrew/bin fehlte in der PATH-Umgebungsvariable des laufenden
    # Prozesses - shutil.which() fand die Programme deshalb nicht, obwohl sie
    # vorhanden waren, und split_audio_file() übersprang jede Aufteilung
    # lautlos (_audio_duration_seconds gab None zurück).
    monkeypatch.setattr(extraction.shutil, "which", lambda name: None)
    fallback = tmp_path / "ffmpeg"
    fallback.write_text("")
    assert extraction._find_binary("ffmpeg", [str(fallback)]) == str(fallback)


def test_find_binary_returns_bare_name_when_nothing_found(monkeypatch):
    monkeypatch.setattr(extraction.shutil, "which", lambda name: None)
    assert extraction._find_binary("ffmpeg", ["/does/not/exist"]) == "ffmpeg"


def test_warn_if_binary_missing_prints_warning_when_not_found(capsys, monkeypatch):
    """Nutzerwunsch (2026-08-03): ffmpeg fehlte auf Produktion komplett -
    der Startup-Check soll das deutlich in den Logs sichtbar machen, statt
    erst beim Scheitern der naechsten grossen Audio-Transkription."""
    monkeypatch.setattr(extraction.shutil, "which", lambda name: None)
    extraction._warn_if_binary_missing("ffmpeg", "/does/not/exist/ffmpeg")

    captured = capsys.readouterr()
    assert "ffmpeg" in captured.err
    assert "WARNUNG" in captured.err
    assert captured.out == ""


def test_warn_if_binary_missing_silent_when_found(capsys):
    extraction._warn_if_binary_missing("python3", sys.executable)

    captured = capsys.readouterr()
    assert captured.err == ""


def test_transcribe_audio_returns_single_chunk_text_unchanged(tmp_path):
    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"fake-bytes")

    with patch.object(extraction, "split_audio_file", return_value=[audio_path]), \
         patch.object(extraction, "_transcribe_chunk_with_retries", return_value=("Nur ein Teil.", None)):
        text, error_detail = transcribe_audio(audio_path)

    assert text == "Nur ein Teil."
    assert error_detail is None


def test_transcribe_audio_concatenates_multiple_segments_with_part_markers(tmp_path):
    split_dir = tmp_path / "split"
    split_dir.mkdir()
    chunk_a = split_dir / "chunk_000.mp3"
    chunk_b = split_dir / "chunk_001.mp3"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")

    with patch.object(extraction, "split_audio_file", return_value=[chunk_a, chunk_b]), \
         patch.object(extraction, "_transcribe_chunk_with_retries", side_effect=[("Text A", None), ("Text B", None)]):
        text, error_detail = transcribe_audio(tmp_path / "original.mp3")

    assert text == "--- Teil 1 ---\n\nText A\n\n--- Teil 2 ---\n\nText B"
    assert error_detail is None
    assert not split_dir.exists()


def test_transcribe_audio_fails_whole_file_when_one_segment_fails_permanently(tmp_path):
    # Der eigentliche Bug (2026-07-29): ein gescheiterter Abschnitt durfte
    # bisher NIE zu einem stillschweigend lückenhaften Ergebnis führen -
    # die ganze Datei muss als Fehler gelten, Abschnitt 1 bleibt aber
    # namentlich im Fehlertext genannt.
    split_dir = tmp_path / "split"
    split_dir.mkdir()
    chunk_a = split_dir / "chunk_000.mp3"
    chunk_b = split_dir / "chunk_001.mp3"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")

    with patch.object(extraction, "split_audio_file", return_value=[chunk_a, chunk_b]), \
         patch.object(
             extraction,
             "_transcribe_chunk_with_retries",
             side_effect=[("Text A", None), ("", "RateLimitError: zu viele Anfragen")],
         ):
        text, error_detail = transcribe_audio(tmp_path / "original.mp3")

    assert text == ""
    assert error_detail == "Abschnitt 2/2: RateLimitError: zu viele Anfragen"
    assert not split_dir.exists()


def test_transcribe_audio_reuses_known_segments_without_calling_openai_again(tmp_path):
    # Kernstück der Kostenschutz-Änderung: ein bereits erfolgreich
    # transkribierter Abschnitt aus einem vorherigen (teilweise
    # gescheiterten) Versuch darf bei einem erneuten Versuch NICHT nochmal
    # bezahlt/angefragt werden.
    split_dir = tmp_path / "split"
    split_dir.mkdir()
    chunk_a = split_dir / "chunk_000.mp3"
    chunk_b = split_dir / "chunk_001.mp3"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")

    with patch.object(extraction, "split_audio_file", return_value=[chunk_a, chunk_b]), \
         patch.object(
             extraction, "_transcribe_chunk_with_retries", return_value=("Text B (neu)", None)
         ) as mock_retry:
        text, error_detail = transcribe_audio(
            tmp_path / "original.mp3", known_segments={0: "Text A (schon erledigt)"}
        )

    assert error_detail is None
    assert text == "--- Teil 1 ---\n\nText A (schon erledigt)\n\n--- Teil 2 ---\n\nText B (neu)"
    mock_retry.assert_called_once()  # nur für Abschnitt 2, nicht für den bereits bekannten Abschnitt 1


def test_transcribe_audio_calls_on_segment_success_for_each_new_segment(tmp_path):
    split_dir = tmp_path / "split"
    split_dir.mkdir()
    chunk_a = split_dir / "chunk_000.mp3"
    chunk_b = split_dir / "chunk_001.mp3"
    chunk_a.write_bytes(b"a")
    chunk_b.write_bytes(b"b")

    calls = []
    with patch.object(extraction, "split_audio_file", return_value=[chunk_a, chunk_b]), \
         patch.object(extraction, "_transcribe_chunk_with_retries", side_effect=[("Text A", None), ("Text B", None)]):
        transcribe_audio(tmp_path / "original.mp3", on_segment_success=lambda i, t, txt: calls.append((i, t, txt)))

    assert calls == [(0, 2, "Text A"), (1, 2, "Text B")]
