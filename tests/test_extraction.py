import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from app import extraction
from app.extraction import (
    UnsafeUrlError,
    _assert_safe_url,
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


# SSRF-Schutz (_assert_safe_url in app/extraction.py) löst seit dem
# Security-Fix (2026-09-23) jeden Hostnamen per echtem DNS auf, bevor eine
# URL abgerufen wird - ohne dieses Mock würde JEDER Test hier, der eine
# (fiktive) example.org-URL verwendet, eine echte Netzwerkanfrage auslösen
# (langsam/flaky, verstößt gegen das etablierte "kein echtes Netzwerk in
# Tests"-Prinzip dieser Suite, siehe client-Fixture in test_api.py). Liefert
# eine öffentliche Test-IP für JEDEN Hostnamen; die dedizierten Tests für
# das Schutzverhalten selbst (test_assert_safe_url_*) überschreiben dieses
# Mock lokal mit einer privaten/internen IP.
@pytest.fixture(autouse=True)
def _mock_dns_resolution(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(extraction, "_getaddrinfo", fake_getaddrinfo)


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
        patch("app.extraction._fetch_html", return_value="<html>...</html>"),
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
    with patch("app.extraction._fetch_html", return_value=None):
        result = extract_from_url("https://example.org/nicht-erreichbar")

    assert result["extracted"] is False
    assert result["text"] == ""


def test_extract_from_url_handles_empty_extraction():
    with (
        patch("app.extraction._fetch_html", return_value="<html></html>"),
        patch("app.extraction.trafilatura.extract", return_value=None),
    ):
        result = extract_from_url("https://example.org/leer")

    assert result["extracted"] is False


def test_extract_from_url_handles_missing_metadata_fields():
    with (
        patch("app.extraction._fetch_html", return_value="<html>...</html>"),
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
    # Bewusst eine gültige (http/https, auflösbare) URL - sonst würde der
    # SSRF-Schutz (_assert_safe_url) schon VOR dem Abruf eingreifen und der
    # hier eigentlich zu testende Exception-Pfad (in _fetch_html) nie
    # erreicht.
    with patch("app.extraction._safe_opener.open", side_effect=RuntimeError("boom")):
        result = extract_from_url("https://example.org/boom")

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
    with patch("app.extraction._safe_opener.open", return_value=resp):
        assert looks_like_pdf("https://example.org/download?id=42") is True


def test_looks_like_pdf_false_for_html_content_type():
    resp = MagicMock()
    resp.headers = {"Content-Type": "text/html"}
    resp.__enter__.return_value = resp
    with patch("app.extraction._safe_opener.open", return_value=resp):
        assert looks_like_pdf("https://example.org/artikel") is False


def test_looks_like_pdf_returns_false_on_network_error():
    with patch("app.extraction._safe_opener.open", side_effect=RuntimeError("boom")):
        assert looks_like_pdf("https://example.org/nope") is False


def test_download_pdf_bytes_returns_content():
    resp = MagicMock()
    resp.read.return_value = b"%PDF-1.4..."
    resp.__enter__.return_value = resp
    with patch("app.extraction._safe_opener.open", return_value=resp):
        assert download_pdf_bytes("https://example.org/paper.pdf") == b"%PDF-1.4..."


def test_download_pdf_bytes_returns_none_on_error():
    with patch("app.extraction._safe_opener.open", side_effect=RuntimeError("boom")):
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
    with patch("app.extraction._safe_opener.open", return_value=resp):
        assert looks_like_audio("https://example.org/download?id=42") is True


def test_looks_like_audio_false_for_html_content_type():
    resp = MagicMock()
    resp.headers = {"Content-Type": "text/html"}
    resp.__enter__.return_value = resp
    with patch("app.extraction._safe_opener.open", return_value=resp):
        assert looks_like_audio("https://example.org/artikel") is False


def test_download_audio_bytes_returns_content():
    resp = MagicMock()
    resp.read.return_value = b"ID3-fake-mp3-data"
    resp.__enter__.return_value = resp
    with patch("app.extraction._safe_opener.open", return_value=resp):
        assert download_audio_bytes("https://example.org/episode.mp3") == b"ID3-fake-mp3-data"


def test_download_audio_bytes_returns_none_on_error():
    with patch("app.extraction._safe_opener.open", side_effect=RuntimeError("boom")):
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


def test_transcribe_chunk_once_passes_prompt_to_whisper():
    """Regressionstest (Nutzerfeedback 2026-08-23): prominente Namen wie
    Niels Pflaeging/Silke Hermann wurden in Transkripten wiederholt falsch
    verstanden - ein Vokabular-Hinweis (OpenAIs "prompt"-Parameter) soll die
    richtige Schreibweise wahrscheinlicher machen."""
    client = MagicMock()
    client.audio.transcriptions.create.return_value = "Text."
    with patch.object(extraction, "_get_openai_client", return_value=client):
        _transcribe_chunk_once(b"fake-flac-bytes", "aufnahme.flac", prompt="Niels Pflaeging, Silke Hermann")

    assert client.audio.transcriptions.create.call_args.kwargs["prompt"] == "Niels Pflaeging, Silke Hermann"


def test_transcribe_chunk_once_omits_prompt_for_diarize_model():
    """Fix (real reproduziert auf Produktion, 2026-08-25): gpt-4o-transcribe-
    diarize lehnt JEDEN gesetzten Prompt pauschal mit 400 ab ("Prompt is not
    supported for diarization models") - anders als bei whisper-1 oben gibt
    es hier keinen Vokabular-Hinweis-Mechanismus. Der vorherige Test hier
    prüfte fälschlich das Gegenteil (an einem gemockten Client unbemerkt),
    bis ein echter Upload in Produktion mit eingetragenen Autor:innen daran
    scheiterte."""
    client = MagicMock()
    client.audio.transcriptions.create.return_value = _fake_diarized_result([("A", "Hallo.")])
    with patch.object(extraction, "_get_openai_client", return_value=client):
        _transcribe_chunk_once(b"fake-mp3-bytes", "episode.mp3", prompt="Niels Pflaeging")

    assert "prompt" not in client.audio.transcriptions.create.call_args.kwargs


def test_transcribe_chunk_once_omits_prompt_kwarg_when_not_given():
    """Die SDK-Signatur erwartet str | Omit statt str | None - ein explizites
    None würde als ungültiger Wert an die API weitergereicht."""
    client = MagicMock()
    client.audio.transcriptions.create.return_value = "Text."
    with patch.object(extraction, "_get_openai_client", return_value=client):
        _transcribe_chunk_once(b"fake-flac-bytes", "aufnahme.flac")

    assert "prompt" not in client.audio.transcriptions.create.call_args.kwargs


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


def test_transcribe_audio_builds_prompt_from_known_names(tmp_path):
    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"fake-bytes")

    with patch.object(extraction, "split_audio_file", return_value=[audio_path]), \
         patch.object(extraction, "_transcribe_chunk_with_retries", return_value=("Text.", None)) as mock_transcribe:
        transcribe_audio(audio_path, known_names=["Niels Pflaeging", "Silke Hermann"])

    assert mock_transcribe.call_args.args[3] == "Niels Pflaeging, Silke Hermann"


def test_transcribe_audio_omits_prompt_when_no_known_names(tmp_path):
    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"fake-bytes")

    with patch.object(extraction, "split_audio_file", return_value=[audio_path]), \
         patch.object(extraction, "_transcribe_chunk_with_retries", return_value=("Text.", None)) as mock_transcribe:
        transcribe_audio(audio_path)

    assert mock_transcribe.call_args.args[3] is None


def test_transcribe_audio_ignores_blank_known_names(tmp_path):
    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"fake-bytes")

    with patch.object(extraction, "split_audio_file", return_value=[audio_path]), \
         patch.object(extraction, "_transcribe_chunk_with_retries", return_value=("Text.", None)) as mock_transcribe:
        transcribe_audio(audio_path, known_names=["Niels Pflaeging", "  ", ""])

    assert mock_transcribe.call_args.args[3] == "Niels Pflaeging"


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


