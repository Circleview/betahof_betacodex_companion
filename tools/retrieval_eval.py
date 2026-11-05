"""Retrieval-Eval ohne LLM-Kosten (2026-09-25, Backlog "zu oft keine Quellen").

Stellt "Was ist {Schlagwort}?" für eine feste Stichprobe kuratierter
Schlagworte (terms.json), die wörtlich in mindestens einem Chunk vorkommen,
und zählt, wie oft unter den Ausschnitten, die das Modell bekäme, einer den
Begriff enthält - einmal nur Vektorsuche, einmal mit Hybrid-Suche
(app/main.py: _ensure_term_hits). Vor und nach jeder Änderung an Suche,
Chunking oder Reranking laufen lassen:

    PYTHONPATH=. python tools/retrieval_eval.py [Anzahl, Default 80]

A/B für die Quellen-Vielfalt (Idee 3c32da30) - KOSTENPFLICHTIG (je Frage 2
Modellaufrufe), stellt jede Frage ohne/mit Vielfalts-Regel und vergleicht
zitierte Quellen, Web-Anteil, Distanzzuwachs je Tausch, max_tokens-Stopps
und die Treffer auf Frage-Begriffe. Die Antworten beider Läufe stehen zum
Handurteil in data/ab_ergebnis.md:

    PYTHONPATH=. python tools/retrieval_eval.py --ab data/ab_fragen.txt
"""
import logging
import random
import re
import sys

from dotenv import load_dotenv

load_dotenv(".env")

from app import embeddings, llm, main, terms, vectorstore, web_index  # noqa: E402

TOP_K = 5
EXTRA_TERMS = ["Democratic Taylorism", "Zellstrukturdesign"]  # reale Problemfälle


def sample_terms(n: int) -> list[str]:
    collection = vectorstore._get_collection()
    candidates = [t["term"] for t in terms.list_terms() if len(t["term"]) >= main.LEXICAL_MIN_TERM_LEN]
    random.Random(7).shuffle(candidates)
    picked = []
    for term in candidates:
        if collection.get(where_document={"$contains": term}, limit=1)["ids"]:
            picked.append(term)
        if len(picked) >= n:
            break
    return picked + EXTRA_TERMS


def retrieve(question: str, hybrid: bool) -> list[str]:
    sources = main._load_sources()
    emb = embeddings.embed_query(question)
    n = TOP_K * main.RELEVANCE_OVERFETCH_MULTIPLIER
    c = vectorstore.query(emb, top_k=n)
    w = vectorstore.query_web(emb, top_k=n, exclude_page_ids=web_index.excluded_page_ids())
    ids = c["ids"][0] + w["ids"][0]
    docs = c["documents"][0] + w["documents"][0]
    dists = c["distances"][0] + w["distances"][0]
    metas = list(c["metadatas"][0]) + [
        {**m, "source_id": m["page_id"], "is_web_fallback": True} for m in w["metadatas"][0]
    ]
    ids, docs, metas = main._rerank_by_relevance(ids, docs, metas, dists, sources, TOP_K)
    if hybrid:
        ids, docs, metas = main._ensure_term_hits(ids, docs, metas, emb, question, TOP_K)
    return docs


def main_eval(n: int) -> None:
    sample = sample_terms(n)
    score = {"vektor": 0, "hybrid": 0}
    misses = []
    for term in sample:
        question = f"Was ist {term}?"
        for mode in score:
            hit = any(term.lower() in d.lower() for d in retrieve(question, hybrid=mode == "hybrid"))
            score[mode] += hit
            if mode == "hybrid" and not hit:
                misses.append(term)
    total = len(sample)
    for mode, hits in score.items():
        print(f"{mode}: {hits}/{total} = {hits / total:.0%}")
    print("Mit Hybrid verfehlt:", misses or "-")


def _cited_numbers(answer: str) -> set[int]:
    return {int(n) for group in re.findall(r"\[(\d+(?:\s*,\s*\d+)*)\]", answer) for n in re.findall(r"\d+", group)}


def cited_keys(answer: str, chunks: list[dict]) -> set[str]:
    """Quellen-Schlüssel der im Text zitierten Chunks ([1][3] oder [1, 3])."""
    return {chunks[n - 1]["source_key"] for n in _cited_numbers(answer) if 1 <= n <= len(chunks)}


