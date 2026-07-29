import hmac
import json
import os
import queue
import re
import subprocess
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app import (
    audit,
    auth,
    author_profiles,
    authors,
    captcha,
    chunking,
    embeddings,
    extraction,
    i18n,
    llm,
    mail,
    monitoring,
    ratelimit,
    summarization,
    terms,
    tts,
    users,
    vectorstore,
)
from app.models import (
    AdminUserOut,
    AuditLogEntryOut,
    AuthorOut,
    AuthorProfileIn,
    BioOut,
    AuthorBioPreviewIn,
    RenameAuthorIn,
    ChunkRef,
    EarlyAccessIn,
    ExtractedSource,
    ExtractedUpload,
    FeedbackIn,
    ImportJobOut,
    InviteIn,
    MessageOut,
    QuestionIn,
    RequestLinkIn,
    SourceIn,
    SourceOut,
    SpeechIn,
    SummaryOut,
    TermOut,
    TurnstileConfigOut,
    UpdateUserNameIn,
    UrlCheckOut,
    UrlIn,
    VersionOut,
    WhoAmIOut,
)

# "development": Cookies werden ohne "Secure"-Flag gesetzt, damit Logins auch
# über http://localhost funktionieren (siehe .env.example).
IS_DEV_ENVIRONMENT = os.environ.get("ENVIRONMENT", "").strip().lower() == "development"

# Der Site-Key ist (anders als TURNSTILE_SECRET_KEY) öffentlich und für den
# Turnstile-Mechanismus ausdrücklich dafür gedacht, im Frontend zu landen -
# über /api/turnstile-config statt fest ins JS einkompiliert, damit Dev/Stabil/
# Produktion unterschiedliche, zum jeweiligen Hostnamen passende Keys nutzen
# können (ein Produktions-Site-Key akzeptiert z.B. kein localhost - siehe
# .env.example für Cloudflares offizielle Test-Keys für die lokale Entwicklung).
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")


def _get_current_user_email(request: Request) -> str | None:
    return auth.verify_session_token(request.cookies.get(auth.SESSION_COOKIE_NAME))


def require_role(role: str):
    def check(request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
        email = _get_current_user_email(request)
        if not users.has_role(email, role):
            raise HTTPException(
                403,
                i18n.get_message("role_required", x_lang, role=role, user=email or "anon"),
            )
        return email

    return check


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SOURCES_FILE = DATA_DIR / "sources.json"
STATIC_DIR = BASE_DIR / "static"
PDF_DIR = DATA_DIR / "pdfs"
PDF_UPLOAD_STAGING_DIR = DATA_DIR / "pdf_uploads"
AUDIO_DIR = DATA_DIR / "audio"
AUDIO_UPLOAD_STAGING_DIR = DATA_DIR / "audio_uploads"

DATA_DIR.mkdir(exist_ok=True)
users.ensure_bootstrap_admin(os.environ.get("SYSTEM_ADMIN_EMAIL", ""))


def _get_version() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "describe", "--tags", "--abbrev=0"],
                cwd=BASE_DIR,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "dev"


APP_VERSION = _get_version()

app = FastAPI(title="BetaCodex Wissensassistent")


# Backlog #58: einzige externe Host, die die App tatsächlich als Ressource
# einbindet, ist Cloudflare Turnstile (Skript + das von ihm erzeugte iFrame).
# img-src erlaubt bewusst beliebige https-Quellen, weil Autor:innen-Fotos
# (photo_url) frei eingetragene externe URLs sind - eine engere Regel würde
# dieses bestehende Feature brechen. Keine Inline-Skripte nötig (siehe
# init-footer.js), daher script-src ohne 'unsafe-inline'.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://challenges.cloudflare.com; "
    "style-src 'self'; "
    "img-src 'self' data: https:; "
    "font-src 'self'; "
    # blob: für die per URL.createObjectURL() erzeugte Audio-Blob-URL beim
    # Abspielen der TTS-Antwort (Backlog #49, siehe static/speech.js) - ohne
    # dieses Directive würde die strikte default-src-Regel das <audio>-
    # Element sonst blockieren.
    "media-src 'self' blob:; "
    "connect-src 'self' https://challenges.cloudflare.com; "
    "frame-src https://challenges.cloudflare.com; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    # Backlog #115: vor dem öffentlichen Livegang soll diese Instanz nicht in
    # Suchmaschinen-/KI-Indizes auftauchen - deckt (anders als die HTML-
    # Meta-Tags) auch Nicht-HTML-Antworten ab. Vor dem eigentlichen Go-Live
    # bewusst wieder entfernen.
    response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


# Backlog #114: Pfade, die auch bei aktiver Early-Access-Sperre erreichbar
# bleiben müssen - die Gate-Seite selbst, ihr JS, der Freischalt-Endpoint und
# die für ihre Darstellung nötigen, bereits bestehenden statischen Assets.
# Bewusst eine kleine, feste Liste statt eines Musters/Präfix-Checks - jeder
# zusätzliche Eintrag hier ist eine bewusste Entscheidung, kein Nebeneffekt.
_EARLY_ACCESS_EXEMPT_PATHS = {
    "/early-access.html",
    "/early-access.js",
    "/api/early-access",
    "/style.css",
    "/i18n.js",
    "/i18n/de.json",
    "/i18n/en.json",
}


@app.middleware("http")
async def enforce_early_access(request: Request, call_next):
    # Bewusst pro Anfrage aus os.environ gelesen (nicht als Modul-Konstante
    # beim Start zwischengespeichert) - analog zu captcha.verify_turnstile_token:
    # ohne gesetzten Wert (Dev/Stabil) bleibt die Sperre inaktiv, die App
    # funktioniert exakt wie zuvor. Erst auf dem künftigen Produktiv-Server,
    # wo dieser Wert gesetzt wird, greift sie.
    early_access_password = os.environ.get("EARLY_ACCESS_PASSWORD", "")
    if early_access_password and request.url.path not in _EARLY_ACCESS_EXEMPT_PATHS:
        if not auth.verify_early_access_token(request.cookies.get(auth.EARLY_ACCESS_COOKIE_NAME)):
            return FileResponse(STATIC_DIR / "early-access.html")
    return await call_next(request)


@app.post("/api/early-access")
def submit_early_access_password(
    body: EarlyAccessIn, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)
):
    # Ein einziges, allen bekanntes Passwort ist ein klassisches Brute-Force-
    # Ziel - deutlich strenger begrenzt als das allgemeine /api/ask-Limit
    # (siehe ratelimit.is_rate_limited), eigener Schlüssel-Namensraum, damit
    # sich beide Limits nicht gegenseitig beeinflussen.
    client_ip = request.client.host if request.client else "unknown"
    if ratelimit.is_rate_limited(f"early-access:{client_ip}", max_requests=5, window_seconds=300):
        raise HTTPException(429, i18n.get_message("early_access_rate_limited", x_lang))

    expected_password = os.environ.get("EARLY_ACCESS_PASSWORD", "")
    if not expected_password or not hmac.compare_digest(body.password, expected_password):
        raise HTTPException(401, i18n.get_message("early_access_wrong_password", x_lang))

    response = Response(status_code=204)
    response.set_cookie(
        auth.EARLY_ACCESS_COOKIE_NAME,
        auth.create_early_access_token(),
        max_age=auth.EARLY_ACCESS_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=not IS_DEV_ENVIRONMENT,
        path="/",
    )
    return response


@app.get("/api/version", response_model=VersionOut)
def get_version():
    return VersionOut(version=APP_VERSION)


@app.get("/api/turnstile-config", response_model=TurnstileConfigOut)
def get_turnstile_config():
    return TurnstileConfigOut(site_key=TURNSTILE_SITE_KEY)


def _load_sources() -> dict:
    if not SOURCES_FILE.exists():
        return {}
    sources = json.loads(SOURCES_FILE.read_text())
    for entry in sources.values():
        if "authors" not in entry:
            # Migration vom alten einzelnen "author"-Feld auf eine Liste -
            # läuft transparent bei jedem Laden mit, kein separates Skript
            # nötig. Beim nächsten Speichern ist der Datensatz bereinigt.
            old_author = entry.pop("author", None)
            entry["authors"] = [old_author] if old_author else []
    return sources


