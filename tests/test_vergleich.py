"""Dev-Vergleichsseite (Idee af02ecb1): Antwort ohne/mit Beraterstimme (und
optional Sonnet) nebeneinander. Alles gemockt - kein Modell-, kein Suchaufruf."""
import pytest
from fastapi.testclient import TestClient

from app import llm
from app import main as main_module

CHUNKS = [
    {"title": "Quelle Eins", "author": "A", "date": "2020", "text": "Text eins.", "source_key": "s1"},
    {"title": "Quelle Zwei", "author": "B", "date": "2021", "text": "Text zwei.", "source_key": "s2"},
]
PAGES = ["/dev/vergleich", "/dev/vergleich.js", "/dev/vergleich.css"]


@pytest.fixture
def env(tmp_path, monkeypatch):
    voice = tmp_path / "stimme.md"
    voice.write_text("STIMME VERSION EINS", encoding="utf-8")
    monkeypatch.setattr(llm, "STIMME_FILE", voice)
    calls = {"context": [], "stream": []}

    def fake_context(question, history, x_lang, top_k=5, usage_email=None, max_per_source=None):
        calls["context"].append({"question": question, "history": history})
        return CHUNKS, [], [], [0.0]

    def fake_stream(question, chunks, lang="de", author_bios=None, history=None, usage=None,
                    system_prompt=None, model=llm.MODEL_NAME, max_tokens=1536):
        calls["stream"].append(
            {"chunks": chunks, "history": history, "system": system_prompt, "model": model,
             "max_tokens": max_tokens, "usage": usage}
        )
        yield f"Antwort {len(calls['stream'])} zur These [1].\n\n---QUOTES---\n[1]: \"Text eins.\"\n"

    monkeypatch.setattr(main_module, "_ask_context", fake_context)
    monkeypatch.setattr(llm, "stream_answer_question", fake_stream)
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", True)
    return {"calls": calls, "voice": voice, "client": TestClient(main_module.app)}


def post(env, **body):
    body.setdefault("question", "Frage?")
    return env["client"].post("/api/dev/vergleich", json=body)


def test_everything_is_404_when_dev_is_off(env, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)
    c = env["client"]
    for path in PAGES + ["/vergleich", "/vergleich.html"]:
        assert c.get(path).status_code == 404, path
    assert post(env).status_code == 404
    assert env["calls"] == {"context": [], "stream": []}


def test_pages_are_served_in_dev_without_inline_script(env):
    c = env["client"]
    html = c.get("/dev/vergleich")
    assert html.status_code == 200 and "text/html" in html.headers["content-type"]
    assert "/dev/vergleich.js" in html.text and "/dev/vergleich.css" in html.text
    assert "<script>" not in html.text
    assert "javascript" in c.get("/dev/vergleich.js").headers["content-type"]
    assert "text/css" in c.get("/dev/vergleich.css").headers["content-type"]


def test_round_searches_once_and_gives_same_chunks_to_each_column(env):
    r = post(env)
    assert r.status_code == 200
    assert len(env["calls"]["context"]) == 1
    streams = env["calls"]["stream"]
    assert len(streams) == 2
    assert all(s["chunks"] == CHUNKS for s in streams)
    assert r.json()["sources"] == ["Quelle Eins", "Quelle Zwei"]


def test_left_column_has_no_voice_and_right_column_has_it(env):
    post(env)
    by_system = {s["system"] for s in env["calls"]["stream"]}
    assert llm._BASE_PROMPTS["de"] in by_system
    voiced = [s["system"] for s in env["calls"]["stream"] if s["system"] != llm._BASE_PROMPTS["de"]]
    assert len(voiced) == 1 and voiced[0] == llm.build_chat_system("de", "STIMME VERSION EINS")


def test_result_has_answer_quotes_and_counts_per_column(env):
    cols = post(env).json()["columns"]
    assert set(cols) == {"basis", "stimme"}
    col = cols["basis"]
    assert col["answer"].startswith("Antwort ") and "---QUOTES---" not in col["answer"]
    assert col["quotes"] == {"1": ["Text eins."]}
    assert col["quote_count"] == 1
    assert col["words"] == len(col["answer"].split())
    assert col["error"] is None


def test_each_column_gets_its_own_history_and_search_uses_left_one(env):
    h_left = [{"question": "q1", "answer": "links"}]
    h_right = [{"question": "q1", "answer": "rechts"}]
    post(env, histories={"basis": h_left, "stimme": h_right})
    assert env["calls"]["context"][0]["history"] == h_left
    histories = [s["history"] for s in env["calls"]["stream"]]
    assert h_left in histories and h_right in histories


def test_sonnet_only_when_requested_with_own_model_and_tokens(env):
    post(env)
    assert {s["model"] for s in env["calls"]["stream"]} == {llm.MODEL_NAME}
    assert {s["max_tokens"] for s in env["calls"]["stream"]} == {1536}
    env["calls"]["stream"].clear()
    cols = post(env, variants=["basis", "stimme", "sonnet"]).json()["columns"]
    assert set(cols) == {"basis", "stimme", "sonnet"}
    sonnet = [s for s in env["calls"]["stream"] if s["model"] == "claude-sonnet-5"]
    assert len(sonnet) == 1 and sonnet[0]["max_tokens"] == 4096
    assert sonnet[0]["system"] == llm.build_chat_system("de", "STIMME VERSION EINS")


def test_costs_go_to_channel_vergleich(env):
    post(env)
    assert len(env["calls"]["stream"]) == 2
    assert all(s["usage"]["channel"] == "vergleich" for s in env["calls"]["stream"])


def test_unknown_variant_gives_400_and_no_calls(env):
    assert post(env, variants=["basis", "gpt"]).status_code == 400
    assert env["calls"] == {"context": [], "stream": []}


def test_voice_file_change_between_rounds_takes_effect(env):
    post(env)
    env["voice"].write_text("STIMME VERSION ZWEI", encoding="utf-8")
    env["calls"]["stream"].clear()
    post(env)
    systems = [s["system"] for s in env["calls"]["stream"]]
    assert llm.build_chat_system("de", "STIMME VERSION ZWEI") in systems
    assert llm.build_chat_system("de", "STIMME VERSION EINS") not in systems


def test_missing_voice_file_fails_only_voice_column(env):
    env["voice"].unlink()
    r = post(env)
    assert r.status_code == 200
    cols = r.json()["columns"]
    assert cols["stimme"]["error"] and cols["stimme"]["answer"] == ""
    assert cols["basis"]["error"] is None and cols["basis"]["answer"]
