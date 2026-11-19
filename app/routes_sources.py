# Idee 313ad93d: aus app/main.py ausgelagert (Verhalten unverändert).

import itertools
import logging
import networkx as nx
import threading
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header, Query, Request
from fastapi.responses import FileResponse
from urllib.parse import quote
from app import (
    audit,
    author_photos,
    author_profiles,
    authors,
    chunking,
    embeddings,
    extraction,
    i18n,
    monitoring,
    source_images,
    summarization,
    terms,
    users,
    vectorstore,
)
from app.models import (
    AuthorBioPreviewIn,
    AuthorOut,
    AuthorProfileIn,
    BioOut,
    GraphEdge,
    GraphNode,
    KeyTermsOut,
    KeyTermsPreviewIn,
    KnowledgeGraphOut,
    MessageOut,
    RenameAuthorIn,
    SourceIn,
    SourceOut,
)

from app import main
from app.background import (
    _acquire_reindex_lock,
    _audio_transcription_queue,
    _backfill_images_holding_lock,
    _persist_url_health_results,
    _reindex_holding_lock,
    _review_source_images,
)
from app.source_processing import (
    _clear_ai_language_fields,
    _consume_audio_upload,
    _consume_pdf_upload,
    _detect_and_store_language,
    _diff_fields,
    _existing_pdf_file,
    _find_author,
    _find_existing_source_by_url,
    _generate_summary_background,
    _is_deferred_audio_import,
    _is_deferred_pdf_import,
    _pdf_upload_staging_path,
    _prepare_chunks,
    _rename_author_entity,
    _save_sources,
    _source_is_missing,
    _sources_write_lock,
    _store_chunks,
    _store_pdf_images,
    _sync_audio_file_from_url,
    _sync_pdf_file_from_url,
    _to_source_out,
    _track_background_job,
    _translate_summary_background,
    _vectorstore_write_lock,
)

router = APIRouter()