def web_share(answer: str, chunks: list[dict]) -> float:
    cited = [chunks[n - 1] for n in _cited_numbers(answer) if 1 <= n <= len(chunks)]
    return sum(c["web"] for c in cited) / len(cited) if cited else 0.0


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _ab_run(question: str, off: bool) -> dict:
    lang = llm._question_language(question) or "de"
    collect = _Collect()
    loggers = [logging.getLogger("app.main"), logging.getLogger("app.llm")]
    for lg in loggers:
        lg.addHandler(collect)
        lg.setLevel(logging.INFO)
    try:
        # max_per_source=0 -> aus, None -> Einstellung der Umgebung (Standard 2)
        llm_chunks, refs, bios, _ = main._ask_context(question, [], lang, 5, None, max_per_source=0 if off else None)
        answer = "".join(llm.stream_answer_question(question, llm_chunks, lang=lang, author_bios=bios or None))
    finally:
        for lg in loggers:
            lg.removeHandler(collect)
    answer = answer.split("---QUOTES---")[0].strip()
    # Schlüssel auch im "aus"-Lauf, damit gezählt werden kann
    chunks = [{"source_key": main._diversity_key({"source_id": r.source_id, "title": r.title,
                                                  "allowlist_entry_id": r.allowlist_entry_id}),
               "web": r.is_web_fallback} for r in refs]
    terms_hit = [t for t in main._question_terms(question) if any(t.lower() in r.text.lower() for r in refs)]
    return {
        "answer": answer,
        "cited": len(cited_keys(answer, chunks)),
        "delivered": len({c["source_key"] for c in chunks}),
        "web": web_share(answer, chunks),
        "swaps": [float(m) for msg in collect.messages for m in re.findall(r"Distanzzuwachs ([\d.]+) %", msg)],
        "truncated": any("max_tokens" in m for m in collect.messages),
        "has_terms": bool(main._question_terms(question)),
        "terms_hit": bool(terms_hit),
    }


def ab_eval(path: str) -> None:
    questions = [q.strip() for q in open(path, encoding="utf-8") if q.strip() and not q.startswith("#")]
    results = [(q, _ab_run(q, off=True), _ab_run(q, off=False)) for q in questions]
    n = len(results)
    mean = lambda mode, key: sum(r[mode][key] for r in results) / n
    swaps = [d for r in results for d in r[2]["swaps"]]
    term_qs = [r for r in results if r[1]["has_terms"]]
    print(f"Fragen: {n}")
    print(f"Zitierte Quellen im Mittel: aus {mean(1, 'cited'):.2f} / an {mean(2, 'cited'):.2f}")
    print(f"Gelieferte Quellen im Mittel: aus {mean(1, 'delivered'):.2f} / an {mean(2, 'delivered'):.2f}")
    print(f"Web-Anteil unter den Zitaten: aus {mean(1, 'web'):.0%} / an {mean(2, 'web'):.0%}")
    print(f"Tausche: {len(swaps)}, Distanzzuwachs im Mittel {sum(swaps) / len(swaps):.1f} %" if swaps else "Tausche: 0")
    print(f"max_tokens-Stopps: aus {sum(r[1]['truncated'] for r in results)} / an {sum(r[2]['truncated'] for r in results)}")
    if term_qs:
        print(f"Begriffs-Trefferquote ({len(term_qs)} Fragen): "
              f"aus {sum(r[1]['terms_hit'] for r in term_qs)} / an {sum(r[2]['terms_hit'] for r in term_qs)}")
    gain = mean(2, "cited") - mean(1, "cited")
    print(f"Tor: Zuwachs zitierter Quellen {gain:+.2f} (Soll >= +0.50): {'ok' if gain >= 0.5 else 'NICHT erreicht'}; "
          f"max_tokens-Stopp an: {'keiner' if not any(r[2]['truncated'] for r in results) else 'VORHANDEN'}; "
          "Handurteil und Web-Anteil siehe oben/data/ab_ergebnis.md")
    with open("data/ab_ergebnis.md", "w", encoding="utf-8") as f:
        for q, off, on in results:
            f.write(f"## {q}\n\nzitiert aus/an: {off['cited']}/{on['cited']}\n\n**AUS**\n\n{off['answer']}\n\n**AN**\n\n{on['answer']}\n\n")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--ab"]:
        ab_eval(sys.argv[2])
    else:
        main_eval(int(sys.argv[1]) if len(sys.argv) > 1 else 80)
