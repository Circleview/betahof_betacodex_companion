import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
AUTHOR_PROFILES_FILE = BASE_DIR / "data" / "author_profiles.json"

_EMPTY_PROFILE = {"bio": "", "photo_url": "", "website": "", "social_links": [], "bio_ai_generated": False}


def _normalize(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def _load() -> dict:
    if AUTHOR_PROFILES_FILE.exists():
        return json.loads(AUTHOR_PROFILES_FILE.read_text())
    return {}


def _save(profiles: dict) -> None:
    AUTHOR_PROFILES_FILE.parent.mkdir(parents=True, exist_ok=True)
    AUTHOR_PROFILES_FILE.write_text(json.dumps(profiles, ensure_ascii=False, indent=2))


def get_profile(name: str) -> dict:
    profiles = _load()
    entry = profiles.get(_normalize(name))
    return dict(entry) if entry is not None else dict(_EMPTY_PROFILE)


def set_profile(
    name: str,
    *,
    bio: str | None = None,
    photo_url: str | None = None,
    website: str | None = None,
    social_links: list[dict] | None = None,
    bio_ai_generated: bool | None = None,
) -> dict:
    # Komplett unabhängig von app/authors.py (bewusst kein Import von dort) -
    # die automatisch abgeleitete Registry löscht einen Autor-Eintrag samt
    # aller Zusatzfelder, sobald dessen letzte Quelle entfernt wird
    # (authors.unregister_source). Ein hier gespeichertes Profil (Foto/Vita/
    # Links) darf davon nicht betroffen sein.
    profiles = _load()
    key = _normalize(name)
    entry = profiles.get(key) or dict(_EMPTY_PROFILE)
    if bio is not None:
        # Ändert sich der Vita-Text durch einen normalen (manuellen) Aufruf
        # ohne explizites bio_ai_generated, gilt er ab jetzt als von einer
        # Person verfasst/überarbeitet - das "generate-bio"-Endpoint setzt
        # bio_ai_generated=True explizit und überschreibt das direkt danach.
        if bio != entry.get("bio", ""):
            entry["bio_ai_generated"] = False
        entry["bio"] = bio
    if bio_ai_generated is not None:
        entry["bio_ai_generated"] = bio_ai_generated
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
