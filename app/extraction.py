import base64
import io
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import trafilatura
from openai import OpenAI
from pypdf import PdfReader
from youtube_transcript_api import YouTubeTranscriptApi

# Manche Server (Bot-/Hotlink-Schutz, z.B. bei WordPress-gehosteten Podcast-
# Medien) lehnen Requests ohne "Accept"-Header mit HTTP 406 ab, selbst mit
# plausiblem User-Agent - ein echter Browser schickt diesen Header immer mit.
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def _split_authors(raw: str) -> list[str]:
    """Zerlegt einen extrahierten Autoren-String an gängigen Trennern in
    einzelne Namen (Best-effort-Heuristik - Nutzer:innen können über die
    "+"-Felder im Formular jederzeit manuell korrigieren/ergänzen)."""
    if not raw or not raw.strip():
        return []
    parts = re.split(r";|,| und | and |&", raw)
    return [p.strip() for p in parts if p.strip()]


def _is_youtube_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "youtube.com" in host or "youtu.be" in host


def _extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        return parsed.path.strip("/").split("/")[0] or None
    if "youtube.com" in host:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[1].split("/")[0] or None
    return None


def _fetch_youtube_metadata(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return {"title": "", "date": ""}

    title_match = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    date_match = re.search(r'<meta itemprop="datePublished" content="([^"]*)"', html)
    return {
        "title": title_match.group(1) if title_match else "",
        "date": date_match.group(1)[:10] if date_match else "",
    }


def _extract_youtube(url: str) -> dict:
    video_id = _extract_video_id(url)
    if not video_id:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    api = YouTubeTranscriptApi()
    try:
        try:
            fetched = api.fetch(video_id, languages=["de", "en"])
        except Exception:
            transcript_list = api.list(video_id)
            transcript = next(iter(transcript_list))
            fetched = transcript.fetch()
    except Exception:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    # Fließtext statt Zeilen mit Zeitstempel-Präfix - für die spätere
    # Verwendung als Antwort-Kontext ist der reine, lesbare Wortlaut
    # hilfreicher als eine mit Sprungmarken durchsetzte Liste.
    text = " ".join(s.text.strip() for s in fetched if s.text.strip())
    text = re.sub(r"\s+", " ", text).strip()
    metadata = _fetch_youtube_metadata(url)

    return {
        "title": metadata["title"],
        "authors": [],
        "date": metadata["date"],
        "text": text,
        "extracted": bool(text),
    }


AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")


def looks_like_audio(url: str) -> bool:
    path = url.lower().split("?")[0]
    if path.endswith(AUDIO_EXTENSIONS):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD", headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.headers.get("Content-Type", "").lower().startswith("audio/")
    except Exception:
        return False


def download_audio_bytes(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except Exception:
        return None


def _guess_title_from_url(url: str) -> str:
    path = urlparse(url).path
    stem = path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.[a-zA-Z0-9]+$", "", stem)
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem.capitalize() if stem else ""


def _extract_audio(url: str) -> dict:
    """Liefert nur den aus der URL geratenen Titel, ohne Download/
    Transkription - Audio-Transkription kann mehrere Minuten dauern und
    läuft deshalb ausschließlich als Hintergrund-Job NACH dem Anlegen der
    Quelle (siehe app/main.py: _process_audio_transcription), damit die
    Vorschau (POST /api/extract-url) schnell bleibt."""
    return {
        "title": _guess_title_from_url(url),
        "authors": [],
        "date": "",
        "text": "",
        "extracted": False,
    }


# Von gpt-4o-transcribe-diarize unterstützte Formate (Sprechererkennung).
# flac/ogg sind zwar Teil von AUDIO_EXTENSIONS (Wiedergabe/Speicherung),
# aber von diesem Modell nicht unterstützt - dafür Fallback auf whisper-1
# (Transkription ohne Sprecher-Label, siehe _transcribe_chunk).
_DIARIZE_EXTENSIONS = (".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm")

AUDIO_UPLOAD_MAX_BYTES = 25 * 1024 * 1024

_openai_client = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def _format_diarized_text(result) -> str:
    speaker_labels: dict[str, str] = {}
    lines = []
    for segment in result.segments:
        label = speaker_labels.setdefault(segment.speaker, f"Sprecher {len(speaker_labels) + 1}")
        text = segment.text.strip()
        if text:
            lines.append(f"{label}: {text}")
    return "\n\n".join(lines)


def _transcribe_chunk(data: bytes, filename: str) -> str:
    """Transkribiert eine einzelne Audiodatei (muss innerhalb des
    OpenAI-Größenlimits liegen, siehe AUDIO_UPLOAD_MAX_BYTES). Gibt bei
    jedem Fehler (API-Fehler, nicht unterstütztes Format, fehlender Key,
    Netzwerkfehler) einen leeren String zurück statt zu crashen - gleiche
    defensive Konvention wie download_audio_bytes/looks_like_audio."""
    extension = Path(filename).suffix.lower()
    client = _get_openai_client()
    try:
        if extension in _DIARIZE_EXTENSIONS:
            result = client.audio.transcriptions.create(
                model="gpt-4o-transcribe-diarize",
                file=(filename, data),
                response_format="diarized_json",
                chunking_strategy="auto",
            )
            return _format_diarized_text(result)

        result = client.audio.transcriptions.create(
            model="whisper-1",
            file=(filename, data),
            response_format="text",
        )
        return str(result).strip()
    except Exception:
        return ""


def _audio_duration_seconds(path: Path) -> float | None:
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return float(completed.stdout.strip())
    except Exception:
        return None


def split_audio_file(path: Path, max_bytes: int = AUDIO_UPLOAD_MAX_BYTES) -> list[Path]:
    """Zerlegt eine Audiodatei in verlustfreie Zeit-Abschnitte, falls sie
    über max_bytes liegt (sonst wird der Originalpfad unverändert
    zurückgegeben, ohne ffmpeg aufzurufen). Die Segment-Dauer wird grob aus
    Dateigröße/Gesamtdauer geschätzt, mit Sicherheitsmarge (70% des Limits),
    damit übliche Sprach-Bitraten sicher darunter bleiben."""
    size = path.stat().st_size
    if size <= max_bytes:
        return [path]

    duration = _audio_duration_seconds(path)
    if not duration:
        return [path]

    bytes_per_second = size / duration
    segment_seconds = max(int((max_bytes * 0.7) / bytes_per_second), 30)

    output_dir = Path(tempfile.mkdtemp(prefix="audio_split_"))
    pattern = output_dir / f"chunk_%03d{path.suffix}"
    try:
        subprocess.run(
            [
                "ffmpeg", "-i", str(path),
                "-f", "segment", "-segment_time", str(segment_seconds),
                "-c", "copy", "-reset_timestamps", "1",
                str(pattern),
            ],
            capture_output=True,
            timeout=600,
            check=True,
        )
    except Exception:
        return [path]

    segments = sorted(output_dir.glob(f"chunk_*{path.suffix}"))
    return segments or [path]


def transcribe_audio(path: Path) -> str:
    """Transkribiert eine Audiodatei beliebiger Größe: Dateien über dem
    OpenAI-Limit werden zuerst per split_audio_file() in Abschnitte
    aufgeteilt, jeder Abschnitt einzeln transkribiert und die Ergebnisse zu
    einem zusammenhängenden Text verkettet. Sprecher-Nummerierung wird pro
    Abschnitt neu vergeben (keine Kontinuität über Abschnittsgrenzen
    hinweg möglich)."""
    segments = split_audio_file(path)
    is_split = len(segments) > 1 or (segments and segments[0] != path)
    texts = []
    for segment_path in segments:
        text = _transcribe_chunk(segment_path.read_bytes(), segment_path.name)
        if text:
            texts.append(text)

    if is_split:
        shutil.rmtree(segments[0].parent, ignore_errors=True)

    if len(texts) <= 1:
        return texts[0] if texts else ""
    return "\n\n".join(f"--- Teil {i + 1} ---\n\n{text}" for i, text in enumerate(texts))


def looks_like_pdf(url: str) -> bool:
    if url.lower().split("?")[0].endswith(".pdf"):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD", headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return "application/pdf" in resp.headers.get("Content-Type", "").lower()
    except Exception:
        return False


def download_pdf_bytes(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception:
        return None


def _parse_pdf_date(raw) -> str:
    # Bei PDFs mit beschädigter/nicht standardkonformer Xref-Tabelle (pypdf
    # loggt dann "Ignoring wrong pointing object ...") liefert meta.get(...)
    # gelegentlich ein unaufgelöstes IndirectObject statt eines Strings -
    # ohne diese Prüfung crashte re.match mit TypeError und riss den
    # gesamten Extraktions-Request (inkl. Seitentext) mit sich.
    if not raw or not isinstance(raw, str):
        return ""
    match = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def extract_pdf(data: bytes) -> dict:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    meta = reader.metadata
    title = (meta.title or "").strip() if meta and meta.title else ""
    author_raw = (meta.author or "").strip() if meta and meta.author else ""
    authors = _split_authors(author_raw)
    date = _parse_pdf_date(meta.get("/CreationDate")) if meta else ""

    text_parts = []
    for page in reader.pages:
        try:
            text_parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = "\n".join(part for part in text_parts if part).strip()

    return {
        "title": title,
        "authors": authors,
        "date": date,
        "text": text,
        "extracted": bool(text),
    }


# Für PDFs ohne eingebettete Text-Ebene (typischerweise ältere, gescannte
# Quellen - extract_pdf() liefert dafür text="" zurück, siehe oben). Nutzt
# denselben Anthropic-Client/dasselbe Modell wie app/summarization.py statt
# eines separaten OCR-Anbieters, da bereits eine funktionierende
# API-Key-Konfiguration dafür existiert.
_OCR_MODEL_NAME = "claude-haiku-4-5-20251001"

_OCR_SYSTEM_PROMPT = """Du transkribierst den sichtbaren Text einer gescannten Buch-/Artikelseite exakt und vollständig, ohne eigene Ergänzungen, Kommentare oder Zusammenfassungen.

Antworte AUSSCHLIESSLICH mit dem erkannten Text - keine Einleitung, keine Beschreibung des Layouts, keine Anführungszeichen. Enthält die Seite keinen lesbaren Fließtext (z.B. leere Seite, reines Bild/Diagramm ohne Text), antworte mit einem leeren String."""

_anthropic_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


def _render_pdf_pages_to_images(data: bytes, dpi: int = 150) -> list[bytes]:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        return [page.get_pixmap(matrix=matrix).tobytes("png") for page in doc]
    finally:
        doc.close()


def _ocr_page(image_bytes: bytes) -> str:
    """Transkribiert eine einzelne Seite. Gibt bei jedem Fehler (API-Fehler,
    fehlender Key, Netzwerkfehler) einen leeren String zurück statt zu
    crashen - gleiche defensive Konvention wie _transcribe_chunk."""
    client = _get_anthropic_client()
    try:
        message = client.messages.create(
            model=_OCR_MODEL_NAME,
            max_tokens=4096,
            system=_OCR_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.b64encode(image_bytes).decode(),
                            },
                        },
                        {"type": "text", "text": "Transkribiere den Text dieser Seite."},
                    ],
                }
            ],
        )
        return message.content[0].text.strip()
    except Exception:
        return ""