# --- strip_tracking_params (2026-08-31) ---
# Nutzerwunsch: dieselbe per Social Media/Newsletter geteilte Seite wirkte
# je nach mitgeschickten Tracking-Anhängen (utm_*, fbclid, ...) wie eine
# ANDERE URL - Duplikat-Prüfung beim Import schlug dadurch nicht an.


def test_strip_tracking_params_removes_utm_parameters():
    url = "https://example.org/artikel?utm_source=twitter&utm_medium=social"
    assert extraction.strip_tracking_params(url) == "https://example.org/artikel"


def test_strip_tracking_params_removes_known_click_ids():
    url = "https://example.org/artikel?fbclid=abc123&gclid=xyz789"
    assert extraction.strip_tracking_params(url) == "https://example.org/artikel"


def test_strip_tracking_params_keeps_functional_query_parameters():
    # Ein funktional relevanter Parameter (z.B. eine Artikel-ID) darf nicht
    # verloren gehen, sonst würde die URL kaputtgehen.
    url = "https://example.org/artikel?p=123&utm_source=twitter"
    assert extraction.strip_tracking_params(url) == "https://example.org/artikel?p=123"


def test_strip_tracking_params_preserves_fragment():
    url = "https://example.org/artikel?utm_source=twitter#abschnitt-2"
    assert extraction.strip_tracking_params(url) == "https://example.org/artikel#abschnitt-2"


def test_strip_tracking_params_returns_url_unchanged_without_query_string():
    url = "https://example.org/artikel"
    assert extraction.strip_tracking_params(url) == url


def test_strip_tracking_params_returns_input_unchanged_for_empty_string():
    assert extraction.strip_tracking_params("") == ""


def test_assert_safe_url_rejects_non_http_scheme():
    with pytest.raises(UnsafeUrlError):
        _assert_safe_url("file:///etc/passwd")


