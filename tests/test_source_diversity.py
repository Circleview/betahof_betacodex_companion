"""Idee 3c32da30: mehr verschiedene Quellen je Antwort (Quellen-Vielfalt im
Rerank). Erwartete Werte folgen aus der Anforderung, nicht aus der Ausgabe."""
import logging
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app import authors, embeddings, llm, terms, vectorstore, web_index
from app import main as main_module


def _pool(spec):
    """spec: Liste (chunk_id, source_id, Distanz[, Text]) -> Rerank-Eingaben.
    Titel = Quell-ID, damit der Vielfalts-Schlüssel je Quelle verschieden ist."""
    ids = [s[0] for s in spec]
    docs = [s[3] if len(s) > 3 else f"Text {s[0]}" for s in spec]
    metas = [{"source_id": s[1], "title": s[1], "url": "", "position": 0} for s in spec]
    dists = [s[2] for s in spec]
    return ids, docs, metas, dists


def _rerank(spec, top_k=5, max_per_source=2, **kwargs):
    ids, docs, metas, dists = _pool(spec)
    out_ids, _, _ = main_module._rerank_by_relevance(
        ids, docs, metas, dists, {}, top_k, max_per_source=max_per_source, **kwargs
    )
    return out_ids


A4 = [("a1", "A", 0.100), ("a2", "A", 0.101), ("a3", "A", 0.102), ("a4", "A", 0.103)]


def test_repeated_source_is_replaced_by_new_sources_within_tolerance():
    out = _rerank(A4 + [("b1", "B", 0.110), ("c1", "C", 0.112), ("d1", "D", 0.113)])
    assert len({main_module._diversity_key(m) for m in [{"source_id": i[0].upper(), "title": i[0].upper()} for i in out]}) >= 3
    assert sum(i.startswith("a") for i in out) <= 2
    assert sorted(out) == ["a1", "a2", "b1", "c1", "d1"]


def test_no_replacement_when_reserve_only_has_already_present_source():
    out = _rerank(A4 + [("b1", "B", 0.110), ("b2", "B", 0.112), ("b3", "B", 0.113)])
    assert out == ["a1", "a2", "a3", "a4", "b1"]


def test_tolerance_boundary_exactly_15_percent_swaps_and_slightly_over_stays():
    base = [("a1", "A", 0.10), ("a2", "A", 0.10001), ("a3", "A", 0.10002), ("a4", "A", 0.2), ("b1", "B", 0.21)]
    assert "c1" in _rerank(base + [("c1", "C", 0.23)])  # 0.2 * 1.15
    assert "a4" in _rerank(base + [("c1", "C", 0.2301)])


def test_single_source_pool_keeps_all_slots():
    spec = [(f"a{i}", "A", 0.1 + i / 100) for i in range(8)]
    assert _rerank(spec) == ["a0", "a1", "a2", "a3", "a4"]


def test_zero_limit_gives_old_result():
    spec = A4 + [("b1", "B", 0.110), ("c1", "C", 0.112)]
    assert _rerank(spec, max_per_source=0) == ["a1", "a2", "a3", "a4", "b1"]


@pytest.mark.parametrize("top_k", [1, 2])
def test_top_k_not_above_limit_changes_nothing(top_k):
    spec = A4 + [("c1", "C", 0.112)]
    assert _rerank(spec, top_k=top_k) == ["a1", "a2", "a3", "a4", "c1"][:top_k]


def test_duplicate_text_never_moves_up():
    spec = A4 + [("b1", "B", 0.110), ("c1", "C", 0.112, "Text a1"), ("d1", "D", 0.113)]
    out = _rerank(spec)
    assert "c1" not in out
    assert "d1" in out


def test_exempt_source_chunks_stay_and_never_move_up():
    stay = [("x1", "X", 0.10), ("x2", "X", 0.101), ("x3", "X", 0.102), ("x4", "X", 0.103), ("y1", "Y", 0.104),
            ("z1", "Z", 0.105)]
    assert _rerank(stay, exempt_source_ids={"X"}) == ["x1", "x2", "x3", "x4", "y1"]
    spec = [("x1", "X", 0.10), ("x2", "X", 0.101), ("y1", "Y", 0.103), ("y2", "Y", 0.104),
            ("y3", "Y", 0.105), ("x3", "X", 0.106), ("z1", "Z", 0.107)]
    out = _rerank(spec, exempt_source_ids={"X"})
    assert "x3" not in out  # Nachrücker nie aus ausgenommener Quelle
    assert sum(i.startswith("y") for i in out) <= 2
    assert "z1" in out


