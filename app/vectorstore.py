import threading
from pathlib import Path

import chromadb

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "chroma"
COLLECTION_NAME = "betacodex_chunks"

_client = None
_client_lock = threading.Lock()
_collection = None
_collection_lock = threading.Lock()


def _get_client():
    global _client
    # Eigener Lock/eigene Funktion (Fix 2026-08-25, siehe tests/test_api.py:
    # client-Fixture): Client- und Collection-Erzeugung waren bisher in
    # _get_collection() verschmolzen, wodurch die Test-Suite (die _collection
    # zwecks Isolation pro Test zurücksetzt) bei JEDEM Test einen kompletten
    # neuen chromadb.PersistentClient erzeugte - dessen native Rust-Bindings
    # starten dabei einen eigenen, nie geschlossenen Thread-Pool. Bei ~350
    # Tests sammelten sich so über 1500 nie freigegebene Betriebssystem-
    # Threads an, bis die Suite praktisch stillstand. Der Client wird jetzt
    # unabhängig von der Collection nur einmal erzeugt und danach
    # wiederverwendet (Produktionsverhalten unverändert: dort werden beide
    # ohnehin nur einmal pro Prozess-Laufzeit gesetzt).
    if _client is None:
        with _client_lock:
            if _client is None:
                DB_PATH.mkdir(parents=True, exist_ok=True)
                _client = chromadb.PersistentClient(path=str(DB_PATH))
    return _client


def _get_collection():
    global _collection
    # Lock aus demselben Grund wie embeddings._get_model: preload() läuft
    # in einem Hintergrund-Thread (siehe app/main.py), eine echte Anfrage
    # kann also währenddessen gleichzeitig hier ankommen.
    if _collection is None:
        with _collection_lock:
            if _collection is None:
                _collection = _get_client().get_or_create_collection(COLLECTION_NAME)
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


def query(embedding: list[float], top_k: int = 5, where: dict | None = None) -> dict:
    # Nutzerwunsch (2026-08-31): optionaler where-Filter, damit app/main.py
    # (ask()) neben der normalen Vektorsuche zusätzlich gezielt INNERHALB der
    # Quellen einer erkannten Autor:in suchen kann (where={"source_id":
    # {"$in": [...]}}) - eine rein themenbezogene Vektorsuche über den
    # GESAMTEN Korpus findet bei einer generischen "Erzähl mir über die
    # Arbeiten von X"-Frage sonst oft keinen ihrer Chunks unter den
    # Top-Treffern, selbst wenn passende Quellen existieren. Default None
    # (= bisheriges Verhalten, unveraendert) haelt alle bestehenden Aufrufer
    # rueckwärtskompatibel.
    collection = _get_collection()
    return collection.query(query_embeddings=[embedding], n_results=top_k, where=where)


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
                # Nutzt seit dem Client/Collection-Fix (siehe _get_client()
                # oben) denselben Client wie die normale Collection, statt
                # einen zweiten, unabhängigen PersistentClient für denselben
                # DB_PATH zu erzeugen (unnötiger doppelter nativer Thread-Pool).
                _web_collection = _get_client().get_or_create_collection(WEB_FALLBACK_COLLECTION_NAME)
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
