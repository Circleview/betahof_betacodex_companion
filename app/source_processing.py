# Idee 313ad93d: aus app/main.py ausgelagert (Verhalten unverändert).

import contextlib
import json
import re
import threading
import time
import uuid
from fastapi import HTTPException
from pathlib import Path
from urllib.parse import urlsplit
from app import (
    author_photos,
    author_profiles,
    authors,
    chunking,
    embeddings,
    extraction,
    i18n,
    jsonstore,
    source_images,
    summarization,
    terms,
    transcription_hints,
    vectorstore,
)
from app.models import SourceIn, SourceOut

from app import main

def _load_sources() -> dict:
    sources = jsonstore.load(main.SOURCES_FILE, {})
    for entry in sources.values():
        if "authors" not in entry:
            # Migration vom alten einzelnen "author"-Feld auf eine Liste -
            # läuft transparent bei jedem Laden mit, kein separates Skript
            # nötig. Beim nächsten Speichern ist der Datensatz bereinigt.
            old_author = entry.pop("author", None)
            entry["authors"] = [old_author] if old_author else []
        # Backlog #51: Relevanz-Score (1-10) - Bestandsquellen ohne dieses
        # Feld gelten als neutral (Mittelwert 5), bis eine:r Quellen-
        # Pfleger:in ihn bewusst setzt.
        entry.setdefault("relevance_score", 5)
    return sources


def _save_sources(sources: dict) -> None:
    jsonstore.save(main.SOURCES_FILE, sources)


def _diff_fields(before: dict, new_values: dict) -> dict:
    """Vergleicht alte gegen neue Werte und gibt NUR tatsächlich
    unterschiedliche Felder als {"feld": {"old": ..., "new": ...}} zurück -
    Grundlage für audit.log_change (Backlog #99). Feldnamen entsprechen
    exakt den Schlüsseln im Roh-Dict (z.B. "summary_de" statt nur
    "summary"), damit ein Revert sie unverändert zurückschreiben kann."""
    changes = {}
    for field, new_value in new_values.items():
        old_value = before.get(field)
        if old_value != new_value:
            changes[field] = {"old": old_value, "new": new_value}
    return changes


def _source_is_missing(sources: dict, source_id: str) -> bool:
    # Weiches Löschen (Backlog #45/#99): eine mit deleted_at geflaggte
    # Quelle bleibt im Rohdatensatz erhalten, soll aber für alle normalen
    # Lesewege wie eine nicht existierende Quelle behandelt werden - nur
    # das Änderungs-Log/der Revert-Endpunkt greifen gezielt darauf zu.
    entry = sources.get(source_id)
    return entry is None or bool(entry.get("deleted_at"))


def _source_in_from_entry(entry: dict) -> SourceIn:
    # Baut ein SourceIn aus einem rohen sources.json-Eintrag nach - für den
    # Revert-Endpunkt (Backlog #99), der Chunking/Embedding über die
    # bestehenden _prepare_chunks/_store_chunks-Helfer erneut ausführen
    # muss, ohne dass ein echter PUT-Request-Body vorliegt.
    return SourceIn(
        title=entry.get("title", ""),
        authors=entry.get("authors", []),
        date=entry.get("date"),
        url=entry.get("url"),
        listen_url=entry.get("listen_url"),
        text=entry.get("text", ""),
        restricted=entry.get("restricted", False),
    )


def _prepare_chunks(source: SourceIn, lang: str) -> tuple[list[str], list[list[float]]]:
    text = source.text.strip()
    if not text:
        raise HTTPException(400, i18n.get_message("text_empty", lang))

    chunks = chunking.chunk_text(text)
    if not chunks:
        raise HTTPException(400, i18n.get_message("no_chunks", lang))

    chunk_embeddings = embeddings.embed_passages(chunks)
    return chunks, chunk_embeddings