def test_only_first_chunk_with_question_term_is_protected_even_in_other_case():
    spec = [("a1", "A", 0.100), ("a2", "A", 0.101), ("a3", "A", 0.102, "Über DOPPELMANAGEMENT hier"),
            ("b1", "B", 0.103), ("b2", "B", 0.104), ("c1", "C", 0.110)]
    out = _rerank(spec, question_terms=["Doppelmanagement"])
    assert "a3" in out


def test_websites_count_as_one_source_and_curated_replacement_beats_web():
    def web(i, d, entry="W1"):
        return (f"w{i}", f"page{i}", d)

    ids, docs, metas, dists = _pool([web(1, 0.10), web(2, 0.101), web(3, 0.102), web(4, 0.103), ("k1", "K", 0.104),
                                     ("w9", "page9", 0.105), ("k2", "K2", 0.105)])
    for m in metas:
        if m["source_id"].startswith("page"):
            m.update(allowlist_entry_id="W1", is_web_fallback=True, title=m["source_id"])
    metas[5]["allowlist_entry_id"] = "W2"  # anderer Web-Eintrag, gleich gut
    out, _, _ = main_module._rerank_by_relevance(ids, docs, metas, dists, {}, 5, max_per_source=2)
    assert "k2" in out
    assert sum(i in ("w1", "w2", "w3", "w4") for i in out) == 2  # Grenze je Website genau 2: w4/w3 weichen
    assert "w9" in out


def test_title_twin_does_not_count_as_new_source():
    ids, docs, metas, dists = _pool(A4 + [("b1", "B", 0.110), ("a9", "A_other", 0.111), ("c1", "C", 0.112)])
    metas[5]["title"] = "  a "  # gleicher Titel (normalisiert) wie A
    metas[0]["title"] = metas[1]["title"] = metas[2]["title"] = metas[3]["title"] = "A"
    out, _, _ = main_module._rerank_by_relevance(ids, docs, metas, dists, {}, 5, max_per_source=2)
    assert "a9" not in out
    assert "c1" in out


@pytest.mark.parametrize(
    "raw, expected",
    [(None, 2), ("", 0), ("0", 0), ("-3", 0), ("abc", 0), ("3", 3)],
)
def test_env_parsing(raw, expected):
    assert main_module._parse_max_per_source(raw) == expected


def test_invalid_env_value_warns(caplog):
    with caplog.at_level(logging.WARNING):
        main_module._parse_max_per_source("abc")
    assert caplog.records


def test_default_limit_is_two():
    assert main_module.SOURCE_DIVERSITY_DEFAULT_MAX_PER_SOURCE == 2
    assert main_module.SOURCE_DIVERSITY_MAX_DISTANCE_INCREASE == 0.15


def test_forced_term_hit_trims_repeated_source_first(monkeypatch):
    monkeypatch.setattr(terms, "list_terms", lambda: [{"term": "NUMMI"}])
    monkeypatch.setattr(
        vectorstore, "query",
        lambda *a, **k: {"ids": [["n1"]], "documents": [["Bei NUMMI"]], "metadatas": [[{"source_id": "N", "title": "N"}]]},
    )
    ids = ["a1", "a2", "b1", "c1", "d1"]
    metas = [{"source_id": s, "title": s} for s in ("A", "A", "B", "C", "D")]
    docs = ["x"] * 5
    out, _, _ = main_module._ensure_term_hits(ids, docs, metas, [0.1], "Was ist NUMMI?", 5, trim_repeats=True)
    assert out == ["a1", "b1", "c1", "d1", "n1"]  # a2 (Wiederholung) fällt, nicht d1
    old, _, _ = main_module._ensure_term_hits(ids, docs, metas, [0.1], "Was ist NUMMI?", 5)
    assert old == ["a1", "a2", "b1", "c1", "n1"]  # altes Kürzen von hinten


# ---- _ask_context: Ausnahmen, Reihenfolge, source_key ----