def test_assert_safe_url_rejects_url_without_hostname():
    with pytest.raises(UnsafeUrlError):
        _assert_safe_url("https://")


def test_assert_safe_url_rejects_unresolvable_hostname(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        raise socket.gaierror("nicht auflösbar")

    monkeypatch.setattr(extraction, "_getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeUrlError):
        _assert_safe_url("https://nirgendwo.invalid/artikel")


@pytest.mark.parametrize(
    "ip",
    [
        "169.254.169.254",  # Cloud-Metadata-Endpunkt
        "127.0.0.1",  # Loopback
        "10.0.0.5",  # Privates Netz
        "192.168.1.1",  # Privates Netz
        "172.16.0.1",  # Privates Netz
        "0.0.0.0",  # Unspecified
    ],
)
def test_assert_safe_url_rejects_private_and_internal_ips(monkeypatch, ip):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(extraction, "_getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeUrlError):
        _assert_safe_url(f"http://interne-adresse.example/{ip}")


def test_assert_safe_url_rejects_if_any_resolved_ip_is_private(monkeypatch):
    # DNS kann mehrere A-Records liefern - reicht EINE private IP darunter,
    # muss die URL trotzdem als unsicher gelten (nicht nur die erste prüfen).
    def fake_getaddrinfo(host, *args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0)),
        ]

    monkeypatch.setattr(extraction, "_getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeUrlError):
        _assert_safe_url("http://mehrfach-aufgeloest.example/artikel")


def test_assert_safe_url_allows_public_ip():
    _assert_safe_url("https://example.org/artikel")


def test_safe_urlopen_blocks_before_reaching_real_urlopen(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(extraction, "_getaddrinfo", fake_getaddrinfo)
    with patch("app.extraction._safe_opener.open") as fake_urlopen:
        req = extraction.urllib.request.Request("http://127.0.0.1:6379/")
        with pytest.raises(UnsafeUrlError):
            extraction._safe_urlopen(req, timeout=5)
        fake_urlopen.assert_not_called()


def test_looks_like_pdf_returns_false_for_internal_address(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(extraction, "_getaddrinfo", fake_getaddrinfo)
    with patch("app.extraction._safe_opener.open") as fake_urlopen:
        assert looks_like_pdf("http://169.254.169.254/latest/meta-data/") is False
        fake_urlopen.assert_not_called()


def test_download_pdf_bytes_returns_none_for_internal_address(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]

    monkeypatch.setattr(extraction, "_getaddrinfo", fake_getaddrinfo)
    with patch("app.extraction._safe_opener.open") as fake_urlopen:
        assert download_pdf_bytes("http://10.0.0.5/internes-dokument.pdf") is None
        fake_urlopen.assert_not_called()


def test_download_audio_bytes_returns_none_for_internal_address(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.1", 0))]

    monkeypatch.setattr(extraction, "_getaddrinfo", fake_getaddrinfo)
    with patch("app.extraction._safe_opener.open") as fake_urlopen:
        assert download_audio_bytes("http://192.168.0.1/internes-audio.mp3") is None
        fake_urlopen.assert_not_called()


def test_extract_from_url_reports_failure_for_internal_address(monkeypatch):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(extraction, "_getaddrinfo", fake_getaddrinfo)
    with patch("app.extraction._fetch_html") as fake_fetch_html:
        result = extract_from_url("http://169.254.169.254/latest/meta-data/")

    assert result["extracted"] is False
    fake_fetch_html.assert_not_called()


# Backlog (2026-09-23): SSRF über Weiterleitungen. Echter lokaler HTTP-Server
# statt Mocks, damit der komplette Redirect-Mechanismus von urllib wirklich
# durchläuft. Die Verbindung selbst geht an 127.0.0.1 (echte DNS-/Socket-
# Auflösung); nur die SSRF-Prüfung (extraction._getaddrinfo) sieht die
# Hostnamen so, wie der Test sie vorgibt.
_ARTICLE_HTML = (
    "<html><head><title>Interner Artikel</title></head><body><article><h1>Intern</h1><p>"
    + "Vertraulicher Inhalt, der nie nach außen gelangen darf. " * 40
    + "</p></article></body></html>"
).encode()


def _serve_redirect(location: str):
    """location darf {port} enthalten (Port des Servers selbst)."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", location.format(port=self.server.server_address[1]))
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_ARTICLE_HTML)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _resolve(mapping: dict):
    def fake_getaddrinfo(host, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (mapping[host], 0))]

    return fake_getaddrinfo


def test_safe_urlopen_blocks_redirect_to_internal_address(monkeypatch):
    server = _serve_redirect("http://metadata.internal/latest/meta-data/")
    try:
        monkeypatch.setattr(
            extraction,
            "_getaddrinfo",
            _resolve({"127.0.0.1": "93.184.216.34", "metadata.internal": "169.254.169.254"}),
        )
        port = server.server_address[1]
        req = extraction.urllib.request.Request(f"http://127.0.0.1:{port}/start")
        with pytest.raises(extraction.UnsafeUrlError):
            extraction._safe_urlopen(req, timeout=5)
    finally:
        server.shutdown()


def test_safe_urlopen_follows_redirect_to_public_address(monkeypatch):
    server = _serve_redirect("/ziel")
    try:
        monkeypatch.setattr(extraction, "_getaddrinfo", _resolve({"127.0.0.1": "93.184.216.34"}))
        port = server.server_address[1]
        req = extraction.urllib.request.Request(f"http://127.0.0.1:{port}/start")
        with extraction._safe_urlopen(req, timeout=5) as resp:
            assert resp.read() == _ARTICLE_HTML
            assert resp.geturl().endswith("/ziel")
    finally:
        server.shutdown()


def test_extract_from_url_fails_quietly_on_redirect_to_internal_address(monkeypatch):
    # Ziel "localhost" ist real erreichbar (derselbe Server, voller Artikel) -
    # ohne Redirect-Prüfung käme der Inhalt also tatsächlich zurück.
    server = _serve_redirect("http://localhost:{port}/intern")
    try:
        monkeypatch.setattr(
            extraction,
            "_getaddrinfo",
            _resolve({"127.0.0.1": "93.184.216.34", "localhost": "127.0.0.1"}),
        )
        port = server.server_address[1]
        result = extract_from_url(f"http://127.0.0.1:{port}/start")
        assert result["extracted"] is False
    finally:
        server.shutdown()


def test_fetch_html_rejects_oversized_response():
    resp = MagicMock()
    resp.read.return_value = b"x" * (extraction._MAX_HTML_BYTES + 1)
    resp.__enter__.return_value = resp
    with patch("app.extraction._safe_opener.open", return_value=resp):
        assert extraction._fetch_html("https://example.org/gross") is None


def test_transcribe_audio_records_stt_cost_per_segment(tmp_path, monkeypatch):
    """2026-09-26: OpenAI-Transkription fließt je Audio-Minute in die Kostenübersicht."""
    from app import usage

    audio = tmp_path / "folge.mp3"
    audio.write_bytes(b"x")
    monkeypatch.setattr(extraction, "split_audio_file", lambda path: [path])
    monkeypatch.setattr(extraction, "_audio_duration_seconds", lambda path: 90.0)
    monkeypatch.setattr(extraction, "_transcribe_chunk_with_retries", lambda *a, **k: ("Text", None))

    text, error = extraction.transcribe_audio(audio)

    assert (text, error) == ("Text", None)
    (entry,) = usage.list_entries()
    assert (entry["channel"], entry["model"], entry["quantity"]) == ("stt", "gpt-4o-transcribe-diarize", 90.0)
    assert entry["cost_usd"] == pytest.approx(0.009)


# --- EPUB / PDF-Lesezeichen (Idee 8d1b69dd) ---------------------------------

import io
import zipfile

from pypdf import PdfWriter

from app.extraction import extract_epub

_CONTAINER = (
    '<?xml version="1.0"?><container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>'
)


def _opf(spine_hrefs, extra_head=""):
    items = "".join(f'<item id="c{i}" href="{h}" media-type="application/xhtml+xml"/>' for i, h in enumerate(spine_hrefs))
    refs = "".join(f'<itemref idref="c{i}"/>' for i in range(len(spine_hrefs)))
    return (
        f'{extra_head}<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>Das Buch</dc:title><dc:creator>Erika Muster</dc:creator></metadata>"
        f"<manifest>{items}</manifest><spine>{refs}</spine></package>"
    )


def _xhtml(body, head=""):
    return f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>t</title>{head}</head><body>{body}</body></html>'


def _make_epub(chapters, opf=None, extra_files=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", opf or _opf(list(chapters)))
        for name, body in chapters.items():
            z.writestr(f"OEBPS/{name}", body)
        for name, body in (extra_files or {}).items():
            z.writestr(name, body)
    return buf.getvalue()


def test_extract_epub_chapters_in_spine_order_with_headings():
    # Spine-Reihenfolge b vor a, abweichend von der Dateireihenfolge im Zip.
    chapters = {
        "a.xhtml": _xhtml("<h1>Zweites Kapitel</h1><p>Text zwei.</p>"),
        "b.xhtml": _xhtml("<h1>Erstes Kapitel</h1><p>Text eins.</p><h3>Unterpunkt</h3><p>Mehr.</p>"),
    }
    data = _make_epub(chapters, opf=_opf(["b.xhtml", "a.xhtml"]))
    result = extract_epub(data)
    assert result["extracted"] is True
    assert result["title"] == "Das Buch"
    assert result["authors"] == ["Erika Muster"]
    text = result["text"]
    assert text.index("# Erstes Kapitel") < text.index("Text eins.") < text.index("### Unterpunkt") < text.index("# Zweites Kapitel")
    assert "Text zwei." in text


def test_extract_epub_without_headings_is_plain_text():
    data = _make_epub({"a.xhtml": _xhtml("<p>Nur Fließtext.</p><p>Zweiter Absatz.</p>")})
    result = extract_epub(data)
    assert result["extracted"] is True
    assert "#" not in result["text"]
    assert "Nur Fließtext." in result["text"] and "Zweiter Absatz." in result["text"]


def test_extract_epub_skips_script_and_style():
    body = "<p>Sichtbar.</p><script>var geheim = 1;</script><style>.x{color:red}</style>"
    data = _make_epub({"a.xhtml": _xhtml(body, head="<style>h1{}</style>")})
    text = extract_epub(data)["text"]
    assert "Sichtbar." in text
    assert "geheim" not in text and "color" not in text


@pytest.mark.parametrize("data", [b"", b"das ist kein zip", b"PK\x03\x04kaputt"])
def test_extract_epub_broken_input_returns_not_extracted(data):
    assert extract_epub(data)["extracted"] is False


def test_extract_epub_rejects_too_many_entries():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(5001):
            z.writestr(f"f{i}.txt", "x")
    assert extract_epub(buf.getvalue())["extracted"] is False


def test_extract_epub_rejects_oversized_archive():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", _opf(["a.xhtml"]))
        z.writestr("OEBPS/a.xhtml", _xhtml("<p>hallo</p>"))
        z.writestr("big.bin", b"\0" * (101 * 1024 * 1024))  # komprimiert winzig
    assert extract_epub(buf.getvalue())["extracted"] is False


def test_extract_epub_rejects_entity_in_opf():
    evil = '<?xml version="1.0"?><!DOCTYPE package [<!ENTITY x "boom">]>'
    data = _make_epub({"a.xhtml": _xhtml("<p>hallo</p>")}, opf=_opf(["a.xhtml"], extra_head=evil))
    assert extract_epub(data)["extracted"] is False


def test_extract_epub_ignores_href_outside_archive():
    data = _make_epub(
        {"a.xhtml": _xhtml("<p>drin</p>")},
        opf=_opf(["../../geheim.xhtml"]),
        extra_files={"geheim.xhtml": _xhtml("<p>draussen</p>")},
    )
    result = extract_epub(data)
    assert result["extracted"] is False
    assert "draussen" not in result["text"]


def _pdf_with_outline(outline):
    w = PdfWriter()
    for _ in range(4):
        w.add_blank_page(200, 200)
    for title, page in outline:
        w.add_outline_item(title, page)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def _page_texts_patch(texts):
    return patch("pypdf.PageObject.extract_text", side_effect=texts)


def test_extract_pdf_outline_adds_heading_before_right_page():
    data = _pdf_with_outline([("Kapitel Eins", 0), ("Kapitel Zwei", 2)])
    with _page_texts_patch(["S1", "S2", "S3", "S4"]):
        text = extract_pdf(data)["text"]
    assert text == "# Kapitel Eins\nS1\nS2\n# Kapitel Zwei\nS3\nS4"


def test_extract_pdf_without_outline_is_unchanged():
    data = _pdf_with_outline([])
    with _page_texts_patch(["S1", "S2", "S3", "S4"]):
        text = extract_pdf(data)["text"]
    assert text == "S1\nS2\nS3\nS4"


# --- Fehler-Check-Befunde (F1, F4, S2, S3) -----------------------------------

def test_extract_pdf_scan_with_outline_is_not_extracted():
    # Scan ohne Text-Ebene, aber mit Lesezeichen: darf nicht als extrahiert
    # gelten, sonst startet die OCR nie.
    data = _pdf_with_outline([("Kapitel Eins", 0), ("Kapitel Zwei", 2)])
    with _page_texts_patch(["", "", "", ""]):
        result = extract_pdf(data)
    assert result["extracted"] is False
    assert result["text"] == ""


def test_extract_epub_drm_encrypted_spine_is_not_extracted():
    enc = (
        '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>'
        '<enc:EncryptionMethod Algorithm="http://www.w3.org/2001/04/xmlenc#aes128-cbc"/>'
        '<enc:CipherData><enc:CipherReference URI="OEBPS/a.xhtml"/></enc:CipherData>'
        "</enc:EncryptedData></encryption>"
    )
    data = _make_epub({"a.xhtml": _xhtml("<p>Kauderwelsch</p>")}, extra_files={"META-INF/encryption.xml": enc})
    assert extract_epub(data)["extracted"] is False


def test_extract_epub_font_obfuscation_is_fine():
    enc = (
        '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        'xmlns:enc="http://www.w3.org/2001/04/xmlenc#"><enc:EncryptedData>'
        '<enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>'
        '<enc:CipherData><enc:CipherReference URI="OEBPS/font.otf"/></enc:CipherData>'
        "</enc:EncryptedData></encryption>"
    )
    data = _make_epub({"a.xhtml": _xhtml("<p>Lesbar.</p>")}, extra_files={"META-INF/encryption.xml": enc})
    assert extract_epub(data)["extracted"] is True


def test_extract_epub_duplicate_spine_entries_read_once():
    chapters = {"a.xhtml": _xhtml("<p>EinzigartigerSatz</p>")}
    data = _make_epub(chapters, opf=_opf(["a.xhtml"] * 50))
    text = extract_epub(data)["text"]
    assert text.count("EinzigartigerSatz") == 1


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le"])
def test_extract_epub_rejects_utf16_opf_with_entity(encoding):
    opf = _opf(["a.xhtml"], extra_head='<!DOCTYPE package [<!ENTITY x "boom">]>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", opf.encode(encoding))
        z.writestr("OEBPS/a.xhtml", _xhtml("<p>hallo</p>"))
    assert extract_epub(buf.getvalue())["extracted"] is False


# --- Bilder aus Web-Seiten (Idee ff895248) ------------------------------------

_P1 = "Der erste Absatz erzählt von der Dezentralisierung der Führung im Unternehmen."
_P2 = "Der zweite Absatz beschreibt, wie Teams ihre Budgets selbst verantworten dürfen."
_ARTICLE_TEXT = f"# Titel\n\n{_P1}\n\n{_P2}"


def _html(body: str) -> str:
    return f"<html><body><article><h1>Titel</h1><p>{_P1}</p>{body}<p>{_P2}</p></article></body></html>"


def _web_images(body: str, text: str = _ARTICLE_TEXT, base="https://example.org/blog/artikel"):
    from app.extraction import extract_web_images

    return extract_web_images(_html(body), base, text)


def test_web_images_resolves_relative_url_and_sets_alt_and_anchor():
    result = _web_images('<img src="../bilder/foto.jpg" width="800" height="600" alt="Ein Foto vom Hof">')

    assert result == [
        {
            "kind": "url",
            "url": "https://example.org/bilder/foto.jpg",
            "alt": "Ein Foto vom Hof",
            "anchor": _P2,
        }
    ]


def test_web_images_uses_data_src_for_lazy_loading():
    result = _web_images(
        '<img src="data:image/gif;base64,R0lGOD" data-src="/lazy.jpg" width="640" height="480" alt="Lazy Bild">'
    )

    assert [img["url"] for img in result] == ["https://example.org/lazy.jpg"]


def test_web_images_drops_unsafe_schemes_and_credentials():
    body = "".join(
        f'<img src="{src}" width="800" height="600" alt="Bild mit langem Alt-Text">'
        for src in (
            "http://example.org/a.jpg",
            "data:image/png;base64,AAAA",
            "javascript:alert(1)",
            "https://user:pw@example.org/b.jpg",
        )
    )
    assert _web_images(body) == []


def test_web_images_drops_svg_gif_logos_and_small_images():
    body = "".join(
        f'<img src="{src}" width="{w}" height="{h}" alt="Beschreibung des Bildes">'
        for src, w, h in (
            ("/a.svg", 800, 600),
            ("/b.gif", 800, 600),
            ("/firmen-logo.png", 800, 600),
            ("/icons/pfeil.png", 800, 600),
            ("/avatar-jane.jpg", 800, 600),
            ("/klein.jpg", 100, 600),
            ("/klein2.jpg", 800, 80),
            ("/gut.jpg", 800, 600),
        )
    )
    assert [img["url"] for img in _web_images(body)] == ["https://example.org/gut.jpg"]


def test_web_images_without_size_keep_only_figure_or_long_alt():
    body = (
        '<img src="/ohne-alt.jpg">'
        '<img src="/kurz.jpg" alt="Foto">'
        '<img src="/lang.jpg" alt="Ein Diagramm der Kreisstruktur">'
        '<figure><img src="/figur.jpg"><figcaption>Unterschrift</figcaption></figure>'
    )
    assert [img["url"] for img in _web_images(body)] == [
        "https://example.org/lang.jpg",
        "https://example.org/figur.jpg",
    ]


def test_web_images_infer_size_from_url_hint_when_attributes_missing():
    # Beobachtet im Spike (betahof.de): weder width/height noch alt, aber die
    # URL nennt die Größe.
    body = (
        '<img src="/u/abc/l0,t104,w1920,h798/image.jpg">'
        '<img src="/u/def/image-64x64.jpg">'
    )
    assert [img["url"] for img in _web_images(body)] == ["https://example.org/u/abc/l0,t104,w1920,h798/image.jpg"]


def test_web_images_keep_closing_bracket_in_alt_text():
    result = _web_images('<img src="/x.jpg" width="800" height="600" alt="Abbildung [1] zur Struktur ]">')

    assert result[0]["alt"] == "Abbildung [1] zur Struktur ]"


def test_web_images_drop_images_in_navigation_header_footer_aside():
    chrome = "".join(
        f'<{tag}><img src="/{tag}.jpg" width="800" height="600" alt="Bild im Seitenrahmen"></{tag}>'
        for tag in ("nav", "header", "footer", "aside")
    )
    html = f"<html><body>{chrome}<article><p>{_P1}</p><img src='/ok.jpg' width='800' height='600' alt='Bild im Artikel'><p>{_P2}</p></article></body></html>"
    from app.extraction import extract_web_images

    result = extract_web_images(html, "https://example.org/", _ARTICLE_TEXT)

    assert [img["url"] for img in result] == ["https://example.org/ok.jpg"]


def test_web_images_drop_image_whose_anchor_is_not_in_text():
    body = '<img src="/x.jpg" width="800" height="600" alt="Bild ohne Textbezug">'
    html = _html(body)
    from app.extraction import extract_web_images

    assert extract_web_images(html, "https://example.org/", "# Titel\n\nGanz anderer Text, der nichts enthält.") == []


def test_web_images_dedupe_by_url_and_limit_to_30():
    same = '<img src="/same.jpg" width="800" height="600" alt="Immer dasselbe Bild">' * 3
    many = "".join(f'<img src="/b{i}.jpg" width="800" height="600" alt="Bild Nummer {i}">' for i in range(40))

    assert len(_web_images(same)) == 1
    assert len(_web_images(many)) == 30


def test_web_images_broken_html_returns_empty_list():
    from app.extraction import extract_web_images

    assert extract_web_images("<img src=", "https://example.org/", "Text") == []
    assert extract_web_images(b"\xff\xfe<<<>>>", "https://example.org/", "Text") == []
    assert extract_web_images("", "https://example.org/", "Text") == []


def test_extract_from_url_text_is_identical_with_and_without_images():
    plain = _html("")
    with_img = _html('<img src="/x.jpg" width="800" height="600" alt="Ein Bild im Artikel">')
    results = []
    for html in (plain, with_img):
        with patch("app.extraction._fetch_html", return_value=html.encode()):
            results.append(extract_from_url("https://example.org/blog/artikel"))

    assert results[0]["text"] == results[1]["text"]
    assert "images" not in results[0]
    assert [img["url"] for img in results[1].get("images", [])] == ["https://example.org/x.jpg"]


# --- Bilder aus PDFs (Idee ff895248) ------------------------------------------


def _png(size, color=(200, 60, 60)) -> bytes:
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


def _pdf_with_images(pages) -> bytes:
    """pages: Liste von (Text oder None, [(png_bytes, Rechteck-Größe (w, h)) | ("xref", Index, (w, h))])."""
    import fitz

    doc = fitz.open()
    xrefs = {}
    for text, images in pages:
        page = doc.new_page(width=595, height=842)
        if text:
            page.insert_text((50, 50), text, fontsize=11)
        y = 100
        for item in images:
            if item[0] == "xref":
                rect = fitz.Rect(50, y, 50 + item[2][0], y + item[2][1])
                page.insert_image(rect, xref=xrefs[item[1]])
            else:
                data, (w, h) = item
                rect = fitz.Rect(50, y, 50 + w, y + h)
                xref = page.insert_image(rect, stream=data)
                xrefs[len(xrefs)] = xref
            y += 5
    return doc.tobytes()


_PAGE_TEXT = "Kapitel eins handelt von der Selbstorganisation in kleinen Teams."


def test_pdf_images_keeps_large_image_with_page_and_anchor():
    from app.extraction import extract_pdf_images

    data = _pdf_with_images([(None, []), (_PAGE_TEXT, [(_png((400, 300)), (200, 150))])])

    result = extract_pdf_images(data)

    assert len(result) == 1
    assert result[0]["page"] == 2
    assert result[0]["anchor"] == _PAGE_TEXT
    from io import BytesIO

    from PIL import Image

    assert Image.open(BytesIO(result[0]["data"])).size == (400, 300)


def test_pdf_images_drops_small_images():
    from app.extraction import extract_pdf_images

    data = _pdf_with_images([(_PAGE_TEXT, [(_png((150, 400)), (100, 100)), (_png((400, 150), (1, 2, 3)), (100, 100))])])

    assert extract_pdf_images(data) == []


def test_pdf_images_drops_image_repeated_on_three_pages_but_keeps_on_two():
    from app.extraction import extract_pdf_images

    logo = _png((300, 300), (10, 10, 10))
    three = _pdf_with_images(
        [(_PAGE_TEXT, [(logo, (100, 100))])] + [(_PAGE_TEXT, [("xref", 0, (100, 100))]) for _ in range(2)]
    )
    two = _pdf_with_images([(_PAGE_TEXT, [(logo, (100, 100))]), (_PAGE_TEXT, [("xref", 0, (100, 100))])])

    assert extract_pdf_images(three) == []
    assert len(extract_pdf_images(two)) == 1


def test_pdf_images_drops_full_page_scan():
    from app.extraction import extract_pdf_images

    data = _pdf_with_images([(_PAGE_TEXT, [(_png((1190, 1684)), (595, 842))])])

    assert extract_pdf_images(data) == []


def test_pdf_images_returns_empty_for_pdf_without_text_layer():
    from app.extraction import extract_pdf_images

    data = _pdf_with_images([(None, [(_png((400, 300)), (200, 150))])])

    assert extract_pdf_images(data) == []


def test_pdf_images_returns_empty_for_corrupt_pdf():
    from app.extraction import extract_pdf_images

    assert extract_pdf_images(b"%PDF-1.4 kaputt") == []
    assert extract_pdf_images(b"") == []


def test_pdf_images_respects_max_images():
    from app.extraction import extract_pdf_images

    pages = [
        (_PAGE_TEXT, [(_png((300, 300), (i, 50, 50)), (100, 100))]) for i in range(5)
    ]
    data = _pdf_with_images(pages)

    assert len(extract_pdf_images(data, max_images=3)) == 3
    assert len(extract_pdf_images(data)) == 5


def test_pdf_images_drop_images_above_pixel_limit():
    import io as _io

    from PIL import Image

    from app.extraction import extract_pdf_images

    buf = _io.BytesIO()
    Image.new("1", (6000, 6000)).save(buf, format="PNG")
    data = _pdf_with_images([(_PAGE_TEXT, [(buf.getvalue(), (200, 200))])])

    assert extract_pdf_images(data) == []


def test_pdf_images_read_text_only_for_pages_with_images():
    import pypdf

    from app.extraction import extract_pdf_images

    data = _pdf_with_images(
        [(_PAGE_TEXT, []), (_PAGE_TEXT, [(_png((400, 300)), (200, 150))]), (_PAGE_TEXT, [])]
    )
    calls = []
    original = pypdf.PageObject.extract_text

    def counting(self, *a, **k):
        calls.append(1)
        return original(self, *a, **k)

    with patch.object(pypdf.PageObject, "extract_text", counting):
        assert len(extract_pdf_images(data)) == 1

    assert len(calls) == 1


def test_pdf_images_use_distinct_anchors_when_pages_share_a_long_header():
    from app.extraction import extract_pdf_images

    header = "Kolumnentitel der Schriftenreihe zur Selbstorganisation und Fuehrung in Teams 2026"
    assert len(header) > 80

    def page(body, color):
        return header + "\n" + body, [(_png((300, 300), color), (100, 100))]

    import fitz

    doc = fitz.open()
    for body, color in (("Erste Seite handelt von Budgets.", (1, 2, 3)), ("Zweite Seite handelt von Teams.", (9, 8, 7))):
        pg = doc.new_page(width=595, height=842)
        pg.insert_text((30, 40), header, fontsize=7)
        pg.insert_text((30, 60), body, fontsize=9)
        pg.insert_image(fitz.Rect(50, 100, 150, 200), stream=_png((300, 300), color))
    result = extract_pdf_images(doc.tobytes())

    assert len(result) == 2
    assert result[0]["anchor"] != result[1]["anchor"]
    assert "Seite" in result[0]["anchor"] and "Seite" in result[1]["anchor"]


def test_web_images_drop_cdn_thumbnails_and_banner_logos():
    """Bug (2026-10-25, Screenshot DEV): Substack-Kopf mit 40x40-Avatar
    (w_40,h_40 im CDN-Pfad, Original 1280x1280) und Schriftzug-Banner
    (Original 1600x334) landeten in der Bildleiste."""
    cdn = "https://substackcdn.com/image/fetch/$s_!x!,{params}/https%3A%2F%2Fs3.amazonaws.com%2Fimages%2F{name}"
    body = "".join(
        f'<img src="{cdn.format(params=p, name=n)}" alt="News from the Beta World">'
        for p, n in (
            ("w_40,h_40,c_fill,f_auto", "a_1280x1280.png"),
            ("h_206,c_limit,f_auto", "b_1600x334.png"),
            ("w_2400,c_limit,f_auto", "c_2000x1261.jpeg"),
        )
    )
    assert [img["url"].split("%2F")[-1] for img in _web_images(body)] == ["c_2000x1261.jpeg"]


def test_web_images_drop_banner_by_attributes():
    assert _web_images('<img src="/band.jpg" width="1600" height="300" alt="Schriftzug der Seite">') == []


def test_web_images_drop_video_previews():
    """Nutzerwunsch (2026-10-25): YouTube-Vorschauen stiften keinen Wert -
    Bild mit Link auf ein Video oder von einem Video-Bildserver fällt weg."""
    body = (
        '<a href="https://www.youtube.com/watch?v=E1ugSiDZ4ec"><img src="/vorschau.jpg" width="800" height="450" alt="Video zur Struktur"></a>'
        '<a href="https://youtu.be/abc"><img src="/vorschau2.jpg" width="800" height="450" alt="Video zur Struktur"></a>'
        '<img src="https://i.ytimg.com/vi/abc/maxresdefault.jpg" width="800" height="450" alt="Video zur Struktur">'
        '<a href="https://vimeo.com/123"><img src="/vorschau3.jpg" width="800" height="450" alt="Video zur Struktur"></a>'
        '<a href="/bilder/gross.jpg"><img src="/gut.jpg" width="800" height="450" alt="Foto zur Struktur"></a>'
    )
    assert [img["url"] for img in _web_images(body)] == ["https://example.org/gut.jpg"]
