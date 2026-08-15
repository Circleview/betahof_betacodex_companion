"""Backlog: LLM/Internet-Fallback bei dünner Quellenlage - periodische
Indizierung der in app/web_allowlist.py freigegebenen Domains/Pfade.

Läuft AUSSCHLIESSLICH im wöchentlichen Hintergrund-Worker (siehe
app/main.py: _web_allowlist_crawl_worker), niemals zur Antwortzeit -
app/main.py:ask() liest nur die hier bereits fertig indizierte Chroma-
Collection (vectorstore.query_web). So löst der Fallback nie eine Live-
Netzwerk-Anfrage nach außen aus, die die Antwortzeit einer laufenden
Konversation verzögern könnte (Nutzerwunsch: "Dieser zusätzliche Lauf
muss sehr schnell gehen").
"""
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import trafilatura.sitemaps

from app import chunking, embeddings, extraction, vectorstore, web_allowlist, web_candidates, web_index

# Nutzerfeedback (real reproduziert): trafilatura.sitemaps.sitemap_search()/
# extraction.extract_from_url() können für bestimmte Websites unbegrenzt
# hängen bleiben, wenn sie in einem Python-Thread statt dem Hauptthread des
# Prozesses laufen (nachgestellt für sichtart.at: im Hauptthread sofortiges
# Ergebnis, im simplen threading.Thread >20s ohne Rückkehr - vermutlich eine
# Threading-Eigenheit der zugrunde liegenden Netzwerk-Bibliotheken bei
# bestimmten Websites). Ein Timeout INNERHALB desselben Prozesses (z.B. über
# einen weiteren ThreadPoolExecutor) verschiebt das Problem nur eine Ebene
# tiefer, statt es zu lösen - der eigentliche Aufruf würde im ThreadPool-
# Worker-Thread genauso hängen. Der wirksame Schutz liegt deshalb NICHT mehr
# hier, sondern eine Ebene höher: app/main.py:_index_web_allowlist_entry_
# with_status() lagert index_entry() komplett in einen eigenen Unterprozess
# aus (app/web_crawl_subprocess.py) - ein Betriebssystem-Prozess hat immer
# einen echten Hauptthread, UND ein hängender Kindprozess lässt sich (anders
# als ein hängender Thread) vom Elternprozess zuverlässig per Timeout
# abbrechen.
# Obergrenze für einen einzelnen index_entry()-Aufruf insgesamt - schützt vor
# vielen langsamen Seitenabrufen einer sehr großen Website. Nicht erreichte
# Seiten werden beim nächsten planmäßigen Lauf automatisch nachgeholt
# (bereits indizierte/vorgeschlagene werden ja übersprungen, siehe
# existing_urls/known_urls unten).
CRAWL_TIME_BUDGET_SECONDS = 120

# Nutzerentscheidung (Design-Gespräch zur Positivselektion): liefert die
# reguläre Erkennung (url_prefix + post-sitemap.xml) nur eine Handvoll (<=2)
# eindeutig zuordenbarer Seiten, reicht das nicht für eine automatische
# Indizierung - die Website hat vermutlich keine klar abgrenzbare
# Quellenstruktur (z.B. flache WordPress-Permalinks ohne gemeinsamen
# Unterpfad, siehe sichtart.at). Statt automatisch zu indizieren und
# nachträglich zu bereinigen ("Negativselektion"), wechselt index_entry()
# dann automatisch zur Positivselektion (siehe _run_positive_selection) -
# für Quellen-Pfleger:innen unsichtbar, sie sehen nur das Ergebnis
# (WebAllowlistEntryOut.selection_mode).
POSITIVE_SELECTION_MAX_DISCOVERED = 2

# Nutzerwunsch: nur Titel+Kurztext pro Kandidat speichern (kein Volltext) -
# reicht für die Ranking-Anzeige, hält data/web_candidates.json auch bei
# hunderten Kandidaten klein. Der echte Volltext wird erst bei Freigabe neu
# geholt (siehe index_approved_candidate).
CANDIDATE_SNIPPET_LENGTH = 300


def _sitemap_urls(url: str) -> list[str]:
    try:
        return trafilatura.sitemaps.sitemap_search(url)
    except Exception:
        return []


def _post_sitemap_url(url_prefix: str) -> str:
    parsed = urlparse(url_prefix)
    return urljoin(f"{parsed.scheme}://{parsed.netloc}/", "post-sitemap.xml")


