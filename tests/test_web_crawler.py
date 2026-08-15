import trafilatura.sitemaps

from app import embeddings, extraction, vectorstore, web_allowlist, web_candidates, web_crawler, web_index

# POSITIVE_SELECTION_MAX_DISCOVERED ist 2 - Sitemap-Fixtures unten mit mehr
# als 2 URLs testen bewusst den normalen ("negativ") Indizierungspfad, mit
# hoechstens 2 URLs den neuen Positivselektions-Pfad (siehe eigene Tests
# weiter unten).
MANY_URLS = [f"https://beispiel.org/{i}" for i in range(5)]


def test_index_entry_indexes_each_discovered_url(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    monkeypatch.setattr(
        trafilatura.sitemaps,
        "sitemap_search",
        lambda url, **kw: ["https://beispiel.org/a", "https://beispiel.org/b", "https://beispiel.org/c"],
    )
    pages = {
        "https://beispiel.org/a": {"title": "Seite A", "text": "Inhalt A zur Organisation."},
        "https://beispiel.org/b": {"title": "Seite B", "text": "Inhalt B zur Führung."},
        "https://beispiel.org/c": {"title": "Seite C", "text": "Inhalt C zur Struktur."},
    }
    monkeypatch.setattr(extraction, "extract_from_url", lambda url: pages[url])
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    count = web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=10)

    assert count == 3
    indexed_pages = web_index.pages_for_entry("entry-1")
    assert {p["url"] for p in indexed_pages.values()} == set(pages)
    assert {p["title"] for p in indexed_pages.values()} == {"Seite A", "Seite B", "Seite C"}


def test_index_entry_stores_extracted_date_per_page(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", lambda url, **kw: MANY_URLS)
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {"title": "Seite A", "date": "2026-03-01", "text": "Inhalt A."},
    )
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=1)

    page = list(web_index.pages_for_entry("entry-1").values())[0]
    assert page["date"] == "2026-03-01"


def test_index_entry_stores_extracted_authors_in_chunk_metadata(tmp_path, monkeypatch):
    # Nutzerfeedback (real reproduziert für flipping-points.org/Jan Krims):
    # trafilatura extrahiert Autor:innen bereits zuverlässig (siehe
    # extraction.extract_from_url), sie wurden beim Indizieren aber
    # verworfen - app/main.py:ask() zeigte Web-Fallback-Zitate dem
    # Sprachmodell deshalb immer als "Autor: unbekannt", selbst wenn die
    # Seite eindeutig einer Person zuzuordnen war. Das Modell verweigerte
    # dadurch berechtigt eine Antwort auf ausdrücklich autor:innen-bezogene
    # Fragen ("...nach Jan Krims?").
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", lambda url, **kw: MANY_URLS)
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {"title": "Seite A", "authors": ["Jan Krims"], "text": "Inhalt A."},
    )
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=1)

    collection = vectorstore._get_web_collection()
    res = collection.get(where={"allowlist_entry_id": "entry-1"})
    assert res["metadatas"][0]["authors"] == ["Jan Krims"]


def test_index_entry_omits_authors_key_when_none_extracted(tmp_path, monkeypatch):
    # ChromaDB-Metadata-Listen dürfen nicht leer sein (siehe
    # app/main.py:_store_chunks) - der Schlüssel muss bei keinem erkannten
    # Autor ganz weggelassen werden statt "authors": [].
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", lambda url, **kw: MANY_URLS)
    monkeypatch.setattr(
        extraction, "extract_from_url", lambda url: {"title": "Seite A", "text": "Inhalt A."}
    )
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=1)

    collection = vectorstore._get_web_collection()
    res = collection.get(where={"allowlist_entry_id": "entry-1"})
    assert "authors" not in res["metadatas"][0]


