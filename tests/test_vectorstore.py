from app import vectorstore


def _reset_vectorstore(tmp_path, monkeypatch):
    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_client", None)
    monkeypatch.setattr(vectorstore, "_collection", None)


def test_add_and_query_roundtrip(tmp_path, monkeypatch):
    _reset_vectorstore(tmp_path, monkeypatch)

    ids = ["a::0", "a::1"]
    texts = ["erster Chunk", "zweiter Chunk"]
    embeddings = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    metadatas = [
        {"source_id": "a", "position": 0},
        {"source_id": "a", "position": 1},
    ]

    vectorstore.add_chunks(ids, texts, embeddings, metadatas)
    result = vectorstore.query([1.0, 0.0, 0.0], top_k=1)

    assert result["ids"][0][0] == "a::0"
    assert result["documents"][0][0] == "erster Chunk"


def test_query_returns_fewer_results_than_top_k_if_not_enough_data(tmp_path, monkeypatch):
    _reset_vectorstore(tmp_path, monkeypatch)

    vectorstore.add_chunks(
        ["a::0"], ["einziger Chunk"], [[1.0, 0.0, 0.0]], [{"source_id": "a", "position": 0}]
    )

    result = vectorstore.query([1.0, 0.0, 0.0], top_k=5)
    assert len(result["ids"][0]) == 1