def _normalize_upload_id(upload_id: str) -> str:
    """Sicherheit (2026-09-23): upload_id kommt beim Anlegen der Quelle vom
    Client (SourceIn.pdf_upload_id/audio_upload_id) - ungeprüft als
    Dateiname/Glob-Muster verwendet, ließe sich damit z.B. via "../" eine
    beliebige, auf ".pdf" endende Datei des Systembenutzers ansprechen
    (siehe _pdf_upload_staging_path/_consume_audio_upload unten, die
    staged_path.replace() aufrufen), oder bei der Audio-Variante sogar per
    "*"-Glob eine FREMDE, gerade erst hochgeladene Datei treffen. Die
    tatsächlich vergebene ID ist immer ein echtes UUID (siehe
    extract_pdf_upload/extract_audio_upload) - jede andere Eingabe wird auf
    einen garantiert nie existierenden Platzhalter abgebildet, statt
    ungeprüft in Pfad/Glob-Muster eingesetzt zu werden."""
    try:
        return str(uuid.UUID(upload_id))
    except (ValueError, AttributeError, TypeError):
        return "invalid-upload-id"


def _pdf_upload_staging_path(upload_id: str) -> Path:
    return main.PDF_UPLOAD_STAGING_DIR / f"{_normalize_upload_id(upload_id)}.pdf"


def _consume_pdf_upload(source_id: str, upload_id: str) -> None:
    staged_path = _pdf_upload_staging_path(upload_id)
    if not staged_path.exists():
        return
    main.PDF_DIR.mkdir(parents=True, exist_ok=True)
    staged_path.replace(main.PDF_DIR / f"{source_id}.pdf")


def _sync_pdf_file_from_url(source_id: str, url: str | None) -> None:
    pdf_path = main.PDF_DIR / f"{source_id}.pdf"
    if url and extraction.looks_like_pdf(url):
        data = extraction.download_pdf_bytes(url)
        if data:
            main.PDF_DIR.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(data)
            return
    if pdf_path.exists():
        pdf_path.unlink()


def _delete_pdf_file(source_id: str) -> None:
    pdf_path = main.PDF_DIR / f"{source_id}.pdf"
    if pdf_path.exists():
        pdf_path.unlink()


def _existing_pdf_file(source_id: str) -> Path | None:
    pdf_path = main.PDF_DIR / f"{source_id}.pdf"
    return pdf_path if pdf_path.exists() else None


def _audio_extension(url: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    return suffix if suffix in extraction.AUDIO_EXTENSIONS else ".mp3"


def _existing_audio_file(source_id: str) -> Path | None:
    matches = list(main.AUDIO_DIR.glob(f"{source_id}.*"))
    return matches[0] if matches else None


def _sync_audio_file_from_url(source_id: str, url: str | None) -> None:
    existing = _existing_audio_file(source_id)
    if url and extraction.looks_like_audio(url):
        data = extraction.download_audio_bytes(url)
        if data:
            main.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            if existing:
                existing.unlink()
            (main.AUDIO_DIR / f"{source_id}{_audio_extension(url)}").write_bytes(data)
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
    matches = list(main.AUDIO_UPLOAD_STAGING_DIR.glob(f"{_normalize_upload_id(upload_id)}.*"))
    if not matches:
        return
    staged_path = matches[0]
    main.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    _delete_audio_file(source_id)
    staged_path.replace(main.AUDIO_DIR / f"{source_id}{staged_path.suffix}")


_AUDIO_MEDIA_TYPES = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aac": "audio/aac",
}


def _store_chunks(
    source_id: str,
    source: SourceIn,
    chunks: list[str],
    chunk_embeddings: list[list[float]],
    images: list[dict] | None = None,
) -> int:
    # Idee ff895248: `images` sind die Bild-Einträge der Quelle (entry["images"]);
    # jeder Aufrufer, der Chunks neu schreibt, übergibt sie, sonst gingen die
    # Bilder an den Chunks verloren.
    chunk_ids = [f"{source_id}::{i}" for i in range(len(chunks))]
    images_per_chunk = chunking.assign_images(chunks, images or [])
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
        if images_per_chunk[i]:
            metadata["images_json"] = json.dumps(images_per_chunk[i], ensure_ascii=False)
        metadatas.append(metadata)
    vectorstore.add_chunks(chunk_ids, chunks, chunk_embeddings, metadatas)
    return len(chunks)