def test_index_entry_skips_already_indexed_urls(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    web_index.upsert_page(
        "existing-page",
        allowlist_entry_id="entry-1",
        url="https://beispiel.org/0",
        title="Seite A",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", lambda url, **kw: MANY_URLS)
    extract_calls = []
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: extract_calls.append(url) or {"title": "Seite", "text": "Inhalt."},
    )
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    count = web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=1)

    assert count == 0
    assert extract_calls == []


def test_index_entry_respects_max_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", lambda url, **kw: MANY_URLS)
    monkeypatch.setattr(
        extraction, "extract_from_url", lambda url: {"title": url, "text": "Inhalt zum Thema."}
    )
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    count = web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=2)

    assert count == 2


def test_index_entry_skips_urls_with_empty_extracted_text(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", lambda url, **kw: MANY_URLS)
    monkeypatch.setattr(extraction, "extract_from_url", lambda url: {"title": "Leer", "text": ""})

    count = web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=10)

    assert count == 0
    assert web_index.pages_for_entry("entry-1") == {}


def test_index_entry_skips_urls_with_lorem_ipsum_placeholder_text(tmp_path, monkeypatch):
    # Nutzerfeedback (real reproduziert für sichtart.at): mitgelieferte
    # WordPress-Theme-Demo-Beiträge bestehen aus reinem Lorem-Ipsum-Text,
    # sind aber URL-technisch nicht von echten Artikeln unterscheidbar -
    # landeten deshalb trotz funktionierendem post-sitemap.xml-Fix
    # weiterhin unter den indizierten Seiten ("selbst wenn es mathematisch
    # korrekt ist, ergibt das aus Nutzersicht keinen Sinn").
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    monkeypatch.setattr(
        trafilatura.sitemaps,
        "sitemap_search",
        lambda url, **kw: [
            "https://beispiel.org/demo",
            "https://beispiel.org/echt",
            "https://beispiel.org/echt-2",
        ],
    )

    def fake_extract(url):
        if url.endswith("demo"):
            return {"title": "Demo-Beitrag", "text": "Lorem ipsum dolor sit amet, consetetur sadipscing elitr."}
        return {"title": "Echter Artikel", "text": "Ein echter Artikel über Selbstorganisation."}

    monkeypatch.setattr(extraction, "extract_from_url", fake_extract)
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    count = web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=10)

    assert count == 2
    pages = web_index.pages_for_entry("entry-1")
    assert {p["url"] for p in pages.values()} == {"https://beispiel.org/echt", "https://beispiel.org/echt-2"}


def test_index_entry_continues_after_extraction_error_for_one_url(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    monkeypatch.setattr(
        trafilatura.sitemaps,
        "sitemap_search",
        lambda url, **kw: ["https://beispiel.org/kaputt", "https://beispiel.org/ok1", "https://beispiel.org/ok2"],
    )

    def fake_extract(url):
        if url.endswith("kaputt"):
            raise RuntimeError("Netzwerkfehler")
        return {"title": "OK-Seite", "text": "Funktionierender Inhalt."}

    monkeypatch.setattr(extraction, "extract_from_url", fake_extract)
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    count = web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=10)

    assert count == 2
    pages = web_index.pages_for_entry("entry-1")
    assert {p["url"] for p in pages.values()} == {"https://beispiel.org/ok1", "https://beispiel.org/ok2"}


def test_index_entry_prefers_post_sitemap_over_full_sitemap_search(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    def fake_sitemap_search(url, **kw):
        if url == "https://beispiel.org/post-sitemap.xml":
            return ["https://beispiel.org/echter-artikel-1", "https://beispiel.org/echter-artikel-2", "https://beispiel.org/echter-artikel-3"]
        # Die volle Sitemap enthielte auch Archivseiten - darf nicht
        # verwendet werden, solange post-sitemap.xml etwas liefert.
        return ["https://beispiel.org/event-archiv/1"]

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", fake_sitemap_search)
    monkeypatch.setattr(
        extraction, "extract_from_url", lambda url: {"title": "Echter Artikel", "text": "Inhalt."}
    )
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=10)

    pages = web_index.pages_for_entry("entry-1")
    assert {p["url"] for p in pages.values()} == {
        "https://beispiel.org/echter-artikel-1",
        "https://beispiel.org/echter-artikel-2",
        "https://beispiel.org/echter-artikel-3",
    }


