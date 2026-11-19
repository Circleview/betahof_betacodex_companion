# Idee 313ad93d: aus app/main.py ausgelagert (Verhalten unverändert).

import json
import logging
import os
from fastapi import APIRouter, HTTPException, Header, Request
from fastapi.responses import Response, StreamingResponse
from urllib.parse import parse_qs, quote, urlsplit
from app import (
    author_profiles,
    authors,
    captcha,
    conversation_handoff,
    embeddings,
    i18n,
    llm,
    mail,
    question_log,
    ratelimit,
    tts,
    usage,
    users,
    vectorstore,
    web_index,
)
from app.models import (
    ChunkRef,
    ConversationHandoffIn,
    CreativeRequestIn,
    FeedbackIn,
    MessageOut,
    QuestionIn,
    SpeechIn,
)

from app import main
from app.retrieval import (
    NO_ANSWER_EXPLANATIONS,
    NO_ANSWER_PHRASES,
    _ASK_LABEL_CHECK_MIN_LEN,
    _ASK_QUOTES_MARKER,
    _ASK_STREAM_HOLDBACK,
    _CITATION_NUMBER_RE,
    _PENDING_IMAGE_MARKER_RE,
    _apply_chunk_images,
    _diversity_key,
    _drop_no_answer_lead,
    _keyword_exempt_source_ids,
    _limit_restricted_images,
    _question_terms,
    _redact_restricted_refs,
    _rerank_by_relevance,
    _should_log_question_event,
    _source_matches_question_keywords,
    _trim_history,
    _truncate_for_log,
    _valid_conversation_id,
    _with_images,
)
from app.source_processing import _source_is_missing, _source_lang_fields

router = APIRouter()