def _to_source_out(
    entry: dict, can_view_full_text: bool = False, lang: str = i18n.DEFAULT_LANG, include_text: bool = True
) -> SourceOut:
    data = dict(entry)
    if data.get("restricted") and not can_view_full_text:
        data["text"] = ""
    if not include_text:
        data["text"] = ""
    # Backlog #51: der Relevanz-Score ist eine reine Pflegeinformation für
    # Quellen-Pfleger:innen/System-Admins (später Grundlage für die
    # KI-Gewichtung) - für alle anderen wird das Feld gar nicht erst
    # mitgeschickt, nicht nur im UI versteckt.
    if not can_view_full_text:
        data["relevance_score"] = None
        # Backlog (2026-08-02): der reine Erreichbarkeits-Status
        # (url_reachable) bleibt für alle sichtbar - deckt sich mit dem
        # generischen Warn-Icon an der Quelle selbst. Der konkrete
        # Fehlergrund/Statuscode ist wie relevance_score eine reine
        # Pflegeinformation.
        data["url_reason_code"] = None
        data["url_status_code"] = None
    lang = lang if lang in ("de", "en") else i18n.DEFAULT_LANG
    data["summary"] = data.get(f"summary_{lang}") or ""
    data["key_terms"] = data.get(f"key_terms_{lang}") or []
    data["summary_ai_generated"] = data.get(f"summary_ai_generated_{lang}", True)
    data["key_terms_ai_generated"] = data.get(f"key_terms_ai_generated_{lang}", True)
    # Nutzerwunsch 2026-11-19: Bildanzahl (auch ausgeblendete) nur für die Pflege.
    data["image_count"] = (
        sum(source_images.image_src(data["id"], image) is not None for image in data.get("images") or [])
        if can_view_full_text
        else 0
    )
    data["has_pdf"] = (main.PDF_DIR / f"{data['id']}.pdf").exists()
    data["has_audio"] = _existing_audio_file(data["id"]) is not None
    return SourceOut(**data)


def _register_all_terms(source_id: str, entry: dict) -> None:
    terms.unregister_source(source_id)
    for term in entry.get("key_terms_de") or []:
        terms.register_term(term, source_id, "de")
    for term in entry.get("key_terms_en") or []:
        terms.register_term(term, source_id, "en")


def _generate_summary_with_retries(text: str) -> dict:
    # Nutzerwunsch (2026-09-22): bereits etablierte Schlagworte der Sammlung
    # (mind. 2 Quellen, siehe terms.list_established_terms) fließen in die
    # Generierung ein, damit das Modell einen passenden vorhandenen Begriff
    # bevorzugt statt eine neue Formulierung fürs selbe Thema zu erfinden.
    known_terms_de = terms.list_established_terms("de")
    known_terms_en = terms.list_established_terms("en")
    result = summarization.generate_bilingual_summary(text, known_terms_de, known_terms_en)
    for attempt in range(1, main.SUMMARY_RETRY_ATTEMPTS):
        if result["de"]["summary"] or result["en"]["summary"]:
            break
        time.sleep(main.SUMMARY_RETRY_DELAY_SECONDS)
        result = summarization.generate_bilingual_summary(text, known_terms_de, known_terms_en)
    return result


