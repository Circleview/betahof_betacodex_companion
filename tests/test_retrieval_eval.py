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


def test_ab_eval_keeps_finished_questions_when_a_later_one_fails(tmp_path, monkeypatch, capsys):
    qfile = tmp_path / "q.txt"
    qfile.write_text("# Kommentar\nErste Frage?\nZweite Frage?\n", encoding="utf-8")
    out = tmp_path / "out.md"
    result = {"answer": "Antwort [1].", "cited": 1, "delivered": 2, "web": 0.0, "swaps": [], "no_successor": 1,
              "truncated": False, "has_terms": False, "terms_hit": False, "vector_terms_hit": False}

    def fake_run(question, off):
        if question.startswith("Zweite"):
            raise RuntimeError("API weg")
        return dict(result)

    monkeypatch.setattr(ev, "_ab_run", fake_run)
    ev.ab_eval(str(qfile), out_path=str(out))

    text = out.read_text(encoding="utf-8")
    assert "Erste Frage?" in text and "Antwort [1]." in text
    assert "Zweite Frage?" in text and "API weg" in text
    assert "Überschuss-Kandidaten ohne Nachrücker" in capsys.readouterr().out


def test_quellen_eval_lists_distinct_sources_and_authors_per_question(tmp_path, monkeypatch, capsys):
    """Idee 78404054: Quellen je Frage ohne Modellaufruf, z. B. mit einer Kopie der Produktionsdaten."""
    from types import SimpleNamespace as R
    qfile = tmp_path / "q.txt"
    qfile.write_text("# Kommentar\nWas ist die Zellstruktur?\n", encoding="utf-8")
    refs = [R(source_id="f848aaaa", authors=["Niels Pflaeging"]), R(source_id="f848aaaa", authors=["Niels Pflaeging"]),
            R(source_id="7d19bbbb", authors=["Peter Pröll"])]
    calls = []

    def fake_context(question, history, lang, top_k, *args, **kwargs):
        calls.append((question, history, top_k))
        return [], refs, [], None

    monkeypatch.setattr(ev.main, "_ask_context", fake_context)
    ev.quellen_eval(str(qfile))
    out = capsys.readouterr().out
    assert calls == [("Was ist die Zellstruktur?", [], ev.TOP_K)]
    assert "Was ist die Zellstruktur? | Quellen 2 | Niels Pflaeging, Peter Pröll | f848 f848 7d19" in out