def _ask_event_stream(
    question_text,
    llm_chunks,
    lang,
    author_bios,
    chunk_refs,
    chunk_docs,
    query_embedding,
    history,
    should_log_question_events,
    log_id,
    usage=None,
    can_view_full_text=True,
):
    """Generator für die NDJSON-Stream-Antwort von /api/ask: ein frühes
    "sources"-Event (Titel/Autor:in/Link, siehe unten), dann ein "delta"-
    Event pro neu angekommenem Text-Fragment, ein "answer"-Event sobald der
    sichtbare Antworttext feststeht, und am Ende ein "done"-Event mit
    denselben Quellen inkl. berechneter Hervorhebungen - oder ein "error"-
    Event, falls die Anfrage an Anthropic fehlschlägt. Der ---QUOTES---Block
    selbst wird NIE an die Nutzer:in gestreamt, da er reine interne Beleg-
    Daten für die Hervorhebungen enthält."""
    # Nutzerwunsch (2026-08-03): Titel/Autor:in/Link jeder Quelle stehen
    # bereits vor dem LLM-Aufruf fest (siehe ask() oben) - ein frühes
    # "sources"-Event macht "[n]"-Verweise im Frontend sofort klickbar,
    # statt bis zum "done"-Event zu warten, dessen Hervorhebungs-Berechnung
    # spürbar länger dauern kann. highlighted_texts ist hier noch leer und
    # wird unten im "done"-Event für dieselben Quellen nachgereicht.
    sources_by_id = main._load_sources()
    offered_images = _limit_restricted_images(chunk_refs, sources_by_id)
    yield json.dumps(
        {
            "type": "sources",
            "sources": [
                r.model_dump()
                for r in _redact_restricted_refs(
                    _with_images(chunk_refs, offered_images), sources_by_id, can_view_full_text
                )
            ],
        }
    ) + "\n"
    # Idee fe44f080: das Modell kennt genau die Bilder, die auch gezeigt werden.
    llm_chunks = [
        {**chunk, "images": [{**image.model_dump(), "from_source": image.from_source} for image in images]}
        for chunk, images in zip(llm_chunks, offered_images)
    ]
    offered_counts = [len(images) for images in offered_images]

    buffer = ""
    sent_len = 0
    label_resolved = False
    answer_sent = False
    # Nutzerwunsch (2026-08-28): erkennt das Modell eine eigentliche
    # Generierungsanfrage statt einer Faktenfrage (siehe Regel in
    # llm.SYSTEM_PROMPTS), verweist es per {{CREATIVE_LINK}}-Platzhalter auf
    # den Kreativ-Modus - hier deterministisch durch die echte, korrekt
    # URL-kodierte Ziel-URL ersetzt (inkl. vorausgefüllter Anweisung), statt
    # dem Modell die fehleranfällige URL-Kodierung selbst zu überlassen.
    creative_link_url = f"/creative.html?instruction={quote(question_text)}"

    try:
        for delta in llm.stream_answer_question(
            question_text, llm_chunks, lang=lang, author_bios=author_bios, history=history, usage=usage
        ):
            buffer += delta
            # Ersetzt eine bereits VOLLSTÄNDIG angekommene Platzhalter-
            # Instanz sofort direkt im Puffer selbst (nicht nur in einer
            # abgeleiteten Kopie) - sonst könnte die Holdback-Kürzung unten
            # (die nur vor einem noch UNVOLLSTÄNDIGEN Platzhalter-Fragment am
            # Pufferende schützt) mitten durch einen bereits vollständigen,
            # aber weiter hinten im Puffer liegenden Treffer schneiden und
            # nur eine Hälfte davon sichtbar machen (reale Regression, siehe
            # test_ask_replaces_creative_link_placeholder_even_when_split_
            # across_chunks). Nach dieser Ersetzung kann im restlichen Puffer
            # nur noch höchstens ein noch UNVOLLSTÄNDIGES Fragment auftreten.
            buffer = buffer.replace(llm.CREATIVE_LINK_PLACEHOLDER, creative_link_url)
            # Ein Marker, dem bisher nur Leerraum folgt, ist noch unentschieden:
            # der Filter schluckt Leerraum DANACH, der erst später ankommt. Er
            # wird erst gefiltert und gesendet, wenn echter Text folgt.
            pending = _PENDING_IMAGE_MARKER_RE.search(buffer)
            pending_start = pending.start() if pending else len(buffer)
            buffer = llm.filter_image_markers(buffer[:pending_start], offered_counts) + buffer[pending_start:]
            pending_start = len(buffer) - (len(pending.group(0)) if pending else 0)
            marker_index = buffer.find(_ASK_QUOTES_MARKER)
            if marker_index != -1:
                visible_raw = buffer[:marker_index]
            else:
                cut = min(max(0, len(buffer) - _ASK_STREAM_HOLDBACK), pending_start)
                # Ein vollständiger (gültiger) Bildmarker wird nie zerschnitten.
                for match in llm.IMAGE_MARKER_RE.finditer(buffer):
                    if match.start() < cut < match.start() + len(match.group(0).rstrip()):
                        cut = match.start()
                visible_raw = buffer[:cut]

            if not label_resolved:
                if marker_index == -1 and len(visible_raw) < _ASK_LABEL_CHECK_MIN_LEN:
                    continue
                label_resolved = True

            visible_final, pending = _drop_no_answer_lead(
                llm._strip_answer_label(visible_raw), final=marker_index != -1
            )
            if pending:
                continue
            new_text = visible_final[sent_len:]
            if new_text:
                yield json.dumps({"type": "delta", "text": new_text}) + "\n"
                sent_len = len(visible_final)

            # Nutzerwunsch (2026-08-03): Vorlesen soll nicht auf den
            # unsichtbaren ---QUOTES---Block warten, der nach dem sichtbaren
            # Antworttext folgt - sobald der Marker im Puffer auftaucht,
            # steht der sichtbare Text (inkl. Zitat-Positionskorrektur,
            # siehe llm.parse_answer_and_quotes/_move_leading_citations_to_
            # sentence_end) bereits fest. Der Rest des Streams (die Zitate
            # selbst) wird unten weiter eingesammelt, aber ohne weitere
            # "delta"-Events (visible_final wächst ab hier nicht mehr).
            if marker_index != -1 and not answer_sent:
                early_answer_text, _ = llm.parse_answer_and_quotes(buffer)
                early_answer_text, _ = _drop_no_answer_lead(early_answer_text, final=True)
                early_answer_text = early_answer_text.replace(llm.CREATIVE_LINK_PLACEHOLDER, creative_link_url)
                yield json.dumps({"type": "answer", "answer": early_answer_text}) + "\n"
                answer_sent = True
    except Exception:
        yield json.dumps({"type": "error", "message": i18n.get_message("ask_llm_failed", lang)}) + "\n"
        return

    buffer = llm.filter_image_markers(llm.drop_partial_marker(buffer), offered_counts)
    raw_answer_text, quotes_by_citation = llm.parse_answer_and_quotes(buffer)
    answer_text, _ = _drop_no_answer_lead(raw_answer_text, final=True)
    answer_text = answer_text.replace(llm.CREATIVE_LINK_PLACEHOLDER, creative_link_url)
    remaining = answer_text[sent_len:]
    if remaining:
        yield json.dumps({"type": "delta", "text": remaining}) + "\n"

    # Nutzerwunsch (2026-09-01): "no_answer"-Ereignis im Fragen-Log, siehe
    # NO_ANSWER_PHRASES oben - erst hier möglich, da answer_text erst jetzt
    # feststeht. log_id ist die vorab von ask() geloggte Frage (None bei
    # Dev/System-Admin/MCP/nicht lesbarem Log, da ein Generator keinen
    # Zugriff auf request hat). Seit Idee 56580b6e wird jede Frage geloggt,
    # "no_answer" ergänzt deshalb immer diesen Eintrag (Fix 2026-09-14: kein
    # zweiter, doppelter Eintrag, siehe question_log.add_event_type).
    # Reine Absage: ins Fragen-Log der kurze Satz statt der langen Erklärung.
    log_answer = raw_answer_text.strip() if answer_text in NO_ANSWER_EXPLANATIONS.values() else answer_text
    log_answer = llm.strip_image_markers(log_answer)
    log_answer = _truncate_for_log(log_answer, main.ANSWER_FEEDBACK_MAX_ANSWER_CHARS)
    # Der Satz kommt in der Sprache der Frage, nicht zwingend der Oberfläche.
    if log_id and should_log_question_events and any(p in raw_answer_text for p in NO_ANSWER_PHRASES.values()):
        question_log.add_event_type(log_id, "no_answer")

    # Nutzerwunsch (Livegang-Vorbereitung, 2026-09-10): die Antwort soll
    # ebenfalls im Fragen-Log stehen - log_question() oben in ask() konnte
    # sie noch nicht kennen (lief bewusst VOR der Suche, siehe dortiger
    # Kommentar), wird hier nachgetragen.
    if log_id:
        question_log.set_answer(log_id, log_answer)

    # Backlog (2026-07-31, ergaenzt 2026-08-03): der fertige Antworttext
    # steht hier bereits fest - die folgende Highlight-Berechnung (lokales
    # Embedding-Modell, siehe _compute_occurrence_highlights/
    # _best_local_sentence) kann auf schwächerer CPU spürbar dauern. Eigenes,
    # frühes Event dafür, damit z.B. der Vorlesen-Button nicht auf Quellen/
    # Highlights warten muss (siehe question.js: onAnswer-Callback schaltet
    # ihn schon hier frei). NUR falls oben (beim Marker-Fund) noch nicht
    # gefeuert - sonst gäbe es zwei identische "answer"-Events.
    if not answer_sent:
        yield json.dumps({"type": "answer", "answer": answer_text}) + "\n"

    occurrence_highlights = main._compute_occurrence_highlights(answer_text, chunk_docs, quotes_by_citation)
    for i, chunk_ref in enumerate(chunk_refs):
        if occurrence_highlights[i]:
            chunk_ref.highlighted_texts = occurrence_highlights[i]
            continue
        # Letzter Ausweg: eine zurückgegebene Quelle, die im finalen
        # Antworttext aus irgendeinem Grund gar nicht per [n] referenziert
        # wird, bekommt trotzdem ein Highlight (gegen die Nutzerfrage
        # gescort) statt gar keins. Bewusst erst HIER (lazy, nach dem
        # Streaming) statt vorab für alle Chunks berechnet - das lokale
        # Embedding-Modell separat pro Chunk aufzurufen kostet spürbar Zeit
        # (Messung: ~2s für 5 Chunks) und wird in der Praxis fast nie
        # gebraucht, da die meisten zurückgegebenen Chunks auch tatsächlich
        # zitiert werden (siehe _compute_occurrence_highlights oben, das
        # denselben Lazy-Ansatz für zitierte Chunks bereits nutzt).
        local_highlight = main._best_local_sentence(chunk_docs[i], query_embedding)
        chunk_ref.highlighted_texts = [local_highlight] if local_highlight else []

    # Das eine restricted-Bild gehört an den ersten ZITIERTEN Ref der Quelle.
    # Idee fe44f080: das Bild am Marker-Chunk bleibt dort, auch wenn eine
    # andere Quelle derselben restricted-Quelle früher zitiert wird.
    inline = llm.IMAGE_MARKER_RE.search(answer_text)
    inline_chunk = [int(inline.group(1)) - 1] if inline else []
    cited = inline_chunk + [
        int(n) - 1 for n in _CITATION_NUMBER_RE.findall(answer_text) if 0 < int(n) <= len(chunk_refs)
    ]
    done_refs = _with_images(chunk_refs, _limit_restricted_images(chunk_refs, sources_by_id, cited))
    yield json.dumps(
        {
            "type": "done",
            "sources": [r.model_dump() for r in _redact_restricted_refs(done_refs, sources_by_id, can_view_full_text)],
        }
    ) + "\n"