# Idee 134c868a: Textsprache + englischer Titel je Quelle. Beide Felder haben
# wie summary_*/key_terms_* ein *_ai_generated-Flag: von Hand gepflegte Werte
# (Flag False) überschreibt kein KI-Lauf.
def _source_lang_fields(entry: dict | None) -> dict:
    """Felder fürs Frontend (ChunkRef, Kreativ-Dict) aus dem Quellen-Eintrag."""
    entry = entry or {}
    return {
        "restricted": bool(entry.get("restricted")),
        "text_lang": entry.get("text_lang") or None,
        "title_en": entry.get("title_en") or None,
        "text_lang_ai_generated": entry.get("text_lang_ai_generated", True),
        "title_en_ai_generated": entry.get("title_en_ai_generated", True),
    }


def _known_lang(entry: dict | None) -> str | None:
    """Von Hand gepflegte Sprache (Flag False) - die KI übernimmt sie, liefert aber den Titel."""
    entry = entry or {}
    return entry.get("text_lang") if entry.get("text_lang_ai_generated") is False else None


def _detect_language_safely(title: str, text: str, known_lang: str | None = None) -> dict:
    # Ein Fehler hier darf nie die Zusammenfassung oder den Nachzug kippen.
    try:
        return summarization.detect_source_language(title, text, known_lang=known_lang)
    except Exception:
        return {"text_lang": None, "title_en": None}


def _apply_language_result(entry: dict, result: dict) -> None:
    """Schreibt ein Erkennungsergebnis in den Eintrag (Aufrufer hält den
    Schreib-Lock). None-Ergebnis überschreibt nichts; Handpflege bleibt."""
    if not result.get("text_lang"):
        return
    if entry.get("text_lang_ai_generated") is not False:
        entry["text_lang"] = result["text_lang"]
        entry["text_lang_ai_generated"] = True
    if entry.get("title_en_ai_generated") is not False:
        entry["title_en"] = result["title_en"]
        entry["title_en_ai_generated"] = True


def _detect_and_store_language(source_id: str, title: str, text: str) -> bool | None:
    """Erkennung als eigener Lauf (Nachzug, Titel-/Textänderung). KI-Aufruf
    vor dem Lock; geschrieben wird erst nach erneutem Laden, und nur wenn die
    Quelle noch existiert und Titel/Text unverändert sind (sonst läuft schon
    eine neuere Erkennung). True = gespeichert, False = KI-Fehler,
    None = Quelle inzwischen geändert/gelöscht (kein KI-Fehler)."""
    with _sources_write_lock:
        current = main._load_sources().get(source_id)
    result = _detect_language_safely(title, text, _known_lang(current))
    if not result.get("text_lang"):
        return False
    with _sources_write_lock:
        sources = main._load_sources()
        if _source_is_missing(sources, source_id):
            return None
        entry = sources[source_id]
        if entry.get("title") != title or (entry.get("text") or "").strip() != text.strip():
            return None
        _apply_language_result(entry, result)
        _save_sources(sources)
    return True


def _clear_ai_language_fields(entry: dict, keep: frozenset = frozenset()) -> None:
    """Titel/Text geändert: KI-erkannte Werte sind veraltet. Handgepflegte
    bleiben."""
    for field in ("text_lang", "title_en"):
        if field not in keep and entry.get(f"{field}_ai_generated") is not False:
            entry.pop(field, None)


