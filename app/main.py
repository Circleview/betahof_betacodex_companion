import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app import chunking, embeddings, extraction, llm, vectorstore
from app.models import (
    AnswerOut,
    ChunkRef,
    ExtractedSource,
    QuestionIn,
    SourceIn,
    SourceOut,
    UrlIn,
)

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SOURCES_FILE = DATA_DIR / "sources.json"
STATIC_DIR = BASE_DIR / "static"

DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="BetaCodex Wissensassistent")


def _load_sources() -> dict:
    if SOURCES_FILE.exists():
        return json.loads(SOURCES_FILE.read_text())
    return {}


def _save_sources(sources: dict) -> None:
    SOURCES_FILE.write_text(json.dumps(sources, ensure_ascii=False, indent=2))


@app.post("/api/sources", response_model=SourceOut)
def add_source(source: SourceIn):
    text = source.text.strip()
    if not text:
        raise HTTPException(400, "Text darf nicht leer sein.")

    chunks = chunking.chunk_text(text)
    if not chunks:
        raise HTTPException(400, "Aus dem Text konnten keine Chunks erzeugt werden.")

    source_id = str(uuid.uuid4())
    imported_at = datetime.now(timezone.utc).isoformat()

    chunk_ids = [f"{source_id}::{i}" for i in range(len(chunks))]
    chunk_embeddings = embeddings.embed_passages(chunks)
    metadatas = [
        {
            "source_id": source_id,
            "title": source.title,
            "author": source.author or "",
            "date": source.date or "",
            "url": source.url or "",
            "position": i,
        }
        for i in range(len(chunks))
    ]
    vectorstore.add_chunks(chunk_ids, chunks, chunk_embeddings, metadatas)

    sources = _load_sources()
    sources[source_id] = {
        "id": source_id,
        "title": source.title,
        "author": source.author,
        "date": source.date,
        "url": source.url,
        "imported_at": imported_at,
        "chunk_count": len(chunks),
    }
    _save_sources(sources)

    return SourceOut(**sources[source_id])


@app.get("/api/sources", response_model=list[SourceOut])
def list_sources():
    sources = _load_sources()
    return list(sources.values())


@app.post("/api/extract-url", response_model=ExtractedSource)
def extract_url(payload: UrlIn):
    result = extraction.extract_from_url(payload.url)
    return ExtractedSource(**result)


@app.post("/api/ask", response_model=AnswerOut)
def ask(question: QuestionIn):
    sources = _load_sources()
    if not sources:
        raise HTTPException(400, "Noch keine Quellen importiert.")

    query_embedding = embeddings.embed_query(question.question)
    results = vectorstore.query(query_embedding, top_k=question.top_k)

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]

    if not ids:
        raise HTTPException(400, "Keine passenden Chunks gefunden.")

    chunk_refs = []
    llm_chunks = []
    for chunk_id, doc, meta in zip(ids, documents, metadatas):
        chunk_refs.append(
            ChunkRef(
                chunk_id=chunk_id,
                source_id=meta["source_id"],
                title=meta["title"],
                author=meta["author"] or None,
                date=meta["date"] or None,
                url=meta["url"] or None,
                position=meta["position"],
                text=doc,
            )
        )
        llm_chunks.append(
            {
                "title": meta["title"],
                "author": meta["author"] or "unbekannt",
                "date": meta["date"] or "unbekannt",
                "text": doc,
            }
        )

    answer_text = llm.answer_question(question.question, llm_chunks)

    return AnswerOut(answer=answer_text, sources=chunk_refs)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