def _ask_context(
    question_text: str,
    history: list[dict],
    x_lang: str,
    top_k: int = 5,
    usage_email: str | None = None,
    max_per_source: int | None = None,
    rewrite_channel: str = "ask",
):
    """Suche für eine Frage (2026-09-26 aus ask() herausgelöst, damit auch
    das MCP-Werkzeug ask_question exakt dieselbe Logik nutzt): Quellen
    finden, gewichten, Hybrid-Suche, Autor:innen-Viten. Liefert
    (llm_chunks, chunk_refs, author_bios, query_embedding)."""
    sources = main._load_sources()
    if not sources:
        raise HTTPException(400, i18n.get_message("no_sources", x_lang))


    # Fix (2026-08-20, per Screenshot gemeldet): eine kurze Folgefrage wie
    # "Erzähle mehr" trägt allein kaum thematischen Anker - die frühere
    # Lösung (nur die letzte Frage anhängen) reichte dafür nicht und landete
    # in einem dicht gefüllten Korpus komplett am Thema vorbei (siehe
    # llm.rewrite_followup_query für die volle Herleitung). Ein eigener,
    # schneller LLM-Call formuliert die Folgefrage stattdessen anhand des
    # Verlaufs zu einer eigenständigen Suchanfrage um. Schlägt der Call fehl
    # (liefert None), fällt es auf die alte, einfache Verkettung zurück -
    # eine Anthropic-Störung darf die Anfrage nie komplett blockieren.
    query_text = question_text
    if history:
        query_text = llm.rewrite_followup_query(
            question_text, history[-main.ASK_REWRITE_HISTORY_TURNS:], x_lang, usage_email=usage_email,
            channel=rewrite_channel,
        ) or (
            f"{history[-1]['question']} {question_text}"
        )

    query_embedding = embeddings.embed_query(query_text)
    # Wiederverwendet weiter unten auch für author_bios - ein Namensabgleich
    # reicht für beides (siehe Kommentar bei AUTHOR_MENTION_DISTANCE_FACTOR).
    mentioned_author_names = authors.find_mentioned(question_text)
    # Idee 3c32da30: Quellen-Vielfalt (max_per_source=None -> Einstellung aus
    # der Umgebung). Ein größerer Pool bringt Nachrücker und Kernquellen, die
    # erst durch ihren Relevanzscore nach vorn rücken.
    if max_per_source is None:
        max_per_source = main.SOURCE_DIVERSITY_MAX_PER_SOURCE
    pool_size = top_k * (main.SOURCE_DIVERSITY_POOL_MULTIPLIER if max_per_source > 0 else main.RELEVANCE_OVERFETCH_MULTIPLIER)
    curated_hits = vectorstore.query(
        query_embedding, top_k=pool_size
    )
    # Idee 78404054: Füllen wenige Quellen den Pool (mehr als max_per_source
    # Chunks), kommen Nachrücker anderer Quellen gar nicht erst hinein - die
    # Toleranz im Rerank hilft dann nicht. Zweite Abfrage ohne diese Quellen.
    if max_per_source > 0:
        counts: dict[str, int] = {}
        for meta in curated_hits["metadatas"][0]:
            counts[meta["source_id"]] = counts.get(meta["source_id"], 0) + 1
        dominant = sorted(sid for sid, n in counts.items() if n > max_per_source)
        if dominant:
            extra = vectorstore.query(
                query_embedding, top_k=pool_size, where={"source_id": {"$nin": dominant}}
            )
            seen = set(curated_hits["ids"][0])
            curated_hits = {
                key: [curated_hits[key][0] + [v for i, v in zip(extra["ids"][0], extra[key][0]) if i not in seen]]
                for key in ("ids", "documents", "distances", "metadatas")
            }
    # Immer mitabgefragt, siehe Kommentar oben - rein lokal, keine spürbare
    # Zeitkosten. exclude_page_ids berücksichtigt manuell ausgeschlossene
    # Einzelseiten (siehe app/web_index.py:set_excluded).
    web_hits = vectorstore.query_web(
        query_embedding,
        top_k=pool_size,
        exclude_page_ids=web_index.excluded_page_ids(),
    )

    ids = curated_hits["ids"][0] + web_hits["ids"][0]
    documents = curated_hits["documents"][0] + web_hits["documents"][0]
    distances = curated_hits["distances"][0] + web_hits["distances"][0]
    metadatas = list(curated_hits["metadatas"][0])
    for meta in web_hits["metadatas"][0]:
        # _rerank_by_relevance liest Quellen-Metadaten einheitlich über
        # "source_id" - Web-Treffer tragen stattdessen "page_id" (siehe
        # app/web_crawler.py). sources.get(page_id) findet dort naturgemäß
        # nichts, relevance_factor() fällt dann auf den neutralen Default-
        # Score 5 zurück - Web-Treffer werden also rein nach (Chroma-)
        # Distanz einsortiert, ohne den kuratierten Relevanz-Score-Bonus.
        metadatas.append({**meta, "source_id": meta["page_id"], "is_web_fallback": True})

    if mentioned_author_names:
        # Index statt reinem Set, damit ein Chunk, der bereits über die
        # normale Vektorsuche oben gefunden wurde, hier nicht übersprungen,
        # sondern dessen Distanz ANGEPASST wird - sonst würde ein Chunk, der
        # zufällig ohnehin schon im generischen Kandidatenpool auftaucht, nie
        # den Rabatt bekommen (genau der Fall, der in der Praxis am
        # häufigsten vorkommt: die eigene Quelle ist unter den
        # überholten Kandidaten meist schon dabei, nur zu weit hinten).
        id_to_index = {chunk_id: i for i, chunk_id in enumerate(ids)}
        author_entries = {entry["name"]: entry for entry in authors.list_authors()}
        author_source_ids = {
            source_id
            for name in mentioned_author_names
            for source_id in author_entries.get(name, {}).get("source_ids", [])
        }
        # Fix (2026-09-01): eine EINZELNE, über alle Quellen der Autor:in
        # gemeinsam laufende top_k-Suche (vorherige Fassung) kann pro Quelle
        # keinen unterschiedlichen Rabatt vergeben - genau das braucht aber
        # AUTHOR_MENTION_KEYWORD_MATCH_FACTOR unten (realer Fall "Andreas
        # Schlegel und Zeitorientierung": die tatsächlich einschlägige, aber
        # embedding-mäßig weiter entfernte Quelle verlor gegen zwei lange,
        # nur gleichsprachige Podcast-Transkripte zu einem ganz anderen
        # Thema derselben Person - ein einheitlicher Rabatt über alle
        # Chunks hinweg ändert an dieser Reihenfolge nichts, er verschiebt
        # beide nur gleichmäßig). Deshalb läuft PRO Quelle eine eigene,
        # kleine Suche: erst dadurch lässt sich pro Quelle einzeln prüfen,
        # ob ihre kuratierten Schlagworte zur Frage passen, und nur bei
        # Treffer den deutlich stärkeren Rabatt anwenden statt des normalen.
        for source_id in author_source_ids:
            source_hits = vectorstore.query(
                query_embedding,
                top_k=main.AUTHOR_MENTION_TOP_K_PER_SOURCE,
                where={"source_id": source_id},
            )
            keyword_match = _source_matches_question_keywords(
                sources.get(source_id, {}), question_text
            )
            factor = (
                main.AUTHOR_MENTION_KEYWORD_MATCH_FACTOR
                if keyword_match
                else main.AUTHOR_MENTION_DISTANCE_FACTOR
            )
            for chunk_id, doc, dist, meta in zip(
                source_hits["ids"][0],
                source_hits["documents"][0],
                source_hits["distances"][0],
                source_hits["metadatas"][0],
            ):
                discounted_distance = dist * factor
                if chunk_id in id_to_index:
                    distances[id_to_index[chunk_id]] = discounted_distance
                else:
                    id_to_index[chunk_id] = len(ids)
                    ids.append(chunk_id)
                    documents.append(doc)
                    distances.append(discounted_distance)
                    metadatas.append(meta)

    if not ids:
        raise HTTPException(400, i18n.get_message("no_matching_chunks", x_lang))

    # Idee 3c32da30: Ausnahmen gelten nur für diesen Rerank.
    diversity_on = max_per_source > 0
    exempt_source_ids = set()
    question_terms = []
    if diversity_on:
        query_lower = query_text.lower()
        names = set(mentioned_author_names) | set(authors.find_mentioned(query_text))
        for entry in authors.list_authors():
            if entry["name"] in names:
                exempt_source_ids.update(entry["source_ids"])
        exempt_source_ids.update(
            sid for sid, src in sources.items()
            if len(src.get("title") or "") >= 12 and src["title"].lower() in query_lower
        )
        exempt_source_ids.update(_keyword_exempt_source_ids(sources, query_text))
        question_terms = _question_terms(query_text)
    ids, documents, metadatas = _rerank_by_relevance(
        ids, documents, metadatas, distances, sources, top_k,
        max_per_source=max_per_source,
        exempt_source_ids=exempt_source_ids,
        question_terms=question_terms,
    )
    ids, documents, metadatas = main._ensure_term_hits(
        ids, documents, metadatas, query_embedding, query_text, top_k, trim_repeats=diversity_on
    )

    unknown_label = "unbekannt" if x_lang == "de" else "unknown"
    summary_lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG

    chunk_refs = []
    llm_chunks = []
    for chunk_id, doc, meta in zip(ids, documents, metadatas):
        is_web = bool(meta.get("is_web_fallback"))
        # Rückwärtskompatibel lesen: alte, noch nicht neu gespeicherte Chunks
        # haben noch den alten skalaren "author"-Schlüssel statt der Liste.
        # Web-Treffer tragen seit dem Autor:innen-Fix in app/web_crawler.py
        # ebenfalls "authors", sofern trafilatura beim Crawlen welche
        # extrahieren konnte - sonst (Feld fehlt in den Chunk-Metadaten)
        # bleibt es bei einer leeren Liste, kein gesonderter Fall nötig.
        authors_list = meta.get("authors") or ([meta["author"]] if meta.get("author") else [])
        # Web-Chunk-Metadaten (siehe app/web_crawler.py) enthalten kein
        # "date" - direkter []-Zugriff würde dort mit KeyError abbrechen.
        date = None if is_web else (meta["date"] or None)
        chunk_refs.append(
            ChunkRef(
                chunk_id=chunk_id,
                source_id=meta["source_id"],
                title=meta["title"],
                authors=authors_list,
                date=date,
                url=meta["url"] or None,
                listen_url=meta.get("listen_url") or None,
                position=meta["position"],
                text=doc,
                summary=sources.get(meta["source_id"], {}).get(f"summary_{summary_lang}") or None,
                summary_ai_generated=sources.get(meta["source_id"], {}).get(f"summary_ai_generated_{summary_lang}", True),
                is_web_fallback=is_web,
                allowlist_entry_id=meta.get("allowlist_entry_id") if is_web else None,
                url_reachable=sources.get(meta["source_id"], {}).get("url_reachable"),
                **_source_lang_fields(sources.get(meta["source_id"])),
            )
        )
        llm_chunks.append(
            {
                "title": meta["title"],
                "author": ", ".join(authors_list) or unknown_label,
                "date": date or unknown_label,
                "text": doc,
                "source_key": _diversity_key(meta) if diversity_on else None,
                "is_web": is_web,
            }
        )

    _apply_chunk_images(chunk_refs, metadatas, sources, summary_lang)

    # Backlog (2026-07-29): rein chunk-basierte Suche findet für biografische
    # Fragen ("Wer ist X?") keine passenden Textausschnitte, da Autor:innen-
    # Namen nur als Zitat-Metadatum, nicht als durchsuchbarer Inhalt indiziert
    # sind - die gepflegte Vita (author_profiles) wurde dadurch nie genutzt.
    # Erkennt hier stattdessen per Namensabgleich, ob die Frage eine
    # registrierte Autor:in nennt, und reicht deren Vita zusätzlich an das
    # Modell weiter (siehe llm.answer_question/author_bios).
    bio_field = f"bio_{x_lang}" if x_lang in ("de", "en") else f"bio_{i18n.DEFAULT_LANG}"
    author_bios = []
    for name in mentioned_author_names:
        bio = author_profiles.get_profile(name).get(bio_field, "")
        if bio:
            author_bios.append({"name": name, "bio": bio})

    return llm_chunks, chunk_refs, author_bios, query_embedding