def ocr_pdf_with_ai(data: bytes) -> str:
    """Texterkennung per KI-Vision für gescannte PDFs ohne Text-Ebene (siehe
    extract_pdf()). Rendert jede Seite als Bild und lässt das Modell den
    sichtbaren Text transkribieren - kann pro Seite mehrere Sekunden dauern,
    läuft deshalb als Hintergrund-Job (siehe _process_pdf_ocr in
    app/main.py) statt die Vorschau/das Anlegen der Quelle zu blockieren."""
    try:
        pages = _render_pdf_pages_to_images(data)
    except Exception:
        return ""
    texts = [_ocr_page(page) for page in pages]
    return "\n\n".join(t for t in texts if t)


def _parse_markdown_extraction(raw: str) -> dict:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.DOTALL)
    if not match:
        return {"title": "", "authors": [], "date": "", "text": raw.strip()}

    frontmatter, body = match.group(1), match.group(2)
    meta = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    return {
        "title": meta.get("title", ""),
        "authors": _split_authors(meta.get("author", "")),
        "date": meta.get("date", ""),
        "text": body.strip(),
    }


def extract_from_url(url: str) -> dict:
    if _is_youtube_url(url):
        return _extract_youtube(url)

    if looks_like_audio(url):
        return _extract_audio(url)

    if looks_like_pdf(url):
        data = download_pdf_bytes(url)
        if not data:
            return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}
        return extract_pdf(data)

    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception:
        downloaded = None

    if not downloaded:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    markdown_result = trafilatura.extract(
        downloaded,
        url=url,
        output_format="markdown",
        with_metadata=True,
        favor_precision=True,
    )
    if not markdown_result:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    parsed = _parse_markdown_extraction(markdown_result)
    text = parsed["text"].strip()
    return {
        "title": parsed["title"],
        "authors": parsed["authors"],
        "date": parsed["date"],
        "text": text,
        "extracted": bool(text),
    }
