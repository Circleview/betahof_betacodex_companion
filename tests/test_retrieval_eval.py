"""Idee 3c32da30: Auswertungs-Bausteine von tools/retrieval_eval.py --ab (ohne Modellaufruf)."""
from tools import retrieval_eval as ev


def test_cited_keys_counts_distinct_sources_for_adjacent_and_listed_references():
    chunks = [{"source_key": "a"}, {"source_key": "a"}, {"source_key": "b"}, {"source_key": "c"}]
    # [1][2] = 2 Chunks derselben Quelle, [3, 4] = zwei weitere, [9] existiert nicht
    assert ev.cited_keys("Satz [1][2]. Noch einer [3, 4]. Unsinn [9].", chunks) == {"a", "b", "c"}
    assert ev.cited_keys("Ohne Verweis.", chunks) == set()


def test_web_share_is_fraction_of_cited_chunks_from_web():
    chunks = [{"source_key": "a", "web": False}, {"source_key": "w", "web": True}]
    assert ev.web_share("Beides [1][2].", chunks) == 0.5
    assert ev.web_share("Nichts.", chunks) == 0.0