@router.post("/api/ask")
def ask(question: QuestionIn, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    client_ip = request.client.host if request.client else "unknown"
    if ratelimit.is_rate_limited(client_ip):
        raise HTTPException(429, i18n.get_message("rate_limited", x_lang))
    if not captcha.verify_turnstile_token(question.turnstile_token, client_ip):
        raise HTTPException(400, i18n.get_message("captcha_failed", x_lang))

    # Backlog #97 (seit Idee 56580b6e: jede Frage): anonymisiertes Log -
    # bewusst schon hier, VOR der eigentlichen RAG-Suche, damit auch Fragen
    # ohne Treffer erfasst werden (gerade die sind für die Lücken-Analyse
    # interessant). Ausschlüsse siehe _should_log_question_event(). Die id
    # wird unten an _ask_event_stream weitergereicht, das die Antwort
    # nachträgt, sobald sie feststeht (Nutzerwunsch, Livegang-Vorbereitung
    # 2026-09-10, siehe question_log.set_answer).
    should_log_question_events = _should_log_question_event(request)
    log_id = None
    if should_log_question_events:
        log_id = question_log.log_question(
            _truncate_for_log(question.question, main.ANSWER_FEEDBACK_MAX_QUESTION_CHARS),
            _valid_conversation_id(question.conversation_id),
            first=question.is_first_message,
        )

    history = _trim_history([turn.model_dump() for turn in question.history])
    for turn in history:  # Idee fe44f080: Bildmarker gehören nicht in den Modell-Verlauf
        turn["answer"] = llm.strip_image_markers(turn["answer"])
    # ponytail: Dev-Umschalter für A/B ohne zweite Instanz - ?vielfalt=aus in
    # der Seiten-URL (kommt per Referer), nur wenn IS_DEV_ENVIRONMENT; Prod
    # ignoriert ihn. Ohne eigenes Feld/Frontend; Ablösung, wenn der Test vorbei ist.
    extra = {}
    try:
        referer_query = urlsplit(request.headers.get("referer", "")).query
    except ValueError:  # kaputter Referer (z. B. "http://[") darf keinen 500 auslösen
        referer_query = ""
    if main.IS_DEV_ENVIRONMENT and "aus" in parse_qs(referer_query).get("vielfalt", []):
        extra["max_per_source"] = 0
    llm_chunks, chunk_refs, author_bios, query_embedding = main._ask_context(
        question.question, history, x_lang, question.top_k, main._get_current_user_email(request), **extra
    )

    chunk_docs = [chunk_ref.text for chunk_ref in chunk_refs]
    return StreamingResponse(
        _ask_event_stream(
            question.question,
            llm_chunks,
            x_lang,
            author_bios or None,
            chunk_refs,
            chunk_docs,
            query_embedding,
            history,
            should_log_question_events,
            log_id,
            {"channel": "ask", "email": main._get_current_user_email(request)},
            users.has_role(main._get_current_user_email(request), users.QUELLEN_PFLEGER),
        ),
        media_type="application/x-ndjson",
    )


# Selbe Zeichenkette wie llm._CREATIVE_SOURCES_MARKER - lokal dupliziert
# statt über den Modul-privaten Namen des anderen Moduls zu greifen, gleiche
# Konvention wie _ASK_QUOTES_MARKER oben für den strikten Modus.
_CREATIVE_SOURCES_MARKER = "---SOURCES---"


def _creative_retrieval_query(instruction: str, document: str) -> str:
    # Kein zusätzlicher LLM-Umformulierungs-Call wie llm.rewrite_followup_query
    # bei /api/ask - hält Überarbeitungen auf dem günstigen Pfad. Bei
    # nicht-leerem Dokument wird ein Ausschnitt des aktuellen Stands an die
    # Anweisung angehängt, damit z.B. "kürze das" thematisch verankert
    # bleibt, auch wenn die Anweisung allein keinen Themenbezug trägt.
    if not document.strip():
        return instruction
    return f"{instruction}\n\n{document[:2000]}"


def _creative_event_stream(lang, betacodex_sources, creative_stream, usage_meta=None, log_request=None):
    """NDJSON-Events für /api/creative: 'delta' pro Text-Fragment des neuen
    Dokuments, ein frühes 'document'-Event sobald der sichtbare
    Dokumenttext feststeht (Analogon zum frühen 'answer'-Event bei
    /api/ask), 'done' mit der nach Vertrauensstufe getrennten Quellenliste,
    oder 'error'. Der ---SOURCES---Block selbst wird NIE gestreamt (reine
    interne Beleg-Daten für die Quellenliste), exakt wie ---QUOTES--- bei
    /api/ask."""
    buffer = ""
    sent_len = 0
    document_sent = False

    try:
        for delta in creative_stream:
            buffer += delta
            marker_index = buffer.find(_CREATIVE_SOURCES_MARKER)
            visible_raw = (
                buffer[:marker_index]
                if marker_index != -1
                else buffer[: max(0, len(buffer) - len(_CREATIVE_SOURCES_MARKER))]
            )
            new_text = visible_raw[sent_len:]
            if new_text:
                yield json.dumps({"type": "delta", "text": new_text}) + "\n"
                sent_len = len(visible_raw)
            # Bei Überarbeitungen gilt erst die bereinigte Fassung am Ende
            # (CreativeStream.clean_text) - kein frühes "document"-Event.
            if marker_index != -1 and not document_sent and not getattr(creative_stream, "is_revision", False):
                early_document, _ = llm.parse_document_and_sources(buffer)
                yield json.dumps({"type": "document", "document": early_document}) + "\n"
                document_sent = True
    except Exception:
        yield json.dumps({"type": "error", "message": i18n.get_message("creative_llm_failed", lang)}) + "\n"
        return

    clean_text = getattr(creative_stream, "clean_text", None)
    document_text, web_source_candidates = llm.parse_document_and_sources(clean_text or buffer)
    remaining = document_text[sent_len:] if clean_text is None else ""
    if remaining:
        yield json.dumps({"type": "delta", "text": remaining}) + "\n"
    if not document_sent:
        yield json.dumps({"type": "document", "document": document_text}) + "\n"

    # Web-Quellen: nur, was das Modell selbst gemeldet hat UND was tatsächlich
    # ein echter Websuche-Treffer DIESES Calls war - Halluzinations-Bremse
    # analog app/source_discovery.py. BetaCodex-Quellen dagegen: deterministisch
    # alles, was tatsächlich als Kontext an das Modell gegeben wurde (siehe
    # creative() unten) - kein Halluzinationsrisiko, da 1:1 aus der eigenen
    # kuratierten Sammlung.
    validated_web_sources = [
        s for s in web_source_candidates if s["url"] in creative_stream.real_web_urls
    ]

    # Kostenmessung (2026-09-24, app/usage.py) - usage_meta trägt Kanal
    # ("ui"/"mcp"), Websuche-Schalter und bei MCP Schlüssel + Konto.
    # Abgesichert (2026-09-24): ein Fehler in der Kostenmessung darf den
    # Kreativ-Modus nie unterbrechen - sonst fehlten Quellenliste und
    # done-Event, obwohl der Text schon da ist. Sichtbar bleibt er im
    # Server-Log. Limits (app/mcp_keys.py) zählen einen solchen Aufruf dann
    # nicht mit - bewusst in Kauf genommen.
    if creative_stream.usage is not None:
        try:
            usage.record(creative_stream.usage, **(usage_meta or {"channel": "ui", "web_search": True}))
        except Exception:
            logging.getLogger("app.main").exception("Kostenmessung für Kreativ-Aufruf fehlgeschlagen")

    # 2026-09-24: Anfrage anonym ins Fragen-Log (log_request = {"instruction",
    # "section"}, nur wenn _should_log_question_event zutrifft) - ebenfalls
    # abgesichert, darf den Kreativ-Modus nie unterbrechen.
    if log_request is not None:
        try:
            question_log.log_creative(log_request["instruction"], document_text, log_request["section"])
        except Exception:
            logging.getLogger("app.main").exception("Fragen-Log für Kreativ-Aufruf fehlgeschlagen")

    yield json.dumps(
        {"type": "done", "sources": {"betacodex": betacodex_sources, "web": validated_web_sources}}
    ) + "\n"


def _creative_context(instruction: str, document: str, x_lang: str) -> tuple[list[dict], list[dict]]:
    """Kuratierter Kontext für den Kreativ-Modus - gemeinsam genutzt von
    /api/creative (Oberfläche) und den MCP-Werkzeugen (app/mcp_server.py).
    Liefert (llm_chunks, betacodex_sources)."""
    # Bewusst KEIN "if not sources: raise no_sources" wie bei /api/ask - der
    # Witz dieses Modus ist gerade, dass er auch Themen bedienen soll, die
    # die kuratierte Sammlung gar nicht abdeckt (z.B. Workshop-Methodik),
    # getragen von der Live-Websuche statt der kuratierten Quellen.
    sources = main._load_sources()
    unknown_label = "unbekannt" if x_lang == "de" else "unknown"

    llm_chunks = []
    betacodex_sources = []
    betacodex_by_work = {}
    if sources:
        query_text = _creative_retrieval_query(instruction, document)
        query_embedding = embeddings.embed_query(query_text)
        curated_hits = vectorstore.query(query_embedding, top_k=main.CREATIVE_TOP_K)
        # Backlog (2026-09-25): Hybrid-Suche wie bei /api/ask - Begriffe aus
        # der Anweisung (nicht aus dem ggf. langen Dokument) bekommen einen
        # garantierten Ausschnitt, der sie wörtlich enthält.
        _, hit_docs, hit_metas = main._ensure_term_hits(
            curated_hits["ids"][0],
            curated_hits["documents"][0],
            curated_hits["metadatas"][0],
            query_embedding,
            instruction,
            main.CREATIVE_TOP_K,
        )
        for doc, meta in zip(hit_docs, hit_metas):
            authors_list = meta.get("authors") or ([meta["author"]] if meta.get("author") else [])
            llm_chunks.append(
                {
                    "title": meta["title"],
                    "author": ", ".join(authors_list) or unknown_label,
                    "date": meta["date"] or unknown_label,
                    "text": doc,
                }
            )
            # Deterministisch aus dem tatsächlich als Kontext gegebenen Chunk
            # gebaut (Analogon zum frühen "sources"-Event bei /api/ask) -
            # unabhängig davon, ob/wie das Modell den Inhalt im Dokument
            # verwendet hat. Mehrere Chunks derselben Quelle (z.B. mehrere
            # Treffer desselben Dokuments unter den Top-K) landen weiterhin
            # alle in llm_chunks (jeder Chunk ist eigener Kontext-Text), aber
            # nur einmal in der angezeigten Quellenliste. Schlüssel ist das
            # WERK (Titel + Autor:innen), nicht die URL: dasselbe Buch kann
            # als zwei Quellen-Datensätze vorliegen (z.B. einmal mit,
            # einmal ohne URL) und würde sonst doppelt erscheinen - der
            # Eintrag mit Link gewinnt dann.
            work_key = (meta["title"].strip().lower(), tuple(authors_list))
            record = sources.get(meta["source_id"]) or {}
            # Link und alles, was an ihm hängt (listen_url, restricted, Sprache),
            # kommen immer vom selben Datensatz.
            link_fields = {
                "url": meta["url"] or None,
                "listen_url": meta.get("listen_url") or None,
                "url_reachable": record.get("url_reachable"),
                **_source_lang_fields(record),
            }
            existing = betacodex_by_work.get(work_key)
            if existing:
                if not existing["url"] and link_fields["url"]:
                    existing.update(link_fields)
                continue
            entry = {
                "title": meta["title"],
                "authors": authors_list,
                "date": meta["date"] or None,
                **link_fields,
            }
            betacodex_by_work[work_key] = entry
            betacodex_sources.append(entry)

    return llm_chunks, betacodex_sources


@router.post("/api/creative")
def creative(payload: CreativeRequestIn, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"creative-ip:{client_ip}"
    if ratelimit.is_rate_limited(
        rate_key,
        max_requests=main.CREATIVE_RATE_LIMIT_MAX_REQUESTS,
        window_seconds=main.CREATIVE_RATE_LIMIT_WINDOW_SECONDS,
    ):
        # Retry-After: die Oberfläche zeigt daraus einen Countdown
        # (static/creative.js: startCooldown).
        retry_after = ratelimit.retry_after_seconds(rate_key, main.CREATIVE_RATE_LIMIT_WINDOW_SECONDS)
        raise HTTPException(
            429, i18n.get_message("rate_limited", x_lang), headers={"Retry-After": str(retry_after)}
        )
    if not captcha.verify_turnstile_token(payload.turnstile_token, client_ip):
        raise HTTPException(400, i18n.get_message("captcha_failed", x_lang))

    instruction = payload.instruction.strip()
    if not instruction:
        raise HTTPException(400, i18n.get_message("creative_instruction_empty", x_lang))
    if len(instruction) > main.CREATIVE_MAX_INSTRUCTION_CHARS:
        raise HTTPException(400, i18n.get_message("creative_instruction_too_long", x_lang))
    document = payload.document
    if len(document) > main.CREATIVE_MAX_DOCUMENT_CHARS:
        raise HTTPException(400, i18n.get_message("creative_document_too_long", x_lang))

    llm_chunks, betacodex_sources = main._creative_context(instruction, document, x_lang)
    creative_stream = llm.stream_creative_response(
        instruction, document, llm_chunks, lang=x_lang, section=payload.section, web_search=payload.web_search
    )

    return StreamingResponse(
        _creative_event_stream(
            x_lang,
            betacodex_sources,
            creative_stream,
            {"channel": "ui", "web_search": payload.web_search, "email": main._get_current_user_email(request)},
            {"instruction": instruction, "section": payload.section is not None}
            if _should_log_question_event(request)
            else None,
        ),
        media_type="application/x-ndjson",
    )


# Nutzerwunsch (2026-08-30): "Vollständig öffnen"-Icon im Embed-Widget
# (static/embed.html) sowie der bestehende "Quelle ansehen/bearbeiten"-Link
# (question.js: appendViewSourceLink/appendEditSourceLink) sollen eine
# laufende Konversation in einen neu geöffneten Tab mitnehmen können -
# sessionStorage ist pro Tab und zusätzlich pro Top-Level-Browsing-Context
# partitioniert (siehe app/conversation_handoff.py), ein neuer Tab bekäme
# also so oder so leeren Storage. Kurzlebiges, einmal abrufbares
# Server-Handoff statt dessen - kein dauerhafter Konversations-Speicher.
CONVERSATION_HANDOFF_MAX_TURNS = 100
# Idee 2070893d: unter REQUEST_BODY_DEFAULT_LIMIT (1 MiB), gemessen in UTF-8-Bytes
# von model_dump_json(); das Frontend kürzt auf < 800_000 (conversation-handoff.js)
# und lässt so Marge für Default-Felder. ponytail: In-Memory-Store; bei Missbrauch
# globale Byte-Obergrenze im Store (conversation_handoff.MAX_TOTAL_BYTES, 503).
CONVERSATION_HANDOFF_MAX_BYTES = 900_000
CONVERSATION_HANDOFF_RATE_LIMIT_MAX_REQUESTS = 20
CONVERSATION_HANDOFF_RATE_LIMIT_WINDOW_SECONDS = 600


@router.post("/api/conversation-handoff")
def create_conversation_handoff(
    payload: ConversationHandoffIn, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)
):
    client_ip = request.client.host if request.client else "unknown"
    if ratelimit.is_rate_limited(
        f"conversation-handoff-ip:{client_ip}",
        max_requests=CONVERSATION_HANDOFF_RATE_LIMIT_MAX_REQUESTS,
        window_seconds=CONVERSATION_HANDOFF_RATE_LIMIT_WINDOW_SECONDS,
    ):
        raise HTTPException(429, i18n.get_message("rate_limited", x_lang))
    if not payload.history:
        raise HTTPException(400, i18n.get_message("conversation_handoff_empty", x_lang))
    size = len(payload.model_dump_json().encode("utf-8"))
    if len(payload.history) > CONVERSATION_HANDOFF_MAX_TURNS or size > CONVERSATION_HANDOFF_MAX_BYTES:
        raise HTTPException(400, i18n.get_message("conversation_handoff_too_large", x_lang))

    # Idee ff895248: der Endpunkt ist anonym - Bilder und Links der Quellen
    # kommen nie vom Client, sondern werden per chunk_id neu gesetzt.
    all_sources = main._load_sources()
    for turn in payload.history:
        metas_by_id = vectorstore.get_chunk_metadatas([ref.chunk_id for ref in turn.sources])
        # Nur Chunks, deren Quelle zum Ref passt (erfundene chunk_ids zählen nicht).
        metas = [
            meta if (meta := metas_by_id.get(ref.chunk_id, {})).get("source_id") == ref.source_id else {}
            for ref in turn.sources
        ]
        _apply_chunk_images(turn.sources, metas, all_sources, x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG)
        for ref in turn.sources:
            ref.url = ref.url if ref.url and ref.url.lower().startswith(("http://", "https://")) else None
            ref.listen_url = (
                ref.listen_url if ref.listen_url and ref.listen_url.lower().startswith(("http://", "https://")) else None
            )
            # Idee 134c868a (K4): Sprache/Titel/restricted nie vom Client,
            # sondern aus dem Quellen-Eintrag (Web-Treffer/Unbekannte: Standard).
            record = None if _source_is_missing(all_sources, ref.source_id) else all_sources[ref.source_id]
            for field, value in _source_lang_fields(record).items():
                setattr(ref, field, value)

    # restricted-Grenze über ALLE Turns gemeinsam, nicht je Turn.
    flat = [ref for turn in payload.history for ref in turn.sources]
    for ref, images in zip(flat, _limit_restricted_images(flat, all_sources)):
        ref.images = images
    # Größe für das Speicher-Budget erst nach dem Neusetzen der Bilder messen.
    size = len(payload.model_dump_json().encode("utf-8"))

    try:
        token = conversation_handoff.create(
            [turn.model_dump() for turn in payload.history], _valid_conversation_id(payload.conversation_id), size
        )
    except conversation_handoff.StoreFull:
        raise HTTPException(503, i18n.get_message("conversation_handoff_store_full", x_lang))
    return {"token": token}


@router.get("/api/conversation-handoff/{token}")
def get_conversation_handoff(token: str, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    client_ip = request.client.host if request.client else "unknown"
    if ratelimit.is_rate_limited(
        f"conversation-handoff-ip:{client_ip}",
        max_requests=CONVERSATION_HANDOFF_RATE_LIMIT_MAX_REQUESTS,
        window_seconds=CONVERSATION_HANDOFF_RATE_LIMIT_WINDOW_SECONDS,
    ):
        raise HTTPException(429, i18n.get_message("rate_limited", x_lang))
    handoff = conversation_handoff.pop(token)
    if handoff is None:
        raise HTTPException(404, i18n.get_message("conversation_handoff_not_found", x_lang))
    history, conversation_id = handoff
    return {"history": history, "conversation_id": conversation_id}


@router.post("/api/speech")
def synthesize_speech(payload: SpeechIn, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    # Bewusst ohne require_role (wie /api/ask öffentlich nutzbar) - das
    # Vorlesen einer ohnehin öffentlich sichtbaren Antwort braucht keine
    # Anmeldung. Der Endpunkt ist direkt aufrufbar (nicht an /api/ask
    # gebunden) und Google TTS rechnet je Zeichen ab: deshalb Zeichenbudget
    # je IP (IPv6 als /64) und Stunde.
    # ponytail: Bremse nur pro IP; bei rotierenden IPs signiertes Ask-Token nötig.
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, i18n.get_message("speech_text_required", x_lang))
    client_ip = request.client.host if request.client else "unknown"
    if ratelimit.is_char_budget_exceeded(
        f"speech-ip:{ratelimit.ip_key(client_ip)}", len(text), max_chars=60000, window_seconds=3600
    ):
        raise HTTPException(429, i18n.get_message("rate_limited", x_lang))

    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    try:
        audio = tts.synthesize_speech(text, lang=lang, speaking_rate=payload.rate)
    except tts.SpeechSynthesisError:
        raise HTTPException(502, i18n.get_message("speech_synthesis_failed", x_lang))
    # Kostenmessung (2026-09-26): Google TTS rechnet je Zeichen ab.
    usage.track_service("tts", "google-tts-chirp3-hd", len(text), main._get_current_user_email(request))
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/api/feedback", response_model=MessageOut)
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
