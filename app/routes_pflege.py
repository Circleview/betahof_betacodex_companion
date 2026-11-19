# Idee 313ad93d: aus app/main.py ausgelagert (Verhalten unverändert).

import threading
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Header, Request, UploadFile
from fastapi.responses import FileResponse
from app import (
    audit,
    extraction,
    i18n,
    monitoring,
    source_images,
    source_suggestions,
    summarization,
    terms,
    users,
    vectorstore,
    web_allowlist,
    web_candidates,
    web_crawler,
    web_index,
)
from app.models import (
    BrokenLinksCountOut,
    ExtractedSource,
    ExtractedUpload,
    ImportJobOut,
    LanguageDetectionOut,
    MessageOut,
    SourceOut,
    SourceSuggestionOut,
    SummaryOut,
    UrlCheckOut,
    UrlIn,
    WebAllowlistEntryIn,
    WebAllowlistEntryOut,
    WebCandidateOut,
    WebIndexPageOut,
)

from app import main
from app.background import _audio_transcription_queue, _index_new_web_allowlist_entry
from app.source_processing import (
    _AUDIO_MEDIA_TYPES,
    _apply_language_result,
    _audio_extension,
    _detect_language_safely,
    _diff_fields,
    _existing_audio_file,
    _existing_pdf_file,
    _guess_title_from_filename,
    _known_lang,
    _save_sources,
    _source_is_missing,
    _sources_write_lock,
    _to_source_out,
)

router = APIRouter()


@router.get("/api/sources/{source_id}/check-url", response_model=UrlCheckOut)
def check_source_url(
    source_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = main._load_sources()
    if _source_is_missing(sources, source_id):
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    url = sources[source_id].get("url")
    if not url:
        return UrlCheckOut(has_url=False)

    result = monitoring.check_url(url)
    return UrlCheckOut(has_url=True, **result)


@router.post("/api/sources/{source_id}/verify-link", response_model=MessageOut)
def verify_source_link(
    source_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    # Nutzerwunsch (2026-09-01): der automatische wöchentliche Link-Check
    # (siehe _run_url_health_check_once) meldet gelegentlich einen Link als
    # nicht erreichbar, obwohl er tatsächlich funktioniert (z.B. blockiert
    # eine Website automatisierte Anfragen von Server-IPs, funktioniert aber
    # im echten Browser). Statt den Warnhinweis bis zum nächsten Lauf (bis
    # zu einer Woche) stehen zu lassen, können Quellen-Pfleger:innen den
    # Link nach eigener manueller Prüfung als in Ordnung markieren - setzt
    # url_reachable zurück auf True, bis der nächste automatische Lauf ihn
    # erneut bewertet (überschreibt diese Markierung dann ggf. wieder,
    # falls der Link tatsächlich weiterhin nicht erreichbar ist). Wie jede
    # andere Feld-Änderung im Änderungs-Log protokolliert und damit
    # rückgängig machbar (siehe audit.log_change/POST .../revert).
    with _sources_write_lock:
        sources = main._load_sources()
        if _source_is_missing(sources, source_id):
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))
        entry = sources[source_id]
        if entry.get("url_reachable") is not False:
            raise HTTPException(400, i18n.get_message("link_not_broken", x_lang))
        before = dict(entry)
        entry["url_reachable"] = True
        entry["url_reason_code"] = None
        entry["url_status_code"] = None
        entry["url_checked_at"] = datetime.now(timezone.utc).isoformat()
        title = entry.get("title", source_id)
        _save_sources(sources)

    changes = _diff_fields(
        before,
        {
            "url_reachable": True,
            "url_reason_code": None,
            "url_status_code": None,
            "url_checked_at": entry["url_checked_at"],
        },
    )
    if changes:
        audit.log_change(_user, "source_link_manually_verified", "source", source_id, title, changes)
    return MessageOut(detail=i18n.get_message("link_verified", x_lang))


@router.get("/api/sources/broken-links-count", response_model=BrokenLinksCountOut)
def get_broken_links_count(_user: str = Depends(main.require_role(users.QUELLEN_PFLEGER))):
    # Backlog (2026-08-02): leichtgewichtiger Endpoint fürs Warn-Badge am
    # "Quellen"-Menüpunkt (static/header.js) - auf JEDER Seite aufrufbar,
    # ohne (wie GET /api/sources) den kompletten Quellenbestand inkl.
    # Volltext übertragen zu müssen. Liest den von
    # _run_url_health_check_once() zuletzt gespeicherten Stand, prüft
    # nicht live nach.
    sources = main._load_sources()
    count = sum(
        1
        for entry in sources.values()
        if entry.get("url_reachable") is False and not entry.get("deleted_at")
    )
    return BrokenLinksCountOut(count=count)


