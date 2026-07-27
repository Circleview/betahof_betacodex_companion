import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUTHOR_PROFILES_FILE = BASE_DIR / "data" / "author_profiles.json"

_EMPTY_PROFILE = {
    "bio_de": "",
    "bio_en": "",
    "bio_ai_generated_de": False,
    "bio_ai_generated_en": False,
    "photo_url": "",
    "website": "",
    "social_links": [],
}


def _normalize(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def _migrate_entry(entry: dict) -> dict:
    # Vor Backlog "bilinguale Vita" gab es nur ein einzelnes bio-Feld (Sprache
    # je nachdem, welche UI-Sprache beim Schreiben/Generieren aktiv war). Beim
    # Umstieg auf getrennte bio_de/bio_en wird der bestehende Text als
    # deutsche Vita übernommen (DEFAULT_LANG ist "de") - die englische Vita
    # bleibt bewusst leer, statt geraten/mitübersetzt zu werden, und muss
    # einmalig neu generiert werden.
    if "bio_de" in entry or "bio_en" in entry:
        return entry
    if "bio" not in entry:
        return entry
    migrated = dict(entry)
    migrated["bio_de"] = migrated.pop("bio", "")
    migrated["bio_ai_generated_de"] = migrated.pop("bio_ai_generated", False)
    migrated.setdefault("bio_en", "")
    migrated.setdefault("bio_ai_generated_en", False)
    return migrated


def _load() -> dict:
    if not AUTHOR_PROFILES_FILE.exists():
        return {}
    raw = json.loads(AUTHOR_PROFILES_FILE.read_text())
    return {key: _migrate_entry(entry) for key, entry in raw.items()}


def _save(profiles: dict) -> None:
    AUTHOR_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTHOR_PROFILES_FILE.write_text(json.dumps(profiles, ensure_ascii=False, indent=2))


def get_profile(name: str) -> dict:
    profiles = _load()
    entry = profiles.get(_normalize(name))
    if entry is None:
        return dict(_EMPTY_PROFILE)
    return {**_EMPTY_PROFILE, **entry}


def set_profile(
    name: str,
    *,
    bio_de: str | None = None,
    bio_en: str | None = None,
    photo_url: str | None = None,
    website: str | None = None,
    social_links: list[dict] | None = None,
    bio_ai_generated_de: bool | None = None,
    bio_ai_generated_en: bool | None = None,
) -> dict:
    # Komplett unabhängig von app/authors.py (bewusst kein Import von dort) -
    # die automatisch abgeleitete Registry löscht einen Autor-Eintrag samt
    # aller Zusatzfelder, sobald dessen letzte Quelle entfernt wird
    # (authors.unregister_source). Ein hier gespeichertes Profil (Foto/Vita/
    # Links) darf davon nicht betroffen sein.
    profiles = _load()
    key = _normalize(name)
    entry = {**_EMPTY_PROFILE, **(profiles.get(key) or {})}
    if bio_de is not None:
        # Ändert sich der Vita-Text durch einen normalen (manuellen) Aufruf
        # ohne explizites bio_ai_generated_*, gilt er ab jetzt als von einer
        # Person verfasst/überarbeitet - das "generate-bio"-Endpoint setzt
        # bio_ai_generated_* explizit und überschreibt das direkt danach.
        if bio_de != entry.get("bio_de", ""):
            entry["bio_ai_generated_de"] = False
        entry["bio_de"] = bio_de
    if bio_en is not None:
        if bio_en != entry.get("bio_en", ""):
            entry["bio_ai_generated_en"] = False
        entry["bio_en"] = bio_en
    if bio_ai_generated_de is not None:
        entry["bio_ai_generated_de"] = bio_ai_generated_de
    if bio_ai_generated_en is not None:
        entry["bio_ai_generated_en"] = bio_ai_generated_en
    if photo_url is not None:
        entry["photo_url"] = photo_url
    if website is not None:
        entry["website"] = website
    if social_links is not None:
        entry["social_links"] = social_links
    profiles[key] = entry
    _save(profiles)
    return dict(entry)


def rename_profile(old_name: str, new_name: str) -> None:
    old_key = _normalize(old_name)
    new_key = _normalize(new_name)
    if old_key == new_key:
        # Nur Schreibweise/Groß-Kleinschreibung geändert - Profildaten liegen
        # bereits unter demselben Schlüssel, nichts zu tun.
        return

    profiles = _load()
    entry = profiles.pop(old_key, None)
    if entry is None:
        return

    if new_key not in profiles:
        profiles[new_key] = entry
    # Existiert am Zielnamen bereits ein eigenes Profil, wird es bewusst
    # NICHT automatisch mit dem alten zusammengeführt (Konfliktrisiko bei
    # Vita/Foto/Links) - das alte Profil geht dann verloren, das Ziel-Profil
    # bleibt unangetastet.
    _save(profiles)
