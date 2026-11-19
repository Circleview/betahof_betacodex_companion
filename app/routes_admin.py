# Idee 313ad93d: aus app/main.py ausgelagert (Verhalten unverändert).

import json
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Header, Request
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from app import (
    audit,
    auth,
    author_profiles,
    authors,
    i18n,
    llm,
    mail,
    mcp_server,
    question_log,
    ratelimit,
    source_suggestions,
    summarization,
    terms,
    users,
    vectorstore,
)
from app.models import (
    AdminUserOut,
    AnswerFeedbackIn,
    AuditLogEntryOut,
    InviteIn,
    MessageOut,
    QuestionLogEntryOut,
    RequestLinkIn,
    TermMergeIn,
    TermMergeOut,
    TermMergeSuggestionsIn,
    TermOut,
    TermsDeleteIn,
    UpdateUserNameIn,
    UpdateUserRolesIn,
    WhoAmIOut,
)

from app import main
from app.retrieval import _should_log_question_event, _truncate_for_log, _valid_conversation_id
from app.source_processing import (
    _clear_ai_language_fields,
    _detect_and_store_language,
    _find_author,
    _prepare_chunks,
    _rename_author_entity,
    _save_sources,
    _source_in_from_entry,
    _sources_write_lock,
    _store_chunks,
    _vectorstore_write_lock,
)

router = APIRouter()


@router.get("/api/terms", response_model=list[TermOut])
def list_terms():
    return terms.list_terms()


def _term_merge_suggestions_stream(lang: str, term_list: list[str]):
    for i in range(0, len(term_list), main._TERM_MERGE_BATCH_SIZE):
        batch = term_list[i : i + main._TERM_MERGE_BATCH_SIZE]
        for group in summarization.find_similar_term_groups(batch, lang):
            yield json.dumps(
                {"type": "group", "lang": lang, "canonical": group["canonical"], "variants": group["variants"]}
            ) + "\n"
    yield json.dumps({"type": "done"}) + "\n"


# Bewusst zweigeteilt (Vorschlag vs. Anwenden, siehe /api/terms/merge unten)
# statt automatischem Sofort-Merge - ein fälschlich erkanntes "Synonym"
# würde sonst unbemerkt zwei unterschiedliche Konzepte vermischen, eine
# Quellen-Pfleger:in bestätigt deshalb jede Gruppe einzeln, bevor irgendetwas
# an den Quellen geändert wird.
@router.post("/api/terms/merge-suggestions")
def get_term_merge_suggestions(
    payload: TermMergeSuggestionsIn,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
):
    lang = payload.lang if payload.lang in ("de", "en") else "de"
    term_strings = [entry["term"] for entry in terms.list_terms() if lang in entry["langs"]]
    return StreamingResponse(
        _term_merge_suggestions_stream(lang, term_strings), media_type="application/x-ndjson"
    )


