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
    spec = [("x1", "X", 0.10), ("x2", "X", 0.101), ("x3", "X", 0.102), ("y1", "Y", 0.103), ("y2", "Y", 0.104),
            ("y3", "Y", 0.105), ("x4", "X", 0.106), ("z1", "Z", 0.107)]
    out = _rerank(spec, exempt_source_ids={"X"})
    assert {"x1", "x2", "x3"} <= set(out)
    assert "x4" not in out  # Nachrücker nie aus ausgenommener Quelle
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
    assert sum(i.startswith("w") for i in out) <= 3


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


# ---- Umschalter vielfalt=aus ----

def _spy_ask(client, monkeypatch, dev, referer):
    seen = {}

    def fake(question, history, lang, top_k=5, usage_email=None, max_per_source=None):
        seen["max_per_source"] = max_per_source
        raise HTTPException(400, "stop")

    monkeypatch.setattr(main_module, "_ask_context", fake)
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", dev)
    headers = {"Referer": referer} if referer else {}
    client.post("/api/ask", json={"question": "Frage?"}, headers=headers)
    return seen["max_per_source"]


def test_vielfalt_aus_switches_off_on_dev_only(client, monkeypatch):
    url = "http://localhost/index.html?vielfalt=aus"
    assert _spy_ask(client, monkeypatch, True, url) == 0
    assert _spy_ask(client, monkeypatch, False, url) is None
    assert _spy_ask(client, monkeypatch, True, None) is None
    assert _spy_ask(client, monkeypatch, True, "http://localhost/?vielfalt=an") is None


def test_mcp_calls_ask_context_without_override():
    import inspect
    from app import mcp_server
    assert "max_per_source" not in inspect.getsource(mcp_server)


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