def _url_path_matches_prefix(url: str, url_prefix: str) -> bool:
    """Nutzerfeedback (real reproduziert für sichtart.at ohne "www."): eine
    Sitemap listet ihre URLs in EINER kanonischen Form (z.B. immer mit
    "www."), unabhängig davon, mit welcher Host-Schreibweise man die
    Sitemap selbst abgerufen hat. Ein wörtlicher Vergleich des kompletten
    eingegebenen url_prefix ("https://sichtart.at/...") gegen solche
    kanonischen URLs ("https://www.sichtart.at/...") schlägt dann für JEDE
    URL fehl - _discover_urls fiel deshalb komplett auf die ungefilterte
    volle Sitemap-Suche zurück (wieder Archivseiten statt Artikel, siehe
    Kommentar dort). Vergleicht deshalb nur den Pfad-Teil, unabhängig von
    Protokoll/Subdomain-Schreibweise - beide URLs gehören ohnehin zur
    selben Website, da post-sitemap.xml bereits anhand von url_prefix
    abgerufen wurde."""
    return urlparse(url).path.startswith(urlparse(url_prefix).path)


def _discover_urls(url_prefix: str) -> list[str]:
    """Nutzerwunsch (real reproduziert für sichtart.at): die vollständige
    sitemap_search() mischt bei vielen WordPress-Sites tausende automatisch
    generierte Archivseiten (Events, Tags, Orte, Kategorien) MIT den
    eigentlichen Artikeln - bei sichtart.at etwa 3488 Gesamt-URLs, davon nur
    ~410 echte Beiträge, dazu noch in beliebiger Reihenfolge. Ergebnis: das
    max_pages-Budget wurde komplett von Archivseiten verbraucht, bevor auch
    nur ein echter Artikel dabei war. Die WordPress-Konvention post-
    sitemap.xml enthält NUR echte Beiträge - wird hier bevorzugt versucht,
    mit Fallback auf die bisherige vollständige sitemap_search() (z.B. für
    Nicht-WordPress-Sites). sitemap_search filtert dabei bereits auf
    Unterseiten innerhalb url_prefix, SOFERN url_prefix keine reine Domain-
    Startseite ist - genau das erlaubt Sektions-Freigaben wie ".../blog",
    ohne die gesamte Domain zu indizieren."""
    urls = [u for u in _sitemap_urls(_post_sitemap_url(url_prefix)) if _url_path_matches_prefix(u, url_prefix)]
    if not urls:
        urls = _sitemap_urls(url_prefix)
    return urls


def discover_candidate_urls(url_prefix: str) -> list[str]:
    """Für die Positivselektion (siehe _run_positive_selection): alle
    Kandidaten-URLs der GESAMTEN Website, bewusst OHNE Filterung auf
    url_prefix - genau der (offenbar nicht tragfähige) Prefix hat ja dazu
    geführt, dass _discover_urls() zu wenig gefunden hat. Bevorzugt weiterhin
    post-sitemap.xml gegenüber der vollständigen Sitemap (siehe
    _discover_urls-Kommentar)."""
    urls = _sitemap_urls(_post_sitemap_url(url_prefix))
    if not urls:
        urls = _sitemap_urls(url_prefix)
    return urls


def _is_placeholder_text(text: str) -> bool:
    """Nutzerfeedback (real reproduziert für sichtart.at): manche WordPress-
    Websites räumen mitgelieferte Theme-Demo-Beiträge (Beispiel-Blogposts,
    die mit dem Theme installiert werden, um verschiedene Beitragsformate
    vorzuführen) nie auf - inhaltlich reiner Lorem-Ipsum-Platzhaltertext,
    aber technisch nicht von echten Artikeln unterscheidbar (normale
    /beitrag-slug/-URL, im post-sitemap.xml gelistet). Ranking gegen den
    Quellenbestand (siehe _relevance_score_against_curated_corpus) reicht
    hier NICHT: Lorem Ipsum landete dort nur wenige Prozentpunkte unter
    echten Artikeln (Anisotropie von Embedding-Räumen, siehe Diskussion) -
    für Nutzer:innen macht das trotzdem keinen Sinn ("selbst wenn es
    mathematisch korrekt ist"). Lorem Ipsum ist dagegen ein eindeutiges,
    deterministisches Textmuster - ein einfacher Substring-Check reicht,
    ohne jedes Risiko eines Fehlalarms bei echtem deutschen/englischen
    Inhalt."""
    return "lorem ipsum" in text[:1000].lower()


