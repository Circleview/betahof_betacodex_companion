"""Nutzerwunsch (Positivselektion, siehe app/web_crawler.py): manche
Websites bieten über url_prefix/post-sitemap.xml zu wenige eindeutig
zuordenbare Unterseiten, um sie wie sonst üblich automatisch zu
indizieren und nur nachträglich zu bereinigen ("Negativselektion").
Stattdessen werden hier gegen den bestehenden kuratierten Quellenbestand
bewertete Kandidaten-Seiten abgelegt, aus denen Quellen-Pfleger:innen
gezielt einzelne für die Aufnahme auswählen ("Positivselektion") - bewusst
getrennt von app/web_index.py: dort stehen nur bereits WIRKLICH
indizierte Seiten (mit Chunks in der Chroma-Collection), hier nur
Vorschläge (Titel+Kurztext, keine Chunks/Embeddings gespeichert)."""
import json
import os
import threading
import uuid
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WEB_CANDIDATES_FILE = BASE_DIR / "data" / "web_candidates.json"

_web_candidates_lock = threading.Lock()


def _load() -> dict:
    if not WEB_CANDIDATES_FILE.exists():
        return {}
    try:
        return json.loads(WEB_CANDIDATES_FILE.read_text())
    except Exception:
        return {}


def _save(candidates: dict) -> None:
    WEB_CANDIDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = WEB_CANDIDATES_FILE.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(candidates, ensure_ascii=False, indent=2))
    tmp.replace(WEB_CANDIDATES_FILE)


def candidates_for_entry(allowlist_entry_id: str, status: str | None = "pending") -> dict:
    all_candidates = _load()
    return {
        cid: c
        for cid, c in all_candidates.items()
        if c.get("allowlist_entry_id") == allowlist_entry_id and (status is None or c.get("status") == status)
    }


def get_candidate(candidate_id: str) -> dict | None:
    return _load().get(candidate_id)


def upsert_candidates(allowlist_entry_id: str, candidates: list[dict]) -> None:
    """Fügt neu entdeckte Kandidaten hinzu bzw. aktualisiert deren Score/
    Titel/Kurztext, FALLS sie noch "pending" sind (der Korpus kann seit dem
    letzten Lauf gewachsen sein, siehe app/web_crawler.py). Bereits von
    Menschenhand entschiedene Kandidaten (approved/rejected) werden bewusst
    NICHT erneut vorgeschlagen - sonst würde ein abgelehnter Kandidat bei
    jedem wöchentlichen Lauf erneut in der Liste auftauchen."""
    with _web_candidates_lock:
        all_candidates = _load()
        by_url = {
            c["url"]: cid
            for cid, c in all_candidates.items()
            if c.get("allowlist_entry_id") == allowlist_entry_id
        }
        for candidate in candidates:
            existing_id = by_url.get(candidate["url"])
            if existing_id is not None:
                if all_candidates[existing_id].get("status") != "pending":
                    continue
                all_candidates[existing_id].update(
                    title=candidate["title"],
                    snippet=candidate["snippet"],
                    relevance_score=candidate["relevance_score"],
                )
                continue
            candidate_id = str(uuid.uuid4())
            all_candidates[candidate_id] = {
                "allowlist_entry_id": allowlist_entry_id,
                "url": candidate["url"],
                "title": candidate["title"],
                "snippet": candidate["snippet"],
                "relevance_score": candidate["relevance_score"],
                "status": "pending",
            }
        _save(all_candidates)


def set_status(candidate_id: str, status: str) -> dict | None:
    with _web_candidates_lock:
        all_candidates = _load()
        candidate = all_candidates.get(candidate_id)
        if candidate is None:
            return None
        candidate["status"] = status
        _save(all_candidates)
        return {"id": candidate_id, **candidate}


def delete_candidate(candidate_id: str) -> bool:
    with _web_candidates_lock:
        all_candidates = _load()
        if candidate_id not in all_candidates:
            return False
        del all_candidates[candidate_id]
        _save(all_candidates)
        return True


def delete_candidates_for_entry(allowlist_entry_id: str) -> None:
    with _web_candidates_lock:
        all_candidates = _load()
        remaining = {
            cid: c for cid, c in all_candidates.items() if c.get("allowlist_entry_id") != allowlist_entry_id
        }
        _save(remaining)
