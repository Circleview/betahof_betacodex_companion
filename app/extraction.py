import io
import json
import re
import urllib.request
from urllib.parse import parse_qs, urlparse

import trafilatura
from pypdf import PdfReader
from youtube_transcript_api import YouTubeTranscriptApi


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


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _fetch_youtube_metadata(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
        return {"title": "", "author": "", "date": "", "text": "", "extracted": False}

    api = YouTubeTranscriptApi()
    try:
        try:
            fetched = api.fetch(video_id, languages=["de", "en"])
        except Exception:
            transcript_list = api.list(video_id)
            transcript = next(iter(transcript_list))
            fetched = transcript.fetch()
    except Exception:
        return {"title": "", "author": "", "date": "", "text": "", "extracted": False}

    text = "\n".join(f"[{_format_timestamp(s.start)}] {s.text}" for s in fetched).strip()
    metadata = _fetch_youtube_metadata(url)

    return {
        "title": metadata["title"],
        "author": "",
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
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.headers.get("Content-Type", "").lower().startswith("audio/")
    except Exception:
        return False


def download_audio_bytes(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
    return {
        "title": _guess_title_from_url(url),
        "author": "",
        "date": "",
        "text": "",
        "extracted": False,
    }


def looks_like_pdf(url: str) -> bool:
    if url.lower().split("?")[0].endswith(".pdf"):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return "application/pdf" in resp.headers.get("Content-Type", "").lower()
    except Exception:
        return False


def download_pdf_bytes(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception:
        return None


def _parse_pdf_date(raw: str | None) -> str:
    if not raw:
        return ""
    match = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def extract_pdf(data: bytes) -> dict:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return {"title": "", "author": "", "date": "", "text": "", "extracted": False}

    meta = reader.metadata
    title = (meta.title or "").strip() if meta and meta.title else ""
    author = (meta.author or "").strip() if meta and meta.author else ""
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
        "author": author,
        "date": date,
        "text": text,
        "extracted": bool(text),
    }


def extract_from_url(url: str) -> dict:
    if _is_youtube_url(url):
        return _extract_youtube(url)

    if looks_like_audio(url):
        return _extract_audio(url)

    if looks_like_pdf(url):
        data = download_pdf_bytes(url)
        if not data:
            return {"title": "", "author": "", "date": "", "text": "", "extracted": False}
        return extract_pdf(data)

    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception:
        downloaded = None

    if not downloaded:
        return {"title": "", "author": "", "date": "", "text": "", "extracted": False}

    metadata_json = trafilatura.extract(
        downloaded,
        url=url,
        output_format="json",
        with_metadata=True,
        favor_precision=True,
    )
    if not metadata_json:
        return {"title": "", "author": "", "date": "", "text": "", "extracted": False}

    data = json.loads(metadata_json)
    text = (data.get("text") or "").strip()
    return {
        "title": data.get("title") or "",
        "author": data.get("author") or "",
        "date": data.get("date") or "",
        "text": text,
        "extracted": bool(text),
    }