def _ctx_setup(monkeypatch, sources, pool, reserve=(), authors_by_text=None, author_entries=()):
    def meta(sid):
        return {"source_id": sid, "title": sources[sid]["title"], "authors": [], "date": "", "url": "", "position": 0}

    allspec = list(pool) + list(reserve)
    result = {
        "ids": [[c[0] for c in allspec]],
        "documents": [[f"Text {c[0]}" for c in allspec]],
        "distances": [[c[2] for c in allspec]],
        "metadatas": [[meta(c[1]) for c in allspec]],
    }
    empty = {"ids": [[]], "documents": [[]], "distances": [[]], "metadatas": [[]]}
    monkeypatch.setattr(main_module, "_load_sources", lambda: sources)
    monkeypatch.setattr(embeddings, "embed_query", lambda q: [0.1])
    monkeypatch.setattr(vectorstore, "query", lambda *a, **k: result)
    monkeypatch.setattr(vectorstore, "query_web", lambda *a, **k: empty)
    monkeypatch.setattr(web_index, "excluded_page_ids", lambda: set())
    monkeypatch.setattr(terms, "list_terms", lambda: [])
    monkeypatch.setattr(llm, "rewrite_followup_query", lambda q, h, lang, usage_email=None: f"{q} Schlegel" if authors_by_text else None)
    monkeypatch.setattr(authors, "find_mentioned", lambda text: ["Andreas Schlegel"] if authors_by_text and "Schlegel" in text else [])
    monkeypatch.setattr(authors, "list_authors", lambda: list(author_entries))


SRC = {
    "A": {"title": "Quelle A lang genug", "key_terms_de": []},
    "B": {"title": "Quelle B", "key_terms_de": []},
    "C": {"title": "Quelle C", "key_terms_de": []},
    "D": {"title": "Quelle D", "key_terms_de": []},
}
POOL = [("a1", "A", 0.100), ("a2", "A", 0.101), ("a3", "A", 0.102), ("a4", "A", 0.103), ("b1", "B", 0.104)]
RESERVE = [("c1", "C", 0.110), ("d1", "D", 0.111)]


def test_ask_context_limits_repeats_and_keeps_numbering_aligned(monkeypatch):
    _ctx_setup(monkeypatch, SRC, POOL, RESERVE)
    chunks, refs, _, _ = main_module._ask_context("Frage zum Thema?", [], "de")
    assert sum(r.source_id == "A" for r in refs) == 2
    assert len({r.source_id for r in refs}) >= 3
    assert [c["text"] for c in chunks] == [r.text for r in refs]  # [n] zeigt auf den richtigen Chunk
    assert len({c["source_key"] for c in chunks}) == len({r.source_id for r in refs})


def test_ask_context_off_gives_old_order_and_no_source_key(monkeypatch):
    _ctx_setup(monkeypatch, SRC, POOL, RESERVE)
    monkeypatch.setattr(main_module, "SOURCE_DIVERSITY_MAX_PER_SOURCE", 0)
    chunks, refs, _, _ = main_module._ask_context("Frage zum Thema?", [], "de")
    assert [r.chunk_id for r in refs] == ["a1", "a2", "a3", "a4", "b1"]
    assert all(c["source_key"] is None for c in chunks)


def test_author_named_only_in_rewritten_query_is_exempt(monkeypatch):
    entries = [{"name": "Andreas Schlegel", "source_count": 1, "source_ids": ["A"]}]
    _ctx_setup(monkeypatch, SRC, POOL, RESERVE, authors_by_text=True, author_entries=entries)
    monkeypatch.setattr(main_module.author_profiles, "get_profile", lambda name: {})
    _, refs, _, _ = main_module._ask_context(
        "Erzähl mehr", [{"question": "Was sagt Schlegel?", "answer": "x"}], "de"
    )
    assert sum(r.source_id == "A" for r in refs) == 4  # Ausnahme greift, Rabatt/Vita unverändert


def test_title_in_query_exempts_source_but_short_title_does_not(monkeypatch):
    _ctx_setup(monkeypatch, SRC, POOL, RESERVE)
    _, refs, _, _ = main_module._ask_context("Was steht in Quelle A lang genug?", [], "de")
    assert sum(r.source_id == "A" for r in refs) == 4
    src = {**SRC, "A": {**SRC["A"], "title": "Kurz"}}
    _ctx_setup(monkeypatch, src, POOL, RESERVE)
    _, refs, _, _ = main_module._ask_context("Was steht in Kurz?", [], "de")
    assert sum(r.source_id == "A" for r in refs) == 2


def test_keyword_exempts_only_when_at_most_three_sources_match(monkeypatch):
    few = {**SRC, "A": {**SRC["A"], "key_terms_de": ["Zeitorientierung"]}}
    _ctx_setup(monkeypatch, few, POOL, RESERVE)
    _, refs, _, _ = main_module._ask_context("Was ist Zeitorientierung?", [], "de")
    assert sum(r.source_id == "A" for r in refs) == 4
    many = {k: {**v, "key_terms_de": ["Zeitorientierung"]} for k, v in SRC.items()}
    _ctx_setup(monkeypatch, many, POOL, RESERVE)
    _, refs, _, _ = main_module._ask_context("Was ist Zeitorientierung?", [], "de")
    assert sum(r.source_id == "A" for r in refs) == 2


