import difflib
import json
import re
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUTHORS_FILE = BASE_DIR / "data" / "authors.json"

# Ab dieser Nachnamenlänge lohnt sich ein Tippfehler-toleranter Abgleich -
# bei kürzeren Nachnamen (z.B. "Li") würde ein Tippfehler-Radius zu viele
# unbeteiligte Wörter fälschlich treffen.
_FUZZY_MIN_SURNAME_LEN = 4
_FUZZY_CUTOFF = 0.8


def _normalize(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def normalize_name(name: str) -> str:
    """Öffentlicher Zugriff auf _normalize() für Abgleiche außerhalb dieses
    Moduls (z.B. app/main.py:_build_knowledge_graph gegen Schlagworte)."""
    return _normalize(name)


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


def find_mentioned(text: str) -> list[str]:
    """Findet registrierte Autor:innen, die in text (z.B. eine Chat-Frage)
    per vollem Namen, per Nachnamen allein (Wortgrenze, siehe Bug
    2026-09-14: "List die Texte von Ackoff auf" nannte nie "Russell Ackoff"
    vollständig) oder per Tippfehler-nahem Nachnamen (z.B. "Russel Ackoff")
    erwähnt werden - Grundlage dafür, biografische Fragen ("Wer ist X?") mit
    der gepflegten Autor:innen-Vita zu beantworten statt nur mit inhaltlich
    unpassenden Quellen-Chunks (siehe app/main.py, ask()). Reiner Vorname
    allein zählt bewusst NICHT (zu häufig mehrdeutig, siehe
    test_find_mentioned_ignores_partial_first_name_only) - die
    Tippfehler-Toleranz gilt deshalb nur für den Nachnamen, nicht für
    beliebige Wörter im Text."""
    text_lower = text.lower()
    words = re.findall(r"\w+", text_lower)
    mentioned = []
    for entry in list_authors():
        full_name_lower = entry["name"].lower()
        surname = full_name_lower.rsplit(" ", 1)[-1]
        exact = full_name_lower in text_lower or re.search(rf"\b{re.escape(surname)}\b", text_lower)
        fuzzy = (
            not exact
            and len(surname) >= _FUZZY_MIN_SURNAME_LEN
            and difflib.get_close_matches(surname, words, n=1, cutoff=_FUZZY_CUTOFF)
        )
        if exact or fuzzy:
            mentioned.append(entry["name"])
    return mentioned