def _index_single_page(entry_id: str, url: str, now: str) -> bool:
    try:
        result = extraction.extract_from_url(url)
    except Exception:
        return False
    text = result.get("text", "").strip()
    if not text or _is_placeholder_text(text):
        return False
    chunks = chunking.chunk_text(text)
    if not chunks:
        return False

    page_id = str(uuid.uuid4())
    title = result.get("title") or url
    # Nutzerfeedback (real reproduziert für flipping-points.org/Jan Krims):
    # extraction.extract_from_url() liefert bereits per-Seite extrahierte
    # Autor:innen (trafilatura, siehe app/extraction.py), wurden hier aber
    # bisher verworfen - app/main.py:ask() zeigte Web-Fallback-Zitate dem
    # Sprachmodell deshalb immer als "Autor: unbekannt", auch wenn die Seite
    # eindeutig einer Person zuzuordnen war ("Jan Krims" wurde von
    # trafilatura korrekt erkannt). Das Modell verweigerte dadurch berechtigt
    # eine Antwort auf ausdrücklich autor:innen-bezogene Fragen ("...nach Jan
    # Krims?"), obwohl der Inhalt selbst vorlag. Gleiches Muster wie bei
    # kuratierten Quellen (siehe app/main.py:_store_chunks): ChromaDB-
    # Metadata-Listen dürfen nicht leer sein, daher den Schlüssel bei keinem
    # erkannten Autor ganz weglassen statt "authors": [].
    authors = result.get("authors") or []
    chunk_ids = [f"{page_id}::{i}" for i in range(len(chunks))]
    metadatas = []
    for i in range(len(chunks)):
        metadata = {
            "page_id": page_id,
            "allowlist_entry_id": entry_id,
            "url": url,
            "title": title,
            "position": i,
        }
        if authors:
            metadata["authors"] = authors
        metadatas.append(metadata)
    chunk_embeddings = embeddings.embed_passages(chunks)
    vectorstore.add_web_chunks(chunk_ids, chunks, chunk_embeddings, metadatas)
    web_index.upsert_page(
        page_id,
        allowlist_entry_id=entry_id,
        url=url,
        title=title,
        date=result.get("date") or None,
        indexed_at=now,
        chunk_count=len(chunks),
    )
    return True


def _relevance_score_against_curated_corpus(title: str, snippet: str) -> float:
    """Nutzerentscheidung: Relevanz eines Kandidaten wird NICHT gegen das
    reason-Feld des Allowlist-Eintrags bewertet, sondern gegen den
    gesamten bestehenden kuratierten Quellenbestand - so dürfen Quellen
    über die Zeit in neue inhaltliche Bereiche hineinwachsen, ohne dass die
    Grundidee des Beta-Kodex im Companion verwässert wird. Rein lokales
    Embedding (siehe app/embeddings.py), keine API-Kosten. Distanz wird in
    einen Score umgerechnet (höher = relevanter), damit die Anzeige
    "absteigend nach Relevanz sortiert" intuitiv bleibt."""
    embedding = embeddings.embed_query(f"{title}. {snippet}")
    try:
        hits = vectorstore.query(embedding, top_k=1)
    except Exception:
        return 0.0
    distances = hits.get("distances") or [[]]
    if not distances[0]:
        return 0.0
    return 1.0 / (1.0 + distances[0][0])


