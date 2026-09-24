"""Retrieval-Eval ohne LLM-Kosten (2026-09-25, Backlog "zu oft keine Quellen").

Stellt "Was ist {Schlagwort}?" für eine feste Stichprobe kuratierter
Schlagworte (terms.json), die wörtlich in mindestens einem Chunk vorkommen,
und zählt, wie oft unter den Ausschnitten, die das Modell bekäme, einer den
Begriff enthält - einmal nur Vektorsuche, einmal mit Hybrid-Suche
(app/main.py: _ensure_term_hits). Vor und nach jeder Änderung an Suche,
Chunking oder Reranking laufen lassen:

    PYTHONPATH=. python tools/retrieval_eval.py [Anzahl, Default 80]
"""
import random
import sys

from dotenv import load_dotenv

load_dotenv(".env")

from app import embeddings, main, terms, vectorstore, web_index  # noqa: E402

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
    metas = list(c["metadatas"][0]) + [{**m, "source_id": m["page_id"]} for m in w["metadatas"][0]]
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


if __name__ == "__main__":
    main_eval(int(sys.argv[1]) if len(sys.argv) > 1 else 80)