@router.post("/api/admin/reindex-sources", response_model=MessageOut)
def reindex_sources(
    background_tasks: BackgroundTasks,
    images_only: bool = False,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    lock_file = _acquire_reindex_lock()
    if lock_file is None:
        raise HTTPException(409, i18n.get_message("reindex_running", x_lang))
    if images_only:
        background_tasks.add_task(_backfill_images_holding_lock, lock_file)
        return MessageOut(detail=i18n.get_message("reindex_started", x_lang))
    background_tasks.add_task(_reindex_holding_lock, lock_file, fetch_missing_images=True)
    return MessageOut(detail=i18n.get_message("reindex_started", x_lang))


def _create_pending_source(source_id: str, source: SourceIn, imported_at: str) -> None:
    with _sources_write_lock:
        sources = main._load_sources()
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
            "relevance_score": source.relevance_score if source.relevance_score is not None else 5,
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
    with _track_background_job(source_id):
        with _sources_write_lock:
            sources = main._load_sources()
            if source_id not in sources:
                done_event.set()
                return
            sources[source_id]["processing_status"] = "running"
            sources[source_id]["processing_step"] = "indexing"
            _save_sources(sources)

        try:
            # Bilder erst hier (nicht im Request): PDF-Datei liegt seit add_source vor.
            try:
                images = _import_images(source_id, source)
            except Exception:
                logging.getLogger("app.main").exception("Bild-Import von Quelle %s fehlgeschlagen", source_id)
                images = None
            chunk_embeddings = embeddings.embed_passages(chunks)
            with _vectorstore_write_lock:
                chunk_count = _store_chunks(source_id, source, chunks, chunk_embeddings, images)
        except Exception as exc:
            outcome["error"] = exc
            with _sources_write_lock:
                sources = main._load_sources()
                if source_id in sources:
                    sources[source_id]["processing_status"] = "error"
                    sources[source_id]["processing_step"] = None
                    sources[source_id]["processing_error"] = str(exc)
                    _save_sources(sources)
            done_event.set()
            return

        outcome["chunk_count"] = chunk_count
        with _sources_write_lock:
            sources = main._load_sources()
            if source_id in sources:
                sources[source_id]["text"] = text
                sources[source_id]["chunk_count"] = chunk_count
                if images is not None:
                    sources[source_id]["images"] = images
                    sources[source_id]["images_checked_at"] = datetime.now(timezone.utc).isoformat()
                # processing_status bleibt bewusst "running" - erst
                # _generate_summary_background setzt ihn zurück, siehe dort.
                sources[source_id]["processing_error"] = None
                _save_sources(sources)
        # Muss NACH dem Speichern des Ergebnisses, aber VOR der (potenziell
        # mehrere Sekunden dauernden) Zusammenfassung gesetzt werden - eine
        # noch wartende add_source-Anfrage soll durch die Zusammenfassung
        # nicht zusätzlich blockiert werden, die läuft komplett unabhängig
        # weiter (aber weiterhin unter _track_background_job, siehe oben).
        done_event.set()
        _generate_summary_background(source_id, text)
        if images:
            try:
                _review_source_images(source_id)
            except Exception:
                logging.getLogger("app.main").exception("Bildprüfung von Quelle %s fehlgeschlagen", source_id)


def _import_images(source_id: str, source: SourceIn) -> list[dict] | None:
    """Bilder für eine neue Quelle (Idee ff895248): aus der gespeicherten
    PDF-Datei oder aus dem Staging der URL-Vorschau (nur bei exakt gleicher
    URL, vom Server erneut gefiltert). Der Client schickt nie Bilder selbst.
    None = nichts versucht/gefunden (kein `images_checked_at`)."""
    pdf_file = _existing_pdf_file(source_id)
    if pdf_file is not None:
        return _store_pdf_images(source_id, pdf_file.read_bytes())
    if source.image_token and source.url:
        # [] (Seite geprüft, keine Bilder) zählt als geprüft; None = ungültiger Token.
        return source_images.take_staged_web_images(main.IMAGE_STAGING_DIR, source.image_token, source.url)
    return None


@router.post("/api/sources", response_model=SourceOut)
def add_source(
    source: SourceIn,
    background_tasks: BackgroundTasks,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    if source.url:
        # Nutzerwunsch (2026-08-31): Tracking-Parameter (utm_*, fbclid, ...)
        # sollen weder in die gespeicherte Quelle übernommen werden noch die
        # Duplikat-Prüfung durcheinanderbringen - hier einmalig bereinigt,
        # bevor source.url irgendwo verwendet wird (Duplikat-Prüfung,
        # PDF/Audio-Sync, gespeicherter Datensatz weiter unten).
        source.url = extraction.strip_tracking_params(source.url)
        # Serverseitiges Gegenstück zum Frontend-Check (findExistingSourceByUrl
        # in import.js) - das Frontend prüft nur gegen den zuletzt geladenen
        # allSources-Stand und schützt daher nicht vor gleichzeitigen Imports
        # derselben URL oder direkten API-Aufrufen ohne UI.
        existing = _find_existing_source_by_url(main._load_sources(), source.url)
        if existing:
            raise HTTPException(
                400, i18n.get_message("url_already_exists", x_lang, title=existing["title"])
            )

    # Fix (2026-08-23, per realem Produktions-Vorfall): pdf_upload_id kam
    # bisher unhinterfragt bis zu _consume_pdf_upload() weiter unten durch -
    # war die hochgeladene Datei zu dem Zeitpunkt schon nicht mehr da (z.B.
    # ein bereits verwendeter/veralteter upload_id-Wert), legte add_source()
    # trotzdem klaglos eine "deferred_pdf"-Quelle an. Der spätere Hintergrund-
    # Job (_process_pdf_ocr) fand dann natürlich auch keine PDF-Datei, brach
    # mit leerem Text ab und landete als "Texterkennung fehlgeschlagen" -
    # ununterscheidbar von einem ECHTEN KI-Vision-Fehlschlag, obwohl die
    # KI-Texterkennung dabei nie auch nur aufgerufen wurde. Früh und
    # synchron prüfen, damit ein derartiger Fall sofort eine klare
    # Fehlermeldung bekommt, statt lautlos Wochen später als rätselhafter
    # OCR-Fehler wieder aufzutauchen.
    if source.pdf_upload_id and not _pdf_upload_staging_path(source.pdf_upload_id).exists():
        raise HTTPException(400, i18n.get_message("pdf_upload_not_found", x_lang))

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

    # Idee ff895248: die PDF-Datei muss vor dem Chunk-Speichern vorliegen, damit
    # die PDF-Bilder gleich den Chunks zugeordnet werden können.
    if source.pdf_upload_id:
        _consume_pdf_upload(source_id, source.pdf_upload_id)
    else:
        _sync_pdf_file_from_url(source_id, source.url)

    slow_import = False
    if not deferred:
        outcome: dict = {}
        done_event = threading.Event()
        threading.Thread(
            target=main._finish_synchronous_import,
            args=(source_id, source, chunks, text, outcome, done_event),
            daemon=True,
        ).start()
        finished = done_event.wait(main.SLOW_IMPORT_TIMEOUT_SECONDS)
        if finished and "error" in outcome:
            raise outcome["error"]
        slow_import = not finished

    for name in source.authors:
        is_new_author = _find_author(name) is None
        authors.register_author(name, source_id)
        if is_new_author:
            background_tasks.add_task(_generate_author_bio_background, name)

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
        background_tasks.add_task(main._process_pdf_ocr, source_id, x_lang)
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
            "relevance_score": source.relevance_score if source.relevance_score is not None else 5,
            "summary_de": "",
            "summary_en": "",
            "key_terms_de": [],
            "key_terms_en": [],
            # Spiegelt den Stand, den _finish_synchronous_import im selben
            # Moment auf der Platte hinterlässt: die Zusammenfassung läuft
            # gerade erst an (siehe _generate_summary_background).
            "processing_status": "running",
            "processing_step": "summarizing",
            "processing_error": None,
        }
    else:
        sources = main._load_sources()
        entry = sources[source_id]
    audit.log_action(_user, "source_created", "source", source_id, entry.get("title", source_id))
    return _to_source_out(entry, can_view_full_text=True, lang=x_lang)


@router.put("/api/sources/{source_id}", response_model=SourceOut)
def update_source(
    source_id: str,
    source: SourceIn,
    background_tasks: BackgroundTasks,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    # Idee 134c868a (K4/H2): der Code landet später in einer URL - nur 2-3
    # Kleinbuchstaben. "" gilt wie None als "nicht mitgeschickt".
    if source.text_lang and not summarization.is_valid_lang_code(source.text_lang):
        raise HTTPException(400, i18n.get_message("invalid_text_lang", x_lang))
    with _sources_write_lock:
        sources = main._load_sources()
        if _source_is_missing(sources, source_id):
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

        # Momentaufnahme VOR jeder Änderung - Grundlage für den Feld-Diff
        # weiter unten (Backlog #99), der ins Änderungs-Log wandert und
        # spätere gezielte Reverts ermöglicht.
        before = dict(sources[source_id])

        metadata_only = bool(sources[source_id].get("restricted")) and not source.text.strip()

        # Neue PDF-Datei oder neue URL: die alten Bilder gehören nicht mehr dazu
        # (Dateien weg, Eintrag leer -> der Admin-Reindex holt sie neu nach).
        if not metadata_only and (source.pdf_upload_id or (source.url or None) != (before.get("url") or None)):
            source_images.delete_source_images(main.SOURCE_IMAGES_DIR, source_id)
            sources[source_id].pop("images", None)
            sources[source_id].pop("images_checked_at", None)

        if not metadata_only:
            chunks, chunk_embeddings = _prepare_chunks(source, x_lang)
            with _vectorstore_write_lock:
                vectorstore.delete_source_chunks(source_id)
                chunk_count = _store_chunks(
                    source_id, source, chunks, chunk_embeddings, sources[source_id].get("images")
                )
            sources[source_id]["text"] = source.text.strip()
            sources[source_id]["chunk_count"] = chunk_count
            # Nutzerwunsch (2026-08-03): ein manueller Edit ist die Reparatur
            # fuer einen fehlgeschlagenen Import (z.B. Text von Hand
            # eingefuegt, siehe youtube-transcript.io-Workaround) - ohne
            # dies bliebe die Quelle trotz erfolgreichem Speichern fuer immer
            # auf processing_status="error" stehen.
            sources[source_id]["processing_status"] = None
            sources[source_id]["processing_step"] = None
            sources[source_id]["processing_error"] = None

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
        # Fix (2026-09-26): das Formular schickt Zusammenfassung und
        # Schlagworte bei JEDEM Speichern mit - als "von Hand überarbeitet"
        # zählt nur eine tatsächliche Änderung (sonst verlor z. B. eine reine
        # Titeländerung das KI-Icon und löste eine Übersetzung aus).
        summary_changed = source.summary is not None and source.summary != (
            sources[source_id].get(f"summary_{x_lang}") or ""
        )
        if summary_changed:
            sources[source_id][f"summary_{x_lang}"] = source.summary
            # Nutzerwunsch (2026-08-23): eine von Hand überarbeitete
            # Zusammenfassung gilt ab jetzt als kuratiert - ein späterer KI-
            # Lauf (generate_source_summary) darf sie nicht mehr
            # kommentarlos überschreiben (siehe dort).
            sources[source_id][f"summary_ai_generated_{x_lang}"] = False
        if source.key_terms is not None and source.key_terms != (sources[source_id].get(f"key_terms_{x_lang}") or []):
            sources[source_id][f"key_terms_{x_lang}"] = source.key_terms
            sources[source_id][f"key_terms_ai_generated_{x_lang}"] = False
        if source.relevance_score is not None:
            sources[source_id]["relevance_score"] = source.relevance_score
        # Idee 134c868a (K2): geänderter Titel/Text macht KI-erkannte Sprache
        # und englischen Titel ungültig - leeren und neu erkennen lassen.
        # Danach erst die mitgeschickten Werte: nur eine tatsächliche
        # Änderung gegenüber vorher zählt als Handpflege (wie bei summary).
        redetect = source.title != before.get("title") or (
            not metadata_only and source.text.strip() != (before.get("text") or "").strip()
        )
        if redetect:
            _clear_ai_language_fields(sources[source_id])
        if source.text_lang and source.text_lang != before.get("text_lang"):
            sources[source_id]["text_lang"] = source.text_lang
            sources[source_id]["text_lang_ai_generated"] = False
        title_en = summarization.clean_title_en(source.title_en) if source.title_en is not None else None
        if source.title_en is not None and (title_en or None) != (before.get("title_en") or None):
            sources[source_id]["title_en"] = title_en
            sources[source_id]["title_en_ai_generated"] = False
        _save_sources(sources)

    if redetect:
        background_tasks.add_task(
            _detect_and_store_language, source_id, source.title, sources[source_id].get("text", "")
        )

    if summary_changed and source.summary.strip():
        other_lang = "en" if x_lang == "de" else "de"
        background_tasks.add_task(_translate_summary_background, source_id, source.summary, other_lang)

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
        main._register_all_terms(source_id, sources[source_id])

    if source.pdf_upload_id:
        _consume_pdf_upload(source_id, source.pdf_upload_id)
    elif not metadata_only:
        _sync_pdf_file_from_url(source_id, source.url)

    if not source.url and source.audio_upload_id:
        _consume_audio_upload(source_id, source.audio_upload_id)
    elif not metadata_only:
        _sync_audio_file_from_url(source_id, source.url)

    new_values = {
        "title": source.title,
        "authors": source.authors,
        "date": source.date,
        "url": source.url,
        "listen_url": source.listen_url,
        "restricted": source.restricted,
    }
    if not metadata_only:
        new_values["text"] = source.text.strip()
    if source.summary is not None:
        new_values[f"summary_{x_lang}"] = source.summary
    if source.key_terms is not None:
        new_values[f"key_terms_{x_lang}"] = source.key_terms
    if source.relevance_score is not None:
        new_values["relevance_score"] = source.relevance_score
    for field in ("text_lang", "title_en"):
        if field in sources[source_id] and sources[source_id][field] != before.get(field):
            new_values[field] = sources[source_id][field]
    changes = _diff_fields(before, new_values)
    if changes:
        audit.log_change(
            _user, "source_updated", "source", source_id, sources[source_id].get("title", source_id), changes
        )

    # Backlog (Nutzerwunsch, 2026-08-02): wer eine als kaputt markierte
    # Quelle bearbeitet, will direkt sehen, ob der Link jetzt wieder
    # erreichbar ist - statt bis zu eine Woche auf den naechsten
    # Hintergrund-Lauf (_run_url_health_check_once) warten zu muessen.
    if before.get("url_reachable") is False:
        if source.url:
            result = monitoring.check_url(source.url)
            _persist_url_health_results({source_id: result})
        else:
            # URL entfernt - nichts mehr zu pruefen. Der alte "kaputt"-
            # Status darf nicht fuer immer stehen bleiben, da der
            # woechentliche Hintergrund-Check Quellen ohne URL uebergeht.
            with _sources_write_lock:
                fresh = main._load_sources()
                entry = fresh.get(source_id)
                if entry and not entry.get("deleted_at"):
                    for field in ("url_reachable", "url_reason_code", "url_status_code", "url_checked_at"):
                        entry[field] = None
                    _save_sources(fresh)
        with _sources_write_lock:
            sources[source_id] = main._load_sources().get(source_id, sources[source_id])

    return _to_source_out(sources[source_id], can_view_full_text=True, lang=x_lang)


@router.delete("/api/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    # Weiches Löschen (Backlog #45/#99): die Quelle verschwindet aus RAG/
    # Konversation/Übersicht, aber weder der Datensatz noch eine angehängte
    # PDF-/Audio-Datei werden physisch entfernt - beides bleibt für ein
    # spätere Wiederherstellung übers Änderungs-Log erhalten (siehe
    # POST /api/audit-log/{id}/revert). _delete_pdf_file/_delete_audio_file
    # bleiben bewusst unangetastet für ihren bisherigen Zweck (Datei wird
    # beim Bearbeiten durch eine andere URL ersetzt), werden hier aber
    # NICHT mehr aufgerufen.
    with _sources_write_lock:
        sources = main._load_sources()
        if _source_is_missing(sources, source_id):
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

        title = sources[source_id].get("title", source_id)
        deleted_at = datetime.now(timezone.utc).isoformat()
        with _vectorstore_write_lock:
            vectorstore.delete_source_chunks(source_id)
        sources[source_id]["deleted_at"] = deleted_at
        _save_sources(sources)
    audit.log_change(
        _user, "source_deleted", "source", source_id, title, {"deleted_at": {"old": None, "new": deleted_at}}
    )
    authors.unregister_source(source_id)
    terms.unregister_source(source_id)


@router.get("/api/sources/{source_id}/images/{name}")
def get_source_image(source_id: str, name: str, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    # Öffentlich wie die Autorenfotos (Idee ff895248). Der Zufallsname im
    # Pfad ist die Zugriffsgrenze; der Pfad entsteht nur aus geprüften Teilen.
    # ponytail: bei restricted-Quellen genügt der unratbare Name, kein Ablauf -
    # Ausbaustufe wäre eine signierte URL mit Ablaufzeit.
    path = source_images.image_path(main.SOURCE_IMAGES_DIR, source_id, name)
    if path is None or _source_is_missing(main._load_sources(), source_id):
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))
    return FileResponse(
        path,
        media_type="image/webp",
        headers={"Cache-Control": "private, max-age=604800", "X-Content-Type-Options": "nosniff"},
    )


@router.get("/api/sources", response_model=list[SourceOut])
def list_sources(
    request: Request,
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
    include_text: bool = True,
):
    # Nutzerwunsch (2026-08-31): der Volltext aller Quellen macht die Antwort
    # groß (dient nur der client-seitigen Volltextsuche, Backlog #94) - das
    # Frontend lädt die sichtbare Liste deshalb zuerst per include_text=false
    # und den Volltext erst danach im Hintergrund nach (siehe
    # static/import.js: loadSources/loadFullSourceText). Default bleibt True,
    # damit kein anderer/künftiger Aufrufer sich implizit auf schlankere
    # Antworten verlassen muss.
    email = main._session_user_email(request)
    can_view_full_text = users.has_role(email, users.QUELLEN_PFLEGER)
    # Idee 669405f0: Gäste bekommen nie Volltexte (Crawler-Schutz); ihre
    # Suche läuft über GET /api/sources/search.
    include_text = include_text and email is not None
    sources = main._load_sources()
    return [
        _to_source_out(entry, can_view_full_text, x_lang, include_text=include_text)
        for entry in sources.values()
        if not entry.get("deleted_at")
    ]


_SEARCH_INDEX: dict = {"key": None, "rows": []}


def _search_index() -> list:
    """Kleinbuchstaben-Suchfelder je Quelle, neu gebaut nur wenn sich
    sources.json (Pfad, mtime, Größe) ändert."""
    st = main.SOURCES_FILE.stat() if main.SOURCES_FILE.exists() else None
    key = (str(main.SOURCES_FILE), st and st.st_mtime_ns, st and st.st_size)
    if _SEARCH_INDEX["key"] != key:
        rows = []
        for sid, e in main._load_sources().items():
            if e.get("deleted_at"):
                continue
            fields = {}
            for lang in ("de", "en"):
                f = [e.get("title"), e.get("summary_" + lang), " ".join(e.get("key_terms_" + lang) or []),
                     " ".join(e.get("authors") or [])]
                if lang == "en" and e.get("text_lang") not in (None, "", "en"):
                    f.append(e.get("title_en"))
                fields[lang] = [(x or "").lower() for x in f]
            rows.append((sid, bool(e.get("restricted")), (e.get("text") or "").lower(), fields))
        _SEARCH_INDEX.update(key=key, rows=rows)
    return _SEARCH_INDEX["rows"]


# Route steht VOR /api/sources/{source_id}. Antwort nur IDs - nie Text/Ausschnitt.
@router.get("/api/sources/search")
def search_sources(
    request: Request,
    q: str = Query(default="", max_length=200),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    q = q.strip().lower()
    if len(q) < 2:
        return {"ids": []}
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    full = users.has_role(main._session_user_email(request), users.QUELLEN_PFLEGER)
    ids = []
    for sid, restricted, text, fields in _search_index():
        if any(q in f for f in fields[lang]) or (text and (full or not restricted) and q in text):
            ids.append(sid)
    return {"ids": ids}


def _author_photo_urls(name: str) -> dict:
    # Nutzerwunsch (2026-08-23): unterschiedliche Auflösungen für Vita-Panel
    # (groß, gute Qualität) und Explore-Graph (klein) - siehe app/
    # author_photos.py. Leerer String, solange (noch) kein Cache existiert,
    # z.B. weil die Original-URL nie erreichbar war oder das Caching im
    # Hintergrund-Worker noch nicht dran war - das Frontend fällt dann auf
    # photo_url bzw. bei komplett fehlendem Foto auf den bloßen Namen zurück.
    return {
        size: f"/api/authors/{quote(name)}/photo/{size}" if author_photos.has_cached_photo(name, size) else ""
        for size in author_photos.SIZES
    }


def _resolve_profile_for_lang(name: str, profile: dict, lang: str) -> dict:
    # API-seitig bleibt "bio"/"bio_ai_generated" ein einzelnes, sprach-
    # aufgelöstes Feld (wie summary_{lang} bei Quellen) - nur die Speicherung
    # in author_profiles.py ist bilingual (bio_de/bio_en), damit Frontend und
    # Wire-Format unverändert einfach bleiben.
    photo_urls = _author_photo_urls(name)
    return {
        "bio": profile.get(f"bio_{lang}", ""),
        "bio_ai_generated": profile.get(f"bio_ai_generated_{lang}", False),
        "photo_url": profile.get("photo_url", ""),
        "photo_small": photo_urls["small"],
        "photo_large": photo_urls["large"],
        "website": profile.get("website", ""),
        "social_links": profile.get("social_links", []),
    }


@router.get("/api/authors", response_model=list[AuthorOut])
def list_authors(x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    entries = authors.list_authors()
    for entry in entries:
        entry.update(_resolve_profile_for_lang(entry["name"], author_profiles.get_profile(entry["name"]), lang))
    return entries


# Nutzerwunsch (2026-08-23): lokal gecachte Autor:innen-Fotos ausliefern
# (siehe app/author_photos.py) - öffentlich wie /api/sources selbst, da
# auch die Vita-Ansicht/der Explore-Graph für alle Besucher:innen sichtbar
# sind. Eine Woche Cache-Control, da eine einmal erzeugte Datei sich nur
# durch eine neue photo_url ändert (dann entsteht ohnehin ein neuer,
# inhaltlich anderer Dateiinhalt unter demselben Pfad - kurzfristig
# veraltete Browser-Caches sind hier unkritisch).
@router.get("/api/authors/{name}/photo/{size}")
def get_author_photo(name: str, size: str):
    if size not in author_photos.SIZES:
        raise HTTPException(404)
    path = author_photos.photo_path(name, size)
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "public, max-age=604800"})


# Nutzerwunsch (2026-08-23): "Explore"-Modus - ein Schlagwort-/Autor:innen-
# Netzwerk statt der Konversationsansicht, per neuem Icon in der
# Kopfzeile erreichbar (siehe static/header.js/explore.js). Knoten:
# Schlagworte (aus key_terms_de) und Autor:innen; Kanten: zwei Schlagworte
# sind verbunden, wenn sie in derselben Quelle vorkommen (macht thematisch
# verwandte Texte indirekt sichtbar), eine Autorin/ein Autor ist mit jedem
# Schlagwort verbunden, das in ihren/seinen Quellen vorkommt. Wird bei
# jedem Request frisch berechnet (Datenmenge klein genug, siehe
# _build_source_suggestion_topic_seed für dasselbe Muster) - damit zeigt
# ein Rücksprung aus dem Bearbeiten-Modus (import.html) sofort den
# aktuellen Stand, ganz ohne eigene Cache-Invalidierung.
_GRAPH_MIN_TERM_OCCURRENCES = 2


def _build_knowledge_graph(lang: str = "de") -> KnowledgeGraphOut:
    lang = lang if lang in ("de", "en") else "de"
    key_terms_field = f"key_terms_{lang}"
    sources = main._load_sources()
    active_sources = {sid: entry for sid, entry in sources.items() if not entry.get("deleted_at")}
    author_entries = authors.list_authors()

    # Nutzerwunsch (2026-08-24): Ein Schlagwort, das namensgleich mit einer
    # registrierten Autorin/einem Autor ist (z.B. "Jos de Blok" taucht als
    # Schlagwort in einem FREMDEN Text auf, der über ihn schreibt), bekommt
    # keinen eigenen Schlagwort-Knoten - alle seine Kanten zeigen stattdessen
    # direkt auf den bestehenden Autor-Knoten. So verbindet ein Text, der
    # jemanden nur thematisch erwähnt, sich im Netzwerk sichtbar mit dessen
    # Autor:innen-Knoten statt mit einem zweiten, gleichnamigen Knoten ohne
    # Bezug. Die Schlagwort-Suche selbst (app/terms.py, /api/terms) bleibt
    # davon unberührt, die liest weiterhin direkt aus key_terms_*.
    author_key_by_normalized_name = {
        authors.normalize_name(author["name"]): f"author:{author['name']}" for author in author_entries
    }

    def _node_key(term: str) -> str:
        return author_key_by_normalized_name.get(authors.normalize_name(term), f"term:{term}")

    # Nutzerfeedback (2026-08-23): Begriffe, die nur ein einziges Mal in der
    # gesamten Sammlung vorkommen (oft Extraktionsrauschen wie bloße
    # Einzelbuchstaben), werden ausgeblendet - sonst hinge ein Großteil der
    # Knoten unverbunden am Rand.
    term_counts: dict[str, int] = {}
    for entry in active_sources.values():
        for term in set(entry.get(key_terms_field) or []):
            term_counts[term] = term_counts.get(term, 0) + 1
    kept_terms = {term for term, count in term_counts.items() if count >= _GRAPH_MIN_TERM_OCCURRENCES}
    plain_terms = {term for term in kept_terms if _node_key(term) == f"term:{term}"}

    graph = nx.Graph()
    for term in plain_terms:
        graph.add_node(f"term:{term}")
    for author in author_entries:
        graph.add_node(f"author:{author['name']}")

    def _bump_edge(key_a: str, key_b: str) -> None:
        if key_a == key_b:
            # Eigene Quelle einer Autorin/eines Autors enthält deren/dessen
            # eigenen Namen als Schlagwort (Selbstbezug) - kein Self-Loop.
            return
        if graph.has_edge(key_a, key_b):
            graph[key_a][key_b]["weight"] += 1
        else:
            graph.add_edge(key_a, key_b, weight=1)

    for entry in active_sources.values():
        terms = sorted(set(entry.get(key_terms_field) or []) & kept_terms)
        for term_a, term_b in itertools.combinations(terms, 2):
            _bump_edge(_node_key(term_a), _node_key(term_b))

    for author in author_entries:
        author_key = f"author:{author['name']}"
        for source_id in author["source_ids"]:
            source = active_sources.get(source_id)
            if not source:
                continue
            for term in set(source.get(key_terms_field) or []) & kept_terms:
                _bump_edge(author_key, _node_key(term))

    communities = nx.community.louvain_communities(graph, weight="weight", seed=0)
    cluster_of = {node_id: idx for idx, community in enumerate(communities) for node_id in community}

    nodes = [
        GraphNode(id=f"term:{term}", type="term", label=term, weight=term_counts[term], cluster=cluster_of[f"term:{term}"])
        for term in plain_terms
    ]
    for author in author_entries:
        key = f"author:{author['name']}"
        profile = author_profiles.get_profile(author["name"])
        # Nutzerwunsch (2026-08-23): im Graphen die kleine, lokal gecachte
        # Auflösung nutzen (Speicherverbrauch/Kompression, siehe app/
        # author_photos.py) - existiert noch kein Cache (frisch gesetzt,
        # Caching im Hintergrund noch nicht durch), übergangsweise die rohe
        # photo_url, damit nicht bis zum nächsten Tages-Lauf gar kein Foto
        # erscheint.
        photo_url = (
            f"/api/authors/{quote(author['name'])}/photo/small"
            if author_photos.has_cached_photo(author["name"], "small")
            else (profile.get("photo_url") or None)
        )
        nodes.append(
            GraphNode(
                id=key,
                type="author",
                label=author["name"],
                photo_url=photo_url,
                weight=sum(1 for sid in author["source_ids"] if sid in active_sources),
                cluster=cluster_of[key],
            )
        )

    edges = [GraphEdge(source=a, target=b, weight=data["weight"]) for a, b, data in graph.edges(data=True)]
    return KnowledgeGraphOut(nodes=nodes, edges=edges)


@router.get("/api/knowledge-graph", response_model=KnowledgeGraphOut)
def get_knowledge_graph(x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    return _build_knowledge_graph(lang)


def _collect_author_bio_texts(matching: dict, lang: str) -> list[str]:
    sources = main._load_sources()
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


@router.put("/api/authors/{name}", response_model=AuthorOut)
def update_author_profile(
    name: str,
    profile: AuthorProfileIn,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
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
    before = author_profiles.get_profile(name)
    updated_profile = author_profiles.set_profile(
        name,
        photo_url=profile.photo_url,
        website=profile.website,
        social_links=[link.model_dump() for link in profile.social_links]
        if profile.social_links is not None
        else None,
        **bio_kwargs,
    )
    # Nutzerwunsch (2026-08-23): neue/geänderte photo_url einmalig lokal
    # cachen (siehe app/author_photos.py) - im Hintergrund-Thread, damit ein
    # langsamer/unerreichbarer externer Server dieses Speichern nicht
    # blockiert. Nur bei TATSÄCHLICHER Änderung anstoßen, sonst würde jede
    # unabhängige Vita-Bearbeitung erneut denselben Download auslösen.
    if updated_profile["photo_url"] and updated_profile["photo_url"] != before.get("photo_url"):
        threading.Thread(
            target=author_photos.cache_photo,
            args=(matching["name"], updated_profile["photo_url"]),
            daemon=True,
        ).start()
    matching.update(_resolve_profile_for_lang(matching["name"], author_profiles.get_profile(name), lang))
    new_values = {
        field: updated_profile[field]
        for field in (f"bio_{lang}", "photo_url", "website", "social_links")
    }
    changes = _diff_fields(before, new_values)
    if changes:
        audit.log_change(_user, "author_profile_updated", "author", matching["name"], matching["name"], changes)
    return matching


@router.post("/api/authors/{name}/rename", response_model=AuthorOut)
def rename_author_endpoint(
    name: str,
    payload: RenameAuthorIn,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    matching = _find_author(name)
    if matching is None:
        raise HTTPException(404, i18n.get_message("author_not_found", x_lang))

    new_name = payload.new_name.strip()
    if not new_name:
        raise HTTPException(400, i18n.get_message("invalid_author_name", x_lang))

    old_name = matching["name"]
    updated = _rename_author_entity(old_name, new_name)
    if updated is None:
        raise HTTPException(404, i18n.get_message("author_not_found", x_lang))
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    updated.update(_resolve_profile_for_lang(new_name, author_profiles.get_profile(new_name), lang))
    audit.log_change(
        _user,
        "author_renamed",
        "author",
        new_name,
        f"{old_name} → {new_name}",
        {"name": {"old": old_name, "new": new_name}},
    )
    return updated


@router.post("/api/authors/{name}/generate-bio", response_model=BioOut)
def generate_author_bio_endpoint(
    name: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    matching = _find_author(name)
    if matching is None:
        raise HTTPException(404, i18n.get_message("author_not_found", x_lang))

    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    texts = _collect_author_bio_texts(matching, lang)
    old_bio = author_profiles.get_profile(matching["name"]).get(f"bio_{lang}", "")
    bio = summarization.generate_author_bio(matching["name"], texts, lang)
    author_profiles.set_profile(name, **{f"bio_{lang}": bio, f"bio_ai_generated_{lang}": True})
    changes = _diff_fields({f"bio_{lang}": old_bio}, {f"bio_{lang}": bio})
    if changes:
        audit.log_change(_user, "author_bio_generated", "author", matching["name"], matching["name"], changes)
    return BioOut(bio=bio)


@router.post("/api/authors/generate-bio-preview", response_model=BioOut)
def generate_author_bio_preview_endpoint(
    payload: AuthorBioPreviewIn,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
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


@router.post("/api/sources/generate-key-terms-preview", response_model=KeyTermsOut)
def generate_key_terms_preview_endpoint(
    payload: KeyTermsPreviewIn,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    # Backlog: Begriffsliste soll auch dann mit einer von Hand überarbeiteten
    # Zusammenfassung synchron gehalten werden können, ohne deren Wortlaut
    # anzutasten - leitet Schlagworte NUR aus dem gerade im Formular
    # stehenden Zusammenfassungstext ab (payload.text), rührt weder die
    # Zusammenfassung noch die gespeicherte Quelle an. Schreibt bewusst
    # NICHTS - Persistierung passiert wie gewohnt erst über den bestehenden
    # PUT-/api/sources/{id}-Weg. Analog zu /api/authors/generate-bio-preview.
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    key_terms = summarization.extract_key_terms(payload.text, lang, terms.list_established_terms(lang))
    return KeyTermsOut(key_terms=key_terms)
