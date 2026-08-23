"""Lokaler Foto-Cache für Autor:innen-Profilbilder (Nutzerwunsch 2026-08-23):
extern verlinkte Fotos sterben regelmäßig weg - besonders LinkedIn-CDN-URLs
(media.licdn.com) sind mit einem eingebauten Ablaufdatum signiert (Query-
Parameter "e=", ein Unix-Timestamp) und daher technisch nie für dauerhaftes
Einbinden auf fremden Seiten gedacht, nur für die Anzeige auf LinkedIn
selbst. Beim ersten erfolgreichen Abruf wird das Bild EINMALIG
heruntergeladen, auf zwei feste Größen skaliert/komprimiert und lokal
abgelegt - danach unabhängig vom Fortbestehen der Original-URL.

data/ statt static/, weil static/ bei jedem Blue-Green-Deploy neu
ausgerollt wird, data/ dagegen auf dem Server ein persistentes, über
Deploys hinweg geteiltes Verzeichnis ist (siehe ~/shared/data/ auf dem
Server).

Komplett unabhängig von app/author_profiles.py (bewusst kein gemeinsamer
Speicher, gleiche Entkopplungs-Idee wie dort für app/authors.py) - eigenes
kleines Manifest statt eines neuen Felds in author_profiles.json."""
import hashlib
import json
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image

BASE_DIR = Path(__file__).resolve().parent.parent
AUTHOR_PHOTOS_DIR = BASE_DIR / "data" / "author_photos"
MANIFEST_FILE = AUTHOR_PHOTOS_DIR / "_manifest.json"

# Klein für den Explore-Graphen (dort nur wenige Pixel groß dargestellt),
# groß genug fürs Vita-Panel in guter Qualität.
SIZES = {"small": 160, "large": 480}

# Gleiche Konvention wie app/extraction.py: manche Server (Bot-/Hotlink-
# Schutz) lehnen Requests ohne plausiblen Browser-User-Agent/Accept-Header ab.
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def _normalize(name: str) -> str:
    return " ".join(name.strip().split()).lower()


def _slug(name: str) -> str:
    # Hash statt Klarname als Dateiname - unabhängig von Sonderzeichen/
    # Umlauten im Namen, kollisionsfrei, und eine Umbenennung (siehe
    # rename() unten) muss dadurch nur die Dateien verschieben, nicht auf
    # Dateisystem-Zeichenbeschränkungen achten.
    return hashlib.sha1(_normalize(name).encode("utf-8")).hexdigest()[:20]


def _load_manifest() -> dict:
    if not MANIFEST_FILE.exists():
        return {}
    return json.loads(MANIFEST_FILE.read_text())


def _save_manifest(manifest: dict) -> None:
    AUTHOR_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))


def photo_path(name: str, size: str) -> Path:
    return AUTHOR_PHOTOS_DIR / f"{_slug(name)}-{size}.webp"


def cached_source_url(name: str) -> str | None:
    return _load_manifest().get(_slug(name), {}).get("source_url")


def has_cached_photo(name: str, size: str = "small") -> bool:
    return photo_path(name, size).exists()


def _resize_and_crop_square(image: Image.Image, dimension: int) -> Image.Image:
    # Mittig auf ein Quadrat zuschneiden - ein Rundausschnitt (Vita-Panel/
    # Explore-Graph) wirkt bei nicht-quadratischen Originalfotos sonst
    # verzerrt/ungünstig beschnitten.
    width, height = image.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cropped = image.crop((left, top, left + side, top + side))
    return cropped.resize((dimension, dimension), Image.LANCZOS)


def cache_photo(name: str, source_url: str) -> bool:
    """Lädt source_url einmal herunter und legt beide Größen lokal ab. Gibt
    True bei Erfolg zurück, False bei jedem Fehler (Fail-leise-Konvention
    wie app/source_discovery.py/app/llm.py) - ein kaputter/unerreichbarer
    Link darf das Setzen eines Profils nie verhindern oder crashen."""
    try:
        req = urllib.request.Request(source_url, headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        image = Image.open(BytesIO(data))
        image = image.convert("RGB")
    except Exception:
        return False

    AUTHOR_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
    for size_name, dimension in SIZES.items():
        resized = _resize_and_crop_square(image, dimension)
        resized.save(photo_path(name, size_name), "WEBP", quality=82)

    manifest = _load_manifest()
    manifest[_slug(name)] = {"source_url": source_url}
    _save_manifest(manifest)
    return True


def rename(old_name: str, new_name: str) -> None:
    old_slug, new_slug = _slug(old_name), _slug(new_name)
    if old_slug == new_slug:
        return
    manifest = _load_manifest()
    moved = False
    for size_name in SIZES:
        old_path = AUTHOR_PHOTOS_DIR / f"{old_slug}-{size_name}.webp"
        if old_path.exists():
            old_path.rename(AUTHOR_PHOTOS_DIR / f"{new_slug}-{size_name}.webp")
            moved = True
    entry = manifest.pop(old_slug, None)
    if entry is not None:
        manifest[new_slug] = entry
        moved = True
    if moved:
        _save_manifest(manifest)