def test_index_entry_filters_post_sitemap_urls_by_url_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    def fake_sitemap_search(url, **kw):
        assert url == "https://beispiel.org/post-sitemap.xml"
        return [
            "https://beispiel.org/blog/a",
            "https://beispiel.org/blog/b",
            "https://beispiel.org/blog/c",
            "https://beispiel.org/andere-sektion/d",
        ]

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", fake_sitemap_search)
    monkeypatch.setattr(extraction, "extract_from_url", lambda url: {"title": "A", "text": "Inhalt."})
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    web_crawler.index_entry("entry-1", "https://beispiel.org/blog", max_pages=10)

    pages = web_index.pages_for_entry("entry-1")
    assert {p["url"] for p in pages.values()} == {
        "https://beispiel.org/blog/a",
        "https://beispiel.org/blog/b",
        "https://beispiel.org/blog/c",
    }


def test_index_entry_matches_post_sitemap_urls_despite_www_prefix_mismatch(tmp_path, monkeypatch):
    # Nutzerfeedback (real reproduziert für sichtart.at): eine Sitemap listet
    # ihre URLs in EINER kanonischen Form (hier: immer mit "www."), auch wenn
    # der eingegebene url_prefix das weglässt - ein wörtlicher String-
    # Präfix-Vergleich hätte hier ALLE URLs verworfen und wäre auf die volle,
    # ungefilterte Sitemap-Suche zurückgefallen (siehe Kommentar in
    # _url_path_matches_prefix).
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    def fake_sitemap_search(url, **kw):
        assert url == "https://beispiel.org/post-sitemap.xml"
        return [
            "https://www.beispiel.org/artikel-1",
            "https://www.beispiel.org/artikel-2",
            "https://www.beispiel.org/artikel-3",
        ]

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", fake_sitemap_search)
    monkeypatch.setattr(extraction, "extract_from_url", lambda url: {"title": "A", "text": "Inhalt."})
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    web_crawler.index_entry("entry-1", "https://beispiel.org/", max_pages=10)

    pages = web_index.pages_for_entry("entry-1")
    assert {p["url"] for p in pages.values()} == {
        "https://www.beispiel.org/artikel-1",
        "https://www.beispiel.org/artikel-2",
        "https://www.beispiel.org/artikel-3",
    }


def test_index_entry_falls_back_to_full_sitemap_when_post_sitemap_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    def fake_sitemap_search(url, **kw):
        if url == "https://beispiel.org/post-sitemap.xml":
            return []
        return MANY_URLS

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", fake_sitemap_search)
    monkeypatch.setattr(extraction, "extract_from_url", lambda url: {"title": "A", "text": "Inhalt."})
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=10)

    pages = web_index.pages_for_entry("entry-1")
    assert {p["url"] for p in pages.values()} == set(MANY_URLS)


def test_index_entry_falls_back_to_full_sitemap_when_post_sitemap_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    def fake_sitemap_search(url, **kw):
        if url == "https://beispiel.org/post-sitemap.xml":
            raise RuntimeError("404")
        return MANY_URLS

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", fake_sitemap_search)
    monkeypatch.setattr(extraction, "extract_from_url", lambda url: {"title": "A", "text": "Inhalt."})
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=10)

    pages = web_index.pages_for_entry("entry-1")
    assert {p["url"] for p in pages.values()} == set(MANY_URLS)


def test_index_entry_returns_zero_when_sitemap_search_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    def raise_error(url, **kw):
        raise RuntimeError("kein Netzwerk")

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", raise_error)

    count = web_crawler.index_entry("entry-1", "https://beispiel.org", max_pages=10)

    assert count == 0


