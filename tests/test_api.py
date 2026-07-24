import pytest
from fastapi.testclient import TestClient

from app import embeddings, llm, vectorstore
from app import main as main_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_module, "SOURCES_FILE", tmp_path / "sources.json")

    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_client", None)
    monkeypatch.setattr(vectorstore, "_collection", None)

    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [1.0, 0.0])
    monkeypatch.setattr(llm, "answer_question", lambda question, chunks: "Testantwort [1].")

    return TestClient(main_module.app)


def test_add_source_creates_chunks(client):
    response = client.post(
        "/api/sources",
        json={
            "title": "Testquelle",
            "author": "Autor X",
            "date": "2024-01-01",
            "url": "https://example.org",
            "text": "Ein kurzer Beispieltext für den Test.",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Testquelle"
    assert data["chunk_count"] == 1


def test_add_source_rejects_empty_text(client):
    response = client.post("/api/sources", json={"title": "Leer", "text": "   "})
    assert response.status_code == 400


def test_list_sources_returns_imported_sources(client):
    client.post("/api/sources", json={"title": "Quelle A", "text": "Text A"})
    response = client.get("/api/sources")
    assert response.status_code == 200
    titles = [s["title"] for s in response.json()]
    assert "Quelle A" in titles


def test_ask_without_sources_returns_400(client):
    response = client.post("/api/ask", json={"question": "Was ist der BetaCodex?"})
    assert response.status_code == 400


def test_ask_returns_answer_with_sources(client):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "author": "Autor Y",
            "date": "2023-05-01",
            "url": "https://example.org/quelle",
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Testantwort [1]."
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "BetaCodex Quelle"