def _generate_summary_background(source_id: str, text: str) -> None:
    # Nutzerwunsch (2026-09-22): eine Quelle galt bisher schon als "fertig"
    # (processing_status=None), sobald Text+Chunks gespeichert waren - die
    # anschliessende Zusammenfassung/Tag-Generierung lief zwar weiter, aber
    # unsichtbar für die Fortschrittsanzeige. processing_status bleibt jetzt
    # bis zum Ende dieser Funktion auf "running" (von den Aufrufern absichtlich
    # nicht mehr zurückgesetzt), mit eigenem processing_step fürs Icon/Label.
    with _sources_write_lock:
        sources = main._load_sources()
        title = ""
        known_lang = None
        if source_id in sources:
            title = sources[source_id].get("title", "")
            known_lang = _known_lang(sources[source_id])
            sources[source_id]["processing_step"] = "summarizing"
            _save_sources(sources)

    result = main._generate_summary_with_retries(text)
    # Beide KI-Aufrufe vor dem Lock; ein Erkennungsfehler verwirft nie die Zusammenfassung.
    language = _detect_language_safely(title, text, known_lang)
    with _sources_write_lock:
        sources = main._load_sources()
        if source_id not in sources:
            return
        _apply_language_result(sources[source_id], language)
        sources[source_id]["summary_de"] = result["de"]["summary"]
        sources[source_id]["summary_en"] = result["en"]["summary"]
        sources[source_id]["key_terms_de"] = result["de"]["key_terms"]
        sources[source_id]["key_terms_en"] = result["en"]["key_terms"]
        sources[source_id]["summary_ai_generated_de"] = True
        sources[source_id]["summary_ai_generated_en"] = True
        sources[source_id]["key_terms_ai_generated_de"] = True
        sources[source_id]["key_terms_ai_generated_en"] = True
        sources[source_id]["processing_status"] = None
        sources[source_id]["processing_step"] = None
        _save_sources(sources)
        main._register_all_terms(source_id, sources[source_id])


def _translate_summary_background(source_id: str, summary_text: str, target_lang: str) -> None:
    # Nutzerwunsch (2026-08-23): eine von Hand überarbeitete Zusammenfassung
    # soll automatisch in die jeweils andere Sprache übersetzt werden, statt
    # dort einen inhaltlich abweichenden (oder veralteten) Stand stehen zu
    # lassen. Läuft im Hintergrund, damit der Speicher-Request selbst nicht
    # auf den langsamen KI-Aufruf warten muss.
    translated = summarization.translate_summary(summary_text, target_lang)
    if not translated:
        return
    with _sources_write_lock:
        sources = main._load_sources()
        if _source_is_missing(sources, source_id):
            return
        # Erneute Prüfung unmittelbar vor dem Schreiben (analog
        # _generate_author_bio_one_lang): die Übersetzung dauert mehrere
        # Sekunden - in dieser Zeit könnte die Zielsprache inzwischen selbst
        # von Hand überarbeitet worden sein. Eine soeben gespeicherte
        # manuelle Fassung darf die automatische Übersetzung nie
        # kommentarlos überschreiben.
        if sources[source_id].get(f"summary_ai_generated_{target_lang}") is False:
            return
        sources[source_id][f"summary_{target_lang}"] = translated
        sources[source_id][f"summary_ai_generated_{target_lang}"] = False
        _save_sources(sources)


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


def _normalize_url_for_comparison(url: str) -> str:
    """Spiegelt static/import.js#normalizeUrlForComparison serverseitig -
    verschiedene YouTube-URL-Formen (youtu.be/watch/shorts) fuer dasselbe
    Video sollen als Duplikat erkannt werden, alle anderen URLs werden um
    bekannte Tracking-Parameter (siehe extraction.strip_tracking_params),
    Groß-/Kleinschreibung und einen abschließenden Slash bereinigt."""
    video_id = extraction.extract_youtube_video_id(url)
    if video_id:
        return f"youtube:{video_id.lower()}"
    return extraction.strip_tracking_params(url).strip().rstrip("/").lower()


def _find_existing_source_by_url(sources: dict, url: str) -> dict | None:
    normalized = _normalize_url_for_comparison(url)
    if not normalized:
        return None
    for entry in sources.values():
        if entry.get("deleted_at") or not entry.get("url"):
            continue
        if _normalize_url_for_comparison(entry["url"]) == normalized:
            return entry
    return None


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


