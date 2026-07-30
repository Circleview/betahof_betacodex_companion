import threading
from pathlib import Path

import chromadb

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"
COLLECTION_NAME = "betacodex_chunks"

_client = None
_collection = None
_collection_lock = threading.Lock()


def _get_collection():
    global _client, _collection
    # Lock aus demselben Grund wie embeddings._get_model: preload() läuft
    # in einem Hintergrund-Thread (siehe app/main.py), eine echte Anfrage
    # kann also währenddessen gleichzeitig hier ankommen.
    if _collection is None:
        with _collection_lock:
            if _collection is None:
                DB_PATH.mkdir(parents=True, exist_ok=True)
                _client = chromadb.PersistentClient(path=str(DB_PATH))
                _collection = _client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def preload() -> None:
    """Öffnet die Chroma-Collection vorab (siehe app/main.py: läuft dort in
    einem Hintergrund-Thread beim Server-Start) statt lazy bei der ersten
    echten Anfrage (siehe embeddings.preload_model - gleicher Grund, hier
    deutlich kleinerer Anteil an der Ladezeit)."""
    _get_collection()


def add_chunks(
    chunk_ids: list[str],
    texts: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    collection = _get_collection()
    collection.add(ids=chunk_ids, embeddings=embeddings, documents=texts, metadatas=metadatas)


def query(embedding: list[float], top_k: int = 5) -> dict:
    collection = _get_collection()
    return collection.query(query_embeddings=[embedding], n_results=top_k)


def delete_source_chunks(source_id: str) -> None:
    collection = _get_collection()
    collection.delete(where={"source_id": source_id})
