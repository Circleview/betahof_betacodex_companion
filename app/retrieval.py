# Idee 313ad93d: aus app/main.py ausgelagert (Verhalten unverändert).

import hashlib
import json
import logging
import re
from fastapi import Request
from app import chunking, embeddings, i18n, llm, source_images, terms, users, vectorstore
from app.models import ImageRef

from app import main

def _truncate_for_log(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


# Idee 56580b6e: kanonische UUID (Kleinbuchstaben) wie crypto.randomUUID() -
# uuid.UUID() allein ließe auch andere Schreibweisen zu. Ungültig -> None,
# der Chat läuft ohne Zuordnung weiter.
_CONVERSATION_ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _valid_conversation_id(value: str | None) -> str | None:
    return value if value and _CONVERSATION_ID_RE.fullmatch(value) else None


# Fix (2026-08-20, per Screenshot gemeldet): das "wörtliche" Zitat des LLM
# im ---QUOTES---Block weicht in der Formatierung leicht vom Original ab
# (z.B. wird ein geschütztes Leerzeichen \xa0 - typisch bei aus Websites
# gecrawltem Text - beim Generieren zu einem normalen Leerzeichen normalisiert).
# Bislang wurde nach erfolgreicher toleranter Prüfung trotzdem der
# MODELLTEXT als Highlight übernommen - der exakte String-Vergleich im
# Frontend (findHighlightRange, static/question.js) schlug dadurch fehl,
# nur die dortige Whitespace-tolerante Regex-Notlösung rettete die Anzeige
# (und auch nur für reine Whitespace-Abweichungen, nicht z.B. bei
# Anführungszeichen-Varianten). _find_quote_span() liefert stattdessen die
# TATSÄCHLICHE Textspanne aus dem Chunk selbst zurück (Original-Whitespace/
# -Schreibweise), an exakt der vom Zitat referenzierten Stelle - der
# Frontend-Exakttreffer greift dann direkt, die Regex bleibt nur noch
# Sicherheitsnetz statt Regelfall.
#
# Fix (2026-09-14, gemeldeter Bug "falsches Highlight"): genau die oben schon
# als bekannte Lücke benannten Anführungszeichen-Varianten waren der reale
# Fall - Quelltexte (v.a. gecrawlt/PDF) enthalten oft typografische
# Apostrophe/Anführungszeichen (’‘“”), das Modell zitiert im ---QUOTES---
# Block aber mit geraden ('/"). Schlug der Match dadurch fehl, fiel das
# Highlighting auf die semantisch (nicht wörtlich) nächstliegende Satz-
# Vermutung zurück - bei mehrfach zitierter Quelle konnte das dann das
# Highlight der JEWEILS ANDEREN Textstelle zeigen. Jede Anführungszeichen-
# Variante wird deshalb vor dem Vergleich auf eine gemeinsame Zeichenklasse
# abgebildet, unabhängig davon, welche Schreibweise auf welcher Seite steht.
_QUOTE_CHAR_CLASSES = {"'": "['’‘`]", '"': '["“”]'}


def _find_quote_span(doc: str, candidate: str) -> str | None:
    # Das Modell zitiert teils mit Markdown-Zeichen ("- **Text", "## Text"), der
    # Quelltext hat sie nicht (oder umgekehrt): Listen-/Überschrift-Marker am
    # Anfang und "*" an Wortgrenzen zählen deshalb nicht, im Text dürfen sie
    # zwischen den Wörtern stehen.
    words = candidate.split()
    if words and re.fullmatch(r"[-+*]|#{1,6}", words[0]):
        words = words[1:]
    words = [w.strip("*") for w in words]
    words = [w for w in words if w]
    if not words:
        return None
    escaped_words = []
    for word in words:
        escaped = re.escape(word)
        for literal, char_class in _QUOTE_CHAR_CLASSES.items():
            escaped = escaped.replace(re.escape(literal), char_class)
        escaped_words.append(escaped)
    pattern = r"\**\s+\**".join(escaped_words)
    match = re.search(pattern, doc, re.IGNORECASE)
    return doc[match.start() : match.end()] if match else None


def _get_chunk_sentence_embeddings(doc: str) -> tuple[list[str], list[list[float]] | None]:
    cache_key = hashlib.sha256(doc.encode("utf-8")).hexdigest()
    cached = main._CHUNK_SENTENCE_EMBEDDING_CACHE.get(cache_key)
    if cached is not None:
        return cached
    sentences = chunking.split_sentences(doc)
    sentence_embeddings = embeddings.embed_passages(sentences) if len(sentences) > 1 else None
    main._CHUNK_SENTENCE_EMBEDDING_CACHE[cache_key] = (sentences, sentence_embeddings)
    return sentences, sentence_embeddings


def _best_local_sentence(doc: str, query_embedding: list[float]) -> str | None:
    """Lokales Fallback-Highlighting (Baustein A): zerlegt den Chunk in
    Sätze und wählt per Skalarprodukt (beide Embeddings normalisiert) den
    Satz, der der Frage am nächsten kommt - kostet keine Anthropic-API,
    läuft komplett mit dem bereits geladenen lokalen Embedding-Modell."""
    sentences, sentence_embeddings = _get_chunk_sentence_embeddings(doc)
    if not sentences:
        return None
    if len(sentences) == 1:
        return sentences[0]
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
                highlight = _find_quote_span(doc, quotes[next_index])

            if highlight is None:
                doc_sentences, doc_embeddings = _get_chunk_sentence_embeddings(doc)
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
# Größter der beiden Marker, die im gestreamten Text erkannt werden müssen,
# bevor Zeichen an die Nutzer:in gehen (siehe _ask_event_stream) - verhindert,
# dass ein noch unvollständiger {{CREATIVE_LINK}}-Platzhalter (siehe
# llm.CREATIVE_LINK_PLACEHOLDER) am Puffer-Ende teilweise sichtbar wird,
# bevor er komplett angekommen und ersetzt werden kann.
# Der Bildmarker [bild:nn.mm] (höchstens 12 Zeichen) passt ebenfalls hinein
# (Idee fe44f080); ein vollständiger Marker, den der Schnitt träfe, wird
# in _ask_event_stream vorgezogen.
_PENDING_IMAGE_MARKER_RE = re.compile(r"\[bild:[^\]\n]{0,12}\]\s*\Z", re.I)
_ASK_STREAM_HOLDBACK = max(len(_ASK_QUOTES_MARKER), len(llm.CREATIVE_LINK_PLACEHOLDER), len("[bild:123456789012]"))


def _history_bytes(turns: list[dict]) -> int:
    return sum(len(t["question"].encode("utf-8")) + len(t["answer"].encode("utf-8")) for t in turns)


def _trim_history(turns: list[dict]) -> list[dict]:
    """Leere Fragen und Antworten verwerfen (Anthropic lehnt leere assistant-Inhalte
    ab), dann den Anfang blockweise kappen: erst für die Turn-Grenze, dann solange
    das Byte-Budget überschritten ist (je 10 Turns, höchstens bis zum letzten Turn,
    danach einzeln). Gleiche Regel wie buildAskHistory in static/question.js.

    Bekanntes, bewusst akzeptiertes Risiko (Idee 2070893d, Bestand): der Client
    liefert auch die assistant-Turns, ein manipulierter Request kann also
    erfundene Antworten einschleusen (Prompt-Injection). Option bei Bedarf:
    HMAC-Signatur je Antwort, die der Server beim Streamen mitgibt und hier prüft."""
    turns = [t for t in turns if t["question"].strip() and t["answer"].strip()]
    n = len(turns)
    start = -(-(n - main.ASK_HISTORY_MAX_TURNS) // main.ASK_HISTORY_CUT_BLOCK) * main.ASK_HISTORY_CUT_BLOCK if n > main.ASK_HISTORY_MAX_TURNS else 0
    start = min(start, max(n - 1, 0))
    while start < n - 1 and _history_bytes(turns[start:]) > main.ASK_HISTORY_MAX_BYTES:
        start = min(start + main.ASK_HISTORY_CUT_BLOCK, n - 1)
    while start < n and _history_bytes(turns[start:]) > main.ASK_HISTORY_MAX_BYTES:
        start += 1
    return turns[start:]

# Backlog: LLM/Internet-Fallback bei dünner Quellenlage - ergänzt die
# kuratierten Treffer automatisch (kein Opt-in, Nutzer:innen merken nichts
# davon) um vorab indizierte Web-Fallback-Chunks (siehe app/web_crawler.py).
# Bewusst NUR eine Vektorsuche gegen die bereits fertig indizierte Collection
# (vectorstore.query_web) - kein Live-Fetch zur Antwortzeit, damit sich die
# Antwortzeit dadurch nicht spürbar verändert.
#
# Nutzerfeedback (2026-08-15, realer Fall): ursprünglich wurde diese Suche
# nur ausgelöst, wenn die kuratierten Treffer laut einem Distanz-Schwellwert
# "dünn" waren. Bei diesem thematisch dicht gefüllten Korpus (Organisations-
# entwicklung/Beta-Kodex) lag aber praktisch immer IRGENDein kuratierter
# Treffer nah genug, selbst wenn er das eigentliche Thema der Frage gar
# nicht behandelte - der Fallback griff dadurch fast nie, obwohl die
# freigegebene Website die passende Aussage enthielt. Die Suche läuft
# deshalb jetzt IMMER (rein lokal, kostet keine spürbare Zeit) und die
# Web-Treffer fließen direkt mit ins Reranking (_rerank_by_relevance) ein -
# ein wirklich einschlägiger Web-Treffer kann so mehrere nur thematisch
# benachbarte kuratierte Treffer verdrängen, statt nie eine Chance zu
# bekommen.


def _source_matches_question_keywords(source: dict, question_text: str) -> bool:
    """Siehe AUTHOR_MENTION_KEYWORD_MATCH_FACTOR oben - simpler,
    case-insensitiver Substring-Abgleich wie authors.find_mentioned, nur
    gegen die kuratierten Schlagworte einer einzelnen Quelle statt gegen
    Autor:innen-Namen."""
    question_lower = question_text.lower()
    for field in ("key_terms_de", "key_terms_en"):
        for term in source.get(field) or []:
            if term.lower() in question_lower:
                return True
    return False
LEXICAL_MIN_TERM_LEN = 4
# Backlog (2026-09-25): gebeugte Formen in der Frage ("Leistungsbeurteilungen",
# "Zellstrukturen") treffen das Schlagwort in Grundform. ponytail: nur
# typische deutsche/englische Endungen, kein Stemmer - add when: Umlaut-
# Plurale o. Ä. auffallen.
_INFLECTION_SUFFIX = r"(?:e|n|s|en|er|es|ern|ns)?"
_QUOTED_TERM_RE = re.compile(r'["„“”«»]([^"„“”«»]{3,80})["„“”«»]')


def _question_terms(text: str) -> list[str]:
    candidates = [q.strip() for q in _QUOTED_TERM_RE.findall(text)] + [
        entry["term"]
        for entry in terms.list_terms()
        if len(entry["term"]) >= LEXICAL_MIN_TERM_LEN
        and re.search(r"(?<!\w)" + re.escape(entry["term"]) + _INFLECTION_SUFFIX + r"(?!\w)", text, re.IGNORECASE)
    ]
    chosen: list[str] = []
    # Längster zuerst: "OpenSpace Agility" verdrängt "OpenSpace"/"Agility".
    for term in sorted(dict.fromkeys(candidates), key=len, reverse=True):
        if not any(term.lower() in c.lower() for c in chosen):
            chosen.append(term)
    return chosen[:main.LEXICAL_MAX_TERMS]


def _diversity_key(meta: dict) -> str:
    """Eine Website (allowlist_entry_id) und Titel-Zwillinge zählen als EINE Quelle."""
    if meta.get("allowlist_entry_id"):
        return f"web:{meta['allowlist_entry_id']}"
    title = " ".join((meta.get("title") or "").lower().split())
    return f"title:{title}" if title else f"id:{meta['source_id']}"


def _author_keys(meta: dict) -> list[str]:
    names = meta.get("authors") or ([meta["author"]] if meta.get("author") else [])
    return [" ".join(name.lower().split()) for name in names]


SOURCE_DIVERSITY_KEYWORD_MIN_LEN = 4
SOURCE_DIVERSITY_KEYWORD_MAX_SOURCES = 3


def _keyword_exempt_source_ids(sources: dict, query_text: str) -> set[str]:
    """Quellen, die von der Vielfalts-Regel ausgenommen sind, weil ein
    Schlagwort in der Frage steht (Wortgrenzen, Mindestlänge). Die Grenze
    "höchstens 3 Quellen" gilt je Schlagwort - ein häufiges Schlagwort wie
    "Beta-Kodex" nimmt niemanden aus, ein seltenes daneben schon."""
    carriers: dict[str, set[str]] = {}
    for sid, src in sources.items():
        for field in ("key_terms_de", "key_terms_en"):
            value = src.get(field)
            for term in value if isinstance(value, list) else []:
                if isinstance(term, str) and len(term.strip()) >= SOURCE_DIVERSITY_KEYWORD_MIN_LEN:
                    carriers.setdefault(term.strip().lower(), set()).add(sid)
    query_lower = query_text.lower()
    exempt: set[str] = set()
    for term, sids in carriers.items():
        if len(sids) <= SOURCE_DIVERSITY_KEYWORD_MAX_SOURCES and re.search(
            r"(?<!\w)" + re.escape(term) + r"(?!\w)", query_lower
        ):
            exempt |= sids
    return exempt


def _ensure_term_hits(ids, documents, metadatas, embedding, text, top_k, trim_repeats=False):
    forced = []
    for term in _question_terms(text):
        if any(term.lower() in doc.lower() for doc in documents + [f[1] for f in forced]):
            continue
        hits = vectorstore.query(embedding, top_k=1, where_document={"$contains": term})
        if hits["ids"][0]:
            forced.append((hits["ids"][0][0], hits["documents"][0][0], hits["metadatas"][0][0]))
    if not forced:
        return ids, documents, metadatas
    if trim_repeats:
        # Idee 3c32da30: zuerst überzählige Chunks mehrfach vertretener
        # Quellen (schlechtester zuerst) opfern, erst danach von hinten.
        kept = list(range(len(ids)))
        q_terms = [t.lower() for t in _question_terms(text)]
        for _ in range(max(0, len(ids) - (top_k - len(forced)))):
            if not kept:
                break
            counts = {}
            for i in kept:
                key = _diversity_key(metadatas[i])
                counts[key] = counts.get(key, 0) + 1
            # Einziger Träger eines Frage-Begriffs wird nicht geopfert.
            sole = {
                only[0] for t in q_terms
                if len(only := [i for i in kept if t in documents[i].lower()]) == 1
            }
            repeated = [i for i in kept if counts[_diversity_key(metadatas[i])] > 1 and i not in sole]
            kept.remove(repeated[-1] if repeated else kept[-1])
        return (
            [ids[i] for i in kept] + [f[0] for f in forced],
            [documents[i] for i in kept] + [f[1] for f in forced],
            [metadatas[i] for i in kept] + [f[2] for f in forced],
        )
    keep = min(len(ids), top_k - len(forced))
    return (
        ids[:keep] + [f[0] for f in forced],
        documents[:keep] + [f[1] for f in forced],
        metadatas[:keep] + [f[2] for f in forced],
    )


def _rerank_by_relevance(
    ids: list[str],
    documents: list[str],
    metadatas: list[dict],
    distances: list[float],
    sources: dict,
    top_k: int,
    max_per_source: int = 0,
    exempt_source_ids: set[str] | None = None,
    question_terms: list[str] | None = None,
) -> tuple[list[str], list[str], list[dict]]:
    def relevance_factor(source_id: str) -> float:
        score = sources.get(source_id, {}).get("relevance_score")
        score = score if score is not None else 5
        return 1 - main.RELEVANCE_MAX_ADJUSTMENT * (score - 5) / 5

    def score(i: int) -> float:
        return distances[i] * relevance_factor(metadatas[i]["source_id"])

    # Backlog (2026-09-25): derselbe Text kann mehrfach im Pool stehen
    # (doppelt importierte Quelle, kuratiert + Web-Index) und belegte dann
    # mehrere der wenigen Plätze - nur das erste (beste) Vorkommen zählt.
    ranked = []
    seen_texts = set()
    for i in sorted(range(len(ids)), key=score):
        text_key = " ".join(documents[i].split())
        if text_key in seen_texts:
            continue
        seen_texts.add(text_key)
        ranked.append(i)
    order = ranked[:top_k]
    if max_per_source > 0 and top_k > max_per_source:
        order = _diversify(
            order, ranked[top_k:], metadatas, documents, score, max_per_source,
            exempt_source_ids or set(), question_terms or [],
        )
    return (
        [ids[i] for i in order],
        [documents[i] for i in order],
        [metadatas[i] for i in order],
    )


def _diversify(order, reserve, metadatas, documents, score, max_per_source, exempt, question_terms):
    """Idee 3c32da30: siehe Kommentar bei SOURCE_DIVERSITY_*. Tauscht
    überzählige Chunks einer Quelle gegen Chunks noch nicht vertretener Quellen."""
    key = lambda i: _diversity_key(metadatas[i])
    # Pro Frage-Begriff schützt der erste Chunk (beste Platzierung), der ihn enthält.
    protected = set()
    for term in question_terms:
        first = next((i for i in order if term.lower() in documents[i].lower()), None)
        if first is not None:
            protected.add(first)
    counts = {}
    author_counts = {}
    candidates = []
    for i in order:
        if metadatas[i]["source_id"] in exempt:
            continue
        counts[key(i)] = counts.get(key(i), 0) + 1
        over_limit = counts[key(i)] > max_per_source
        for author in _author_keys(metadatas[i]):
            author_counts[author] = author_counts.get(author, 0) + 1
            over_limit = over_limit or author_counts[author] > max_per_source
        if over_limit and i not in protected:
            candidates.append(i)
    order = list(order)
    present = {key(i) for i in order}
    is_web = lambda i: bool(metadatas[i].get("is_web_fallback"))
    # Je neuer Quelle zählt nur ihr bester Ausschnitt.
    best_per_key = {}
    for r in sorted(reserve, key=score):
        if key(r) not in present and metadatas[r]["source_id"] not in exempt:
            best_per_key.setdefault(key(r), r)
    kept = [i for i in order if i not in candidates]
    author_load = {}
    for i in kept:
        for author in _author_keys(metadatas[i]):
            author_load[author] = author_load.get(author, 0) + 1
    max_score = max((score(c) for c in candidates), default=0) * (1 + main.SOURCE_DIVERSITY_MAX_DISTANCE_INCREASE) + 1e-12
    # Neue Autor:innen zuerst, dann kuratierte vor Web, dann der Score.
    successors = []
    for r in sorted(
        best_per_key.values(),
        key=lambda r: (any(a in author_load for a in _author_keys(metadatas[r])), is_web(r), score(r)),
    ):
        r_authors = _author_keys(metadatas[r])
        if (
            score(r) > max_score
            or any(author_load.get(a, 0) >= max_per_source for a in r_authors)
        ):
            continue
        successors.append(r)
        for author in r_authors:
            author_load[author] = author_load.get(author, 0) + 1
    candidates = sorted(candidates, key=score)

    def allowed(cand, succ):
        limit = score(cand) * (1 + main.SOURCE_DIVERSITY_MAX_DISTANCE_INCREASE) + 1e-12
        # Web ersetzt nie einen kuratierten Chunk.
        return score(succ) <= limit and (is_web(cand) or not is_web(succ))

    # Möglichst viele Täusche: die k schlechtesten Kandidaten gegen die k besten
    # Nachrücker, aufsteigend gepaart.
    swaps = []
    for k in range(min(len(candidates), len(successors)), 0, -1):
        pairs = list(zip(candidates[-k:], sorted(successors[:k], key=lambda r: (is_web(r), score(r)))))
        if all(allowed(c, r) for c, r in pairs):
            swaps = pairs
            break
    log = logging.getLogger("app.main")
    for cand in candidates[: len(candidates) - len(swaps)]:
        log.info("Quellen-Vielfalt: kein Nachrücker für %s", metadatas[cand]["source_id"])
    for cand, pick in swaps:
        log.info(
            "Quellen-Vielfalt: Tausch %s -> %s, Distanzzuwachs %.1f %%",
            metadatas[cand]["source_id"], metadatas[pick]["source_id"],
            (score(pick) / score(cand) - 1) * 100 if score(cand) else 0.0,
        )
        order[order.index(cand)] = pick
    return sorted(order, key=score)


# Nutzerwunsch (2026-09-01): einheitlicher Ausschluss für alle drei
# Fragen-Log-Ereignistypen (first_question/no_answer/feedback) - vorher nur
# inline beim first_question-Fall geprüft (Backlog #97), jetzt hier
# extrahiert, damit _ask_event_stream (no_answer) und /api/answer-feedback
# (feedback) dieselbe Regel verwenden. Ausgeschlossen: Dev/Stabil
# (IS_DEV_ENVIRONMENT ist dort identisch gesetzt, siehe .env) und der
# System-Admin selbst - Quellen-Pfleger:innen werden bewusst NICHT
# ausgeschlossen (ihre eigene Nutzung bleibt ein sinnvolles Signal).
def _should_log_question_event(request: Request) -> bool:
    return not main.IS_DEV_ENVIRONMENT and not users.has_role(
        main._get_current_user_email(request), users.SYSTEM_ADMIN
    )


# Nutzerwunsch (2026-09-01): Grundlage für das "no_answer"-Ereignis im
# Fragen-Log - die Systemanweisung (siehe app/llm.py: SYSTEM_PROMPTS) gibt
# dem Modell diesen Satz WÖRTLICH vor, wenn die bereitgestellten
# Textausschnitte GAR NICHTS zur Frage hergeben (seit 2026-09-24 nicht mehr
# bei Teilantworten - dort kam der Satz als enttäuschender Einstieg vor
# einer echten Antwort, Nutzerwunsch). Ein reiner
# Substring-Check reicht deshalb aus (kein separates Konfidenz-Signal
# nötig) - siehe _ask_event_stream unten.
NO_ANSWER_PHRASES = {
    "de": "Die vorliegende Quellenlage gibt darauf keine Antwort.",
    "en": "The available sources do not answer this.",
}

# Nutzerwunsch (2026-09-25): steht der Absage-Satz ALLEIN, sehen Nutzer:innen
# statt des knappen Satzes diese freundliche Erklärung. Der Satz selbst bleibt
# der Marker (Prompt, Fragen-Log) - ins Fragen-Log geht weiter der kurze Satz.
NO_ANSWER_EXPLANATIONS = {
    "de": (
        "Dazu habe ich in den kuratierten Quellen leider nichts gefunden.\n\n"
        "Ich antworte bewusst nur auf Basis der hinterlegten Texte zum Beta-Kodex, "
        "damit jede Aussage belegt ist – steht dort nichts Passendes, rate ich lieber nicht.\n\n"
        "Was helfen kann:\n"
        "- **Anders formulieren** – mit Begriffen, die im Beta-Kodex üblich sind, "
        "z. B. „Gesetze“ statt „Prinzipien“ oder „Zellstruktur“ statt „Teamorganisation“.\n"
        "- **Konkreter fragen** – ein bestimmtes Konzept, eine Autorin oder einen Autor nennen.\n"
        "- **Quellen erkunden** – in der [Quellenübersicht](/import.html) oder im "
        "[Explore-Modus](/explore.html) sehen, welche Themen abgedeckt sind."
    ),
    "en": (
        "Unfortunately, I couldn't find anything on this in the curated sources.\n\n"
        "I deliberately answer only based on the stored BetaCodex texts so that every "
        "statement is backed up – if nothing there fits, I'd rather not guess.\n\n"
        "What can help:\n"
        "- **Rephrase** – use terms common in the BetaCodex, "
        "e.g. “laws” instead of “principles” or “cell structure” instead of “team organization”.\n"
        "- **Be more specific** – name a particular concept or author.\n"
        "- **Explore the sources** – see which topics are covered in the "
        "[source overview](/import.html) or the [Explore mode](/explore.html)."
    ),
}


# Nutzerwunsch (2026-09-24): Das Modell stellt den Absage-Satz trotz
# Anweisung manchmal einer echten (Teil-)Antwort voran ("Die vorliegende
# Quellenlage gibt darauf keine Antwort." + Inhalt) - eine enttäuschende
# Einleitung. Folgt dem Satz noch Text, fällt er in der Anzeige weg; steht er
# allein, bleibt er. Solange das noch offen ist, wird er im Stream
# zurückgehalten (pending=True). Das no_answer-Ereignis im Fragen-Log prüft
# weiterhin den Rohtext - für die Lückenanalyse zählt auch die Teilantwort.
def _drop_no_answer_lead(text: str, final: bool) -> tuple[str, bool]:
    stripped = text.lstrip()
    for lang, phrase in NO_ANSWER_PHRASES.items():
        if stripped.startswith(phrase):
            rest = stripped[len(phrase):].lstrip()
            if rest:
                return rest, False
            return (NO_ANSWER_EXPLANATIONS[lang], False) if final else ("", True)
        if stripped and phrase.startswith(stripped) and not final:
            return "", True
    return text, False


# Obergrenze der Belegstellen, die restricted-Quellen an Nicht-Pfleger:innen preisgeben.
RESTRICTED_EXCERPT_MAX_PASSAGES = 2
RESTRICTED_EXCERPT_MAX_CHARS = 300


def _chunk_images(meta: dict, is_web_fallback: bool = False, lang: str = i18n.DEFAULT_LANG) -> list[ImageRef]:
    """Bilder eines Chunks aus seinen Metadaten (Idee ff895248). Nur https-
    `url` oder gültiger `file`-Name; alles Kaputte ergibt []. Web-Fallback-
    Chunks bekommen nie Bilder, von der KI-Prüfung als Deko erkannte
    (relevant=False) auch nicht. Alt-Text: KI-Beschreibung in `lang`, sonst
    der ursprüngliche."""
    if is_web_fallback:
        return []
    try:
        items = json.loads(meta.get("images_json") or "[]")
    except (ValueError, TypeError):
        return []
    result = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("relevant") is False:
            continue
        if item.get("kind") == "url" and source_images.is_safe_https(item.get("url")):
            src = source_images.upgrade_image_url(item["url"])
        elif (
            item.get("kind") == "file"
            and isinstance(item.get("file"), str)
            and source_images.IMAGE_NAME_RE.match(item["file"])
            and meta.get("source_id")
        ):
            src = f"/api/sources/{meta['source_id']}/images/{item['file']}"
        else:
            continue
        page = item.get("page")
        result.append(
            ImageRef(
                src=src,
                alt=str(item.get(f"alt_{lang}") or item.get("alt") or "")[: source_images.ALT_MAX],
                page=page if isinstance(page, int) and not isinstance(page, bool) else None,
            )
        )
    return result


FALLBACK_IMAGES_PER_SOURCE = 2


def _apply_chunk_images(
    refs: list, metas: list[dict], sources: dict | None = None, lang: str = i18n.DEFAULT_LANG
) -> None:
    """Setzt `images` je ChunkRef aus den Chunk-Metadaten (nie aus Client-
    Angaben). Die restricted-Grenze folgt separat in _limit_restricted_images.
    Quellen-Fallback (Idee fe44f080): hat der erste Ref einer Quelle kein
    eigenes Bild, bekommt er höchstens 2 Bilder aus der Quelle selbst -
    zuerst solche, die an keinem Chunk hängen; keine src doppelt."""
    for ref, meta in zip(refs, metas):
        ref.images = _chunk_images(meta, ref.is_web_fallback, lang)
    used = {image.src for ref in refs for image in ref.images}
    handled: set[str] = set()
    for ref in refs:
        if ref.is_web_fallback or ref.source_id in handled:
            continue
        handled.add(ref.source_id)
        entry_images = (sources or {}).get(ref.source_id, {}).get("images")
        if ref.images or not isinstance(entry_images, list):
            continue
        candidates = _chunk_images({"images_json": json.dumps(entry_images), "source_id": ref.source_id}, lang=lang)
        on_chunks = {
            image.src
            for chunk_meta in vectorstore.get_source_chunks(ref.source_id)[2]
            for image in _chunk_images({**chunk_meta, "source_id": ref.source_id})
        }
        candidates.sort(key=lambda image: image.src in on_chunks)  # stabil: Quellreihenfolge bleibt
        fallback = [image for image in candidates if image.src not in used][:FALLBACK_IMAGES_PER_SOURCE]
        ref.images = [image.model_copy(update={"from_source": True}) for image in fallback]
        used.update(image.src for image in fallback)


def _limit_restricted_images(refs: list, sources: dict, priority: list[int] | None = None) -> list[list]:
    """Je restricted-Quelle höchstens 1 Bild über ALLE übergebenen Refs.
    Das Bild geht an den ersten Ref der Quelle in `priority`-Reihenfolge
    (danach Rangfolge). Liefert die Bildlisten je Ref, ändert die Refs nicht."""
    order = list(dict.fromkeys(priority or [])) + [i for i in range(len(refs)) if i not in set(priority or [])]
    result: list[list] = [list(ref.images) for ref in refs]
    used: set[str] = set()
    for i in order:
        source_id = refs[i].source_id
        if not result[i] or not sources.get(source_id, {}).get("restricted"):
            continue
        if source_id in used:
            result[i] = []
        else:
            result[i] = result[i][:1]
            used.add(source_id)
    return result


def _with_images(refs: list, image_lists: list[list]) -> list:
    return [ref.model_copy(update={"images": images}) for ref, images in zip(refs, image_lists)]


def _redact_restricted_refs(refs, sources: dict, can_view_full_text: bool) -> list:
    """Geschützte (restricted) Quellen verbergen nicht nur den Volltext,
    sondern auch Chunk-Auszüge: für Nicht-Pfleger:innen bleibt nur die
    markierte Belegstelle (leer, solange noch keine Hervorhebung feststeht).
    Das Modell bekommt intern weiter den vollen Chunk."""
    if can_view_full_text:
        return list(refs)
    out = []
    for ref in refs:
        if sources.get(ref.source_id, {}).get("restricted"):
            passages = [
                h if len(h) <= RESTRICTED_EXCERPT_MAX_CHARS else h[:RESTRICTED_EXCERPT_MAX_CHARS] + "…"
                for h in ref.highlighted_texts[:RESTRICTED_EXCERPT_MAX_PASSAGES]
            ]
            ref = ref.model_copy(update={"text": " … ".join(passages)})
        out.append(ref)
    return out
