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


# Backlog: LLM/Internet-Fallback bei dünner Quellenlage - eigene, komplett
# getrennte Collection statt eines Flags in COLLECTION_NAME, damit die
# normale Suche (query() oben) niemals versehentlich Web-Fallback-Chunks
# mit zurückgibt, selbst wenn app/main.py:ask() sie aus irgendeinem Grund
# nicht explizit ausschließen würde. Eigener Lock/Cache-Slot statt den
# bestehenden _get_collection()/_collection_lock zu parametrisieren - hält
# den bereits bewährten Pfad für die 261 kuratierten Quellen unangetastet.
WEB_FALLBACK_COLLECTION_NAME = "web_fallback_chunks"

_web_collection = None
_web_collection_lock = threading.Lock()


def _get_web_collection():
    global _web_collection
    if _web_collection is None:
        with _web_collection_lock:
            if _web_collection is None:
                client = chromadb.PersistentClient(path=str(DB_PATH))
                _web_collection = client.get_or_create_collection(WEB_FALLBACK_COLLECTION_NAME)
    return _web_collection


def add_web_chunks(
    chunk_ids: list[str],
    texts: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
) -> None:
    collection = _get_web_collection()
    collection.add(ids=chunk_ids, embeddings=embeddings, documents=texts, metadatas=metadatas)


def query_web(embedding: list[float], top_k: int, exclude_page_ids: set[str] | None = None) -> dict:
    collection = _get_web_collection()
    count = collection.count()
    if count == 0:
        return {"ids": [[]], "documents": [[]], "metadatas": [[]], "distances": [[]]}
    if not exclude_page_ids:
        return collection.query(query_embeddings=[embedding], n_results=min(top_k, count))
    # Nutzerwunsch: einzelne Seiten lassen sich gezielt ausschließen (siehe
    # app/web_index.py:set_excluded), ohne ihre Chunks zu löschen - eine
    # Wiederaufnahme ist so ohne erneutes Crawlen/Embedden sofort wirksam.
    # Bewusst die komplette (rein lokale, überschaubar große) Collection
    # abfragen statt eine Overfetch-Menge zu schätzen: eine ausgeschlossene
    # Seite kann beliebig viele Chunks haben, ein zu knapper Overfetch würde
    # sonst zu wenige Treffer liefern.
    raw = collection.query(query_embeddings=[embedding], n_results=count)
    keep = [
        i for i, meta in enumerate(raw["metadatas"][0]) if meta.get("page_id") not in exclude_page_ids
    ][:top_k]
    return {
        "ids": [[raw["ids"][0][i] for i in keep]],
        "documents": [[raw["documents"][0][i] for i in keep]],
        "metadatas": [[raw["metadatas"][0][i] for i in keep]],
        "distances": [[raw["distances"][0][i] for i in keep]],
    }


def delete_web_page_chunks(page_id: str) -> None:
    collection = _get_web_collection()
    collection.delete(where={"page_id": page_id})
