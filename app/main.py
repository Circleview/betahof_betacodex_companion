import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
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
    SummaryOut,
    TermOut,
    UrlCheckOut,
    UrlIn,
    UserOut,
    VersionOut,
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
AUDIO_DIR = DATA_DIR / "audio"

DATA_DIR.mkdir(exist_ok=True)


def _get_version() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "describe", "--tags", "--abbrev=0"],
                cwd=BASE_DIR,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "dev"


APP_VERSION = _get_version()

app = FastAPI(title="BetaCodex Wissensassistent")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/api/version", response_model=VersionOut)
def get_version():
    return VersionOut(version=APP_VERSION)


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


def _audio_extension(url: str) -> str:
    suffix = Path(urlsplit(url).path).suffix.lower()
    return suffix if suffix in extraction.AUDIO_EXTENSIONS else ".mp3"


def _existing_audio_file(source_id: str) -> Path | None:
    matches = list(AUDIO_DIR.glob(f"{source_id}.*"))
    return matches[0] if matches else None


def _sync_audio_file_from_url(source_id: str, url: str | None) -> None:
    existing = _existing_audio_file(source_id)
    if url and extraction.looks_like_audio(url):
        data = extraction.download_audio_bytes(url)
        if data:
            AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            if existing:
                existing.unlink()
            (AUDIO_DIR / f"{source_id}{_audio_extension(url)}").write_bytes(data)
            return
    if existing:
        existing.unlink()


def _delete_audio_file(source_id: str) -> None:
    existing = _existing_audio_file(source_id)
    if existing:
        existing.unlink()


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
            "listen_url": source.listen_url or "",
            "position": i,
        }
        for i in range(len(chunks))
    ]
    vectorstore.add_chunks(chunk_ids, chunks, chunk_embeddings, metadatas)
    return len(chunks)


def _to_source_out(
    entry: dict, can_view_full_text: bool = False, lang: str = i18n.DEFAULT_LANG
) -> SourceOut:
    data = dict(entry)
    if data.get("restricted") and not can_view_full_text:
        data["text"] = ""
    lang = lang if lang in ("de", "en") else i18n.DEFAULT_LANG
    data["summary"] = data.get(f"summary_{lang}") or ""
    data["key_terms"] = data.get(f"key_terms_{lang}") or []
    data["has_pdf"] = (PDF_DIR / f"{data['id']}.pdf").exists()
    data["has_audio"] = _existing_audio_file(data["id"]) is not None
    return SourceOut(**data)


def _register_all_terms(source_id: str, entry: dict) -> None:
    terms.unregister_source(source_id)
    for term in (entry.get("key_terms_de") or []) + (entry.get("key_terms_en") or []):
        terms.register_term(term, source_id)


def _generate_summary_background(source_id: str, text: str) -> None:
    result = summarization.generate_bilingual_summary(text)
    sources = _load_sources()
    if source_id not in sources:
        return
    sources[source_id]["summary_de"] = result["de"]["summary"]
    sources[source_id]["summary_en"] = result["en"]["summary"]
    sources[source_id]["key_terms_de"] = result["de"]["key_terms"]
    sources[source_id]["key_terms_en"] = result["en"]["key_terms"]
    _save_sources(sources)
    _register_all_terms(source_id, sources[source_id])


@app.post("/api/sources", response_model=SourceOut)
def add_source(
    source: SourceIn,
    background_tasks: BackgroundTasks,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    chunks, chunk_embeddings = _prepare_chunks(source, x_lang)

    source_id = str(uuid.uuid4())
    imported_at = datetime.now(timezone.utc).isoformat()
    chunk_count = _store_chunks(source_id, source, chunks, chunk_embeddings)

    sources = _load_sources()
    sources[source_id] = {
        "id": source_id,
        "title": source.title,
        "author": source.author,
        "date": source.date,
        "url": source.url,
        "listen_url": source.listen_url,
        "imported_at": imported_at,
        "chunk_count": chunk_count,
        "text": source.text.strip(),
        "restricted": source.restricted,
        "summary_de": "",
        "summary_en": "",
        "key_terms_de": [],
        "key_terms_en": [],
    }
    _save_sources(sources)
    authors.register_author(source.author or "", source_id)
    background_tasks.add_task(_generate_summary_background, source_id, source.text.strip())

    if source.pdf_upload_id:
        _consume_pdf_upload(source_id, source.pdf_upload_id)
    else:
        _sync_pdf_file_from_url(source_id, source.url)
        _sync_audio_file_from_url(source_id, source.url)

    return _to_source_out(sources[source_id], can_view_full_text=True, lang=x_lang)


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
            "listen_url": source.listen_url,
            "restricted": source.restricted,
        }
    )
    if source.summary is not None:
        sources[source_id][f"summary_{x_lang}"] = source.summary
    if source.key_terms is not None:
        sources[source_id][f"key_terms_{x_lang}"] = source.key_terms
    _save_sources(sources)

    authors.unregister_source(source_id)
    authors.register_author(source.author or "", source_id)

    if source.summary is not None or source.key_terms is not None:
        _register_all_terms(source_id, sources[source_id])

    if source.pdf_upload_id:
        _consume_pdf_upload(source_id, source.pdf_upload_id)
    elif not metadata_only:
        _sync_pdf_file_from_url(source_id, source.url)
        _sync_audio_file_from_url(source_id, source.url)

    return _to_source_out(sources[source_id], can_view_full_text=True, lang=x_lang)


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
    _delete_audio_file(source_id)


@app.get("/api/sources", response_model=list[SourceOut])
def list_sources(
    x_dev_user: str = Header(default="anon"),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    can_view_full_text = users.has_role(x_dev_user, users.QUELLEN_PFLEGER)
    sources = _load_sources()
    return [_to_source_out(entry, can_view_full_text, x_lang) for entry in sources.values()]


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


@app.get("/api/sources/{source_id}/pdf")
def get_source_pdf(
    source_id: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = _load_sources()
    if source_id not in sources:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    pdf_path = PDF_DIR / f"{source_id}.pdf"
    if not pdf_path.exists():
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    return FileResponse(pdf_path, media_type="application/pdf")


@app.post("/api/sources/{source_id}/generate-summary", response_model=SummaryOut)
def generate_source_summary(
    source_id: str,
    _user: str = Depends(require_role(users.QUELLEN_PFLEGER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    sources = _load_sources()
    if source_id not in sources:
        raise HTTPException(404, i18n.get_message("source_not_found", x_lang))

    text = sources[source_id].get("text", "")
    result = summarization.generate_bilingual_summary(text)
    sources[source_id]["summary_de"] = result["de"]["summary"]
    sources[source_id]["summary_en"] = result["en"]["summary"]
    sources[source_id]["key_terms_de"] = result["de"]["key_terms"]
    sources[source_id]["key_terms_en"] = result["en"]["key_terms"]
    _save_sources(sources)
    _register_all_terms(source_id, sources[source_id])

    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    return SummaryOut(summary=result[lang]["summary"], key_terms=result[lang]["key_terms"])


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
                listen_url=meta.get("listen_url") or None,
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


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", NoCacheStaticFiles(directory=str(STATIC_DIR), html=True), name="static")