# Nutzerwunsch (2026-09-25): Bearbeiten- und Lese-Dialog in der Konversation
# (static/question.js) brauchen EINE Quelle - ohne dafür wie GET /api/sources
# den ganzen Bestand zu laden. Öffentlich wie GET /api/sources: geschützte
# Volltexte (restricted) sehen nur Quellen-Pfleger:innen. Steht bewusst NACH
# broken-links-count, sonst würde {source_id} diese Route verdecken.
@router.get("/api/sources/{source_id}", response_model=SourceOut)
def get_source(
    source_id: str,
    request: Request,
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    entry = main._load_sources().get(source_id)
    if not entry or entry.get("deleted_at"):
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))
    email = main._session_user_email(request)
    can_view_full_text = users.has_role(email, users.QUELLEN_PFLEGER)
    # Idee 669405f0: Gäste bekommen nie Volltext (Crawler-Schutz).
    return _to_source_out(entry, can_view_full_text, lang=x_lang, include_text=email is not None)


# Backlog: LLM/Internet-Fallback bei dünner Quellenlage - eine freigegebene
# Domain/Sektion gilt nach einem Jahr ohne erneute menschliche Bestätigung
# als prüfungsfällig (Redaktionslinie einer Website kann sich ändern, ohne
# dass die URL selbst bricht - der bestehende url_reachable-Check bei den
# normalen Quellen würde das nicht erkennen).
WEB_ALLOWLIST_REVIEW_INTERVAL_DAYS = 365


def _web_allowlist_entry_needs_review(reviewed_at: str | None, now: datetime) -> bool:
    if not reviewed_at:
        return True
    try:
        reviewed = datetime.fromisoformat(reviewed_at)
    except ValueError:
        return True
    if reviewed.tzinfo is None:
        reviewed = reviewed.replace(tzinfo=timezone.utc)
    return (now - reviewed).days >= WEB_ALLOWLIST_REVIEW_INTERVAL_DAYS


@router.get("/api/web-allowlist", response_model=list[WebAllowlistEntryOut])
def list_web_allowlist_entries(_user: str = Depends(main.require_role(users.QUELLEN_PFLEGER))):
    now = datetime.now(timezone.utc)
    return [
        WebAllowlistEntryOut(
            id=entry_id,
            page_count=web_index.active_page_count_for_entry(entry_id),
            needs_review=_web_allowlist_entry_needs_review(entry.get("reviewed_at"), now),
            **entry,
        )
        for entry_id, entry in web_allowlist.list_entries().items()
    ]


