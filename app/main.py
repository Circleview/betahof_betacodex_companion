import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles

load_dotenv()

from app import (
    authors,
    chunking,
    embeddings,
    extraction,
    i18n,
    llm,
    monitoring,
    summarization,
    terms,
    users,
    vectorstore,
)
from app.models import (
    AnswerOut,
    AuthorOut,
    ChunkRef,
    ExtractedSource,
    ExtractedUpload,
    QuestionIn,
    SourceIn,
    SourceOut,
    TermOut,
    UrlCheckOut,
    UrlIn,
    UserOut,
)


def require_role(role: str):
    def check(
        x_dev_user: str = Header(default="anon"),
        x_lang: str = Header(default=i18n.DEFAULT_LANG),
    ):
        if not users.has_role(x_dev_user, role):
            raise HTTPException(
                403,
                i18n.get_message("role_required", x_lang, role=role, user=x_dev_user),
            )
        return x_dev_user

    return check


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SOURCES_FILE = DATA_DIR / "sources.json"
STATIC_DIR = BASE_DIR / "static"
PDF_DIR = DATA_DIR / "pdfs"
PDF_UPLOAD_STAGING_DIR = DATA_DIR / "pdf_uploads"

DATA_DIR.mkdir(exist_ok=True)

app = FastAPI(title="BetaCodex Wissensassistent")


def _load_sources() -> dict:
    if SOURCES_FILE.exists():
        return json.loads(SOURCES_FILE.read_text())
    return {}


def _save_sources(sources: dict) -> None:
    SOURCES_FILE.write_text(json.dumps(sources, ensure_ascii=False, indent=2))


def _prepare_chunks(source: SourceIn, lang: str) -> tuple[list[str], list[list[float]]]:
    text = source.text.strip()
    if not text:
        raise HTTPException(400, i18n.get_message("text_empty", lang))

    chunks = chunking.chunk_text(text)
    if not chunks:
        raise HTTPException(400, i18n.get_message("no_chunks", lang))

    chunk_embeddings = embeddings.embed_passages(chunks)
    return chunks, chunk_embeddings


def _consume_pdf_upload(source_id: str, upload_id: str) -> None:
    staged_path = PDF_UPLOAD_STAGING_DIR / f"{upload_id}.pdf"
    if not staged_path.exists():
        return
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    staged_path.replace(PDF_DIR / f"{source_id}.pdf")


def _sync_pdf_file_from_url(source_id: str, url: str | None) -> None:
    pdf_path = PDF_DIR / f"{source_id}.pdf"
    if url and extraction.looks_like_pdf(url):
        data = extraction.download_pdf_bytes(url)
        if data:
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(data)
            return
    if pdf_path.exists():
        pdf_path.unlink()


def _delete_pdf_file(source_id: str) -> None:
    pdf_path = PDF_DIR / f"{source_id}.pdf"
    if pdf_path.exists():
        pdf_path.unlink()


def _store_chunks(
    source_id: str, source: SourceIn, chunks: list[str], chunk_embeddings: list[list[float]]
) -> int:
    chunk_ids = [f"{source_id}::{i}" for i in range(len(chunks))]
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
    return len(chunks)


def _to_source_out(entry: dict) -> SourceOut:
    data = dict(entry)
    if data.get("restricted"):
        data["text"] = ""
    return SourceOut(**data)