def test_index_entry_sets_selection_mode_negativ_on_healthy_yield(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://beispiel.org", label="B", reason="R", added_by="x", added_at="2026-01-01T00:00:00+00:00"
    )
    web_allowlist.set_selection_mode(entry["id"], "positiv")

    monkeypatch.setattr(trafilatura.sitemaps, "sitemap_search", lambda url, **kw: MANY_URLS)
    monkeypatch.setattr(extraction, "extract_from_url", lambda url: {"title": "A", "text": "Inhalt."})
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    web_crawler.index_entry(entry["id"], "https://beispiel.org", max_pages=10)

    assert web_allowlist.get_entry(entry["id"])["selection_mode"] == "negativ"


# --- Positivselektion (Backlog: Website ohne klar abgrenzbare Quellenstruktur) ---


def test_index_entry_switches_to_positive_selection_when_too_few_urls_discovered(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://beispiel.org", label="B", reason="R", added_by="x", added_at="2026-01-01T00:00:00+00:00"
    )

    # Nur 2 entdeckte URLs (post-sitemap.xml UND volle Sitemap liefern
    # gleichermaßen wenig) - <= POSITIVE_SELECTION_MAX_DISCOVERED.
    monkeypatch.setattr(
        trafilatura.sitemaps,
        "sitemap_search",
        lambda url, **kw: ["https://beispiel.org/a", "https://beispiel.org/b"],
    )
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {"title": f"Titel {url}", "text": "Ein Text über Selbstorganisation und Beta-Kodex."},
    )
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [1.0, 0.0])
    monkeypatch.setattr(vectorstore, "query", lambda embedding, top_k=1: {"distances": [[0.1]]})

    count = web_crawler.index_entry(entry["id"], "https://beispiel.org", max_pages=50)

    assert count == 2  # 2 neue Kandidaten, KEINE indizierten Seiten
    assert web_index.pages_for_entry(entry["id"]) == {}
    assert web_allowlist.get_entry(entry["id"])["selection_mode"] == "positiv"
    candidates = web_candidates.candidates_for_entry(entry["id"])
    assert {c["url"] for c in candidates.values()} == {"https://beispiel.org/a", "https://beispiel.org/b"}


def test_positive_selection_ranks_candidates_by_distance_to_curated_corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://beispiel.org", label="B", reason="R", added_by="x", added_at="2026-01-01T00:00:00+00:00"
    )

    monkeypatch.setattr(
        trafilatura.sitemaps,
        "sitemap_search",
        lambda url, **kw: ["https://beispiel.org/nah", "https://beispiel.org/fern"],
    )
    monkeypatch.setattr(
        extraction, "extract_from_url", lambda url: {"title": url, "text": "Text " + url}
    )

    # embed_query bekommt Titel+Kurztext - wir kodieren die URL einfach im
    # (gemockten) "Embedding" selbst, um "nah" und "fern" unterscheidbar zu
    # machen, ohne ein echtes Embedding-Modell zu laden.
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [text])

    def fake_query(embedding, top_k=1):
        return {"distances": [[0.1 if "nah" in embedding[0] else 0.9]]}

    monkeypatch.setattr(vectorstore, "query", fake_query)

    web_crawler.index_entry(entry["id"], "https://beispiel.org", max_pages=50)

    candidates = list(web_candidates.candidates_for_entry(entry["id"]).values())
    scores = {c["url"]: c["relevance_score"] for c in candidates}
    assert scores["https://beispiel.org/nah"] > scores["https://beispiel.org/fern"]