def _save_sources(sources: dict) -> None:
    # Atomar schreiben (Temp-Datei + Rename statt direktem write_text):
    # write_text() truncatet die Datei zuerst und schreibt dann - liest ein
    # anderer Thread währenddessen (siehe _finish_synchronous_import, das
    # parallel zum Request-Thread auf sources.json zugreift), bekommt er
    # eine leere/unvollständige Datei und _load_sources() crasht mit
    # JSONDecodeError. os.replace() ist auf POSIX-Systemen atomar - ein
    # gleichzeitiger Leser sieht immer entweder die alte oder die neue
    # vollständige Version, nie einen Zwischenzustand.
    #
    # Der Temp-Dateiname MUSS je Aufruf eindeutig sein (siehe reales
    # Datenverlust-Vorkommnis 2026-07-28): teilten sich zwei gleichzeitige
    # Schreibvorgänge denselben Temp-Pfad, konnte Schreibvorgang B den
    # Temp-Dateiinhalt von Schreibvorgang A überschreiben, BEVOR A
    # umbenennt - A's replace() hätte dann B's (evtl. kleineren/älteren)
    # Datensatz "gewonnen", nicht A's eigenen. Das atomare Rename schützt
    # nur EINEN Schreiber vor kaputten Lesevorgängen, nicht mehrere
    # Schreiber voreinander.
    tmp_path = SOURCES_FILE.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp_path.write_text(json.dumps(sources, ensure_ascii=False, indent=2))
    tmp_path.replace(SOURCES_FILE)


def _prepare_chunks(source: SourceIn, lang: str) -> tuple[list[str], list[list[float]]]:
    text = source.text.strip()
    if not text:
        raise HTTPException(400, i18n.get_message("text_empty", lang))

    chunks = chunking.chunk_text(text)
    if not chunks:
        raise HTTPException(400, i18n.get_message("no_chunks", lang))

    chunk_embeddings = embeddings.embed_passages(chunks)
    return chunks, chunk_embeddings


def _consume_pdf_upload(source_id: str, upload_id: str) -> None:
    staged_path = PDF_UPLOAD_STAGING_DIR / f"{upload_id}.pdf"
    if not staged_path.exists():
        return
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    staged_path.replace(PDF_DIR / f"{source_id}.pdf")


def _sync_pdf_file_from_url(source_id: str, url: str | None) -> None:
    pdf_path = PDF_DIR / f"{source_id}.pdf"
    if url and extraction.looks_like_pdf(url):
        data = extraction.download_pdf_bytes(url)
        if data:
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(data)
            return
    if pdf_path.exists():
        pdf_path.unlink()


def _delete_pdf_file(source_id: str) -> None:
    pdf_path = PDF_DIR / f"{source_id}.pdf"
    if pdf_path.exists():
        pdf_path.unlink()


def _existing_pdf_file(source_id: str) -> Path | None:
    pdf_path = PDF_DIR / f"{source_id}.pdf"
    return pdf_path if pdf_path.exists() else None


