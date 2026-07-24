import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TERMS_FILE = BASE_DIR / "data" / "terms.json"


def _normalize(term: str) -> str:
    return " ".join(term.strip().split()).lower()


def _load() -> dict:
    if TERMS_FILE.exists():
        return json.loads(TERMS_FILE.read_text())
    return {}


def _save(terms: dict) -> None:
    TERMS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TERMS_FILE.write_text(json.dumps(terms, ensure_ascii=False, indent=2))


def register_term(term: str, source_id: str) -> None:
    term = (term or "").strip()
    if not term:
        return

    key = _normalize(term)
    terms = _load()
    entry = terms.get(key)
    if entry is None:
        entry = {"term": term, "source_ids": []}
    if source_id not in entry["source_ids"]:
        entry["source_ids"].append(source_id)
    terms[key] = entry
    _save(terms)


def unregister_source(source_id: str) -> None:
    terms = _load()
    changed = False
    for key in list(terms.keys()):
        entry = terms[key]
        if source_id in entry["source_ids"]:
            entry["source_ids"].remove(source_id)
            changed = True
            if not entry["source_ids"]:
                del terms[key]
    if changed:
        _save(terms)


def list_terms() -> list[dict]:
    terms = _load()
    entries = [
        {
            "term": entry["term"],
            "source_count": len(entry["source_ids"]),
            "source_ids": entry["source_ids"],
        }
        for entry in terms.values()
    ]
    return sorted(entries, key=lambda t: t["term"].lower())