# Fix (2026-08-03, Vorfall auf Produktion): ein Blue/Green-Deploy sendet dem
# alten Prozess SIGTERM, sobald der neue Slot gesund ist - uvicorns eigenes
# "graceful shutdown" wartet dabei nur auf offene HTTP-Requests, nicht auf
# unsere eigenen Hintergrund-Threads (Embedding+Zusammenfassung, PDF-OCR,
# Audio-Transkription). Ein Import, der genau während eines Deploys noch
# verarbeitet wurde, wurde dadurch mitten in der Verarbeitung abgebrochen
# und blieb für immer auf processing_status="pending" stehen (Text und
# Zusammenfassung nie gespeichert). _track_background_job() markiert einen
# laufenden Job, der Shutdown-Hook unten wartet beim Beenden kurz (bounded)
# darauf, dass alle laufenden Jobs fertig werden, bevor der Prozess endet.
_in_flight_background_jobs = 0
_in_flight_jobs_lock = threading.Lock()
_in_flight_jobs_drained = threading.Event()
_in_flight_jobs_drained.set()
# Welche Quelle(n) gerade in einem _track_background_job()-Block stecken -
# damit der Shutdown-Hook unten (falls die Wartezeit doch nicht reicht,
# z.B. bei sehr langen Audio-Transkriptionen) genau diese Quellen markieren
# kann, statt raten zu müssen, wer betroffen ist.
_in_flight_background_job_source_ids: set[str] = set()


@contextlib.contextmanager
def _track_background_job(source_id: str):
    global _in_flight_background_jobs
    with _in_flight_jobs_lock:
        _in_flight_background_jobs += 1
        _in_flight_background_job_source_ids.add(source_id)
        _in_flight_jobs_drained.clear()
    try:
        yield
    finally:
        with _in_flight_jobs_lock:
            _in_flight_background_jobs -= 1
            _in_flight_background_job_source_ids.discard(source_id)
            if _in_flight_background_jobs <= 0:
                _in_flight_jobs_drained.set()


def _wait_for_background_jobs_on_shutdown() -> None:
    finished_in_time = _in_flight_jobs_drained.wait(timeout=main.BACKGROUND_JOB_SHUTDOWN_GRACE_SECONDS)
    if finished_in_time:
        return
    # Nutzerwunsch (2026-08-03): Wartezeit hat nicht gereicht - die
    # betroffenen Quellen bekommen ein Merkmal, damit der nächste
    # Prozessstart (_recover_interrupted_processing_jobs) sie automatisch
    # neu einreiht statt (wie bei einem "echten" Absturz) nur als Fehler zu
    # markieren. Ein Prozess, der stattdessen hart abstürzt (OOM, kill -9),
    # durchläuft diesen Hook gar nicht erst - solche Quellen bleiben bewusst
    # beim bisherigen Verhalten (manueller Re-Import).
    with _in_flight_jobs_lock:
        still_running = set(_in_flight_background_job_source_ids)
    if not still_running:
        return
    with _sources_write_lock:
        sources = main._load_sources()
        changed = False
        for source_id in still_running:
            entry = sources.get(source_id)
            if entry and entry.get("processing_status") == "running":
                entry["interrupted_by_deploy"] = True
                changed = True
        if changed:
            _save_sources(sources)


