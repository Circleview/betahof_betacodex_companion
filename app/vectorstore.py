from pathlib import Path

import chromadb

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"
COLLECTION_NAME = "betacodex_chunks"

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        DB_PATH.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(DB_PATH))
        _collection = _client.get_or_create_collection(COLLECTION_NAME)
    return _collection


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
