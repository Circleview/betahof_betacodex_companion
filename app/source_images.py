"""Bilder zu Quellen (Idee ff895248).

Web-Bilder bleiben fremde Links (`{kind:"url"}`); PDF-Bilder werden als
verkleinerte WebP-Kopie unter <base>/<source_id>/<uuid4hex>.webp abgelegt
(`{kind:"file"}`) - Muster wie app/author_photos.py. Der Zufallsname
verhindert das Durchprobieren; Pillow kodiert neu und entfernt dabei alle
Metadaten. Die Verzeichnisse übergibt der Aufrufer (main.py), damit Tests
sie umlenken können."""
import json
import re
import shutil
import time
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

MAX_IMAGES_PER_SOURCE = 30
MAX_BYTES_PER_SOURCE = 5 * 1024 * 1024
MAX_SIDE_PX = 800
MAX_PIXELS = 25_000_000  # Schutz vor Dekompressionsbomben
ALT_MAX = 300
STAGING_MAX_AGE_SECONDS = 24 * 3600

IMAGE_NAME_RE = re.compile(r"^[0-9a-f]{32}\.webp$")
_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_TOKEN_RE = re.compile(r"^[0-9a-f]{32}$")


def store_images(base_dir: Path, source_id: str, items: list[dict]) -> list[dict]:
    """items: {data: bytes, page, anchor}. Liefert {kind:"file", file, page, anchor}."""
    folder = Path(base_dir) / source_id
    entries, total = [], 0
    for item in items:
        if len(entries) >= MAX_IMAGES_PER_SOURCE:
            break
        try:
            image = Image.open(BytesIO(item["data"]))
            if image.width * image.height > MAX_PIXELS:
                continue
            image.draft("RGB", (MAX_SIDE_PX, MAX_SIDE_PX))  # JPEG: gleich verkleinert dekodieren
            image.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
            buf = BytesIO()
            image.save(buf, format="WEBP", quality=80)
        except Exception:
            continue
        if total + buf.tell() > MAX_BYTES_PER_SOURCE:
            continue
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.webp"
        (folder / name).write_bytes(buf.getvalue())
        total += buf.tell()
        entries.append({"kind": "file", "file": name, "page": item.get("page"), "anchor": item.get("anchor", "")})
    return entries


def image_path(base_dir: Path, source_id: str, name: str) -> Path | None:
    """Geprüfter Pfad oder None - der Pfad entsteht nur aus validierten Teilen."""
    if not (_SOURCE_ID_RE.match(source_id or "") and IMAGE_NAME_RE.match(name or "")):
        return None
    path = Path(base_dir) / source_id / name
    return path if path.is_file() else None


def delete_source_images(base_dir: Path, source_id: str) -> None:
    if _SOURCE_ID_RE.match(source_id or ""):
        shutil.rmtree(Path(base_dir) / source_id, ignore_errors=True)


def is_safe_https(url) -> bool:
    try:
        parts = urlparse(url)
    except (ValueError, TypeError):
        return False
    return parts.scheme == "https" and bool(parts.hostname) and not parts.username and not parts.password


def sanitize_web_images(items) -> list[dict]:
    """Erneuter Server-Filter für Web-Bilder: nur https-`url`-Einträge."""
    out = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, dict) and item.get("kind") == "url" and is_safe_https(item.get("url")):
            out.append(
                {
                    "kind": "url",
                    "url": item["url"],
                    "alt": str(item.get("alt") or "")[:ALT_MAX],
                    "anchor": str(item.get("anchor") or ""),
                }
            )
        if len(out) >= MAX_IMAGES_PER_SOURCE:
            break
    return out


def stage_web_images(staging_dir: Path, url: str, images: list[dict]) -> str:
    """Legt die beim Vorschau-Abruf gefundenen Web-Bilder unter einem Token ab."""
    staging_dir = Path(staging_dir)
    staging_dir.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - STAGING_MAX_AGE_SECONDS
    for old in staging_dir.glob("*.json"):
        if old.stat().st_mtime < cutoff:
            old.unlink(missing_ok=True)
    token = uuid.uuid4().hex
    (staging_dir / f"{token}.json").write_text(json.dumps({"url": url, "images": images}), encoding="utf-8")
    return token


def take_staged_web_images(staging_dir: Path, token: str, url: str) -> list[dict] | None:
    """Bilder zum Token - nur bei exakt gleicher URL; sonst None (ungültig).
    [] heißt: Seite geprüft, keine Bilder."""
    if not _TOKEN_RE.match(token or ""):
        return None
    path = Path(staging_dir) / f"{token}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("url") != url:
        return None
    path.unlink(missing_ok=True)
    return sanitize_web_images(data.get("images"))