@router.post("/api/terms/merge", response_model=TermMergeOut)
def merge_terms(
    payload: TermMergeIn,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    lang = payload.lang if payload.lang in ("de", "en") else "de"
    field = f"key_terms_{lang}"
    canonical = payload.canonical.strip()
    variant_set = {v.strip() for v in payload.variants if v and v.strip()} - {canonical}
    if not canonical or not variant_set:
        raise HTTPException(400, i18n.get_message("term_merge_invalid", x_lang))

    with _sources_write_lock:
        sources = main._load_sources()
        # Nutzerwunsch (2026-09-22): dieselbe Feld-Diff-Protokollierung wie
        # bei jeder anderen Quellen-Änderung (siehe update_source/
        # generate_source_summary) - jede betroffene Quelle bekommt einen
        # eigenen Änderungs-Log-Eintrag, dadurch ist ein fälschlich
        # zusammengeführtes Begriffspaar über den bestehenden
        # POST /api/audit-log/{id}/revert-Weg gezielt pro Quelle rückgängig
        # zu machen - keine eigene Undo-Logik nötig.
        touched = []
        for source_id, entry in sources.items():
            current = entry.get(field) or []
            if not any(t in variant_set for t in current):
                continue
            merged: list[str] = []
            for term in current:
                replacement = canonical if term in variant_set else term
                if replacement not in merged:
                    merged.append(replacement)
            touched.append((source_id, entry.get("title", source_id), list(current), merged))
            entry[field] = merged
        if touched:
            _save_sources(sources)

    for source_id, title, before_terms, after_terms in touched:
        main._register_all_terms(source_id, sources[source_id])
        audit.log_change(_user, "terms_merged", "source", source_id, title, {field: {"old": before_terms, "new": after_terms}})

    return TermMergeOut(affected_sources=len(touched))


@router.post("/api/terms/delete", response_model=TermMergeOut)
def delete_terms(
    payload: TermsDeleteIn,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    # Nutzerwunsch (2026-09-22): eine als Rauschen erkannte Gruppe (z.B.
    # OCR-Artefakte) soll sich statt eines Zusammenführens auch komplett
    # entfernen lassen - entfernt jeden gegebenen Begriff ersatzlos aus
    # key_terms_{lang} jeder betroffenen Quelle. Gleiches Protokoll-/Revert-
    # Prinzip wie merge_terms oben.
    lang = payload.lang if payload.lang in ("de", "en") else "de"
    field = f"key_terms_{lang}"
    to_delete = {t.strip() for t in payload.terms if t and t.strip()}
    if not to_delete:
        raise HTTPException(400, i18n.get_message("term_merge_invalid", x_lang))

    with _sources_write_lock:
        sources = main._load_sources()
        touched = []
        for source_id, entry in sources.items():
            current = entry.get(field) or []
            if not any(t in to_delete for t in current):
                continue
            remaining = [t for t in current if t not in to_delete]
            touched.append((source_id, entry.get("title", source_id), list(current), remaining))
            entry[field] = remaining
        if touched:
            _save_sources(sources)

    for source_id, title, before_terms, after_terms in touched:
        main._register_all_terms(source_id, sources[source_id])
        audit.log_change(_user, "terms_deleted", "source", source_id, title, {field: {"old": before_terms, "new": after_terms}})

    return TermMergeOut(affected_sources=len(touched))


@router.post("/api/auth/request-link", response_model=MessageOut)
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
        link_url = _login_link(request, token)
        mail.send_login_link_email(email, link_url, x_lang)
    return MessageOut(detail=i18n.get_message("magic_link_sent", x_lang))


@router.get("/api/auth/verify")
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
        secure=not main.IS_DEV_ENVIRONMENT,
        path="/",
    )
    return response


@router.post("/api/auth/logout", status_code=204)
def logout():
    response = Response(status_code=204)
    response.delete_cookie(auth.SESSION_COOKIE_NAME, path="/")
    return response


@router.get("/api/auth/whoami", response_model=WhoAmIOut)
def whoami(request: Request):
    email = main._get_current_user_email(request)
    user = users.get_user(email) if email else None
    return WhoAmIOut(email=email, roles=users.get_roles(email), name=user.get("name") if user else None)


@router.get("/api/auth/users", response_model=list[AdminUserOut])
def list_invited_users(_user: str = Depends(main.require_role(users.USER_ADMIN))):
    return users.list_users()


@router.post("/api/auth/invite", response_model=AdminUserOut, status_code=201)
def invite_user(
    payload: InviteIn,
    request: Request,
    current_user: str = Depends(main.require_role(users.USER_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    roles = payload.roles or ([payload.role] if payload.role else [])
    if not roles:
        raise HTTPException(400, i18n.get_message("invite_no_roles", x_lang))
    if any(role not in users.ALL_ROLES for role in roles):
        raise HTTPException(400, i18n.get_message("invite_invalid_role", x_lang))
    if set(roles) & set(users.ADMIN_ROLES) and not users.has_role(current_user, users.SYSTEM_ADMIN):
        raise HTTPException(403, i18n.get_message("invite_role_forbidden", x_lang))

    email = payload.email.strip().lower()
    for role in roles:
        entry = users.invite_user(email, role, invited_by=current_user, name=payload.name)
    _send_invite(request, email, roles, x_lang)
    return entry


def _login_link(request: Request, token: str) -> str:
    # Nie den Host-Header des Aufrufers in Mail-Links übernehmen (Link-Vergiftung):
    # nur lokale Dev-Hosts bleiben, sonst immer die öffentliche Adresse (2026-11-18).
    base = str(request.base_url) if request.url.hostname in ("localhost", "127.0.0.1") else mcp_server.PUBLIC_BASE_URL + "/"
    return base + f"api/auth/verify?token={token}"


def _send_invite(request: Request, email: str, roles: list[str], x_lang: str) -> None:
    token = auth.create_magic_link_token(email, auth.INVITE_LINK_MAX_AGE_SECONDS)
    link_url = _login_link(request, token)
    mail.send_invite_email(email, link_url, roles, x_lang)


# 2026-09-26: Nutzerverwaltung als eigene Seite (static/users.js) - Einladung
# erneut senden (nur noch nicht angemeldete Konten, gegen Spam begrenzt).
@router.post("/api/auth/users/{email}/resend-invite", response_model=AdminUserOut)
def resend_invite(
    email: str,
    request: Request,
    _user: str = Depends(main.require_role(users.USER_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    entry = users.get_user(email)
    if entry is None:
        raise HTTPException(404, i18n.get_message("user_not_found", x_lang))
    if entry["status"] != "invited":
        raise HTTPException(400, i18n.get_message("resend_only_invited", x_lang))
    if ratelimit.is_rate_limited(f"resend-invite:{entry['email']}", max_requests=5, window_seconds=3600):
        raise HTTPException(429, i18n.get_message("rate_limited", x_lang))
    _send_invite(request, entry["email"], entry["roles"], x_lang)
    return entry


# 2026-09-26: Konto entfernen - nicht das eigene, nicht den letzten System-
# Admin, Admin-Konten nur durch System-Admins (gleiche Regel wie Rollen).
# MCP-Schlüssel des Kontos werden damit ungültig (an die Rolle gebunden).
@router.delete("/api/auth/users/{email}", status_code=204)
def delete_user(
    email: str,
    current_user: str = Depends(main.require_role(users.USER_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    entry = users.get_user(email)
    if entry is None:
        raise HTTPException(404, i18n.get_message("user_not_found", x_lang))
    if entry["email"] == (current_user or "").strip().lower():
        raise HTTPException(400, i18n.get_message("user_delete_self", x_lang))
    if set(entry["roles"]) & set(users.ADMIN_ROLES) and not users.has_role(current_user, users.SYSTEM_ADMIN):
        raise HTTPException(403, i18n.get_message("user_delete_forbidden", x_lang))
    if users.SYSTEM_ADMIN in entry["roles"] and users.count_with_role(users.SYSTEM_ADMIN) <= 1:
        raise HTTPException(400, i18n.get_message("last_system_admin_delete", x_lang))
    users.delete_user(email)
    return Response(status_code=204)


# Nutzerwunsch (2026-09-24): Rollen eines bestehenden Kontos einzeln
# vergeben/entziehen (Häkchen in der Nutzerverwaltung, static/auth.js).
# Gleiche Rechteregel wie beim Einladen: Admin-Rollen ändern nur System-
# Admins. Der letzte System-Admin kann sich nicht aussperren.
@router.put("/api/auth/users/{email}/roles", response_model=AdminUserOut)
def set_user_roles(
    email: str,
    payload: UpdateUserRolesIn,
    current_user: str = Depends(main.require_role(users.USER_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    if any(r not in users.ALL_ROLES for r in payload.roles):
        raise HTTPException(400, i18n.get_message("invite_invalid_role", x_lang))
    existing = users.get_user(email)
    if existing is None:
        raise HTTPException(404, i18n.get_message("user_not_found", x_lang))
    changed = set(existing["roles"]) ^ set(payload.roles)
    if changed & set(users.ADMIN_ROLES) and not users.has_role(current_user, users.SYSTEM_ADMIN):
        raise HTTPException(403, i18n.get_message("invite_role_forbidden", x_lang))
    if (
        users.SYSTEM_ADMIN in existing["roles"]
        and users.SYSTEM_ADMIN not in payload.roles
        and users.count_with_role(users.SYSTEM_ADMIN) <= 1
    ):
        raise HTTPException(400, i18n.get_message("last_system_admin", x_lang))
    return users.set_roles(email, payload.roles)


@router.put("/api/auth/users/{email}/name", response_model=AdminUserOut)
def set_user_name(
    email: str,
    payload: UpdateUserNameIn,
    _user: str = Depends(main.require_role(users.USER_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    entry = users.set_name(email, payload.name)
    if entry is None:
        raise HTTPException(404, i18n.get_message("user_not_found", x_lang))
    return entry


def _with_actor_name(entry: dict) -> dict:
    user = users.get_user(entry["actor_email"])
    return {**entry, "actor_name": user.get("name") if user else None}


@router.get("/api/audit-log", response_model=list[AuditLogEntryOut])
def get_audit_log(_user: str = Depends(main.require_role(users.QUELLEN_PFLEGER))):
    return [_with_actor_name(entry) for entry in audit.list_entries()]


@router.get("/api/question-log", response_model=list[QuestionLogEntryOut])
def get_question_log(
    include_answers: bool = True, _user: str = Depends(main.require_role(users.SYSTEM_ADMIN))
):
    # include_answers=false (Fragen-Log-Seite): die Antworttexte sind der
    # Löwenanteil der Datenmenge - die Liste kommt ohne sie (has_answer zeigt
    # nur, dass es eine gibt), jede Antwort wird erst beim Aufklappen über
    # GET /api/question-log/{id} nachgeladen (gleiche Idee wie
    # include_text=false bei /api/sources).
    return [
        {
            **{k: v for k, v in entry.items() if include_answers or k != "answer"},
            "has_answer": bool(entry.get("answer")),
            "conversation_id": entry.get("conversation_id"),
        }
        for entry in question_log.list_entries()
    ]


@router.get("/api/question-log/{entry_id}", response_model=QuestionLogEntryOut)
def get_question_log_entry(
    entry_id: str, x_lang: str = Header(default=i18n.DEFAULT_LANG), _user: str = Depends(main.require_role(users.SYSTEM_ADMIN))
):
    entry = question_log.get_entry(entry_id)
    if entry is None:
        raise HTTPException(404, i18n.get_message("question_log_entry_not_found", x_lang))
    return {**entry, "has_answer": bool(entry.get("answer"))}


# Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): löscht einen einzelnen
# Fragen-Log-Eintrag unwiderruflich (jeden event_type - erste Frage,
# unbeantwortete Frage, Feedback) - deckt das in der Datenschutzerklärung
# (Abschnitt 5/11) beschriebene, zuvor nur manuelle Löschen tatsächlich als
# Funktion ab. Dieselbe Rolle wie beim Lesen (SYSTEM_ADMIN, seit Idee
# 56580b6e - das Log enthält jetzt jede Frage), keine Sonderregel.
@router.delete("/api/question-log/{entry_id}", response_model=MessageOut)
def delete_question_log_entry(
    entry_id: str, x_lang: str = Header(default=i18n.DEFAULT_LANG), _user: str = Depends(main.require_role(users.SYSTEM_ADMIN))
):
    if not question_log.delete_entry(entry_id):
        raise HTTPException(404, i18n.get_message("question_log_entry_not_found", x_lang))
    return MessageOut(detail=i18n.get_message("question_log_entry_deleted", x_lang))


# Idee 56580b6e: ein ganzes Gespräch (alle Einträge mit dieser
# conversation_id) auf einmal löschen. Der Pfad hat mehr Segmente als
# /api/question-log/{entry_id} und kollidiert deshalb nicht damit.
@router.delete("/api/question-log/conversation/{conversation_id}", response_model=MessageOut)
def delete_question_log_conversation(
    conversation_id: str,
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
    _user: str = Depends(main.require_role(users.SYSTEM_ADMIN)),
):
    if not question_log.delete_conversation(conversation_id):
        raise HTTPException(404, i18n.get_message("question_log_conversation_not_found", x_lang))
    return MessageOut(detail=i18n.get_message("question_log_conversation_deleted", x_lang))


ANSWER_FEEDBACK_VALUES = {"good", "bad"}
ANSWER_FEEDBACK_MODES = {"conversation", "creative"}


@router.post("/api/answer-feedback", response_model=MessageOut)
def submit_answer_feedback(
    payload: AnswerFeedbackIn, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)
):
    # Nutzerwunsch (2026-09-01): Daumen-hoch/-runter je Antwort (siehe
    # static/question.js: attachFeedbackButtons). Bewusst OHNE Captcha,
    # analog zu /api/speak: nur nach einer bereits erfolgreich beantworteten
    # /api/ask-Anfrage erreichbar, die selbst schon captcha-/ratenbegrenzt
    # ist. Ein deutlich lockereres Limit als /api/feedback (das E-Mails
    # verschickt) reicht trotzdem, um Skript-Missbrauch des Logs zu
    # verhindern - ein Klick pro Antwort ist normale Nutzung, mehrere pro
    # Konversation üblich.
    client_ip = request.client.host if request.client else "unknown"
    if ratelimit.is_rate_limited(f"answer-feedback-ip:{client_ip}", max_requests=30, window_seconds=3600):
        raise HTTPException(429, i18n.get_message("rate_limited", x_lang))
    if payload.feedback not in ANSWER_FEEDBACK_VALUES or payload.mode not in ANSWER_FEEDBACK_MODES:
        raise HTTPException(400, i18n.get_message("invalid_feedback_value", x_lang))

    if _should_log_question_event(request):
        question_log.log_feedback(
            _truncate_for_log(payload.question, main.ANSWER_FEEDBACK_MAX_QUESTION_CHARS),
            _truncate_for_log(llm.strip_image_markers(payload.answer), main.ANSWER_FEEDBACK_MAX_ANSWER_CHARS),
            payload.feedback,
            payload.mode,
            _valid_conversation_id(payload.conversation_id),
        )

    return MessageOut(detail=i18n.get_message("feedback_sent", x_lang))


def _restore_deleted_source(source_id: str, x_lang: str) -> None:
    """Rückgängig-machen einer Löschung (Backlog #99): der Rohdatensatz und
    eine angehängte PDF-/Audio-Datei waren nie weg (siehe delete_source) -
    es genügt, deleted_at zu entfernen und die Vectorstore-Chunks aus dem
    weiterhin vorhandenen Text neu aufzubauen (kein KI-Aufruf nötig,
    Zusammenfassung/Begriffe stehen schon im Datensatz)."""
    with _sources_write_lock:
        sources = main._load_sources()
        entry = sources.get(source_id)
        if entry is None or not entry.get("deleted_at"):
            raise HTTPException(400, i18n.get_message("audit_revert_failed", x_lang))
        entry["deleted_at"] = None
        source_in = _source_in_from_entry(entry)
        chunks, chunk_embeddings = _prepare_chunks(source_in, x_lang)
        with _vectorstore_write_lock:
            entry["chunk_count"] = _store_chunks(
                source_id, source_in, chunks, chunk_embeddings, entry.get("images")
            )
        _save_sources(sources)
    for name in entry.get("authors") or []:
        authors.register_author(name, source_id)
    main._register_all_terms(source_id, entry)


def _revert_source_changes(
    source_id: str, changes: dict, x_lang: str, background_tasks: BackgroundTasks | None = None
) -> None:
    with _sources_write_lock:
        sources = main._load_sources()
        if source_id not in sources:
            raise HTTPException(400, i18n.get_message("audit_revert_failed", x_lang))
        entry = sources[source_id]
        for field, diff in changes.items():
            entry[field] = diff["old"]
        # Idee 134c868a (K2): wie update_source - zurückgesetzter Titel/Text
        # macht die KI-erkannte Sprache ungültig (ausgenommen explizit
        # mitzurückgesetzte Sprachfelder).
        redetect = "title" in changes or "text" in changes
        # Zurückgesetzte Sprachfelder gelten wieder als KI-Stand (auch bei
        # altem Wert None: sonst blieben sie ohne Nachzug leer).
        for field in ("text_lang", "title_en"):
            if field in changes:
                entry[f"{field}_ai_generated"] = True
        if redetect:
            _clear_ai_language_fields(entry, keep=frozenset(changes))
        if "text" in changes:
            source_in = _source_in_from_entry(entry)
            chunks, chunk_embeddings = _prepare_chunks(source_in, x_lang)
            with _vectorstore_write_lock:
                vectorstore.delete_source_chunks(source_id)
                entry["chunk_count"] = _store_chunks(
                    source_id, source_in, chunks, chunk_embeddings, entry.get("images")
                )
        _save_sources(sources)
    if redetect and background_tasks is not None:
        background_tasks.add_task(_detect_and_store_language, source_id, entry.get("title", ""), entry.get("text", ""))
    if "authors" in changes:
        authors.unregister_source(source_id)
        for name in entry.get("authors") or []:
            authors.register_author(name, source_id)
    if any(field.startswith(("summary_", "key_terms_")) for field in changes):
        main._register_all_terms(source_id, entry)


def _revert_author_changes(name: str, changes: dict, x_lang: str) -> None:
    matching = _find_author(name)
    if matching is None:
        raise HTTPException(400, i18n.get_message("audit_revert_failed", x_lang))
    kwargs = {field: diff["old"] for field, diff in changes.items()}
    author_profiles.set_profile(name, **kwargs)


def _revert_source_suggestion_changes(suggestion_id: str, changes: dict, x_lang: str) -> None:
    # Deutlich einfacher als ein Quellen-Revert: Annehmen/Ablehnen ändert
    # nur den Status der Vorschlags-Zeile selbst (siehe accept/reject_
    # source_suggestion oben) - keine damit verknüpfte, angelegte Quelle,
    # die hier mit rückgängig gemacht werden müsste.
    suggestion = source_suggestions.get_suggestion(suggestion_id)
    if suggestion is None:
        raise HTTPException(400, i18n.get_message("audit_revert_failed", x_lang))
    old_status = changes["status"]["old"]
    new_status = changes["status"]["new"]
    source_suggestions.set_status(suggestion_id, old_status)
    # War die rückgängig gemachte Aktion ein Accept (+1), zieht der Revert
    # die Gewichtung wieder ab, und umgekehrt bei einem Reject (-1).
    delta = -1 if new_status == "accepted" else 1
    source_suggestions.adjust_weight(
        author_hint=suggestion.get("author_hint"), url=suggestion["url"], delta=delta
    )


@router.post("/api/audit-log/{entry_id}/revert", response_model=MessageOut)
def revert_audit_entry(
    entry_id: str,
    background_tasks: BackgroundTasks,
    _user: str = Depends(main.require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    entry = audit.get_entry(entry_id)
    if entry is None:
        raise HTTPException(404, i18n.get_message("audit_entry_not_found", x_lang))
    if entry.get("reverted_at"):
        raise HTTPException(409, i18n.get_message("audit_entry_already_reverted", x_lang))
    if not entry.get("revertible") or not entry.get("changes"):
        raise HTTPException(400, i18n.get_message("audit_revert_failed", x_lang))

    action = entry["action"]
    entity_type = entry["entity_type"]
    entity_id = entry["entity_id"]
    changes = entry["changes"]

    if action == "source_deleted":
        _restore_deleted_source(entity_id, x_lang)
    elif action == "author_renamed":
        old_name = changes["name"]["old"]
        new_name = changes["name"]["new"]
        if _rename_author_entity(new_name, old_name) is None:
            raise HTTPException(400, i18n.get_message("audit_revert_failed", x_lang))
    elif entity_type == "source":
        _revert_source_changes(entity_id, changes, x_lang, background_tasks)
    elif entity_type == "author":
        _revert_author_changes(entity_id, changes, x_lang)
    elif entity_type == "source_suggestion":
        _revert_source_suggestion_changes(entity_id, changes, x_lang)
    else:
        raise HTTPException(400, i18n.get_message("audit_revert_failed", x_lang))

    audit.mark_reverted(entry_id)
    # Der Revert selbst wird wieder als ganz normaler Log-Eintrag
    # protokolliert (mit vertauschten old/new-Werten) - dadurch ist auch
    # ein Revert seinerseits erneut revertierbar, ohne Sonderlogik für
    # "Redo" (Backlog #99).
    reverted_changes = {field: {"old": diff["new"], "new": diff["old"]} for field, diff in changes.items()}
    audit.log_change(_user, f"{action}_reverted", entity_type, entity_id, entry["target_label"], reverted_changes)
    return MessageOut(detail=i18n.get_message("audit_reverted", x_lang))