@router.post("/api/web-allowlist", response_model=WebAllowlistEntryOut, status_code=201)
def add_web_allowlist_entry(
    payload: WebAllowlistEntryIn,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    url_prefix = payload.url_prefix.strip()
    if not url_prefix.startswith(("http://", "https://")):
        raise HTTPException(400, i18n.get_message("web_allowlist_invalid_url", x_lang))
    reason = payload.reason.strip()
    if not reason:
        raise HTTPException(400, i18n.get_message("web_allowlist_reason_required", x_lang))
    entry = web_allowlist.add_entry(
        url_prefix=url_prefix,
        label=payload.label.strip() or url_prefix,
        reason=reason,
        added_by=_user,
        added_at=datetime.now(timezone.utc).isoformat(),
        max_pages=payload.max_pages,
    )
    threading.Thread(
        target=_index_new_web_allowlist_entry,
        args=(entry["id"], url_prefix, payload.max_pages),
        daemon=True,
    ).start()
    return WebAllowlistEntryOut(page_count=0, needs_review=False, **entry)


@router.post("/api/web-allowlist/{entry_id}/mark-reviewed", response_model=WebAllowlistEntryOut)
def mark_web_allowlist_entry_reviewed(
    entry_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    entry = web_allowlist.mark_reviewed(entry_id, datetime.now(timezone.utc).isoformat())
    if entry is None:
        raise HTTPException(404, i18n.get_message("web_allowlist_entry_not_found", x_lang))
    return WebAllowlistEntryOut(
        page_count=web_index.active_page_count_for_entry(entry_id), needs_review=False, **entry
    )


@router.delete("/api/web-allowlist/{entry_id}", status_code=204)
def delete_web_allowlist_entry(
    entry_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    if not web_allowlist.delete_entry(entry_id):
        raise HTTPException(404, i18n.get_message("web_allowlist_entry_not_found", x_lang))
    # Gecrawlte Unterseiten UND ihre Chunks in der separaten Chroma-Collection
    # gehören zu genau diesem Eintrag - ohne diese Aufräumung blieben nach
    # dem Entfernen einer Freigabe verwaiste Web-Fallback-Treffer bestehen.
    for page_id in web_index.delete_pages_for_entry(entry_id):
        vectorstore.delete_web_page_chunks(page_id)
    web_candidates.delete_candidates_for_entry(entry_id)


# Nutzerwunsch: einzelne indizierte Seiten (z.B. werbliche Inhalte innerhalb
# einer sonst passenden Website) sollen gezielt vom Fallback ausgeschlossen
# werden können, ohne die ganze Freigabe zu löschen - Ausklapp-Liste je
# Eintrag in import.js. Ausschluss/Wiederaufnahme löscht/erzeugt KEINE
# Chunks neu (siehe vectorstore.query_web), sondern setzt nur ein Flag -
# beides ist damit sofort wirksam.
@router.get("/api/web-allowlist/{entry_id}/pages", response_model=list[WebIndexPageOut])
def list_web_allowlist_pages(
    entry_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    if web_allowlist.get_entry(entry_id) is None:
        raise HTTPException(404, i18n.get_message("web_allowlist_entry_not_found", x_lang))
    return [
        WebIndexPageOut(id=page_id, **page)
        for page_id, page in web_index.pages_for_entry(entry_id).items()
    ]


@router.post("/api/web-allowlist/{entry_id}/pages/{page_id}/exclude", response_model=WebIndexPageOut)
def exclude_web_allowlist_page(
    entry_id: str,
    page_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    page = web_index.get_page(page_id)
    if page is None or page.get("allowlist_entry_id") != entry_id:
        raise HTTPException(404, i18n.get_message("web_allowlist_page_not_found", x_lang))
    updated = web_index.set_excluded(page_id, True)
    audit.log_action(
        _user, "web_page_excluded", "web_page", page_id, page.get("title") or page.get("url")
    )
    return WebIndexPageOut(**updated)


@router.post("/api/web-allowlist/{entry_id}/pages/{page_id}/include", response_model=WebIndexPageOut)
def include_web_allowlist_page(
    entry_id: str,
    page_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    page = web_index.get_page(page_id)
    if page is None or page.get("allowlist_entry_id") != entry_id:
        raise HTTPException(404, i18n.get_message("web_allowlist_page_not_found", x_lang))
    updated = web_index.set_excluded(page_id, False)
    audit.log_action(
        _user, "web_page_included", "web_page", page_id, page.get("title") or page.get("url")
    )
    return WebIndexPageOut(**updated)


# Nutzerwunsch (Positivselektion): findet index_entry() zu wenige eindeutig
# zuordenbare Seiten (siehe app/web_crawler.py:POSITIVE_SELECTION_MAX_
# DISCOVERED), werden stattdessen gegen den bestehenden Quellenbestand
# bewertete Kandidaten abgelegt (WebAllowlistEntryOut.selection_mode ==
# "positiv") - Quellen-Pfleger:innen wählen hier gezielt einzelne Seiten
# zur Aufnahme aus, statt wie sonst üblich bereits indizierte Seiten zu
# bereinigen. Absteigend nach Relevanz sortiert, damit die vielversprechend-
# sten Vorschläge zuerst erscheinen (Frontend paginiert clientseitig in
# 10er-Schritten aus dieser vollständigen Liste).
@router.get("/api/web-allowlist/{entry_id}/candidates", response_model=list[WebCandidateOut])
def list_web_allowlist_candidates(
    entry_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    if web_allowlist.get_entry(entry_id) is None:
        raise HTTPException(404, i18n.get_message("web_allowlist_entry_not_found", x_lang))
    candidates = [
        WebCandidateOut(id=candidate_id, **candidate)
        for candidate_id, candidate in web_candidates.candidates_for_entry(entry_id).items()
    ]
    candidates.sort(key=lambda c: c.relevance_score, reverse=True)
    return candidates


@router.post(
    "/api/web-allowlist/{entry_id}/candidates/{candidate_id}/approve", response_model=WebIndexPageOut
)
def approve_web_allowlist_candidate(
    entry_id: str,
    candidate_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    candidate = web_candidates.get_candidate(candidate_id)
    if candidate is None or candidate.get("allowlist_entry_id") != entry_id:
        raise HTTPException(404, i18n.get_message("web_allowlist_candidate_not_found", x_lang))
    if not web_crawler.index_approved_candidate(entry_id, candidate["url"]):
        raise HTTPException(502, i18n.get_message("web_allowlist_candidate_index_failed", x_lang))
    web_candidates.delete_candidate(candidate_id)
    audit.log_action(_user, "web_candidate_approved", "web_page", candidate_id, candidate.get("title"))
    page_id, page = next(
        (pid, p)
        for pid, p in web_index.pages_for_entry(entry_id).items()
        if p["url"] == candidate["url"]
    )
    return WebIndexPageOut(id=page_id, **page)


@router.post(
    "/api/web-allowlist/{entry_id}/candidates/{candidate_id}/reject", response_model=WebCandidateOut
)
def reject_web_allowlist_candidate(
    entry_id: str,
    candidate_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    candidate = web_candidates.get_candidate(candidate_id)
    if candidate is None or candidate.get("allowlist_entry_id") != entry_id:
        raise HTTPException(404, i18n.get_message("web_allowlist_candidate_not_found", x_lang))
    updated = web_candidates.set_status(candidate_id, "rejected")
    audit.log_action(_user, "web_candidate_rejected", "web_page", candidate_id, candidate.get("title"))
    return WebCandidateOut(**updated)


@router.get("/api/source-suggestions", response_model=list[SourceSuggestionOut])
def list_source_suggestions(_user: str = Depends(main.require_role(users.QUELLEN_PFLEGER))):
    suggestions = [
        SourceSuggestionOut(id=sid, **s)
        for sid, s in source_suggestions.list_suggestions(status="pending").items()
    ]
    suggestions.sort(key=lambda s: s.discovered_at)
    return suggestions


@router.post("/api/source-suggestions/{suggestion_id}/accept", response_model=SourceSuggestionOut)
def accept_source_suggestion(
    suggestion_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    # Legt bewusst KEINE Quelle an - das Frontend öffnet stattdessen das
    # bestehende "Quelle per URL"-Formular mit der hier zurückgegebenen URL
    # vorausgefüllt (siehe static/import.js), Extraktion/Review/Speichern
    # laufen 1:1 über den bereits existierenden manuellen Import-Pfad.
    suggestion = source_suggestions.get_suggestion(suggestion_id)
    if suggestion is None:
        raise HTTPException(404, i18n.get_message("source_suggestion_not_found", x_lang))
    updated = source_suggestions.set_status(suggestion_id, "accepted")
    source_suggestions.adjust_weight(
        author_hint=suggestion.get("author_hint"), url=suggestion["url"], delta=1
    )
    audit.log_change(
        _user,
        "source_suggestion_accepted",
        "source_suggestion",
        suggestion_id,
        suggestion.get("title"),
        {"status": {"old": "pending", "new": "accepted"}},
    )
    return SourceSuggestionOut(**updated)


@router.post("/api/source-suggestions/{suggestion_id}/reject", response_model=SourceSuggestionOut)
def reject_source_suggestion(
    suggestion_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    suggestion = source_suggestions.get_suggestion(suggestion_id)
    if suggestion is None:
        raise HTTPException(404, i18n.get_message("source_suggestion_not_found", x_lang))
    updated = source_suggestions.set_status(suggestion_id, "rejected")
    source_suggestions.adjust_weight(
        author_hint=suggestion.get("author_hint"), url=suggestion["url"], delta=-1
    )
    audit.log_change(
        _user,
        "source_suggestion_rejected",
        "source_suggestion",
        suggestion_id,
        suggestion.get("title"),
        {"status": {"old": "pending", "new": "rejected"}},
    )
    return SourceSuggestionOut(**updated)


@router.get("/api/sources/{source_id}/pdf")
def get_source_pdf(
    source_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = main._load_sources()
    if _source_is_missing(sources, source_id):
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    pdf_path = main.PDF_DIR / f"{source_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    return FileResponse(pdf_path, media_type="application/pdf")


@router.get("/api/sources/{source_id}/audio")
def get_source_audio(
    source_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = main._load_sources()
    if _source_is_missing(sources, source_id):
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    audio_path = _existing_audio_file(source_id)
    if not audio_path:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    media_type = _AUDIO_MEDIA_TYPES.get(audio_path.suffix.lower(), "application/octet-stream")
    return FileResponse(audio_path, media_type=media_type)


@router.get("/api/import-jobs", response_model=list[ImportJobOut])
def list_import_jobs(_user: str = Depends(main.require_role(users.QUELLEN_PFLEGER))):
    # Fix (2026-08-23, per Nutzerfeedback): delete_source() setzt beim
    # weichen Löschen bewusst NUR deleted_at, lässt processing_status einer
    # zuvor fehlgeschlagenen Quelle aber unangetastet stehen (kein Grund,
    # das beim Löschen extra zu bereinigen) - ohne diesen Filter blieb eine
    # gelöschte, fehlgeschlagene Quelle trotzdem für immer in der
    # Fehler-Warteschlange/dem Jobs-Badge sichtbar.
    sources = main._load_sources()
    return [
        ImportJobOut(
            id=source_id,
            title=entry.get("title", ""),
            processing_status=entry["processing_status"],
            processing_step=entry.get("processing_step"),
            processing_error=entry.get("processing_error"),
        )
        for source_id, entry in sources.items()
        if entry.get("processing_status") and not entry.get("deleted_at")
    ]


@router.post("/api/sources/{source_id}/reprocess", response_model=MessageOut)
def reprocess_source(
    source_id: str,
    background_tasks: BackgroundTasks,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    with _sources_write_lock:
        sources = main._load_sources()
        if _source_is_missing(sources, source_id):
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

        is_audio = bool(_existing_audio_file(source_id))
        if not is_audio and not _existing_pdf_file(source_id):
            raise HTTPException(400, i18n.get_message("no_processing_file", x_lang))

        sources[source_id]["processing_status"] = "pending"
        sources[source_id]["processing_step"] = None
        sources[source_id]["processing_error"] = None
        title = sources[source_id].get("title", source_id)
        _save_sources(sources)
    audit.log_action(_user, "source_reprocessed", "source", source_id, title)
    if is_audio:
        # Backlog #113: siehe add_source - auch ein erneuter Versuch reiht
        # sich hinten in der Warteschlange ein, statt sofort parallel zu
        # anderen laufenden Transkriptionen zu starten.
        _audio_transcription_queue.put((source_id, x_lang))
    else:
        background_tasks.add_task(main._process_pdf_ocr, source_id, x_lang)
    return MessageOut(detail=i18n.get_message("reprocess_started", x_lang))


@router.post("/api/sources/{source_id}/detect-language", response_model=LanguageDetectionOut)
def detect_source_language_endpoint(
    source_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    # Wie generate-summary: speichert das Ergebnis als KI-Stand (Flag True);
    # von Hand gepflegte Felder (Flag False) bleiben unberührt.
    sources = main._load_sources()
    if _source_is_missing(sources, source_id):
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))
    entry = sources[source_id]
    title, text = entry.get("title", ""), entry.get("text", "")
    result = _detect_language_safely(title, text, _known_lang(entry))
    with _sources_write_lock:
        sources = main._load_sources()
        if _source_is_missing(sources, source_id):
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))
        before = dict(sources[source_id])
        _apply_language_result(sources[source_id], result)
        after = sources[source_id]
        _save_sources(sources)
        out = {"text_lang": after.get("text_lang") or None, "title_en": after.get("title_en") or None}
    changes = _diff_fields(before, {f: out[f] for f in out if out[f] != (before.get(f) or None)})
    if changes:
        audit.log_change(_user, "source_language_detected", "source", source_id, before.get("title", source_id), changes)
    return LanguageDetectionOut(**out)


@router.post("/api/sources/{source_id}/generate-summary", response_model=SummaryOut)
def generate_source_summary(
    source_id: str,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = main._load_sources()
    if _source_is_missing(sources, source_id):
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))
    text = sources[source_id].get("text", "")
    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG

    # Nutzerwunsch (2026-08-23): eine von Hand überarbeitete Zusammenfassung
    # (summary_ai_generated_{lang} explizit False, siehe update_source) gilt
    # als kuratiert und darf ein erneuter KI-Lauf nie kommentarlos
    # überschreiben. Sind BEIDE Sprachen geschützt, lohnt sich nicht einmal
    # der (kostenpflichtige) API-Aufruf.
    if sources[source_id].get("summary_ai_generated_de") is False and sources[source_id].get(
        "summary_ai_generated_en"
    ) is False:
        return SummaryOut(
            summary=sources[source_id].get(f"summary_{lang}", ""),
            key_terms=sources[source_id].get(f"key_terms_{lang}", []),
        )

    # generate_bilingual_summary ist der langsame KI-Aufruf - die Momentaufnahme
    # von oben deshalb NICHT für den späteren Schreibvorgang wiederverwenden
    # (siehe _sources_write_lock-Kommentar), sondern direkt davor neu einlesen.
    result = summarization.generate_bilingual_summary(
        text, terms.list_established_terms("de"), terms.list_established_terms("en")
    )
    with _sources_write_lock:
        sources = main._load_sources()
        if _source_is_missing(sources, source_id):
            raise HTTPException(404, i18n.get_message("source_not_found", x_lang))
        before = dict(sources[source_id])
        if sources[source_id].get("summary_ai_generated_de") is not False:
            sources[source_id]["summary_de"] = result["de"]["summary"]
            sources[source_id]["key_terms_de"] = result["de"]["key_terms"]
            sources[source_id]["summary_ai_generated_de"] = True
            sources[source_id]["key_terms_ai_generated_de"] = True
        if sources[source_id].get("summary_ai_generated_en") is not False:
            sources[source_id]["summary_en"] = result["en"]["summary"]
            sources[source_id]["key_terms_en"] = result["en"]["key_terms"]
            sources[source_id]["summary_ai_generated_en"] = True
            sources[source_id]["key_terms_ai_generated_en"] = True
        title = sources[source_id].get("title", source_id)
        _save_sources(sources)
        main._register_all_terms(source_id, sources[source_id])
        after = dict(sources[source_id])

    changes = _diff_fields(
        before,
        {
            "summary_de": after["summary_de"],
            "summary_en": after["summary_en"],
            "key_terms_de": after["key_terms_de"],
            "key_terms_en": after["key_terms_en"],
        },
    )
    if changes:
        audit.log_change(_user, "source_summary_generated", "source", source_id, title, changes)
    return SummaryOut(summary=after[f"summary_{lang}"], key_terms=after[f"key_terms_{lang}"])


@router.post("/api/extract-pdf-upload", response_model=ExtractedUpload)
def extract_pdf_upload(
    file: UploadFile = File(...),
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
):
    data = file.file.read()
    result = extraction.extract_pdf(data)

    upload_id = str(uuid.uuid4())
    main.PDF_UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    (main.PDF_UPLOAD_STAGING_DIR / f"{upload_id}.pdf").write_bytes(data)

    return ExtractedUpload(**result, upload_id=upload_id)


@router.post("/api/extract-epub-upload", response_model=ExtractedUpload)
def extract_epub_upload(
    file: UploadFile = File(...),
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
):
    # Kein Staging: anders als PDF wird die EPUB-Datei nicht aufbewahrt
    # (upload_id bleibt None) - nur der extrahierte Text wird übernommen.
    return ExtractedUpload(**extraction.extract_epub(file.file.read()), upload_id=None)


@router.post("/api/extract-audio-upload", response_model=ExtractedUpload)
def extract_audio_upload(
    file: UploadFile = File(...),
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
):
    # Transkribiert bewusst NICHT hier - kann mehrere Minuten dauern und
    # läuft stattdessen als Hintergrund-Job nach dem Anlegen der Quelle
    # (siehe _process_audio_transcription), damit die Vorschau schnell bleibt.
    data = file.file.read()
    extension = _audio_extension(file.filename or "")

    upload_id = str(uuid.uuid4())
    main.AUDIO_UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staged_path = main.AUDIO_UPLOAD_STAGING_DIR / f"{upload_id}{extension}"
    staged_path.write_bytes(data)

    title = _guess_title_from_filename(file.filename or "")

    return ExtractedUpload(title=title, authors=[], date="", text="", extracted=False, upload_id=upload_id)


@router.post("/api/extract-url", response_model=ExtractedSource)
def extract_url(payload: UrlIn, _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER))):
    result = extraction.extract_from_url(payload.url)
    images = result.pop("images", None)
    is_audio = extraction.looks_like_audio(payload.url)
    is_pdf = extraction.looks_like_pdf(payload.url)
    # Idee ff895248: Web-Bilder der Vorschau liegen serverseitig im Staging;
    # der Client bekommt nur den Token und schickt ihn beim Anlegen zurück.
    token = (
        source_images.stage_web_images(main.IMAGE_STAGING_DIR, extraction.strip_tracking_params(payload.url), images or [])
        if result.get("extracted") and not (is_audio or is_pdf)
        else None
    )
    return ExtractedSource(**result, is_audio=is_audio, is_pdf=is_pdf, image_token=token)