def _finalize_extracted_text(source_id: str, lang: str, text: str, failure_i18n_key: str) -> None:
    """Gemeinsamer Ablauf ab dem Punkt, an dem der Volltext einer Quelle
    feststeht (oder leer ist, siehe unten): chunkt/indiziert die Quelle,
    oder markiert sie bei leerem Text als Fehler. Wird sowohl von der PDF-
    Texterkennung (_run_deferred_text_extraction) als auch - nach
    vollständig erfolgreicher, ggf. mehrteiliger Transkription - von
    _process_audio_transcription aufgerufen."""
    with _sources_write_lock:
        sources = main._load_sources()
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
            sources = main._load_sources()
            if source_id not in sources:
                return
            sources[source_id]["processing_status"] = "error"
            sources[source_id]["processing_step"] = None
            sources[source_id]["processing_error"] = i18n.get_message("no_chunks", lang)
            _save_sources(sources)
        return

    with _sources_write_lock:
        sources = main._load_sources()
        if source_id not in sources:
            return
        sources[source_id]["processing_step"] = "indexing"
        _save_sources(sources)
    chunk_embeddings = embeddings.embed_passages(chunks)

    with _sources_write_lock:
        sources = main._load_sources()
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
            chunk_count = _store_chunks(source_id, source_stub, chunks, chunk_embeddings, entry.get("images"))

            sources = main._load_sources()
            if source_id not in sources:
                return
            sources[source_id]["text"] = text
            sources[source_id]["chunk_count"] = chunk_count
            # processing_status bleibt bewusst "running" - erst
            # _generate_summary_background setzt ihn zurück, siehe dort.
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
        sources = main._load_sources()
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
        sources = main._load_sources()
        if source_id not in sources:
            return
        entry = sources[source_id]
        entry["processing_status"] = "running"
        entry["processing_step"] = "transcribe"
        known_segments = {int(k): v for k, v in (entry.get("processing_segments") or {}).items()}
        # Reihenfolge bewusst erhalten (erste Nennung zählt), Dubletten
        # entfernt - z.B. wenn eine Person sowohl als Autor:in dieser Quelle
        # eingetragen als auch bereits in transcription_hints.json gelistet
        # ist (siehe dort), soll ihr Name nicht doppelt im Prompt stehen.
        known_names = list(
            dict.fromkeys(
                list(entry.get("authors") or [])
                + transcription_hints.get_hints(lang if lang in ("de", "en") else i18n.DEFAULT_LANG)
            )
        )
        _save_sources(sources)

    def on_segment_success(index: int, total: int, segment_text: str) -> None:
        with _sources_write_lock:
            sources = main._load_sources()
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
            audio_path,
            known_segments=known_segments,
            on_segment_success=on_segment_success,
            known_names=known_names,
        )

    if error_detail:
        with _sources_write_lock:
            sources = main._load_sources()
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
    with _track_background_job(source_id):
        pdf_path = _existing_pdf_file(source_id)
        _run_deferred_text_extraction(
            source_id,
            lang,
            initial_step="ocr",
            compute_text=lambda: extraction.ocr_pdf_with_ai(pdf_path.read_bytes()) if pdf_path else "",
            failure_i18n_key="pdf_ocr_failed",
        )


def _store_pdf_images(source_id: str, data: bytes) -> list[dict]:
    return source_images.store_images(main.SOURCE_IMAGES_DIR, source_id, extraction.extract_pdf_images(data))


def _find_author(name: str) -> dict | None:
    normalized = " ".join(name.strip().split()).lower()
    return next(
        (a for a in authors.list_authors() if " ".join(a["name"].strip().split()).lower() == normalized),
        None,
    )


def _rename_author_entity(old_name: str, new_name: str) -> dict | None:
    """Kern-Logik einer Autor:innen-Umbenennung, unabhängig vom aufrufenden
    Endpoint - genutzt sowohl von rename_author_endpoint als auch vom
    Rückgängig-machen einer Umbenennung (POST /api/audit-log/{id}/revert,
    einfach mit vertauschtem alten/neuen Namen aufgerufen). Der Name ist
    kein eigenständiges Feld, sondern wird aus dem authors-Feld jeder Quelle
    abgeleitet (siehe app/authors.py) - eine Umbenennung muss deshalb in
    JEDER betroffenen Quelle nachvollzogen werden, sonst würde die nächste
    Quellen-Bearbeitung (die authors.py per unregister/register neu
    aufbaut) den alten Namen wiederherstellen. Gibt den aktualisierten,
    rohen Autor:innen-Eintrag zurück oder None, falls old_name nicht (mehr)
    existiert."""
    matching = _find_author(old_name)
    if matching is None:
        return None
    old_key = " ".join(old_name.strip().split()).lower()

    with _sources_write_lock:
        sources = main._load_sources()
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
    author_photos.rename(old_name, new_name)
    return _find_author(new_name)