# ---- Umschalter vielfalt=aus: HTTP-Tests in tests/test_api.py ----


# ---- Hinweis im Prompt und stop_reason ----

def _content(chunks, question="Was ist Teamarbeit im Beta-Kodex?", lang="de"):
    client = MagicMock()
    client.messages.stream.return_value.__enter__.return_value.text_stream = iter(["x"])
    with patch.object(llm, "_get_client", return_value=client):
        list(llm.stream_answer_question(question, chunks, lang=lang))
    return client, client.messages.stream.call_args.kwargs["messages"][0]["content"]


def _chunk(key):
    return {"title": "T", "author": "A", "date": "D", "text": "Text", "source_key": key}


@pytest.mark.parametrize("lang, question, explicit", [
    ("de", "Was ist Teamarbeit im Beta-Kodex?", "Antworte ausschließlich auf Deutsch."),
    ("en", "How does the team decide what to do?", "Answer exclusively in English."),
])
def test_multi_source_hint_present_before_language_line(lang, question, explicit):
    _, content = _content([_chunk("a"), _chunk("b")], question, lang)
    hint = llm._MULTI_SOURCE_REMINDERS[lang]
    assert hint in content
    assert content.index(hint) < content.index(explicit)
    assert content.rstrip().endswith(explicit)


def test_multi_source_hint_absent_for_one_key_or_off():
    for chunks in ([_chunk("a"), _chunk("a")], [_chunk(None), _chunk(None)]):
        _, content = _content(chunks)
        assert llm._MULTI_SOURCE_REMINDERS["de"] not in content


def test_max_tokens_stop_warns_and_answer_continues(caplog):
    client = MagicMock()
    stream = client.messages.stream.return_value.__enter__.return_value
    stream.text_stream = iter(["Teil ", "zwei"])
    stream.get_final_message.return_value.stop_reason = "max_tokens"
    with patch.object(llm, "_get_client", return_value=client), caplog.at_level(logging.WARNING):
        out = list(llm.stream_answer_question("Frage?", [_chunk("a")]))
    assert out == ["Teil ", "zwei"]
    assert client.messages.stream.call_args.kwargs["max_tokens"] == 1536
    assert any("max_tokens" in r.getMessage() for r in caplog.records)


def test_restricted_sources_keep_at_most_one_image_each_with_many_sources():
    ref = lambda i, sid: MagicMock(source_id=sid, images=[f"{i}a", f"{i}b"])
    refs = [ref(0, "R1"), ref(1, "R1"), ref(2, "R2"), ref(3, "R2"), ref(4, "R3")]
    sources = {s: {"restricted": True} for s in ("R1", "R2", "R3")}
    out = main_module._limit_restricted_images(refs, sources)
    assert [len(x) for x in out] == [1, 0, 1, 0, 1]


# ---- Fehler-Check-Nachbesserung ----

def _web(spec, entry="W"):
    ids, docs, metas, dists = _pool(spec)
    for m in metas:
        if m["source_id"].startswith("page"):
            m.update(allowlist_entry_id=entry, is_web_fallback=True)
    return ids, docs, metas, dists


def test_web_chunk_never_replaces_curated_overflow_chunk():
    spec = A4 + [("b1", "B", 0.110), ("page1", "page1", 0.112)]
    ids, docs, metas, dists = _web(spec)
    out, _, _ = main_module._rerank_by_relevance(ids, docs, metas, dists, {}, 5, max_per_source=2)
    assert "page1" not in out
    assert out == ["a1", "a2", "a3", "a4", "b1"]


def test_web_overflow_chunk_may_get_web_or_curated_replacement():
    spec = [("page1", "page1", 0.100), ("page2", "page2", 0.101), ("page3", "page3", 0.102), ("page4", "page4", 0.103),
            ("b1", "B", 0.104), ("c1", "C", 0.110)]
    ids, docs, metas, dists = _web(spec)
    out, _, _ = main_module._rerank_by_relevance(ids, docs, metas, dists, {}, 5, max_per_source=2)
    assert "c1" in out


def test_no_swap_is_wasted_by_greedy_assignment():
    # a4 (.110) darf c (.112) oder e (.120) nehmen, a3 (.100) nur c: zwei Tausche moeglich
    spec = [("a1", "A", 0.09), ("a2", "A", 0.095), ("a3", "A", 0.100), ("a4", "A", 0.110), ("b1", "B", 0.111),
            ("c1", "C", 0.112), ("e1", "E", 0.120)]
    out = _rerank(spec)
    assert sorted(out) == ["a1", "a2", "b1", "c1", "e1"]