@app.post("/api/sources", response_model=SourceOut)
def add_source(
    source: SourceIn,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    chunks, chunk_embeddings = _prepare_chunks(source, x_lang)

    source_id = str(uuid.uuid4())
    imported_at = datetime.now(timezone.utc).isoformat()
    chunk_count = _store_chunks(source_id, source, chunks, chunk_embeddings)

    summary_result = summarization.generate_summary(source.text.strip(), lang=x_lang)

    sources = _load_sources()
    sources[source_id] = {
        "id": source_id,
        "title": source.title,
        "author": source.author,
        "date": source.date,
        "url": source.url,
        "imported_at": imported_at,
        "chunk_count": chunk_count,
        "text": source.text.strip(),
        "restricted": source.restricted,
        "summary": summary_result["summary"],
        "key_terms": summary_result["key_terms"],
    }
    _save_sources(sources)
    authors.register_author(source.author or "", source_id)
    for term in summary_result["key_terms"]:
        terms.register_term(term, source_id)

    if source.pdf_upload_id:
        _consume_pdf_upload(source_id, source.pdf_upload_id)
    else:
        _sync_pdf_file_from_url(source_id, source.url)

    return _to_source_out(sources[source_id])


@app.put("/api/sources/{source_id}", response_model=SourceOut)
def update_source(
    source_id: str,
    source: SourceIn,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = _load_sources()
    if source_id not in sources:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    metadata_only = bool(sources[source_id].get("restricted")) and not source.text.strip()

    if not metadata_only:
        chunks, chunk_embeddings = _prepare_chunks(source, x_lang)
        vectorstore.delete_source_chunks(source_id)
        chunk_count = _store_chunks(source_id, source, chunks, chunk_embeddings)
        sources[source_id]["text"] = source.text.strip()
        sources[source_id]["chunk_count"] = chunk_count

    sources[source_id].update(
        {
            "title": source.title,
            "author": source.author,
            "date": source.date,
            "url": source.url,
            "restricted": source.restricted,
        }
    )
    if source.summary is not None:
        sources[source_id]["summary"] = source.summary
    if source.key_terms is not None:
        sources[source_id]["key_terms"] = source.key_terms
    _save_sources(sources)

    authors.unregister_source(source_id)
    authors.register_author(source.author or "", source_id)

    if source.summary is not None or source.key_terms is not None:
        terms.unregister_source(source_id)
        for term in sources[source_id].get("key_terms", []):
            terms.register_term(term, source_id)

    if source.pdf_upload_id:
        _consume_pdf_upload(source_id, source.pdf_upload_id)
    elif not metadata_only:
        _sync_pdf_file_from_url(source_id, source.url)

    return _to_source_out(sources[source_id])


@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(
    source_id: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = _load_sources()
    if source_id not in sources:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    vectorstore.delete_source_chunks(source_id)
    del sources[source_id]
    _save_sources(sources)
    authors.unregister_source(source_id)
    terms.unregister_source(source_id)
    _delete_pdf_file(source_id)


@app.get("/api/sources", response_model=list[SourceOut])
def list_sources():
    sources = _load_sources()
    return [_to_source_out(entry) for entry in sources.values()]


@app.get("/api/authors", response_model=list[AuthorOut])
def list_authors():
    return authors.list_authors()


@app.get("/api/terms", response_model=list[TermOut])
def list_terms():
    return terms.list_terms()


@app.get("/api/dev/users", response_model=list[UserOut])
def dev_list_users():
    return users.list_users()


@app.get("/api/sources/{source_id}/check-url", response_model=UrlCheckOut)
def check_source_url(
    source_id: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = _load_sources()
    if source_id not in sources:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    url = sources[source_id].get("url")
    if not url:
        return UrlCheckOut(has_url=False)

    result = monitoring.check_url(url)
    return UrlCheckOut(has_url=True, **result)


@app.post("/api/extract-pdf-upload", response_model=ExtractedUpload)
def extract_pdf_upload(
    file: UploadFile = File(...),
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
):
    data = file.file.read()
    result = extraction.extract_pdf(data)

    upload_id = str(uuid.uuid4())
    PDF_UPLOAD_STAGING_DIR.mkdir(parents=True, exist_ok=True)
    (PDF_UPLOAD_STAGING_DIR / f"{upload_id}.pdf").write_bytes(data)

    return ExtractedUpload(**result, upload_id=upload_id)


@app.post("/api/extract-url", response_model=ExtractedSource)
def extract_url(payload: UrlIn, _user: str = Depends(require_role(users.QUELLEN_PFLEGER))):
    result = extraction.extract_from_url(payload.url)
    return ExtractedSource(**result)


@app.post("/api/ask", response_model=AnswerOut)
def ask(question: QuestionIn, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    sources = _load_sources()
    if not sources:
        raise HTTPException(400, i18n.get_message("no_sources", x_lang))

    query_embedding = embeddings.embed_query(question.question)
    results = vectorstore.query(query_embedding, top_k=question.top_k)

    ids = results["ids"][0]
    documents = results["documents"][0]
    metadatas = results["metadatas"][0]

    if not ids:
        raise HTTPException(400, i18n.get_message("no_matching_chunks", x_lang))

    unknown_label = "unbekannt" if x_lang == "de" else "unknown"

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
                "author": meta["author"] or unknown_label,
                "date": meta["date"] or unknown_label,
                "text": doc,
            }
        )

    answer_text = llm.answer_question(question.question, llm_chunks, lang=x_lang)

    return AnswerOut(answer=answer_text, sources=chunk_refs)


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