def _run_positive_selection(entry_id: str, url_prefix: str) -> int:
    """Nutzerwunsch: statt automatisch zu indizieren, werden Kandidaten-
    Unterseiten gegen den bestehenden Quellenbestand bewertet und zur
    manuellen Freigabe abgelegt (siehe app/web_candidates.py). Gibt die
    Anzahl NEU hinzugefügter Kandidaten zurück (bereits bekannte URLs -
    egal ob schon indiziert oder schon vorgeschlagen - werden
    übersprungen, damit wiederholte wöchentliche Läufe nur Neues
    ergänzen, keine bereits entschiedenen Kandidaten zurückholen)."""
    web_allowlist.set_selection_mode(entry_id, "positiv")
    urls = discover_candidate_urls(url_prefix)
    if not urls:
        return 0

    known_urls = {p["url"] for p in web_index.pages_for_entry(entry_id).values()}
    known_urls |= {c["url"] for c in web_candidates.candidates_for_entry(entry_id, status=None).values()}

    added_count = 0
    deadline = time.monotonic() + CRAWL_TIME_BUDGET_SECONDS
    for url in urls:
        if time.monotonic() > deadline:
            break
        if url in known_urls:
            continue
        try:
            result = extraction.extract_from_url(url)
        except Exception:
            continue
        text = result.get("text", "").strip()
        if not text or _is_placeholder_text(text):
            continue
        title = result.get("title") or url
        snippet = text[:CANDIDATE_SNIPPET_LENGTH]
        candidate = {
            "url": url,
            "title": title,
            "snippet": snippet,
            "relevance_score": _relevance_score_against_curated_corpus(title, snippet),
        }
        # Nutzerfeedback (real reproduziert): die Positivselektion braucht
        # pro Kandidat zusätzlich ein Embedding + eine Vectorstore-Abfrage
        # (siehe oben) - bei vielen Kandidaten kann der äußere Unterprozess-
        # Timeout (app/main.py:WEB_ALLOWLIST_SUBPROCESS_TIMEOUT_SECONDS)
        # greifen, BEVOR diese Funktion überhaupt fertig ist. Wurden
        # Kandidaten erst ganz am Ende gesammelt gespeichert, gingen dabei
        # ALLE bereits gefundenen verloren - jetzt wird jeder Kandidat
        # sofort gespeichert, sodass ein Abbruch nur die noch nicht
        # erreichten URLs kostet, nicht den bisherigen Fortschritt.
        web_candidates.upsert_candidates(entry_id, [candidate])
        added_count += 1

    return added_count


def index_entry(entry_id: str, url_prefix: str, max_pages: int) -> int:
    """Crawlt/indiziert bis zu max_pages noch unbekannte Unterseiten
    innerhalb url_prefix, gibt die Anzahl neu indizierter Seiten zurück.
    Bereits bekannte URLs (siehe web_index.pages_for_entry) werden
    übersprungen - ein wöchentlicher Lauf muss nicht jedes Mal die
    komplette Sektion neu einlesen, nur das seither Hinzugekommene.
    Aus der Sitemap verschwundene alte Seiten werden bewusst NICHT
    automatisch entfernt (das würde echten Inhalt löschen, nur weil eine
    Sitemap sich geändert hat) - Bereinigung bleibt der jährlichen
    menschlichen Prüfung des Allowlist-Eintrags vorbehalten.

    Liefert die reguläre Erkennung zu wenige Seiten, wird stattdessen auf
    Positivselektion umgeschaltet (siehe _run_positive_selection) - der
    Rückgabewert ist dann die Anzahl neuer KANDIDATEN, nicht indizierter
    Seiten (0 tatsächlich indizierte Seiten in diesem Lauf)."""
    urls = _discover_urls(url_prefix)
    if len(urls) <= POSITIVE_SELECTION_MAX_DISCOVERED:
        return _run_positive_selection(entry_id, url_prefix)
    web_allowlist.set_selection_mode(entry_id, "negativ")

    existing_urls = {p["url"] for p in web_index.pages_for_entry(entry_id).values()}
    now = datetime.now(timezone.utc).isoformat()

    indexed_count = 0
    deadline = time.monotonic() + CRAWL_TIME_BUDGET_SECONDS
    for url in urls[:max_pages]:
        if time.monotonic() > deadline:
            break
        if url in existing_urls:
            continue
        if _index_single_page(entry_id, url, now):
            indexed_count += 1

    return indexed_count


def index_approved_candidate(entry_id: str, url: str) -> bool:
    """Nutzerwunsch (Positivselektion): eine von Hand bestätigte Kandidaten-
    Unterseite wird jetzt tatsächlich indiziert - nutzt dieselbe Extract/
    Chunk/Embed-Pipeline wie der normale Crawl (_index_single_page), damit
    beide Wege identisch behandelte, zitierfähige Seiten erzeugen. Holt den
    Volltext bewusst neu (statt den beim Ranking gespeicherten Kurztext zu
    nutzen) - so bleibt data/web_candidates.json klein, und eine
    zwischenzeitlich geänderte Seite wird mit aktuellem Inhalt indiziert."""
    now = datetime.now(timezone.utc).isoformat()
    return _index_single_page(entry_id, url, now)