def test_successor_is_the_best_chunk_of_a_new_source_not_the_weakest_in_tolerance():
    # Qualitaetsvorgabe: Ein Tausch nimmt den besten Ausschnitt der neuen Quelle.
    spec = [("a1", "A", 0.100), ("a2", "A", 0.101), ("a3", "A", 0.102), ("a4", "A", 0.103), ("b1", "B", 0.104),
            ("c1", "C", 0.105), ("c2", "C", 0.110)]
    assert sorted(_rerank(spec)) == ["a1", "a2", "a3", "b1", "c1"]


def test_single_swap_takes_best_new_source_and_drops_worst_candidate():
    spec = [("a1", "A", 0.100), ("a2", "A", 0.101), ("a3", "A", 0.102), ("b1", "B", 0.103), ("e1", "E", 0.104),
            ("d1", "D", 0.106), ("c1", "C", 0.112)]
    assert sorted(_rerank(spec)) == ["a1", "a2", "b1", "d1", "e1"]


def _term_fixture(monkeypatch, forced_by_term):
    monkeypatch.setattr(terms, "list_terms", lambda: [{"term": t} for t in forced_by_term])

    def fake_query(embedding, top_k=5, where=None, where_document=None):
        term = where_document["$contains"]
        return {"ids": [[f"f-{term}"]], "documents": [[f"Treffer {term}"]], "metadatas": [[{"source_id": f"F{term}", "title": f"F{term}"}]]}

    monkeypatch.setattr(vectorstore, "query", fake_query)


def test_trim_keeps_sole_carrier_of_question_term(monkeypatch):
    _term_fixture(monkeypatch, ["Doppelmanagement", "NUMMI"])
    ids = ["a1", "a2", "a3", "b1", "c1"]
    metas = [{"source_id": s, "title": s} for s in ("A", "A", "A", "B", "C")]
    docs = ["x", "y", "Über Doppelmanagement", "z", "w"]
    out, _, _ = main_module._ensure_term_hits(
        ids, docs, metas, [0.1], "Was ist Doppelmanagement bei NUMMI?", 5, trim_repeats=True
    )
    assert out == ["a1", "a3", "b1", "c1", "f-NUMMI"]


def test_trim_with_more_terms_than_slots_does_not_crash(monkeypatch):
    _term_fixture(monkeypatch, ["NUMMI", "Seddon"])
    out, _, _ = main_module._ensure_term_hits(
        ["a1"], ["x"], [{"source_id": "A", "title": "A"}], [0.1], "NUMMI und Seddon?", 1, trim_repeats=True
    )
    assert set(out) <= {"a1", "f-NUMMI", "f-Seddon"}


def test_keyword_exemption_uses_word_boundaries_and_min_length():
    sources = {
        "T": {"key_terms_de": ["Team"], "key_terms_en": []},
        "K": {"key_terms_de": ["KI"], "key_terms_en": []},
        "Z": {"key_terms_de": ["Zeitorientierung"], "key_terms_en": []},
    }
    assert main_module._keyword_exempt_source_ids(sources, "Wie funktioniert Teamarbeit mit KI?") == set()
    assert main_module._keyword_exempt_source_ids(sources, "Was ist zeitorientierung?") == {"Z"}


def test_keyword_exemption_threshold_applies_per_term_not_in_sum():
    sources = {f"B{i}": {"key_terms_de": ["Beta-Kodex"], "key_terms_en": []} for i in range(10)}
    sources["D1"] = {"key_terms_de": ["Doppelmanagement"], "key_terms_en": ["Beta-Kodex"]}
    sources["D2"] = {"key_terms_de": ["Doppelmanagement"], "key_terms_en": []}
    out = main_module._keyword_exempt_source_ids(sources, "Was sagt der Beta-Kodex über Doppelmanagement?")
    assert out == {"D1", "D2"}


def test_keyword_exemption_ignores_garbage_single_letter_terms():
    sources = {"G": {"key_terms_de": [], "key_terms_en": list("OpenSpace")}}
    assert main_module._keyword_exempt_source_ids(sources, "Open Space e p n?") == set()


def test_overflow_chunk_without_replacement_is_logged(caplog):
    with caplog.at_level(logging.INFO, logger="app.main"):
        _rerank(A4 + [("b1", "B", 0.110), ("b2", "B", 0.112)])
    assert any("kein Nachrücker" in r.getMessage() for r in caplog.records)
