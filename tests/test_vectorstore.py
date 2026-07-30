import threading
import time

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


def test_delete_source_chunks_removes_only_matching_source(tmp_path, monkeypatch):
    _reset_vectorstore(tmp_path, monkeypatch)

    vectorstore.add_chunks(
        ["a::0", "b::0"],
        ["Quelle A", "Quelle B"],
        [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        [{"source_id": "a", "position": 0}, {"source_id": "b", "position": 0}],
    )

    vectorstore.delete_source_chunks("a")

    result = vectorstore.query([1.0, 0.0, 0.0], top_k=5)
    assert result["ids"][0] == ["b::0"]


def test_preload_opens_the_collection_eagerly(tmp_path, monkeypatch):
    """Backlog: die Collection soll beim Server-Start geöffnet werden statt
    lazy bei der ersten echten Anfrage."""
    _reset_vectorstore(tmp_path, monkeypatch)

    assert vectorstore._collection is None
    vectorstore.preload()
    assert vectorstore._collection is not None


def test_get_collection_is_thread_safe_and_opens_only_once(tmp_path, monkeypatch):
    """Regression: preload() läuft in einem Hintergrund-Thread (siehe
    app/main.py), eine echte Anfrage kann also gleichzeitig add_chunks()/
    query() aufrufen, während die Collection noch geöffnet wird. Ohne Lock
    würde das parallel mehrfach passieren."""
    _reset_vectorstore(tmp_path, monkeypatch)
    call_count = {"n": 0}

    class SlowFakeClient:
        def __init__(self, *args, **kwargs):
            call_count["n"] += 1
            time.sleep(0.2)

        def get_or_create_collection(self, name):
            return object()

    monkeypatch.setattr(vectorstore.chromadb, "PersistentClient", SlowFakeClient)

    threads = [threading.Thread(target=vectorstore._get_collection) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert call_count["n"] == 1