def _audio_extension(url: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    return suffix if suffix in extraction.AUDIO_EXTENSIONS else ".mp3"


def _existing_audio_file(source_id: str) -> Path | None:
    matches = list(AUDIO_DIR.glob(f"{source_id}.*"))
    return matches[0] if matches else None


def _sync_audio_file_from_url(source_id: str, url: str | None) -> None:
    existing = _existing_audio_file(source_id)
    if url and extraction.looks_like_audio(url):
        data = extraction.download_audio_bytes(url)
        if data:
            AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            if existing:
                existing.unlink()
            (AUDIO_DIR / f"{source_id}{_audio_extension(url)}").write_bytes(data)
            return
    if existing:
        existing.unlink()


def _delete_audio_file(source_id: str) -> None:
    existing = _existing_audio_file(source_id)
    if existing:
        existing.unlink()


def _guess_title_from_filename(filename: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem.capitalize() if stem else ""


def _consume_audio_upload(source_id: str, upload_id: str) -> None:
    matches = list(AUDIO_UPLOAD_STAGING_DIR.glob(f"{upload_id}.*"))
    if not matches:
        return
    staged_path = matches[0]
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    _delete_audio_file(source_id)
    staged_path.replace(AUDIO_DIR / f"{source_id}{staged_path.suffix}")


_AUDIO_MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
}


def _store_chunks(
    source_id: str, source: SourceIn, chunks: list[str], chunk_embeddings: list[list[float]]
) -> int:
    chunk_ids = [f"{source_id}::{i}" for i in range(len(chunks))]
    metadatas = []
    for i in range(len(chunks)):
        metadata = {
            "source_id": source_id,
            "title": source.title,
            "date": source.date or "",
            "url": source.url or "",
            "listen_url": source.listen_url or "",
            "position": i,
        }
        # ChromaDB-Metadata-Listen dürfen nicht leer sein - bei keinem Autor
        # den Schlüssel ganz weglassen statt "authors": [].
        if source.authors:
            metadata["authors"] = source.authors
        metadatas.append(metadata)
    vectorstore.add_chunks(chunk_ids, chunks, chunk_embeddings, metadatas)
    return len(chunks)


def _to_source_out(
    entry: dict, can_view_full_text: bool = False, lang: str = i18n.DEFAULT_LANG
) -> SourceOut:
    data = dict(entry)
    if data.get("restricted") and not can_view_full_text:
        data["text"] = ""
    lang = lang if lang in ("de", "en") else i18n.DEFAULT_LANG
    data["summary"] = data.get(f"summary_{lang}") or ""
    data["key_terms"] = data.get(f"key_terms_{lang}") or []
    data["has_pdf"] = (PDF_DIR / f"{data['id']}.pdf").exists()
    data["has_audio"] = _existing_audio_file(data["id"]) is not None
    return SourceOut(**data)


def _register_all_terms(source_id: str, entry: dict) -> None:
    terms.unregister_source(source_id)
    for term in (entry.get("key_terms_de") or []) + (entry.get("key_terms_en") or []):
        terms.register_term(term, source_id)


def _generate_summary_background(source_id: str, text: str) -> None:
    result = summarization.generate_bilingual_summary(text)
    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            return
        sources[source_id]["summary_de"] = result["de"]["summary"]
        sources[source_id]["summary_en"] = result["en"]["summary"]
        sources[source_id]["key_terms_de"] = result["de"]["key_terms"]
        sources[source_id]["key_terms_en"] = result["en"]["key_terms"]
        _save_sources(sources)
        _register_all_terms(source_id, sources[source_id])


def _is_deferred_audio_import(source: SourceIn) -> bool:
    """Audio-Transkription kann mehrere Minuten dauern - für diesen Fall
    wird die Quelle sofort mit leerem Text angelegt und der Text erst
    später per Hintergrund-Job (_process_audio_transcription) ergänzt,
    statt den Anlege-Request darauf warten zu lassen. Spiegelt dieselbe
    URL-vs-Upload-Priorität wie weiter unten in add_source (URL hat
    Vorrang vor audio_upload_id, wenn beides gesetzt ist)."""
    if source.text.strip() or source.pdf_upload_id:
        return False
    if source.url:
        return extraction.looks_like_audio(source.url)
    return bool(source.audio_upload_id)


def _is_deferred_pdf_import(source: SourceIn) -> bool:
    """PDF-Texterkennung per KI-Vision (siehe extraction.ocr_pdf_with_ai)
    kann pro Seite mehrere Sekunden dauern - für PDFs ohne extrahierbare
    Text-Ebene (typischerweise ältere, gescannte Quellen; extract_pdf()
    liefert dafür schon in der Vorschau leeren Text) wird die Quelle
    deshalb sofort mit leerem Text angelegt und der Text erst später per
    Hintergrund-Job (_process_pdf_ocr) ergänzt - analog zu
    _is_deferred_audio_import."""
    if source.text.strip():
        return False
    if source.pdf_upload_id:
        return True
    return bool(source.url) and extraction.looks_like_pdf(source.url)


# Serialisiert nur den kurzen "chunken + in Chroma schreiben"-Abschnitt
# von _process_audio_transcription - app/vectorstore.py hat selbst keine
# Locks, zwei gleichzeitig fertig werdende Hintergrund-Jobs könnten sich
# sonst beim Schreiben in die Vektor-DB in die Quere kommen. Download und
# Transkription laufen weiterhin unabhängig/parallel im Thread-Pool.
_vectorstore_write_lock = threading.Lock()

# Schützt JEDEN read-modify-write-Zyklus auf sources.json (_load_sources()
# ... _save_sources()), der aus einem Hintergrund-Thread heraus läuft
# (Audio-Transkription, PDF-OCR, Zusammenfassung, Autor:innen-Vita, der neue
# "langsamer Import"-Pfad). Ohne diesen Lock kann Thread A eine alte
# Momentaufnahme lesen, während Thread B currently schreibt - A's spätere
# _save_sources() überschreibt dann B's Änderung wieder (klassisches
# Lost-Update). Genau das führte am 2026-07-28 zu massivem Datenverlust in
# sources.json (127 auf 3 Quellen) - siehe auch die Absicherung gegen
# denselben Temp-Dateinamen in _save_sources().
_sources_write_lock = threading.Lock()


def _finalize_extracted_text(source_id: str, lang: str, text: str, failure_i18n_key: str) -> None:
    """Gemeinsamer Ablauf ab dem Punkt, an dem der Volltext einer Quelle
    feststeht (oder leer ist, siehe unten): chunkt/indiziert die Quelle,
    oder markiert sie bei leerem Text als Fehler. Wird sowohl von der PDF-
    Texterkennung (_run_deferred_text_extraction) als auch - nach
    vollständig erfolgreicher, ggf. mehrteiliger Transkription - von
    _process_audio_transcription aufgerufen."""
    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            return
        if not text:
            sources[source_id]["processing_status"] = "error"
            sources[source_id]["processing_step"] = None
            sources[source_id]["processing_error"] = i18n.get_message(failure_i18n_key, lang)
            _save_sources(sources)
            return

        sources[source_id]["processing_step"] = "chunking"
        _save_sources(sources)
    chunks = chunking.chunk_text(text)
    if not chunks:
        with _sources_write_lock:
            sources = _load_sources()
            if source_id not in sources:
                return
            sources[source_id]["processing_status"] = "error"
            sources[source_id]["processing_step"] = None
            sources[source_id]["processing_error"] = i18n.get_message("no_chunks", lang)
            _save_sources(sources)
        return

    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            return
        sources[source_id]["processing_step"] = "indexing"
        _save_sources(sources)
    chunk_embeddings = embeddings.embed_passages(chunks)

    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            return
        entry = sources[source_id]
        source_stub = SourceIn(
            title=entry["title"],
            authors=entry.get("authors", []),
            date=entry.get("date"),
            url=entry.get("url"),
            listen_url=entry.get("listen_url"),
            text=text,
            restricted=entry.get("restricted", False),
        )

        with _vectorstore_write_lock:
            vectorstore.delete_source_chunks(source_id)
            chunk_count = _store_chunks(source_id, source_stub, chunks, chunk_embeddings)

            sources = _load_sources()
            if source_id not in sources:
                return
            sources[source_id]["text"] = text
            sources[source_id]["chunk_count"] = chunk_count
            sources[source_id]["processing_status"] = None
            sources[source_id]["processing_step"] = None
            sources[source_id]["processing_error"] = None
            sources[source_id]["processing_segments"] = None
            _save_sources(sources)

    _generate_summary_background(source_id, text)


def _run_deferred_text_extraction(
    source_id: str,
    lang: str,
    initial_step: str,
    compute_text,
    failure_i18n_key: str,
) -> None:
    """Hintergrund-Job-Ablauf für die PDF-Texterkennung (_process_pdf_ocr):
    setzt den Verarbeitungsstatus, berechnet den Text in einem Rutsch
    (keine Mehrteiligkeit wie bei Audio nötig) und übergibt an
    _finalize_extracted_text."""
    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            return
        sources[source_id]["processing_status"] = "running"
        sources[source_id]["processing_step"] = initial_step
        _save_sources(sources)

    text = compute_text()
    _finalize_extracted_text(source_id, lang, text, failure_i18n_key)


def _process_audio_transcription(source_id: str, lang: str = i18n.DEFAULT_LANG) -> None:
    """Hintergrund-Job (siehe add_source): transkribiert eine bereits
    angelegte, aber noch textlose Audio-Quelle. Die Audiodatei liegt zu
    diesem Zeitpunkt schon in AUDIO_DIR (add_source lädt/speichert sie
    synchron, nur die Transkription selbst ist der langsame Teil).

    Anders als _run_deferred_text_extraction (PDF) läuft hier ein eigener
    Ablauf, weil eine lange Audiodatei aus mehreren, EINZELN bezahlten
    OpenAI-Aufrufen besteht (siehe extraction.transcribe_audio): bereits
    erfolgreiche Abschnitte werden aus einem vorherigen Versuch übernommen
    (processing_segments) und nach jedem neu erfolgreichen Abschnitt sofort
    gespeichert - ein erneuter "Retry" nach einem teilweisen Fehlschlag
    bezahlt so nicht für bereits erledigte Abschnitte erneut."""
    audio_path = _existing_audio_file(source_id)

    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            return
        entry = sources[source_id]
        entry["processing_status"] = "running"
        entry["processing_step"] = "transcribe"
        known_segments = {int(k): v for k, v in (entry.get("processing_segments") or {}).items()}
        _save_sources(sources)

    def on_segment_success(index: int, total: int, segment_text: str) -> None:
        with _sources_write_lock:
            sources = _load_sources()
            if source_id not in sources:
                return
            segments = sources[source_id].get("processing_segments") or {}
            segments[str(index)] = segment_text
            sources[source_id]["processing_segments"] = segments
            _save_sources(sources)

    if audio_path is None:
        text, error_detail = "", None
    else:
        text, error_detail = extraction.transcribe_audio(
            audio_path, known_segments=known_segments, on_segment_success=on_segment_success
        )

    if error_detail:
        with _sources_write_lock:
            sources = _load_sources()
            if source_id not in sources:
                return
            # processing_segments bleibt bewusst erhalten - siehe Docstring:
            # ein erneuter Versuch soll die schon erfolgreichen Abschnitte
            # wiederverwenden statt sie erneut zu bezahlen.
            sources[source_id]["processing_status"] = "error"
            sources[source_id]["processing_step"] = None
            sources[source_id]["processing_error"] = i18n.get_message(
                "audio_segment_failed", lang, detail=error_detail
            )
            _save_sources(sources)
        return

    _finalize_extracted_text(source_id, lang, text, "audio_transcription_failed")


def _process_pdf_ocr(source_id: str, lang: str = i18n.DEFAULT_LANG) -> None:
    """Hintergrund-Job (siehe add_source): erkennt per KI-Vision den Text
    einer bereits angelegten, aber noch textlosen PDF-Quelle ohne
    extrahierbare Text-Ebene (typischerweise ältere, gescannte Dateien -
    siehe extraction.ocr_pdf_with_ai). Die PDF-Datei liegt zu diesem
    Zeitpunkt schon in PDF_DIR (add_source speichert sie synchron, nur die
    Texterkennung selbst ist der langsame Teil) - analog zu
    _process_audio_transcription."""
    pdf_path = _existing_pdf_file(source_id)
    _run_deferred_text_extraction(
        source_id,
        lang,
        initial_step="ocr",
        compute_text=lambda: extraction.ocr_pdf_with_ai(pdf_path.read_bytes()) if pdf_path else "",
        failure_i18n_key="pdf_ocr_failed",
    )


# Backlog #113: Audio-Transkriptionen liefen bisher völlig unbegrenzt
# parallel (jeder add_source-Request startete sofort seinen eigenen
# Hintergrund-Job) - beim gleichzeitigen Import vieler Audios (23 auf
# einmal, realer Vorfall 2026-07-28) sendet das entsprechend viele
# gleichzeitige, kostenpflichtige OpenAI-Aufrufe los und kann das Budget
# aufbrauchen, bevor auch nur eine einzige Datei fertig transkribiert ist.
# Ein einzelner Worker-Thread verarbeitet die Warteschlange strikt
# nacheinander - eine noch nicht dran gekommene Quelle bleibt einfach auf
# ihrem bereits bestehenden "pending"-Status (siehe _create_pending_source),
# bis der Worker sie tatsächlich aufgreift und auf "running" setzt. PDF-
# Texterkennung ist bewusst NICHT betroffen (nicht Teil des gemeldeten
# Vorfalls, weiterhin über background_tasks wie zuvor).
_audio_transcription_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()


def _audio_transcription_worker() -> None:
    while True:
        source_id, lang = _audio_transcription_queue.get()
        try:
            _process_audio_transcription(source_id, lang)
        except Exception:
            # Ein unerwarteter Fehler hier darf den Worker nicht beenden -
            # sonst bliebe die gesamte restliche Warteschlange für den Rest
            # der Prozess-Laufzeit stehen. _run_deferred_text_extraction
            # fängt reguläre Fehler (z.B. OpenAI-Kontingent) bereits selbst
            # ab und setzt "error" - dies ist nur das allerletzte Netz.
            pass
        finally:
            _audio_transcription_queue.task_done()


threading.Thread(target=_audio_transcription_worker, daemon=True).start()


def _recover_interrupted_processing_jobs() -> None:
    """Nach einem Server-Neustart läuft kein Hintergrund-Job mehr, dessen
    Quelle noch auf "running" steht - kein Auto-Resume (unklar, wie weit
    er kam), stattdessen klar als Fehler markieren, damit ein Re-Import
    bewusst manuell angestoßen wird (siehe POST /.../reprocess).

    Audio-Quellen, die noch auf "pending" stehen (Backlog #113: warten in
    _audio_transcription_queue, bevor sie überhaupt angefangen haben),
    werden dagegen automatisch neu eingereiht - die In-Memory-Warteschlange
    selbst überlebt einen Neustart nicht, ohne dies blieben sie sonst
    unbemerkt für immer auf "pending" stehen, statt (wie vor #113) zeitnah
    von selbst dranzukommen. PDF-Texterkennung ist hiervon nicht betroffen
    (siehe #113-Kommentar bei _audio_transcription_queue)."""
    pending_audio_ids: list[str] = []
    with _sources_write_lock:
        sources = _load_sources()
        changed = False
        for source_id, entry in sources.items():
            if entry.get("processing_status") == "running":
                entry["processing_status"] = "error"
                entry["processing_step"] = None
                entry["processing_error"] = i18n.get_message("processing_interrupted", i18n.DEFAULT_LANG)
                changed = True
            elif entry.get("processing_status") == "pending" and _existing_audio_file(source_id):
                pending_audio_ids.append(source_id)
        if changed:
            _save_sources(sources)
    for source_id in pending_audio_ids:
        _audio_transcription_queue.put((source_id, i18n.DEFAULT_LANG))


_recover_interrupted_processing_jobs()


def _reindex_all_sources() -> None:
    """Chunked/embedded jede vorhandene Quelle neu (z.B. nach einer
    Änderung an `chunking.chunk_text()`) - `sources.json` selbst bleibt
    unangetastet, nur der abgeleitete Chroma-Index wird ersetzt. Pro Quelle
    gekapselt, damit ein einzelner defekter Datensatz nicht den gesamten
    Lauf abbricht."""
    sources = _load_sources()
    for source_id, data in sources.items():
        try:
            source = SourceIn(
                title=data.get("title", ""),
                authors=data.get("authors") or [],
                date=data.get("date"),
                url=data.get("url"),
                listen_url=data.get("listen_url"),
                text=data.get("text", ""),
            )
            chunks, chunk_embeddings = _prepare_chunks(source, i18n.DEFAULT_LANG)
        except Exception:
            continue
        vectorstore.delete_source_chunks(source_id)
        _store_chunks(source_id, source, chunks, chunk_embeddings)


@app.post("/api/admin/reindex-sources", response_model=MessageOut)
def reindex_sources(
    background_tasks: BackgroundTasks,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    background_tasks.add_task(_reindex_all_sources)
    return MessageOut(detail=i18n.get_message("reindex_started", x_lang))


# Fix: Embedding (lokales Modell, CPU-gebunden) kann bei sehr großen Texten
# (viele hundert Chunks) mehrere Sekunden dauern - bisher blockierte
# add_source in diesem Fall den kompletten Request. Statt IMMER zu warten,
# wird nur noch bis zu diesem Timeout gewartet; dauert es länger, antwortet
# add_source sofort mit processing_status="pending" (siehe unten) - exakt
# dieselbe Warteschlangen-Logik wie bei Audio-Transkription/PDF-OCR.
SLOW_IMPORT_TIMEOUT_SECONDS = 5


def _create_pending_source(source_id: str, source: SourceIn, imported_at: str) -> None:
    with _sources_write_lock:
        sources = _load_sources()
        sources[source_id] = {
            "id": source_id,
            "title": source.title,
            "authors": source.authors,
            "date": source.date,
            "url": source.url,
            "listen_url": source.listen_url,
            "imported_at": imported_at,
            "chunk_count": 0,
            "text": "",
            "restricted": source.restricted,
            "summary_de": "",
            "summary_en": "",
            "key_terms_de": [],
            "key_terms_en": [],
            "processing_status": "pending",
            "processing_step": None,
            "processing_error": None,
        }
        _save_sources(sources)


def _finish_synchronous_import(
    source_id: str,
    source: SourceIn,
    chunks: list[str],
    text: str,
    outcome: dict,
    done_event: threading.Event,
) -> None:
    """Läuft immer in einem eigenen Thread (siehe add_source): embedded und
    speichert eine Quelle, deren Text bereits vollständig vorliegt (normaler
    Text-/URL-Import oder eine PDF mit direkt extrahierbarer Text-Ebene -
    NICHT der Audio-Transkriptions-/PDF-OCR-Pfad, dafür siehe
    _process_audio_transcription/_process_pdf_ocr). Aktualisiert sources.json
    unabhängig davon, ob add_source noch synchron auf done_event wartet
    (Regelfall, meist deutlich unter SLOW_IMPORT_TIMEOUT_SECONDS) oder wegen
    Zeitüberschreitung bei einer sehr großen Datei bereits mit
    processing_status="pending" geantwortet hat - kein Sonderfall nötig, die
    Quelle existiert in sources.json in beiden Fällen schon (siehe
    _create_pending_source), bevor dieser Thread gestartet wird."""
    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            done_event.set()
            return
        sources[source_id]["processing_step"] = "indexing"
        _save_sources(sources)

    try:
        chunk_embeddings = embeddings.embed_passages(chunks)
        with _vectorstore_write_lock:
            chunk_count = _store_chunks(source_id, source, chunks, chunk_embeddings)
    except Exception as exc:
        outcome["error"] = exc
        with _sources_write_lock:
            sources = _load_sources()
            if source_id in sources:
                sources[source_id]["processing_status"] = "error"
                sources[source_id]["processing_step"] = None
                sources[source_id]["processing_error"] = str(exc)
                _save_sources(sources)
        done_event.set()
        return

    outcome["chunk_count"] = chunk_count
    with _sources_write_lock:
        sources = _load_sources()
        if source_id in sources:
            sources[source_id]["text"] = text
            sources[source_id]["chunk_count"] = chunk_count
            sources[source_id]["processing_status"] = None
            sources[source_id]["processing_step"] = None
            sources[source_id]["processing_error"] = None
            _save_sources(sources)
    # Muss NACH dem Speichern des Ergebnisses, aber VOR der (potenziell
    # mehrere Sekunden dauernden) Zusammenfassung gesetzt werden - eine noch
    # wartende add_source-Anfrage soll durch die Zusammenfassung nicht
    # zusätzlich blockiert werden, die läuft komplett unabhängig weiter.
    done_event.set()
    _generate_summary_background(source_id, text)


@app.post("/api/sources", response_model=SourceOut)
def add_source(
    source: SourceIn,
    background_tasks: BackgroundTasks,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    deferred_audio = _is_deferred_audio_import(source)
    deferred_pdf = _is_deferred_pdf_import(source)
    deferred = deferred_audio or deferred_pdf

    text = source.text.strip()
    chunks: list[str] = []
    if not deferred:
        # Validierung + reines Chunking sind schnell und laufen deshalb immer
        # synchron - nur das anschließende Embedding kann bei sehr großen
        # Texten mehrere Sekunden dauern (siehe slow_import unten).
        if not text:
            raise HTTPException(400, i18n.get_message("text_empty", x_lang))
        chunks = chunking.chunk_text(text)
        if not chunks:
            raise HTTPException(400, i18n.get_message("no_chunks", x_lang))

    source_id = str(uuid.uuid4())
    imported_at = datetime.now(timezone.utc).isoformat()
    _create_pending_source(source_id, source, imported_at)

    slow_import = False
    if not deferred:
        outcome: dict = {}
        done_event = threading.Event()
        threading.Thread(
            target=_finish_synchronous_import,
            args=(source_id, source, chunks, text, outcome, done_event),
            daemon=True,
        ).start()
        finished = done_event.wait(SLOW_IMPORT_TIMEOUT_SECONDS)
        if finished and "error" in outcome:
            raise outcome["error"]
        slow_import = not finished

    for name in source.authors:
        is_new_author = _find_author(name) is None
        authors.register_author(name, source_id)
        if is_new_author:
            background_tasks.add_task(_generate_author_bio_background, name)

    if source.pdf_upload_id:
        _consume_pdf_upload(source_id, source.pdf_upload_id)
    else:
        _sync_pdf_file_from_url(source_id, source.url)

    if not source.url and source.audio_upload_id:
        _consume_audio_upload(source_id, source.audio_upload_id)
    else:
        _sync_audio_file_from_url(source_id, source.url)

    if deferred_audio:
        # Backlog #113: bewusst NICHT über background_tasks (das würde sofort
        # parallel zu allen anderen gerade laufenden Imports starten) -
        # landet stattdessen in der Warteschlange, die _audio_transcription_
        # worker strikt nacheinander abarbeitet.
        _audio_transcription_queue.put((source_id, x_lang))
    elif deferred_pdf:
        background_tasks.add_task(_process_pdf_ocr, source_id, x_lang)
    # deferred=False, fertig ODER slow_import: _finish_synchronous_import
    # stößt die Zusammenfassung in JEDEM Fall bereits selbst an, sobald der
    # Hintergrund-Thread mit Embedding/Speichern fertig ist - hier nichts
    # zusätzlich einplanen (sonst liefe die Zusammenfassung doppelt).

    if not deferred and not slow_import:
        # Bewusst NICHT nochmal von der Platte lesen: _finish_synchronous_import
        # läuft nach done_event.set() im selben Thread sofort mit der
        # Zusammenfassung weiter - ein erneutes _load_sources() hier würde
        # in einem echten Nebenläufigkeits-Wettlauf gelegentlich schon die
        # fertige Zusammenfassung sehen, obwohl add_source() sie laut Vertrag
        # (siehe Tests) nie synchron zurückgeben soll.
        entry = {
            "id": source_id,
            "title": source.title,
            "authors": source.authors,
            "date": source.date,
            "url": source.url,
            "listen_url": source.listen_url,
            "imported_at": imported_at,
            "chunk_count": outcome["chunk_count"],
            "text": text,
            "restricted": source.restricted,
            "summary_de": "",
            "summary_en": "",
            "key_terms_de": [],
            "key_terms_en": [],
            "processing_status": None,
            "processing_step": None,
            "processing_error": None,
        }
    else:
        sources = _load_sources()
        entry = sources[source_id]
    audit.log_action(_user, "source_created", entry.get("title", source_id))
    return _to_source_out(entry, can_view_full_text=True, lang=x_lang)


@app.put("/api/sources/{source_id}", response_model=SourceOut)
def update_source(
    source_id: str,
    source: SourceIn,
    background_tasks: BackgroundTasks,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

        metadata_only = bool(sources[source_id].get("restricted")) and not source.text.strip()

        if not metadata_only:
            chunks, chunk_embeddings = _prepare_chunks(source, x_lang)
            with _vectorstore_write_lock:
                vectorstore.delete_source_chunks(source_id)
                chunk_count = _store_chunks(source_id, source, chunks, chunk_embeddings)
            sources[source_id]["text"] = source.text.strip()
            sources[source_id]["chunk_count"] = chunk_count

        sources[source_id].update(
            {
                "title": source.title,
                "authors": source.authors,
                "date": source.date,
                "url": source.url,
                "listen_url": source.listen_url,
                "restricted": source.restricted,
            }
        )
        if source.summary is not None:
            sources[source_id][f"summary_{x_lang}"] = source.summary
        if source.key_terms is not None:
            sources[source_id][f"key_terms_{x_lang}"] = source.key_terms
        _save_sources(sources)

    # VOR unregister_source() erfassen: war dies die letzte Quelle einer
    # Person, würde unregister_source deren Registry-Eintrag kurzzeitig
    # löschen - _find_author(name) läge danach fälschlich bei "neu", obwohl
    # die Person längst existiert (und ggf. schon eine Vita hat).
    existing_author_keys = {
        " ".join(a["name"].strip().split()).lower() for a in authors.list_authors()
    }

    authors.unregister_source(source_id)
    for name in source.authors:
        is_new_author = " ".join(name.strip().split()).lower() not in existing_author_keys
        authors.register_author(name, source_id)
        if is_new_author:
            background_tasks.add_task(_generate_author_bio_background, name)

    if source.summary is not None or source.key_terms is not None:
        _register_all_terms(source_id, sources[source_id])

    if source.pdf_upload_id:
        _consume_pdf_upload(source_id, source.pdf_upload_id)
    elif not metadata_only:
        _sync_pdf_file_from_url(source_id, source.url)

    if not source.url and source.audio_upload_id:
        _consume_audio_upload(source_id, source.audio_upload_id)
    elif not metadata_only:
        _sync_audio_file_from_url(source_id, source.url)

    audit.log_action(_user, "source_updated", sources[source_id].get("title", source_id))
    return _to_source_out(sources[source_id], can_view_full_text=True, lang=x_lang)


@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

        title = sources[source_id].get("title", source_id)
        with _vectorstore_write_lock:
            vectorstore.delete_source_chunks(source_id)
        del sources[source_id]
        _save_sources(sources)
    audit.log_action(_user, "source_deleted", title)
    authors.unregister_source(source_id)
    terms.unregister_source(source_id)
    _delete_pdf_file(source_id)
    _delete_audio_file(source_id)


@app.get("/api/sources", response_model=list[SourceOut])
def list_sources(
    request: Request,
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    email = _get_current_user_email(request)
    can_view_full_text = users.has_role(email, users.QUELLEN_PFLEGER)
    sources = _load_sources()
    return [_to_source_out(entry, can_view_full_text, x_lang) for entry in sources.values()]


def _resolve_profile_for_lang(profile: dict, lang: str) -> dict:
    # API-seitig bleibt "bio"/"bio_ai_generated" ein einzelnes, sprach-
    # aufgelöstes Feld (wie summary_{lang} bei Quellen) - nur die Speicherung
    # in author_profiles.py ist bilingual (bio_de/bio_en), damit Frontend und
    # Wire-Format unverändert einfach bleiben.
    return {
        "bio": profile.get(f"bio_{lang}", ""),
        "bio_ai_generated": profile.get(f"bio_ai_generated_{lang}", False),
        "photo_url": profile.get("photo_url", ""),
        "website": profile.get("website", ""),
        "social_links": profile.get("social_links", []),
    }


@app.get("/api/authors", response_model=list[AuthorOut])
def list_authors(x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    entries = authors.list_authors()
    for entry in entries:
        entry.update(_resolve_profile_for_lang(author_profiles.get_profile(entry["name"]), lang))
    return entries


def _find_author(name: str) -> dict | None:
    normalized = " ".join(name.strip().split()).lower()
    return next(
        (a for a in authors.list_authors() if " ".join(a["name"].strip().split()).lower() == normalized),
        None,
    )


def _collect_author_bio_texts(matching: dict, lang: str) -> list[str]:
    sources = _load_sources()
    texts = []
    for source_id in matching["source_ids"]:
        source = sources.get(source_id)
        if not source:
            continue
        summary = source.get(f"summary_{lang}") or source.get("text", "")
        texts.append(f"{source.get('title', '')}: {summary}")
    return texts


def _generate_author_bio_one_lang(name: str, matching: dict, lang: str) -> None:
    if author_profiles.get_profile(matching["name"])[f"bio_{lang}"]:
        return
    texts = _collect_author_bio_texts(matching, lang)
    bio = summarization.generate_author_bio(matching["name"], texts, lang)
    # Erneute Prüfung unmittelbar vor dem Schreiben: der KI-Aufruf oben
    # dauert mehrere Sekunden - in dieser Zeit kann z.B. das "Autorenprofil
    # pflegen"-Panel (Backlog #86) bereits eine von Hand eingegebene Vita
    # gespeichert haben. Ohne diese zweite Prüfung würde die spätere KI-Vita
    # die gerade erst gespeicherte manuelle Vita kommentarlos überschreiben.
    if bio and not author_profiles.get_profile(matching["name"])[f"bio_{lang}"]:
        author_profiles.set_profile(name, **{f"bio_{lang}": bio, f"bio_ai_generated_{lang}": True})


def _generate_author_bio_background(name: str) -> None:
    # Wird für jede neu im System auftauchende Person angestoßen (siehe
    # add_source/update_source) - jede:r Autor:in soll von Anfang an eine
    # Vita in BEIDEN Sprachen haben (analog summary_de/summary_en bei
    # Quellen), statt nur in der beim Import gerade aktiven UI-Sprache.
    # Läuft im Hintergrund wie die Quellen-Zusammenfassung, damit der Import
    # nicht auf die KI-Aufrufe warten muss.
    matching = _find_author(name)
    if matching is None:
        return
    _generate_author_bio_one_lang(name, matching, "de")
    _generate_author_bio_one_lang(name, matching, "en")


@app.put("/api/authors/{name}", response_model=AuthorOut)
def update_author_profile(
    name: str,
    profile: AuthorProfileIn,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    matching = _find_author(name)
    if matching is None:
        raise HTTPException(404, i18n.get_message("author_not_found", x_lang))

    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    # Die Vita-Eingabe im Bearbeiten-Formular bezieht sich immer auf die
    # gerade aktive UI-Sprache (X-Lang) - wer auf Deutsch pflegt, editiert die
    # deutsche Vita, ohne dass die App zwei separate Felder anzeigen muss.
    bio_kwargs = {f"bio_{lang}": profile.bio} if profile.bio is not None else {}
    author_profiles.set_profile(
        name,
        photo_url=profile.photo_url,
        website=profile.website,
        social_links=[link.model_dump() for link in profile.social_links]
        if profile.social_links is not None
        else None,
        **bio_kwargs,
    )
    matching.update(_resolve_profile_for_lang(author_profiles.get_profile(name), lang))
    audit.log_action(_user, "author_profile_updated", matching["name"])
    return matching


@app.post("/api/authors/{name}/rename", response_model=AuthorOut)
def rename_author_endpoint(
    name: str,
    payload: RenameAuthorIn,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    matching = _find_author(name)
    if matching is None:
        raise HTTPException(404, i18n.get_message("author_not_found", x_lang))

    new_name = payload.new_name.strip()
    if not new_name:
        raise HTTPException(400, i18n.get_message("invalid_author_name", x_lang))

    old_name = matching["name"]
    old_key = " ".join(old_name.strip().split()).lower()

    # Der Name ist kein eigenständiges Feld, sondern wird aus dem
    # authors-Feld jeder Quelle abgeleitet (siehe app/authors.py) - eine
    # Umbenennung muss deshalb in JEDER betroffenen Quelle nachvollzogen
    # werden, sonst würde die nächste Quellen-Bearbeitung (die authors.py
    # per unregister/register neu aufbaut) den alten Namen wiederherstellen.
    with _sources_write_lock:
        sources = _load_sources()
        for source_id in matching["source_ids"]:
            source = sources.get(source_id)
            if not source:
                continue
            updated_names = []
            seen_keys = set()
            for author_name in source.get("authors") or []:
                candidate = (
                    new_name
                    if " ".join(author_name.strip().split()).lower() == old_key
                    else author_name
                )
                key = " ".join(candidate.strip().split()).lower()
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                updated_names.append(candidate)
            source["authors"] = updated_names
        _save_sources(sources)

    for source_id in matching["source_ids"]:
        source = sources.get(source_id)
        if not source:
            continue
        authors.unregister_source(source_id)
        for author_name in source.get("authors") or []:
            authors.register_author(author_name, source_id)

    author_profiles.rename_profile(old_name, new_name)

    updated = _find_author(new_name)
    if updated is None:
        raise HTTPException(404, i18n.get_message("author_not_found", x_lang))
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    updated.update(_resolve_profile_for_lang(author_profiles.get_profile(new_name), lang))
    audit.log_action(_user, "author_renamed", f"{old_name} → {new_name}")
    return updated


@app.post("/api/authors/{name}/generate-bio", response_model=BioOut)
def generate_author_bio_endpoint(
    name: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    matching = _find_author(name)
    if matching is None:
        raise HTTPException(404, i18n.get_message("author_not_found", x_lang))

    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    texts = _collect_author_bio_texts(matching, lang)
    bio = summarization.generate_author_bio(matching["name"], texts, lang)
    author_profiles.set_profile(name, **{f"bio_{lang}": bio, f"bio_ai_generated_{lang}": True})
    audit.log_action(_user, "author_bio_generated", matching["name"])
    return BioOut(bio=bio)


@app.post("/api/authors/generate-bio-preview", response_model=BioOut)
def generate_author_bio_preview_endpoint(
    payload: AuthorBioPreviewIn,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    # Für Co-Autor:innen, die gerade erst im Formular eingetragen wurden und
    # noch nicht als Autor:in registriert sind (siehe _find_author) - die
    # Quelle selbst ist noch nicht gespeichert, es gibt also noch keine
    # indizierten Texte, aus denen _collect_author_bio_texts schöpfen könnte.
    # Nutzt stattdessen den gerade im Formular eingegebenen Text als einziges
    # Quellenmaterial. Schreibt bewusst NICHTS in author_profiles.json - reine
    # Vorschau, die Persistierung passiert erst nach dem Speichern der Quelle
    # über den bestehenden PUT-/api/authors/{name}-Weg.
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    bio = summarization.generate_author_bio(payload.name, [payload.text], lang)
    return BioOut(bio=bio)


@app.get("/api/terms", response_model=list[TermOut])
def list_terms():
    return terms.list_terms()


@app.post("/api/auth/request-link", response_model=MessageOut)
def request_login_link(
    payload: RequestLinkIn,
    request: Request,
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    email = payload.email.strip().lower()
    client_ip = request.client.host if request.client else "unknown"
    if ratelimit.is_rate_limited(f"login-ip:{client_ip}", max_requests=10, window_seconds=3600) or (
        email and ratelimit.is_rate_limited(f"login-email:{email}", max_requests=5, window_seconds=3600)
    ):
        raise HTTPException(429, i18n.get_message("rate_limited", x_lang))
    if "@" not in email:
        raise HTTPException(400, i18n.get_message("invalid_email", x_lang))

    # Immer dieselbe generische Antwort, unabhängig davon, ob die Adresse
    # bekannt ist - verhindert, dass sich per Trial-and-Error herausfinden
    # lässt, welche E-Mails eingeladen wurden.
    if users.get_user(email):
        token = auth.create_magic_link_token(email, auth.LOGIN_LINK_MAX_AGE_SECONDS)
        link_url = str(request.base_url) + f"api/auth/verify?token={token}"
        mail.send_login_link_email(email, link_url, x_lang)
    return MessageOut(detail=i18n.get_message("magic_link_sent", x_lang))


@app.get("/api/auth/verify")
def verify_login_link(token: str):
    email = auth.verify_magic_link_token(token)
    if not email or not users.get_user(email):
        return RedirectResponse("/?auth=expired")

    users.mark_logged_in(email)
    response = RedirectResponse("/")
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        auth.create_session_token(email),
        max_age=auth.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=not IS_DEV_ENVIRONMENT,
        path="/",
    )
    return response


@app.post("/api/auth/logout", status_code=204)
def logout():
    response = Response(status_code=204)
    response.delete_cookie(auth.SESSION_COOKIE_NAME, path="/")
    return response


@app.get("/api/auth/whoami", response_model=WhoAmIOut)
def whoami(request: Request):
    email = _get_current_user_email(request)
    user = users.get_user(email) if email else None
    return WhoAmIOut(email=email, roles=users.get_roles(email), name=user.get("name") if user else None)


@app.get("/api/auth/users", response_model=list[AdminUserOut])
def list_invited_users(_user: str = Depends(require_role(users.USER_ADMIN))):
    return users.list_users()


@app.post("/api/auth/invite", response_model=AdminUserOut, status_code=201)
def invite_user(
    payload: InviteIn,
    request: Request,
    current_user: str = Depends(require_role(users.USER_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    if payload.role not in users.ALL_ROLES:
        raise HTTPException(400, i18n.get_message("invite_invalid_role", x_lang))
    if payload.role in (users.USER_ADMIN, users.SYSTEM_ADMIN) and not users.has_role(
        current_user, users.SYSTEM_ADMIN
    ):
        raise HTTPException(403, i18n.get_message("invite_role_forbidden", x_lang))

    email = payload.email.strip().lower()
    entry = users.invite_user(email, payload.role, invited_by=current_user, name=payload.name)
    token = auth.create_magic_link_token(email, auth.INVITE_LINK_MAX_AGE_SECONDS)
    link_url = str(request.base_url) + f"api/auth/verify?token={token}"
    mail.send_invite_email(email, link_url, payload.role, x_lang)
    return entry


@app.put("/api/auth/users/{email}/name", response_model=AdminUserOut)
def set_user_name(
    email: str,
    payload: UpdateUserNameIn,
    _user: str = Depends(require_role(users.USER_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    entry = users.set_name(email, payload.name)
    if entry is None:
        raise HTTPException(404, i18n.get_message("user_not_found", x_lang))
    return entry


@app.get("/api/audit-log", response_model=list[AuditLogEntryOut])
def get_audit_log(_user: str = Depends(require_role(users.QUELLEN_PFLEGER))):
    return audit.list_entries()


@app.get("/api/sources/{source_id}/check-url", response_model=UrlCheckOut)
def check_source_url(
    source_id: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = _load_sources()
    if source_id not in sources:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    url = sources[source_id].get("url")
    if not url:
        return UrlCheckOut(has_url=False)

    result = monitoring.check_url(url)
    return UrlCheckOut(has_url=True, **result)


@app.get("/api/sources/{source_id}/pdf")
def get_source_pdf(
    source_id: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = _load_sources()
    if source_id not in sources:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    pdf_path = PDF_DIR / f"{source_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    return FileResponse(pdf_path, media_type="application/pdf")


@app.get("/api/sources/{source_id}/audio")
def get_source_audio(
    source_id: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = _load_sources()
    if source_id not in sources:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    audio_path = _existing_audio_file(source_id)
    if not audio_path:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    media_type = _AUDIO_MEDIA_TYPES.get(audio_path.suffix.lower(), "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)


@app.get("/api/import-jobs", response_model=list[ImportJobOut])
def list_import_jobs(_user: str = Depends(require_role(users.QUELLEN_PFLEGER))):
    sources = _load_sources()
    return [
        ImportJobOut(
            id=source_id,
            title=entry.get("title", ""),
            processing_status=entry["processing_status"],
            processing_step=entry.get("processing_step"),
            processing_error=entry.get("processing_error"),
        )
        for source_id, entry in sources.items()
        if entry.get("processing_status")
    ]


@app.post("/api/sources/{source_id}/reprocess", response_model=MessageOut)
def reprocess_source(
    source_id: str,
    background_tasks: BackgroundTasks,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

        is_audio = bool(_existing_audio_file(source_id))
        if not is_audio and not _existing_pdf_file(source_id):
            raise HTTPException(400, i18n.get_message("no_processing_file", x_lang))

        sources[source_id]["processing_status"] = "pending"
        sources[source_id]["processing_step"] = None
        sources[source_id]["processing_error"] = None
        title = sources[source_id].get("title", source_id)
        _save_sources(sources)
    audit.log_action(_user, "source_reprocessed", title)
    if is_audio:
        # Backlog #113: siehe add_source - auch ein erneuter Versuch reiht
        # sich hinten in der Warteschlange ein, statt sofort parallel zu
        # anderen laufenden Transkriptionen zu starten.
        _audio_transcription_queue.put((source_id, x_lang))
    else:
        background_tasks.add_task(_process_pdf_ocr, source_id, x_lang)
    return MessageOut(detail=i18n.get_message("reprocess_started", x_lang))


@app.post("/api/sources/{source_id}/generate-summary", response_model=SummaryOut)
def generate_source_summary(
    source_id: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = _load_sources()
    if source_id not in sources:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))
    text = sources[source_id].get("text", "")

    # generate_bilingual_summary ist der langsame KI-Aufruf - die Momentaufnahme
    # von oben deshalb NICHT für den späteren Schreibvorgang wiederverwenden
    # (siehe _sources_write_lock-Kommentar), sondern direkt davor neu einlesen.
    result = summarization.generate_bilingual_summary(text)
    with _sources_write_lock:
        sources = _load_sources()
        if source_id not in sources:
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))
        sources[source_id]["summary_de"] = result["de"]["summary"]
        sources[source_id]["summary_en"] = result["en"]["summary"]
        sources[source_id]["key_terms_de"] = result["de"]["key_terms"]
        sources[source_id]["key_terms_en"] = result["en"]["key_terms"]
        title = sources[source_id].get("title", source_id)
        _save_sources(sources)
        _register_all_terms(source_id, sources[source_id])

    audit.log_action(_user, "source_summary_generated", title)
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    return SummaryOut(summary=result[lang]["summary"], key_terms=result[lang]["key_terms"])


@app.post("/api/extract-pdf-upload", response_model=ExtractedUpload)
def extract_pdf_upload(
    file: UploadFile = File(...),
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
):
    data = file.file.read()
    result = extraction.extract_pdf(data)

    upload_id = str(uuid.uuid4())
    PDF_UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    (PDF_UPLOAD_STAGING_DIR / f"{upload_id}.pdf").write_bytes(data)

    return ExtractedUpload(**result, upload_id=upload_id)


@app.post("/api/extract-audio-upload", response_model=ExtractedUpload)
def extract_audio_upload(
    file: UploadFile = File(...),
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
):
    # Transkribiert bewusst NICHT hier - kann mehrere Minuten dauern und
    # läuft stattdessen als Hintergrund-Job nach dem Anlegen der Quelle
    # (siehe _process_audio_transcription), damit die Vorschau schnell bleibt.
    data = file.file.read()
    extension = _audio_extension(file.filename or "")

    upload_id = str(uuid.uuid4())
    AUDIO_UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staged_path = AUDIO_UPLOAD_STAGING_DIR / f"{upload_id}{extension}"
    staged_path.write_bytes(data)

    title = _guess_title_from_filename(file.filename or "")

    return ExtractedUpload(title=title, authors=[], date="", text="", extracted=False, upload_id=upload_id)


@app.post("/api/extract-url", response_model=ExtractedSource)
def extract_url(payload: UrlIn, _user: str = Depends(require_role(users.QUELLEN_PFLEGER))):
    result = extraction.extract_from_url(payload.url)
    is_audio = extraction.looks_like_audio(payload.url)
    is_pdf = extraction.looks_like_pdf(payload.url)
    return ExtractedSource(**result, is_audio=is_audio, is_pdf=is_pdf)


def _normalize_for_match(text: str) -> str:
    return " ".join(text.split()).lower()


def _best_local_sentence(doc: str, query_embedding: list[float]) -> str | None:
    """Lokales Fallback-Highlighting (Baustein A): zerlegt den Chunk in
    Sätze und wählt per Skalarprodukt (beide Embeddings normalisiert) den
    Satz, der der Frage am nächsten kommt - kostet keine Anthropic-API,
    läuft komplett mit dem bereits geladenen lokalen Embedding-Modell."""
    sentences = chunking.split_sentences(doc)
    if not sentences:
        return None
    if len(sentences) == 1:
        return sentences[0]
    sentence_embeddings = embeddings.embed_passages(sentences)
    best_index = max(
        range(len(sentences)),
        key=lambda i: sum(a * b for a, b in zip(sentence_embeddings[i], query_embedding)),
    )
    return sentences[best_index]


_CITATION_NUMBER_RE = re.compile(r"\[(\d+)\]")


def _compute_occurrence_highlights(
    answer_text: str,
    chunk_docs: list[str],
    quotes_by_citation: dict[int, list[str]],
) -> list[list[str]]:
    """Bausteine A+B kombiniert, aber pro VORKOMMEN statt pro Chunk: zerlegt
    den fertigen Antworttext in Sätze, findet darin alle [n]-Zitat-Marker
    und bestimmt für jedes Vorkommen (in Auftrittsreihenfolge) ein eigenes
    Highlight - bevorzugt ein verifiziertes KI-Zitat (Baustein B), sonst den
    zur jeweiligen AUSSAGE im Antworttext (nicht zur ursprünglichen
    Nutzerfrage) lokal best-passenden Satz im Chunk (Baustein A). Derselbe
    Chunk kann so für unterschiedliche Aussagen im selben Antworttext
    unterschiedliche Highlights bekommen, statt immer dasselbe zu zeigen."""
    used_quote_index: dict[int, int] = {}
    occurrence_highlights: list[list[str]] = [[] for _ in chunk_docs]
    sentence_cache: dict[int, tuple[list[str], list[list[float]] | None]] = {}

    for sentence in chunking.split_sentences(answer_text):
        matches = list(_CITATION_NUMBER_RE.finditer(sentence))
        if not matches:
            continue
        claim_embedding = None
        for match in matches:
            chunk_index = int(match.group(1)) - 1
            if chunk_index < 0 or chunk_index >= len(chunk_docs):
                continue
            doc = chunk_docs[chunk_index]
            citation_number = chunk_index + 1

            highlight = None
            quotes = quotes_by_citation.get(citation_number, [])
            next_index = used_quote_index.get(citation_number, 0)
            if next_index < len(quotes):
                used_quote_index[citation_number] = next_index + 1
                candidate = quotes[next_index]
                if _normalize_for_match(candidate) in _normalize_for_match(doc):
                    highlight = candidate

            if highlight is None:
                if chunk_index not in sentence_cache:
                    doc_sentences = chunking.split_sentences(doc)
                    doc_embeddings = (
                        embeddings.embed_passages(doc_sentences) if len(doc_sentences) > 1 else None
                    )
                    sentence_cache[chunk_index] = (doc_sentences, doc_embeddings)
                doc_sentences, doc_embeddings = sentence_cache[chunk_index]
                if len(doc_sentences) == 1:
                    highlight = doc_sentences[0]
                elif doc_sentences:
                    if claim_embedding is None:
                        claim_embedding = embeddings.embed_query(sentence)
                    best_index = max(
                        range(len(doc_sentences)),
                        key=lambda i: sum(
                            a * b for a, b in zip(doc_embeddings[i], claim_embedding)
                        ),
                    )
                    highlight = doc_sentences[best_index]

            if highlight is not None:
                occurrence_highlights[chunk_index].append(highlight)

    return occurrence_highlights


# Backlog (2026-07-29): Antwortzeit gefühlt beschleunigen, analog zum
# Streaming im CRT-Tool - vor dieser Zeile brauchte /api/ask, bis die
# GESAMTE Antwort inkl. des internen ---QUOTES---Blocks fertig generiert
# war, bevor überhaupt etwas angezeigt wurde. Anzahl der Zeichen, die vor
# dem ersten sichtbaren Fragment abgewartet werden, um die "Antwort:"/
# "Answer:"-Label-Erkennung (llm._strip_answer_label) sicher einmalig
# entscheiden zu können, bevor irgendein Zeichen an die Nutzer:in geht -
# reicht für die längste realistische Ausprägung des Labels ("**Antwort:**
# ") mit Marge, verzögert die erste sichtbare Ausgabe aber praktisch nicht
# spürbar (typischerweise weniger als ein Streaming-Chunk).
_ASK_LABEL_CHECK_MIN_LEN = 20
_ASK_QUOTES_MARKER = "---QUOTES---"


def _ask_event_stream(question_text, llm_chunks, lang, author_bios, chunk_refs, chunk_docs, local_highlights):
    """Generator für die NDJSON-Stream-Antwort von /api/ask: ein "delta"-
    Event pro neu angekommenem Text-Fragment, am Ende genau ein "done"-Event
    mit der vollständigen (bereits vom Label befreiten) Antwort und den
    Quellen inkl. berechneter Hervorhebungen - oder ein "error"-Event, falls
    die Anfrage an Anthropic fehlschlägt. Der ---QUOTES---Block selbst wird
    NIE an die Nutzer:in gestreamt, da er reine interne Beleg-Daten für die
    Hervorhebungen enthält."""
    buffer = ""
    sent_len = 0
    label_resolved = False

    try:
        for delta in llm.stream_answer_question(question_text, llm_chunks, lang=lang, author_bios=author_bios):
            buffer += delta
            marker_index = buffer.find(_ASK_QUOTES_MARKER)
            if marker_index != -1:
                visible_raw = buffer[:marker_index]
            else:
                visible_raw = buffer[: max(0, len(buffer) - len(_ASK_QUOTES_MARKER))]

            if not label_resolved:
                if marker_index == -1 and len(visible_raw) < _ASK_LABEL_CHECK_MIN_LEN:
                    continue
                label_resolved = True

            visible_final = llm._strip_answer_label(visible_raw)
            new_text = visible_final[sent_len:]
            if new_text:
                yield json.dumps({"type": "delta", "text": new_text}) + "\n"
                sent_len = len(visible_final)
    except Exception:
        yield json.dumps({"type": "error", "message": i18n.get_message("ask_llm_failed", lang)}) + "\n"
        return

    answer_text, quotes_by_citation = llm.parse_answer_and_quotes(buffer)
    remaining = answer_text[sent_len:]
    if remaining:
        yield json.dumps({"type": "delta", "text": remaining}) + "\n"

    occurrence_highlights = _compute_occurrence_highlights(answer_text, chunk_docs, quotes_by_citation)
    for i, chunk_ref in enumerate(chunk_refs):
        # Letzter Ausweg: eine zurückgegebene Quelle, die im finalen
        # Antworttext aus irgendeinem Grund gar nicht per [n] referenziert
        # wird, bekommt trotzdem ein Highlight (gegen die Nutzerfrage
        # gescort) statt gar keins.
        chunk_ref.highlighted_texts = occurrence_highlights[i] or (
            [local_highlights[i]] if local_highlights[i] else []
        )

    yield json.dumps(
        {
            "type": "done",
            "answer": answer_text,
            "sources": [chunk_ref.model_dump() for chunk_ref in chunk_refs],
        }
    ) + "\n"


@app.post("/api/ask")
def ask(question: QuestionIn, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    client_ip = request.client.host if request.client else "unknown"
    if ratelimit.is_rate_limited(client_ip):
        raise HTTPException(429, i18n.get_message("rate_limited", x_lang))
    if not captcha.verify_turnstile_token(question.turnstile_token, client_ip):
        raise HTTPException(400, i18n.get_message("captcha_failed", x_lang))

    sources = _load_sources()
    if not sources:
        raise HTTPException(400, i18n.get_message("no_sources", x_lang))

    query_embedding = embeddings.embed_query(question.question)
    results = vectorstore.query(query_embedding, top_k=question.top_k)

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]

    if not ids:
        raise HTTPException(400, i18n.get_message("no_matching_chunks", x_lang))

    unknown_label = "unbekannt" if x_lang == "de" else "unknown"
    summary_lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG

    chunk_refs = []
    llm_chunks = []
    local_highlights = []
    for chunk_id, doc, meta in zip(ids, documents, metadatas):
        # Rückwärtskompatibel lesen: alte, noch nicht neu gespeicherte Chunks
        # haben noch den alten skalaren "author"-Schlüssel statt der Liste.
        authors_list = meta.get("authors") or ([meta["author"]] if meta.get("author") else [])
        chunk_refs.append(
            ChunkRef(
                chunk_id=chunk_id,
                source_id=meta["source_id"],
                title=meta["title"],
                authors=authors_list,
                date=meta["date"] or None,
                url=meta["url"] or None,
                listen_url=meta.get("listen_url") or None,
                position=meta["position"],
                text=doc,
                summary=sources.get(meta["source_id"], {}).get(f"summary_{summary_lang}") or None,
            )
        )
        llm_chunks.append(
            {
                "title": meta["title"],
                "author": ", ".join(authors_list) or unknown_label,
                "date": meta["date"] or unknown_label,
                "text": doc,
            }
        )
        # Baustein A (kostenloses lokales Fallback-Highlighting): schon hier
        # berechnen, nicht erst wenn ein KI-Zitat fehlschlägt - braucht
        # dieselben Chunks/Embeddings, die wir gerade ohnehin verarbeiten.
        local_highlights.append(_best_local_sentence(doc, query_embedding))

    # Backlog (2026-07-29): rein chunk-basierte Suche findet für biografische
    # Fragen ("Wer ist X?") keine passenden Textausschnitte, da Autor:innen-
    # Namen nur als Zitat-Metadatum, nicht als durchsuchbarer Inhalt indiziert
    # sind - die gepflegte Vita (author_profiles) wurde dadurch nie genutzt.
    # Erkennt hier stattdessen per Namensabgleich, ob die Frage eine
    # registrierte Autor:in nennt, und reicht deren Vita zusätzlich an das
    # Modell weiter (siehe llm.answer_question/author_bios).
    bio_field = f"bio_{x_lang}" if x_lang in ("de", "en") else f"bio_{i18n.DEFAULT_LANG}"
    author_bios = []
    for name in authors.find_mentioned(question.question):
        bio = author_profiles.get_profile(name).get(bio_field, "")
        if bio:
            author_bios.append({"name": name, "bio": bio})

    chunk_docs = [chunk_ref.text for chunk_ref in chunk_refs]
    return StreamingResponse(
        _ask_event_stream(
            question.question, llm_chunks, x_lang, author_bios or None, chunk_refs, chunk_docs, local_highlights
        ),
        media_type="application/x-ndjson",
    )


@app.post("/api/speech")
def synthesize_speech(payload: SpeechIn, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    # Bewusst ohne require_role (wie /api/ask öffentlich nutzbar) - das
    # Vorlesen einer ohnehin öffentlich sichtbaren Antwort braucht keine
    # Anmeldung. Kein Rate-Limiting hier: nur erreichbar über eine bereits
    # erfolgreich beantwortete /api/ask-Anfrage, die selbst schon
    # ratenbegrenzt/Captcha-geschützt ist.
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, i18n.get_message("speech_text_required", x_lang))

    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    try:
        audio = tts.synthesize_speech(text, lang=lang)
    except tts.SpeechSynthesisError:
        raise HTTPException(502, i18n.get_message("speech_synthesis_failed", x_lang))
    return Response(content=audio, media_type="audio/mpeg")


@app.post("/api/feedback", response_model=MessageOut)
def submit_feedback(
    feedback: FeedbackIn, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)
):
    client_ip = request.client.host if request.client else "unknown"
    # Deutlich enger als /api/ask (Standard 10/60s) - Feedback wird von
    # echten Nutzer:innen selten und nie in Serie abgeschickt, ein enges
    # Limit verhindert Postfach-Spam ohne echte Nutzung einzuschränken.
    if ratelimit.is_rate_limited(f"feedback-ip:{client_ip}", max_requests=3, window_seconds=3600):
        raise HTTPException(429, i18n.get_message("rate_limited", x_lang))
    if not captcha.verify_turnstile_token(feedback.turnstile_token, client_ip):
        raise HTTPException(400, i18n.get_message("captcha_failed", x_lang))

    message = feedback.message.strip()
    if not message:
        raise HTTPException(400, i18n.get_message("feedback_empty", x_lang))

    sender = feedback.email.strip() or i18n.get_message("feedback_no_email", x_lang)
    subject = i18n.get_message("mail_feedback_subject", x_lang)
    body = i18n.get_message("mail_feedback_body", x_lang, message=message, sender=sender)
    mail.send_mail(os.environ.get("SYSTEM_ADMIN_EMAIL", ""), subject, body)

    return MessageOut(detail=i18n.get_message("feedback_sent", x_lang))


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Backlog #58: die branded 404.html (siehe unten, StaticFiles html=True liefert
# sie automatisch für jeden nicht gefundenen Pfad) soll NUR für echte
# Browser-Navigation greifen, nicht für einen falsch getippten/nicht (mehr)
# existierenden /api/-Pfad - der muss weiterhin JSON liefern, weil das
# Frontend überall err.detail aus der Antwort liest. Ohne dieses Catch-all
# würde ein unbekannter /api/-Pfad sonst ebenfalls bei der StaticFiles-
# Route landen und fälschlich HTML statt JSON bekommen.
@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
async def api_not_found(full_path: str):
    raise HTTPException(404, "Not Found")


app.mount("/", NoCacheStaticFiles(directory=str(STATIC_DIR), html=True), name="static")
