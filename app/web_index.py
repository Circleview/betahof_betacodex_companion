"""Registry der einzelnen, von app/web_crawler.py bereits indizierten
Unterseiten je Allowlist-Eintrag (Backlog: LLM/Internet-Fallback bei
dünner Quellenlage) - bewusst getrennt von sources.json/app/web_allowlist.py:
jeder Eintrag hier ist eine einzelne gecrawlte URL (nicht eine ganze
freigegebene Domain/Sektion), mit gerade so viel Metadatum, wie
app/main.py:ask() für eine zitierfähige ChunkRef braucht (title/url/
indexed_at). Die eigentlichen Text-Chunks liegen in der separaten
Chroma-Collection app/vectorstore.WEB_FALLBACK_COLLECTION_NAME."""
import json
import os
import threading
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_INDEX_FILE = BASE_DIR / "data" / "web_index.json"

_web_index_lock = threading.Lock()


def _load() -> dict:
    if not WEB_INDEX_FILE.exists():
        return {}
    try:
        return json.loads(WEB_INDEX_FILE.read_text())
    except Exception:
        return {}


def _save(pages: dict) -> None:
    WEB_INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WEB_INDEX_FILE.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(pages, ensure_ascii=False, indent=2))
    tmp.replace(WEB_INDEX_FILE)


def list_pages() -> dict:
    return _load()


def pages_for_entry(allowlist_entry_id: str) -> dict:
    return {pid: p for pid, p in _load().items() if p.get("allowlist_entry_id") == allowlist_entry_id}


def get_page(page_id: str) -> dict | None:
    return _load().get(page_id)


def upsert_page(
    page_id: str,
    *,
    allowlist_entry_id: str,
    url: str,
    title: str,
    indexed_at: str,
    chunk_count: int,
    date: str | None = None,
) -> None:
    with _web_index_lock:
        pages = _load()
        pages[page_id] = {
            "allowlist_entry_id": allowlist_entry_id,
            "url": url,
            "title": title,
            "date": date,
            "indexed_at": indexed_at,
            "chunk_count": chunk_count,
            # Nutzerwunsch: einzelne Seiten sollen gezielt aus dem Fallback
            # ausgeschlossen werden können (z.B. werbliche Inhalte), ohne
            # sie aus der Übersicht zu entfernen - siehe set_excluded/
            # excluded_page_ids sowie app/vectorstore.py:query_web.
            "excluded": False,
        }
        _save(pages)


def set_excluded(page_id: str, excluded: bool) -> dict | None:
    with _web_index_lock:
        pages = _load()
        page = pages.get(page_id)
        if page is None:
            return None
        page["excluded"] = excluded
        _save(pages)
        return {"id": page_id, **page}


def excluded_page_ids() -> set[str]:
    return {pid for pid, p in _load().items() if p.get("excluded")}


def active_page_count_for_entry(allowlist_entry_id: str) -> int:
    """Nutzerwunsch: die angezeigte Seitenzahl je Allowlist-Eintrag soll nur
    tatsächlich aktive (nicht ausgeschlossene) Seiten zählen - schließt
    eine Pfleger:in z.B. 20 von 40 Seiten aus, soll die Übersicht 20 zeigen,
    nicht weiterhin 40."""
    return sum(1 for p in pages_for_entry(allowlist_entry_id).values() if not p.get("excluded"))


def delete_pages_for_entry(allowlist_entry_id: str) -> list[str]:
    """Entfernt alle Seiten-Einträge eines Allowlist-Eintrags (z.B. weil
    dieser gelöscht wurde) und gibt die betroffenen page_ids zurück - der
    Aufrufer nutzt sie, um dieselben Chunks auch aus der Chroma-Collection
    zu entfernen (siehe app/main.py delete_web_allowlist_entry)."""
    with _web_index_lock:
        pages = _load()
        removed_ids = [pid for pid, p in pages.items() if p.get("allowlist_entry_id") == allowlist_entry_id]
        for pid in removed_ids:
            del pages[pid]
        _save(pages)
        return removed_ids