def test_positive_selection_does_not_suggest_lorem_ipsum_candidates(tmp_path, monkeypatch):
    # Nutzerfeedback: dieselben WordPress-Theme-Demo-Beiträge dürfen auch in
    # der Positivselektion nicht als Kandidaten vorgeschlagen werden - eine
    # Pfleger:in müsste sie sonst einzeln manuell ablehnen, obwohl sie
    # eindeutig identifizierbarer Platzhaltertext sind.
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://beispiel.org", label="B", reason="R", added_by="x", added_at="2026-01-01T00:00:00+00:00"
    )

    monkeypatch.setattr(
        trafilatura.sitemaps,
        "sitemap_search",
        lambda url, **kw: ["https://beispiel.org/demo", "https://beispiel.org/echt"],
    )

    def fake_extract(url):
        if url.endswith("demo"):
            return {"title": "Demo-Beitrag", "text": "Lorem ipsum dolor sit amet."}
        return {"title": "Echter Artikel", "text": "Ein echter Artikel über Selbstorganisation."}

    monkeypatch.setattr(extraction, "extract_from_url", fake_extract)
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [1.0, 0.0])
    monkeypatch.setattr(vectorstore, "query", lambda embedding, top_k=1: {"distances": [[0.1]]})

    web_crawler.index_entry(entry["id"], "https://beispiel.org", max_pages=50)

    candidates = web_candidates.candidates_for_entry(entry["id"])
    assert {c["url"] for c in candidates.values()} == {"https://beispiel.org/echt"}


def test_positive_selection_skips_already_known_urls_on_repeated_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://beispiel.org", label="B", reason="R", added_by="x", added_at="2026-01-01T00:00:00+00:00"
    )

    monkeypatch.setattr(
        trafilatura.sitemaps, "sitemap_search", lambda url, **kw: ["https://beispiel.org/a"]
    )
    extract_calls = []
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: extract_calls.append(url) or {"title": "A", "text": "Inhalt."},
    )
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [1.0, 0.0])
    monkeypatch.setattr(vectorstore, "query", lambda embedding, top_k=1: {"distances": [[0.1]]})

    web_crawler.index_entry(entry["id"], "https://beispiel.org", max_pages=50)
    assert len(extract_calls) == 1

    count = web_crawler.index_entry(entry["id"], "https://beispiel.org", max_pages=50)

    assert count == 0
    assert len(extract_calls) == 1  # kein erneuter Fetch für bereits bekannte URL


def test_positive_selection_does_not_resurrect_rejected_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    entry = web_allowlist.add_entry(
        url_prefix="https://beispiel.org", label="B", reason="R", added_by="x", added_at="2026-01-01T00:00:00+00:00"
    )

    monkeypatch.setattr(
        trafilatura.sitemaps, "sitemap_search", lambda url, **kw: ["https://beispiel.org/a"]
    )
    monkeypatch.setattr(extraction, "extract_from_url", lambda url: {"title": "A", "text": "Inhalt."})
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [1.0, 0.0])
    monkeypatch.setattr(vectorstore, "query", lambda embedding, top_k=1: {"distances": [[0.1]]})

    web_crawler.index_entry(entry["id"], "https://beispiel.org", max_pages=50)
    candidate_id = next(iter(web_candidates.candidates_for_entry(entry["id"])))
    web_candidates.set_status(candidate_id, "rejected")

    web_crawler.index_entry(entry["id"], "https://beispiel.org", max_pages=50)

    assert web_candidates.candidates_for_entry(entry["id"], status="pending") == {}


def test_index_approved_candidate_indexes_the_page(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    monkeypatch.setattr(
        extraction, "extract_from_url", lambda url: {"title": "Freigegebene Seite", "text": "Inhalt."}
    )
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])

    result = web_crawler.index_approved_candidate("entry-1", "https://beispiel.org/a")

    assert result is True
    pages = web_index.pages_for_entry("entry-1")
    assert {p["url"] for p in pages.values()} == {"https://beispiel.org/a"}


def test_index_approved_candidate_returns_false_on_extraction_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")

    def raise_error(url):
        raise RuntimeError("nicht erreichbar")

    monkeypatch.setattr(extraction, "extract_from_url", raise_error)

    result = web_crawler.index_approved_candidate("entry-1", "https://beispiel.org/a")

    assert result is False
    assert web_index.pages_for_entry("entry-1") == {}
