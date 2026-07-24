import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUTHORS_FILE = BASE_DIR / "data" / "authors.json"


def _normalize(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def _load() -> dict:
    if AUTHORS_FILE.exists():
        return json.loads(AUTHORS_FILE.read_text())
    return {}


def _save(authors: dict) -> None:
    AUTHORS_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTHORS_FILE.write_text(json.dumps(authors, ensure_ascii=False, indent=2))


def register_author(name: str, source_id: str) -> None:
    name = (name or "").strip()
    if not name:
        return

    key = _normalize(name)
    authors = _load()
    entry = authors.get(key)
    if entry is None:
        entry = {"name": name, "source_ids": []}
    if source_id not in entry["source_ids"]:
        entry["source_ids"].append(source_id)
    authors[key] = entry
    _save(authors)


def unregister_source(source_id: str) -> None:
    authors = _load()
    changed = False
    for key in list(authors.keys()):
        entry = authors[key]
        if source_id in entry["source_ids"]:
            entry["source_ids"].remove(source_id)
            changed = True
            if not entry["source_ids"]:
                del authors[key]
    if changed:
        _save(authors)


def list_authors() -> list[dict]:
    authors = _load()
    entries = [
        {
            "name": entry["name"],
            "source_count": len(entry["source_ids"]),
            "source_ids": entry["source_ids"],
        }
        for entry in authors.values()
    ]
    return sorted(entries, key=lambda a: a["name"].lower())
