import base64
import io
import posixpath
import zipfile
from html.parser import HTMLParser
from xml.etree import ElementTree
import ipaddress
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urljoin, urlparse, urlunparse

import openai
import trafilatura
from openai import OpenAI
from pypdf import PdfReader
from youtube_transcript_api import YouTubeTranscriptApi

from app import usage as usage_log
from app.chunking import norm_anchor

# Manche Server (Bot-/Hotlink-Schutz, z.B. bei WordPress-gehosteten Podcast-
# Medien) lehnen Requests ohne "Accept"-Header mit HTTP 406 ab, selbst mit
# plausiblem User-Agent - ein echter Browser schickt diesen Header immer mit.
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


class UnsafeUrlError(ValueError):
    """SSRF-Schutz: die angegebene URL zeigt auf eine private/interne Adresse."""


# Sicherheit (Security-Review 2026-09-23): jede der Funktionen unten wird mit
# einer von einer Nutzer:in (Quellen-Pfleger:in) frei angegebenen URL
# aufgerufen (Quellen-Import per Link, PDF/Audio-URL) - ungeprüft ließe sich
# der Server so als Proxy für interne Netzwerk-Anfragen missbrauchen (z.B.
# Cloud-Metadata-Endpunkt 169.254.169.254, localhost, internes Netz). Prüft
# ALLE zur Hostname aufgelösten IPs (nicht nur die erste), da DNS mehrere
# A-Records liefern kann. Eine EINZIGE Stelle statt einer Prüfung pro
# Aufrufer, da _safe_urlopen unten von mehreren unabhängigen Stellen in
# app/main.py aus erreicht werden (Import per Link, PDF/Audio-Sync beim
# Anlegen/Bearbeiten einer Quelle).
# ponytail: prüft den Hostnamen einmal vor dem Verbindungsaufbau, pinnt die
# aufgelöste IP aber nicht fest - ein DNS-Rebinding-Angriff (Hostname
# ändert seine Auflösung zwischen dieser Prüfung und dem eigentlichen
# Verbindungsaufbau von urllib) ist damit theoretisch weiter
# möglich. Für den hier adressierten, deutlich wahrscheinlicheren Fall
# (jemand trägt direkt eine interne Adresse ins URL-Feld ein) reicht das;
# echtes IP-Pinning bräuchte einen eigenen, angepassten HTTP-Transport.
def _assert_safe_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeUrlError(f"Unsichere URL (Schema nicht erlaubt): {url}")
    hostname = parsed.hostname
    if not hostname:
        raise UnsafeUrlError(f"Unsichere URL (kein Hostname): {url}")
    try:
        infos = _getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Hostname nicht auflösbar: {hostname}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise UnsafeUrlError(f"Unsichere URL (private/interne Adresse): {url}")


# Backlog (2026-09-23): urlopen folgt 30x-Weiterleitungen sonst ungeprüft -
# eine öffentliche URL könnte per Redirect auf 169.254.169.254/localhost
# zeigen. Jedes Weiterleitungsziel durchläuft deshalb dieselbe Prüfung wie
# die Start-URL; UnsafeUrlError bricht den Abruf ab wie jeder andere Fehler.
class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _assert_safe_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_safe_opener = urllib.request.build_opener(_SafeRedirectHandler)


def _safe_urlopen(req: urllib.request.Request, timeout: float):
    _assert_safe_url(req.full_url)
    return _safe_opener.open(req, timeout=timeout)


# Gleiche Obergrenze wie trafilaturas eigenes fetch_url (MAX_FILE_SIZE).
_MAX_HTML_BYTES = 20_000_000


def _fetch_html(url: str) -> bytes | None:
    """Ersetzt trafilatura.fetch_url(): das nutzt eigenes Networking (urllib3)
    und folgt Weiterleitungen am SSRF-Schutz vorbei. trafilatura.extract()
    erkennt die Zeichenkodierung der Bytes selbst."""
    try:
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with _safe_urlopen(req, timeout=30) as resp:
            data = resp.read(_MAX_HTML_BYTES + 1)
    except Exception:
        return None
    if len(data) > _MAX_HTML_BYTES:
        return None
    return data


# Eigene, separat mockbare Referenz statt socket.getaddrinfo direkt in
# _assert_safe_url unten aufzurufen: `socket` ist EIN EINZIGES, geteiltes
# Modul-Objekt im ganzen Prozess - ein Test, der `extraction.socket.
# getaddrinfo` monkeypatcht, patcht damit versehentlich auch die INTERNE
# DNS-Auflösung von urllib.request.urlopen() selbst (das ruft socket.
# create_connection() -> socket.getaddrinfo() auf) für JEDEN Hostnamen im
# ganzen Testprozess, nicht nur für diese eine Prüfung. Ein Test mit einer
# frei erfundenen Domain (z.B. "cdn.example.org", die real gar nicht
# existiert) würde durch ein solches globales Mock plötzlich eine ECHTE
# TCP/TLS-Verbindung zu einer falschen, aber uber die gefälschte IP
# erreichbaren Adresse versuchen (mit nicht passendem Host-Header/SNI) -
# genau das hat einen CI-Lauf spürbar verlangsamt/zum Hängen gebracht
# (2026-09-23). Tests patchen deshalb NUR `extraction._getaddrinfo`.
_getaddrinfo = socket.getaddrinfo


def _split_authors(raw: str) -> list[str]:
    """Zerlegt einen extrahierten Autoren-String an gängigen Trennern in
    einzelne Namen (Best-effort-Heuristik - Nutzer:innen können über die
    "+"-Felder im Formular jederzeit manuell korrigieren/ergänzen)."""
    if not raw or not raw.strip():
        return []
    parts = re.split(r";|,| und | and |&", raw)
    return [p.strip() for p in parts if p.strip()]


def _is_youtube_url(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "youtube.com" in host or "youtu.be" in host


# Nutzerwunsch (2026-08-31): Tracking-Parameter führten dazu, dass dieselbe
# per Social Media/Newsletter geteilte Seite je nach mitgeschickten
# Anhängen (utm_*, fbclid, ...) wie eine ANDERE URL wirkte und die
# Duplikat-Prüfung (siehe _normalize_url_for_comparison/add_source in
# app/main.py) nicht anschlug. Bewusst nur eine kuratierte Liste bekannter,
# rein Tracking-dienender Parameternamen statt pauschal aller Query-
# Parameter - ein funktional relevanter Parameter (z.B. eine Artikel-ID)
# darf nicht verloren gehen, sonst würde die URL kaputtgehen.
_TRACKING_PARAM_NAMES = {
    "fbclid",
    "gclid",
    "gclsrc",
    "dclid",
    "wbraid",
    "gbraid",
    "msclkid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "_hsenc",
    "_hsmi",
    "mkt_tok",
    "yclid",
    "ttclid",
    "twclid",
}


def strip_tracking_params(url: str) -> str:
    """Entfernt bekannte Tracking-Parameter (utm_* sowie die Namen in
    _TRACKING_PARAM_NAMES) aus einer URL - Rest der URL (Pfad, andere
    Query-Parameter, Fragment) bleibt unverändert. Bei fehlendem/leerem
    Query-String oder einer nicht parsbaren URL wird die Eingabe
    unverändert zurückgegeben, statt sie zu beschädigen."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    if not parsed.query:
        return url
    kept = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in _TRACKING_PARAM_NAMES and not key.lower().startswith("utm_")
    ]
    return urlunparse(parsed._replace(query=urlencode(kept)))


def extract_youtube_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "youtu.be" in host:
        return parsed.path.strip("/").split("/")[0] or None
    if "youtube.com" in host:
        if parsed.path == "/watch":
            return parse_qs(parsed.query).get("v", [None])[0]
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/shorts/")[1].split("/")[0] or None
    return None


def _fetch_youtube_metadata(url: str) -> dict:
    try:
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with _safe_urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return {"title": "", "date": ""}

    title_match = re.search(r'<meta property="og:title" content="([^"]*)"', html)
    date_match = re.search(r'<meta itemprop="datePublished" content="([^"]*)"', html)
    return {
        "title": title_match.group(1) if title_match else "",
        "date": date_match.group(1)[:10] if date_match else "",
    }


def _extract_youtube(url: str) -> dict:
    video_id = extract_youtube_video_id(url)
    if not video_id:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    # Fix (2026-08-03): Metadaten- und Transkript-Abruf sind zwei komplett
    # unabhängige Anfragen an YouTube (unterschiedliche Endpunkte) - vorher
    # brach ein Fehlschlag der Transkript-Abfrage (z.B. RequestBlocked, siehe
    # unten) die Funktion sofort ab, BEVOR die Metadaten je abgerufen wurden.
    # Titel/Datum sollen aber auch dann vorausgefüllt werden, wenn nur das
    # Transkript scheitert - der Quellen-Pfleger muss den Text dann zwar
    # manuell einfügen, spart sich aber wenigstens das Abtippen der Metadaten.
    metadata = _fetch_youtube_metadata(url)

    # Bekannte Einschränkung (2026-08-03): YouTube blockiert automatisierte
    # Transkript-Anfragen von Cloud-/Rechenzentrums-IPs (Fehler
    # "RequestBlocked") - auf Produktion (Hetzner) schlägt dieser Teil daher
    # zuverlässig fehl, lokal (Heim-/Büro-IP) funktioniert derselbe Code
    # anstandslos. Ohne einen kostenpflichtigen Residential-Proxy (von
    # youtube_transcript_api offiziell unterstützt, siehe deren
    # Dokumentation) lässt sich das nicht beheben - der manuelle
    # Copy-Paste-Fallback im Formular bleibt bis dahin der Weg für Produktion.
    text = ""
    try:
        api = YouTubeTranscriptApi()
        try:
            fetched = api.fetch(video_id, languages=["de", "en"])
        except Exception:
            transcript_list = api.list(video_id)
            transcript = next(iter(transcript_list))
            fetched = transcript.fetch()
        # Fließtext statt Zeilen mit Zeitstempel-Präfix - für die spätere
        # Verwendung als Antwort-Kontext ist der reine, lesbare Wortlaut
        # hilfreicher als eine mit Sprungmarken durchsetzte Liste.
        text = " ".join(s.text.strip() for s in fetched if s.text.strip())
        text = re.sub(r"\s+", " ", text).strip()
    except Exception:
        pass

    return {
        "title": metadata["title"],
        "authors": [],
        "date": metadata["date"],
        "text": text,
        "extracted": bool(text),
    }


AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac")


def looks_like_audio(url: str) -> bool:
    path = url.lower().split("?")[0]
    if path.endswith(AUDIO_EXTENSIONS):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD", headers=_REQUEST_HEADERS)
        with _safe_urlopen(req, timeout=10) as resp:
            return resp.headers.get("Content-Type", "").lower().startswith("audio/")
    except Exception:
        return False


def download_audio_bytes(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with _safe_urlopen(req, timeout=60) as resp:
            return resp.read()
    except Exception:
        return None


def _guess_title_from_url(url: str) -> str:
    path = urlparse(url).path
    stem = path.rsplit("/", 1)[-1]
    stem = re.sub(r"\.[a-zA-Z0-9]+$", "", stem)
    stem = re.sub(r"[-_]+", " ", stem).strip()
    return stem.capitalize() if stem else ""


def _extract_audio(url: str) -> dict:
    """Liefert nur den aus der URL geratenen Titel, ohne Download/
    Transkription - Audio-Transkription kann mehrere Minuten dauern und
    läuft deshalb ausschließlich als Hintergrund-Job NACH dem Anlegen der
    Quelle (siehe app/main.py: _process_audio_transcription), damit die
    Vorschau (POST /api/extract-url) schnell bleibt."""
    return {
        "title": _guess_title_from_url(url),
        "authors": [],
        "date": "",
        "text": "",
        "extracted": False,
    }


# Von gpt-4o-transcribe-diarize unterstützte Formate (Sprechererkennung).
# flac/ogg sind zwar Teil von AUDIO_EXTENSIONS (Wiedergabe/Speicherung),
# aber von diesem Modell nicht unterstützt - dafür Fallback auf whisper-1
# (Transkription ohne Sprecher-Label, siehe _transcribe_chunk).
_DIARIZE_EXTENSIONS = (".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm")

AUDIO_UPLOAD_MAX_BYTES = 25 * 1024 * 1024


def _find_binary(name: str, fallback_paths: list[str]) -> str:
    """shutil.which() findet ffmpeg/ffprobe nur, wenn deren Installationsort
    (z.B. /opt/homebrew/bin bei Homebrew auf Apple Silicon) tatsächlich in
    der PATH-Umgebungsvariable des laufenden Prozesses steht - das war hier
    nicht der Fall, obwohl beide Programme installiert waren, wodurch
    split_audio_file() jeden Aufteilungsversuch still übersprang. Bekannte
    Standard-Installationsorte als Fallback, bevor einfach der nackte
    Programmname an subprocess übergeben wird (der dann ggf. mit dem
    ursprünglichen "nicht gefunden"-Fehler fehlschlägt, statt hier zu raten)."""
    found = shutil.which(name)
    if found:
        return found
    for path in fallback_paths:
        if Path(path).exists():
            return path
    return name


_FFMPEG_BIN = _find_binary("ffmpeg", ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"])
_FFPROBE_BIN = _find_binary("ffprobe", ["/opt/homebrew/bin/ffprobe", "/usr/local/bin/ffprobe"])


def _warn_if_binary_missing(name: str, resolved: str) -> None:
    # Vorfall (2026-08-03): ffmpeg fehlte auf Produktion komplett (nie
    # installiert) - split_audio_file() faengt das ab und liefert einfach
    # die unveraenderte Originaldatei zurueck (siehe dort), wodurch grosse
    # Audios erst beim Scheitern der Transkription auffielen, Wochen nach
    # dem eigentlichen Root Cause. Eine deutliche Warnung direkt beim
    # Prozessstart macht die Luecke sofort in den Logs sichtbar.
    if shutil.which(resolved) is None and not Path(resolved).exists():
        print(
            f"WARNUNG: '{name}' wurde beim Start nicht gefunden. Audio-Dateien "
            f"über {AUDIO_UPLOAD_MAX_BYTES // (1024 * 1024)} MB können dann nicht "
            "in Abschnitte aufgeteilt werden und schlagen bei der Transkription "
            "fehl (siehe split_audio_file). Bitte ffmpeg auf dem Server installieren.",
            file=sys.stderr,
        )


_warn_if_binary_missing("ffmpeg", _FFMPEG_BIN)
_warn_if_binary_missing("ffprobe", _FFPROBE_BIN)

# gpt-4o-transcribe-diarize lehnt Dateien über dieser Dauer unabhängig von
# der Byte-Größe mit einem 400er ab ("audio duration X seconds is longer
# than 1400 seconds") - eine ganz normale, unter AUDIO_UPLOAD_MAX_BYTES
# liegende Episode (z.B. 20MB/24,5 Minuten) wurde dadurch bisher NIE
# aufgeteilt und die Transkription schlug jedes Mal fehl. Etwas Marge unter
# dem dokumentierten Limit (statt exakt 1400), falls die tatsächliche Dauer
# durch Container-Rundung minimal höher geschätzt wird als von ffprobe.
MAX_DIARIZE_DURATION_SECONDS = 1350

_openai_client = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI()
    return _openai_client


def _format_diarized_text(result) -> str:
    speaker_labels: dict[str, str] = {}
    lines = []
    for segment in result.segments:
        label = speaker_labels.setdefault(segment.speaker, f"Sprecher {len(speaker_labels) + 1}")
        text = segment.text.strip()
        if text:
            lines.append(f"{label}: {text}")
    return "\n\n".join(lines)


def _transcribe_chunk_once(data: bytes, filename: str, prompt: str | None = None) -> str:
    """Ein einzelner, ungeschützter Transkriptionsversuch - Exceptions werden
    NICHT abgefangen, das übernimmt _transcribe_chunk_with_retries, die
    zwischen vorübergehenden (wiederholbaren) und endgültigen Fehlern
    unterscheiden muss.

    prompt: optionaler Vokabular-Hinweis (siehe transcribe_audio) - OpenAIs
    Transkriptions-Endpunkt nutzt einen mitgegebenen Prompt u.a. dafür,
    unbekannte/seltene Eigennamen eher in der dort vorkommenden Schreibweise
    zu erkennen, statt sie phonetisch zu verballhornen. Gilt NUR für
    whisper-1 - siehe Fix-Kommentar unten bei gpt-4o-transcribe-diarize."""
    extension = Path(filename).suffix.lower()
    client = _get_openai_client()
    # Die SDK-Signatur erwartet für "prompt" str | Omit (kein None) - ohne
    # Vokabular-Hinweis wird das Argument deshalb ganz weggelassen statt
    # explizit None zu übergeben.
    prompt_kwargs = {"prompt": prompt} if prompt else {}
    if extension in _DIARIZE_EXTENSIONS:
        # Fix (real reproduziert auf Produktion, 2026-08-25): gpt-4o-
        # transcribe-diarize lehnt JEDEN gesetzten Prompt pauschal mit 400
        # ab ("Prompt is not supported for diarization models") - anders
        # als bei whisper-1 unten gibt es hier keinen Vokabular-Hinweis-
        # Mechanismus, prompt_kwargs wird deshalb bewusst NICHT
        # durchgereicht. Betraf praktisch jede Audiodatei mit mindestens
        # einer/einem eingetragenen Autor:in, seit dem Vokabular-Hinweis-
        # Feature (v0.52.0).
        result = client.audio.transcriptions.create(
            model="gpt-4o-transcribe-diarize",
            file=(filename, data),
            response_format="diarized_json",
            chunking_strategy="auto",
        )
        return _format_diarized_text(result)

    result = client.audio.transcriptions.create(
        model="whisper-1",
        file=(filename, data),
        response_format="text",
        **prompt_kwargs,
    )
    return str(result).strip()


# Vorübergehende Fehlerklassen, bei denen ein erneuter Versuch nach kurzer
# Wartezeit typischerweise erfolgreich ist - alle anderen Fehler (z.B.
# beschädigte Datei, nicht unterstütztes Format) werden NICHT wiederholt, da
# sich am Ergebnis nichts ändern würde. Die OpenAI-Bibliothek wiederholt
# intern zwar bereits automatisch (kurze Sekunden-Backoffs), das reicht bei
# den strengeren Limits der Audio-Endpunkte aber oft nicht aus - siehe
# Vorfall 2026-07-29 (mehrere Segmente scheiterten still, siehe unten).
_RETRYABLE_OPENAI_ERRORS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
)

# 3 Versuche insgesamt (Erstversuch + 2 Wiederholungen), mit steigender
# Wartezeit - lang genug, um ein Minuten-Rate-Limit auf dem Audio-Endpunkt
# zu überstehen, ohne die ohnehin schon seltenen Fehlerfälle unnötig weiter
# in die Länge zu ziehen.
_SEGMENT_RETRY_DELAYS_SECONDS = [30, 90]

# Grobe, bewusst großzügige Plausibilitätsgrenze: reale, vollständig
# transkribierte Abschnitte lagen in einer Stichprobe durchweg über
# 1000 Zeichen/Minute. Ein von OpenAI ohne Fehlermeldung, aber mit
# auffällig wenig Text beantworteter Abschnitt (beobachtet: nur 538 Zeichen
# für ~15 Minuten Audio) wäre sonst - der eigentliche Auslöser dieser
# Umstrukturierung - als "erfolgreich" durchgerutscht. Absichtlich niedrig
# gewählt, um lange, tatsächlich sehr wortarme Abschnitte (z.B. Musik) nicht
# fälschlich zu blockieren.
_MIN_CHARS_PER_MINUTE = 100


def _transcribe_chunk_with_retries(
    data: bytes, filename: str, duration_seconds: float | None, prompt: str | None = None
) -> tuple[str, str | None]:
    """Transkribiert EINEN Abschnitt mit Wiederholungen bei vorübergehenden
    Fehlern und einer Plausibilitätsprüfung des Ergebnisses. Gibt (text,
    fehlerdetail) zurück - fehlerdetail ist None bei Erfolg, text ist dann
    nie teilweise/fragwürdig (das war der eigentliche Bug: ein Abschnitt
    ohne Exception, aber mit fast leerem Ergebnis, galt bisher als
    Erfolg)."""
    attempts = len(_SEGMENT_RETRY_DELAYS_SECONDS) + 1
    detail = "unbekannter Fehler"
    for attempt in range(attempts):
        is_last_attempt = attempt == attempts - 1
        try:
            text = _transcribe_chunk_once(data, filename, prompt)
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}"
            if is_last_attempt or not isinstance(exc, _RETRYABLE_OPENAI_ERRORS):
                return "", detail
            time.sleep(_SEGMENT_RETRY_DELAYS_SECONDS[attempt])
            continue

        if duration_seconds and len(text) < (duration_seconds / 60) * _MIN_CHARS_PER_MINUTE:
            detail = f"Ergebnis auffällig kurz ({len(text)} Zeichen für {duration_seconds / 60:.0f} Minuten)"
            if is_last_attempt:
                return "", detail
            time.sleep(_SEGMENT_RETRY_DELAYS_SECONDS[attempt])
            continue

        return text, None
    return "", detail


def _audio_duration_seconds(path: Path) -> float | None:
    try:
        completed = subprocess.run(
            [_FFPROBE_BIN, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return float(completed.stdout.strip())
    except Exception:
        return None


def split_audio_file(path: Path, max_bytes: int = AUDIO_UPLOAD_MAX_BYTES) -> list[Path]:
    """Zerlegt eine Audiodatei in verlustfreie Zeit-Abschnitte, falls sie
    über max_bytes ODER (bei einem für gpt-4o-transcribe-diarize
    vorgesehenen Format, siehe _DIARIZE_EXTENSIONS) über
    MAX_DIARIZE_DURATION_SECONDS liegt - sonst wird der Originalpfad
    unverändert zurückgegeben, ohne ffmpeg aufzurufen. Die Segment-Dauer
    wird grob aus Dateigröße/Gesamtdauer geschätzt, mit Sicherheitsmarge
    (70% des Größenlimits) für übliche Sprach-Bitraten, zusätzlich gedeckelt
    auf MAX_DIARIZE_DURATION_SECONDS."""
    size = path.stat().st_size
    duration = _audio_duration_seconds(path)
    exceeds_size = size > max_bytes
    exceeds_duration = (
        path.suffix.lower() in _DIARIZE_EXTENSIONS
        and duration is not None
        and duration > MAX_DIARIZE_DURATION_SECONDS
    )
    if not exceeds_size and not exceeds_duration:
        return [path]
    if not duration:
        return [path]

    bytes_per_second = size / duration
    segment_seconds = max(int((max_bytes * 0.7) / bytes_per_second), 30)
    if path.suffix.lower() in _DIARIZE_EXTENSIONS:
        segment_seconds = min(segment_seconds, MAX_DIARIZE_DURATION_SECONDS)

    output_dir = Path(tempfile.mkdtemp(prefix="audio_split_"))
    pattern = output_dir / f"chunk_%03d{path.suffix}"
    try:
        subprocess.run(
            [
                _FFMPEG_BIN, "-i", str(path),
                "-f", "segment", "-segment_time", str(segment_seconds),
                "-c", "copy", "-reset_timestamps", "1",
                str(pattern),
            ],
            capture_output=True,
            timeout=600,
            check=True,
        )
    except Exception:
        return [path]

    segments = sorted(output_dir.glob(f"chunk_*{path.suffix}"))
    return segments or [path]


def transcribe_audio(
    path: Path,
    known_segments: dict[int, str] | None = None,
    on_segment_success: Callable[[int, int, str], None] | None = None,
    known_names: list[str] | None = None,
) -> tuple[str, str | None]:
    """Transkribiert eine Audiodatei beliebiger Größe: Dateien über dem
    OpenAI-Limit werden zuerst per split_audio_file() in Abschnitte
    aufgeteilt, jeder Abschnitt einzeln transkribiert (mit Wiederholungen,
    siehe _transcribe_chunk_with_retries) und die Ergebnisse zu einem
    zusammenhängenden Text verkettet. Sprecher-Nummerierung wird pro
    Abschnitt neu vergeben (keine Kontinuität über Abschnittsgrenzen
    hinweg möglich).

    known_segments: bereits erfolgreich transkribierte Abschnitte (0-
    indiziert) aus einem vorherigen, teilweise gescheiterten Versuch -
    werden ohne erneuten (kostenpflichtigen) OpenAI-Aufruf übernommen.
    split_audio_file() liefert bei gleicher Datei stets dieselben
    Abschnittsgrenzen, daher bleibt der Index über mehrere Versuche hinweg
    gültig.
    on_segment_success: wird nach JEDEM neu erfolgreich transkribierten
    Abschnitt aufgerufen (index, total, text), damit der Aufrufer (siehe
    app/main.py) den Fortschritt sofort dauerhaft speichern kann - sowohl
    für einen erneuten "Retry"-Versuch (kein doppeltes Bezahlen bereits
    erfolgreicher Abschnitte) als auch für einen Server-Neustart mitten in
    einer langen Datei.
    known_names: Nutzerfeedback (2026-08-23) - prominente Namen (z.B. Niels
    Pflaeging, Silke Hermann) wurden in Transkripten wiederholt falsch
    verstanden/geschrieben. Als Vokabular-Hinweis (OpenAIs "prompt"-
    Parameter) an die Transkription weitergereicht, um die richtige
    Schreibweise wahrscheinlicher zu machen - typischerweise die für diese
    Quelle bereits eingetragenen Autor:innen, siehe _process_audio_
    transcription in app/main.py.

    Rückgabe: (text, fehlerdetail). fehlerdetail ist None nur bei
    VOLLSTÄNDIGEM Erfolg aller Abschnitte - scheitert auch nur ein
    Abschnitt endgültig, ist text leer und fehlerdetail beschreibt Ort und
    Grund. Das war der eigentliche Bug (2026-07-29): ein einzelner
    gescheiterter Abschnitt wurde bisher still übersprungen, die Quelle
    aber trotzdem als vollständig verarbeitet markiert."""
    segments = split_audio_file(path)
    total = len(segments)
    is_split = total > 1 or (segments and segments[0] != path)
    texts: dict[int, str] = dict(known_segments or {})
    prompt = ", ".join(name.strip() for name in known_names if name and name.strip()) if known_names else None

    for index, segment_path in enumerate(segments):
        if index in texts:
            continue
        duration = _audio_duration_seconds(segment_path)
        text, error_detail = _transcribe_chunk_with_retries(
            segment_path.read_bytes(), segment_path.name, duration, prompt
        )
        if error_detail:
            if is_split:
                shutil.rmtree(segments[0].parent, ignore_errors=True)
            return "", f"Abschnitt {index + 1}/{total}: {error_detail}"
        texts[index] = text
        # Kostenmessung (2026-09-26): OpenAI rechnet je Audio-Minute ab.
        if duration:
            model = "gpt-4o-transcribe-diarize" if segment_path.suffix.lower() in _DIARIZE_EXTENSIONS else "whisper-1"
            usage_log.track_service("stt", model, duration)
        if on_segment_success:
            on_segment_success(index, total, text)

    if is_split:
        shutil.rmtree(segments[0].parent, ignore_errors=True)

    ordered = [texts[i] for i in range(total)]
    if len(ordered) <= 1:
        return (ordered[0] if ordered else ""), None
    return "\n\n".join(f"--- Teil {i + 1} ---\n\n{t}" for i, t in enumerate(ordered)), None


def looks_like_pdf(url: str) -> bool:
    if url.lower().split("?")[0].endswith(".pdf"):
        return True
    try:
        req = urllib.request.Request(url, method="HEAD", headers=_REQUEST_HEADERS)
        with _safe_urlopen(req, timeout=10) as resp:
            return "application/pdf" in resp.headers.get("Content-Type", "").lower()
    except Exception:
        return False


def download_pdf_bytes(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with _safe_urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception:
        return None


def _parse_pdf_date(raw) -> str:
    # Bei PDFs mit beschädigter/nicht standardkonformer Xref-Tabelle (pypdf
    # loggt dann "Ignoring wrong pointing object ...") liefert meta.get(...)
    # gelegentlich ein unaufgelöstes IndirectObject statt eines Strings -
    # ohne diese Prüfung crashte re.match mit TypeError und riss den
    # gesamten Extraktions-Request (inkl. Seitentext) mit sich.
    if not raw or not isinstance(raw, str):
        return ""
    match = re.match(r"D:(\d{4})(\d{2})(\d{2})", raw)
    if not match:
        return ""
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def _pdf_outline_headings(reader) -> dict[int, list[str]]:
    """Lesezeichen (max. 2 Ebenen) als {Seitenindex: [Titel]}. Fehler -> leer.
    # ponytail: Kapitel beginnt am Seitenanfang, nicht mitten auf der Seite."""
    result: dict[int, list[str]] = {}
    try:
        for item in reader.outline:
            entries = [item] if not isinstance(item, list) else []
            if isinstance(item, list):
                entries = [sub for sub in item if not isinstance(sub, list)]
            for entry in entries:
                title = (entry.title or "").strip()
                if title:
                    page = reader.get_destination_page_number(entry)
                    result.setdefault(page, []).append(title)
    except Exception:
        return {}
    return result


def extract_pdf(data: bytes) -> dict:
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    meta = reader.metadata
    title = (meta.title or "").strip() if meta and meta.title else ""
    author_raw = (meta.author or "").strip() if meta and meta.author else ""
    authors = _split_authors(author_raw)
    date = _parse_pdf_date(meta.get("/CreationDate")) if meta else ""

    headings = _pdf_outline_headings(reader)
    text_parts = []
    has_body = False
    for index, page in enumerate(reader.pages):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            continue
        if index in headings:
            text_parts.append("\n".join(f"# {t}" for t in headings[index]))
        text_parts.append(page_text)
        has_body = has_body or bool(page_text.strip())
    # Scan ohne Text-Ebene: Lesezeichen allein sind kein Text (sonst startet die OCR nie).
    text = "\n".join(part for part in text_parts if part).strip() if has_body else ""

    return {
        "title": title,
        "authors": authors,
        "date": date,
        "text": text,
        "extracted": bool(text),
    }


# Für PDFs ohne eingebettete Text-Ebene (typischerweise ältere, gescannte
# Quellen - extract_pdf() liefert dafür text="" zurück, siehe oben). Nutzt
# denselben Anthropic-Client/dasselbe Modell wie app/summarization.py statt
# eines separaten OCR-Anbieters, da bereits eine funktionierende
# API-Key-Konfiguration dafür existiert.
_OCR_MODEL_NAME = "claude-haiku-4-5-20251001"

_OCR_SYSTEM_PROMPT = """Du transkribierst den sichtbaren Text einer gescannten Buch-/Artikelseite exakt und vollständig, ohne eigene Ergänzungen, Kommentare oder Zusammenfassungen.

Antworte AUSSCHLIESSLICH mit dem erkannten Text - keine Einleitung, keine Beschreibung des Layouts, keine Anführungszeichen. Enthält die Seite keinen lesbaren Fließtext (z.B. leere Seite, reines Bild/Diagramm ohne Text), antworte mit einem leeren String."""

_anthropic_client = None


def _get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.Anthropic()
    return _anthropic_client


def _render_pdf_pages_to_images(data: bytes, dpi: int = 150) -> list[bytes]:
    import fitz  # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        zoom = dpi / 72
        matrix = fitz.Matrix(zoom, zoom)
        return [page.get_pixmap(matrix=matrix).tobytes("png") for page in doc]
    finally:
        doc.close()


def _ocr_page(image_bytes: bytes) -> str:
    """Transkribiert eine einzelne Seite. Gibt bei jedem Fehler (API-Fehler,
    fehlender Key, Netzwerkfehler) einen leeren String zurück statt zu
    crashen - gleiche defensive Konvention wie _transcribe_chunk.

    Fix (2026-08-23, per realem Produktions-Vorfall): der ursprüngliche
    Fehler ging dabei bisher komplett verloren - ein leerer String sieht für
    _finalize_extracted_text (app/main.py) identisch aus wie "Seite enthält
    keinen Text" (siehe _OCR_SYSTEM_PROMPT), es blieb also nirgends eine
    Spur, WARUM die Texterkennung wirklich fehlschlug. Auf stderr drucken
    reicht hier (landet im journalctl-Log wie jede andere uvicorn-Ausgabe) -
    ein eigenes Logging-Setup gibt es in diesem Projekt bewusst nicht."""
    client = _get_anthropic_client()
    try:
        message = client.messages.create(
            model=_OCR_MODEL_NAME,
            max_tokens=4096,
            system=_OCR_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.b64encode(image_bytes).decode(),
                            },
                        },
                        {"type": "text", "text": "Transkribiere den Text dieser Seite."},
                    ],
                }
            ],
        )
        usage_log.track_anthropic(_OCR_MODEL_NAME, message.usage, "ocr")
        return message.content[0].text.strip()
    except Exception as e:
        print(f"[OCR] _ocr_page fehlgeschlagen: {e!r}", file=sys.stderr)
        return ""


def ocr_pdf_with_ai(data: bytes) -> str:
    """Texterkennung per KI-Vision für gescannte PDFs ohne Text-Ebene (siehe
    extract_pdf()). Rendert jede Seite als Bild und lässt das Modell den
    sichtbaren Text transkribieren - kann pro Seite mehrere Sekunden dauern,
    läuft deshalb als Hintergrund-Job (siehe _process_pdf_ocr in
    app/main.py) statt die Vorschau/das Anlegen der Quelle zu blockieren."""
    try:
        pages = _render_pdf_pages_to_images(data)
    except Exception as e:
        print(f"[OCR] _render_pdf_pages_to_images fehlgeschlagen: {e!r}", file=sys.stderr)
        return ""
    texts = [_ocr_page(page) for page in pages]
    return "\n\n".join(t for t in texts if t)


def _parse_markdown_extraction(raw: str) -> dict:
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.DOTALL)
    if not match:
        return {"title": "", "authors": [], "date": "", "text": raw.strip()}

    frontmatter, body = match.group(1), match.group(2)
    meta = {}
    for line in frontmatter.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()

    return {
        "title": meta.get("title", ""),
        "authors": _split_authors(meta.get("author", "")),
        "date": meta.get("date", ""),
        "text": body.strip(),
    }


def extract_from_url(url: str) -> dict:
    # SSRF-Schutz: alle Zweige unten laden über _safe_urlopen (inkl.
    # Prüfung jedes Weiterleitungsziels), der YouTube-Zweig nutzt aber
    # zusätzlich youtube_transcript_api mit eigenem Networking - deshalb
    # hier einmal vorab geprüft, bevor überhaupt ein Zweig startet. Wie überall
    # sonst in dieser Funktion degradiert eine unsichere URL still zu
    # "nicht extrahierbar" statt einer Fehlermeldung, damit sich dieser Fall
    # nicht von jedem anderen Abruf-Fehlschlag unterscheidet.
    try:
        _assert_safe_url(url)
    except UnsafeUrlError:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    if _is_youtube_url(url):
        return _extract_youtube(url)

    if looks_like_audio(url):
        return _extract_audio(url)

    if looks_like_pdf(url):
        data = download_pdf_bytes(url)
        if not data:
            return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}
        return extract_pdf(data)

    downloaded = _fetch_html(url)
    if not downloaded:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    markdown_result = trafilatura.extract(
        downloaded,
        url=url,
        output_format="markdown",
        with_metadata=True,
        favor_precision=True,
    )
    if not markdown_result:
        return {"title": "", "authors": [], "date": "", "text": "", "extracted": False}

    parsed = _parse_markdown_extraction(markdown_result)
    text = parsed["text"].strip()
    result = {
        "title": parsed["title"],
        "authors": parsed["authors"],
        "date": parsed["date"],
        "text": text,
        "extracted": bool(text),
    }
    images = extract_web_images(downloaded, url, text) if text else []
    if images:
        result["images"] = images
    return result



_EPUB_MAX_UNCOMPRESSED = 100 * 1024 * 1024
_EPUB_MAX_ENTRIES = 5000
_EPUB_BLOCK_TAGS = {"p", "div", "br", "li", "tr", "blockquote", "section", "h1", "h2", "h3", "h4", "h5", "h6"}


class _XhtmlToText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        elif tag in _EPUB_BLOCK_TAGS:
            self.parts.append("\n")
            if tag in ("h1", "h2", "h3"):
                self.parts.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self._skip = max(0, self._skip - 1)
        elif tag in _EPUB_BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _xhtml_to_text(markup: str) -> str:
    parser = _XhtmlToText()
    parser.feed(markup)
    lines = (" ".join(line.split()) for line in "".join(parser.parts).split("\n"))
    return "\n".join(line for line in lines if line)


def _read_capped(z: zipfile.ZipFile, name: str, limit: int = _EPUB_MAX_UNCOMPRESSED) -> bytes:
    with z.open(name) as f:
        data = f.read(limit + 1)
    if len(data) > limit:
        raise ValueError("zu groß")
    return data


def _parse_xml_safe(data: bytes) -> ElementTree.Element:
    # Nur UTF-8: sonst ließe sich die Sperre per UTF-16 umgehen.
    if b"\x00" in data or data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise ValueError("nur UTF-8 erlaubt")
    declared = re.match(rb"\s*<\?xml[^>]*encoding=[\"']([^\"']+)", data[:200])
    if declared and declared.group(1).lower() not in (b"utf-8", b"utf8"):
        raise ValueError("nur UTF-8 erlaubt")
    if re.search(rb"<!(DOCTYPE|ENTITY)", data, re.I):
        raise ValueError("DOCTYPE/ENTITY nicht erlaubt")
    return ElementTree.fromstring(data)


def _epub_encrypted_paths(z: zipfile.ZipFile, names: set[str]) -> set[str]:
    """Pfade aus META-INF/encryption.xml, ausgenommen reine Font-Obfuskation."""
    if "META-INF/encryption.xml" not in names:
        return set()
    root = _parse_xml_safe(_read_capped(z, "META-INF/encryption.xml"))
    fonts = ("http://www.idpf.org/2008/embedding", "http://ns.adobe.com/pdf/enc#RC")
    result = set()
    for data_el in root.iter():
        if data_el.tag.rsplit("}", 1)[-1] != "EncryptedData":
            continue
        algo = next((e.get("Algorithm") for e in data_el.iter() if e.tag.rsplit("}", 1)[-1] == "EncryptionMethod"), "")
        if algo in fonts:
            continue
        result.update(posixpath.normpath(e.get("URI", "")) for e in data_el.iter() if e.tag.rsplit("}", 1)[-1] == "CipherReference")
    return result


def extract_epub(data: bytes) -> dict:
    """Spine-Reihenfolge, h1-h3 als #-###. Jeder Fehler -> extracted False.
    # ponytail: NCX/nav werden nicht ausgewertet."""
    empty = {"title": "", "authors": [], "date": "", "text": "", "extracted": False}
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            infos = z.infolist()
            if len(infos) > _EPUB_MAX_ENTRIES or sum(i.file_size for i in infos) > _EPUB_MAX_UNCOMPRESSED:
                return empty
            names = set(z.namelist())
            encrypted = _epub_encrypted_paths(z, names)
            container = _parse_xml_safe(_read_capped(z, "META-INF/container.xml"))
            opf_path = next(e.get("full-path") for e in container.iter() if e.tag.endswith("}rootfile") or e.tag == "rootfile")
            opf = _parse_xml_safe(_read_capped(z, opf_path))
            ns_local = lambda el: el.tag.rsplit("}", 1)[-1]  # noqa: E731
            hrefs = {el.get("id"): el.get("href") for el in opf.iter() if ns_local(el) == "item"}
            title, authors, parts = "", [], []
            seen: set[str] = set()
            budget = _EPUB_MAX_UNCOMPRESSED
            for el in opf.iter():
                if ns_local(el) == "title" and not title:
                    title = (el.text or "").strip()
                elif ns_local(el) == "creator" and (el.text or "").strip():
                    authors.append(el.text.strip())
                elif ns_local(el) == "itemref":
                    href = hrefs.get(el.get("idref"))
                    if not href:
                        continue
                    path = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), href.split("#")[0]))
                    if path.startswith("..") or path.startswith("/") or path not in names or path in seen:
                        continue
                    if path in encrypted:
                        return empty  # DRM: Inhalt wäre Zeichensalat
                    seen.add(path)
                    raw = _read_capped(z, path, budget)
                    budget -= len(raw)
                    parts.append(_xhtml_to_text(raw.decode("utf-8", errors="replace")))
        text = "\n".join(p for p in parts if p).strip()
        return {"title": title, "authors": authors, "date": "", "text": text, "extracted": bool(text)}
    except Exception:
        return empty


# --- Bilder (Idee ff895248) ---------------------------------------------------
MAX_IMAGES_PER_SOURCE = 30
_MIN_WEB_IMAGE_PX = 120
_MIN_PDF_IMAGE_PX = 200
_IMAGE_ALT_MAX = 300
_ANCHOR_CHARS = 80
_SKIP_IMAGE_NAME_RE = re.compile(r"logo|icon|avatar|sprite|pixel|badge|emoji|gravatar", re.IGNORECASE)
_SKIP_IMAGE_EXT_RE = re.compile(r"\.(svg|ico|gif)$", re.IGNORECASE)
_CHROME_TAGS = {"nav", "header", "footer", "aside"}
_URL_SIZE_HINTS = (
    re.compile(r"w(\d{2,5}),h(\d{2,5})"),
    re.compile(r"(\d{2,5})x(\d{2,5})(?=\.\w+$|[?#]|$)"),
)
# CDN-Transformationen (Cloudinary/Substack: w_40,h_40) nennen die
# angezeigte Größe - sie zählen vor der Originalgröße im Dateinamen.
_CDN_W_RE = re.compile(r"(?:^|[,/])w_(\d{2,5})(?=[,/])")
_CDN_H_RE = re.compile(r"(?:^|[,/])h_(\d{2,5})(?=[,/])")
# Breiter/höher als 4:1 = Schriftzug-Banner oder Trennlinie, keine Grafik.
_MAX_IMAGE_ASPECT = 4
# Nutzerwunsch (2026-10-25): Video-Vorschauen stiften keinen Wert.
_VIDEO_HOST_RE = re.compile(r"^https?://([^/]*\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com|ytimg\.com|vimeo\.com|vimeocdn\.com)(/|$)", re.IGNORECASE)


def _px(value: str | None) -> int | None:
    match = re.match(r"\s*(\d+)", value or "")
    return int(match.group(1)) if match else None


def _size_hint(url: str, srcset: str) -> tuple[int | None, int | None] | None:
    """Größe aus URL-Muster (w1920,h798 / -1366x1366) oder dem größten
    srcset-Deskriptor; None, wenn nichts erkennbar."""
    path = unquote(urlparse(url).path)
    cdn_w, cdn_h = _CDN_W_RE.search(path), _CDN_H_RE.search(path)
    if cdn_w or cdn_h:
        return (int(cdn_w.group(1)) if cdn_w else None, int(cdn_h.group(1)) if cdn_h else None)
    for pattern in _URL_SIZE_HINTS:
        match = pattern.search(path)
        if match:
            return int(match.group(1)), int(match.group(2))
    widths = [int(m) for m in re.findall(r"\s(\d+)w\b", srcset or "")]
    return (max(widths), None) if widths else None


def _safe_https_url(raw: str, base_url: str) -> str | None:
    try:
        url = urljoin(base_url, (raw or "").strip())
        parts = urlparse(url)
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    return url


class _ImageCollector(HTMLParser):
    """Zweiter Durchlauf neben trafilatura: sammelt <img> samt Kontext und die
    Textknoten, aus denen später der Anker gewählt wird."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, object]] = []  # ("text", str) | ("img", dict)
        self._chrome = 0
        self._figure = 0
        self._ignore = 0
        self._link = ""

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._link = dict(attrs).get("href") or ""
        if tag in _CHROME_TAGS:
            self._chrome += 1
        elif tag == "figure":
            self._figure += 1
        elif tag in ("script", "style"):
            self._ignore += 1
        elif tag == "img" and not self._chrome:
            self.events.append(
                ("img", {**dict(attrs), "_in_figure": bool(self._figure), "_video_link": bool(_VIDEO_HOST_RE.match(self._link))})
            )

    def handle_endtag(self, tag):
        if tag == "a":
            self._link = ""
        if tag in _CHROME_TAGS:
            self._chrome = max(0, self._chrome - 1)
        elif tag == "figure":
            self._figure = max(0, self._figure - 1)
        elif tag in ("script", "style"):
            self._ignore = max(0, self._ignore - 1)

    def handle_data(self, data):
        if self._chrome or self._ignore:
            return
        collapsed = " ".join(data.split())
        if len(collapsed) >= 20:
            self.events.append(("text", collapsed))


def _image_candidate(attrs: dict, base_url: str) -> tuple[str, str] | None:
    src = attrs.get("data-src") or attrs.get("data-lazy-src") or attrs.get("src") or ""
    url = _safe_https_url(src, base_url)
    if not url or attrs.get("_video_link") or _VIDEO_HOST_RE.match(url):
        return None
    path = urlparse(url).path
    if _SKIP_IMAGE_EXT_RE.search(path) or _SKIP_IMAGE_NAME_RE.search(path):
        return None
    alt = " ".join((attrs.get("alt") or "").split())[:_IMAGE_ALT_MAX]
    width, height = _px(attrs.get("width")), _px(attrs.get("height"))
    if width is None and height is None:
        hint = _size_hint(url, attrs.get("srcset") or attrs.get("data-srcset") or "")
        if hint:
            width, height = hint
    if width is None and height is None:
        if not attrs["_in_figure"] and len(alt) < 10:
            return None
    elif min(v for v in (width, height) if v is not None) < _MIN_WEB_IMAGE_PX:
        return None
    if not (width and height):
        original = _URL_SIZE_HINTS[1].search(unquote(path))
        width, height = (int(original.group(1)), int(original.group(2))) if original else (width, height)
    if width and height and max(width, height) > _MAX_IMAGE_ASPECT * min(width, height):
        return None
    return url, alt


def extract_web_images(html, base_url: str, text: str) -> list[dict]:
    """Bilder einer Web-Seite als {kind:"url", url, alt, anchor}. Nur https,
    ohne Logos/Icons/Navigation; der Anker (80 Zeichen des nächsten
    Textknotens) muss im extrahierten Text stehen, sonst fällt das Bild weg.
    Fehler -> []."""
    try:
        if isinstance(html, bytes):
            html = html.decode("utf-8", errors="replace")
        collector = _ImageCollector()
        collector.feed(html)
        collector.close()
        events = collector.events
        text_norm = norm_anchor(text)
        images, seen = [], set()
        for index, (kind, payload) in enumerate(events):
            if kind != "img":
                continue
            candidate = _image_candidate(payload, base_url)
            if not candidate or candidate[0] in seen:
                continue
            following = [e[1] for e in events[index + 1 :] if e[0] == "text"][:8]
            preceding = [e[1] for e in reversed(events[:index]) if e[0] == "text"][:1]
            for node in following + preceding:
                anchor = node[:_ANCHOR_CHARS]
                if norm_anchor(anchor) and norm_anchor(anchor) in text_norm:
                    seen.add(candidate[0])
                    images.append({"kind": "url", "url": candidate[0], "alt": candidate[1], "anchor": anchor})
                    break
            if len(images) >= MAX_IMAGES_PER_SOURCE:
                break
        return images
    except Exception:
        return []


_MAX_PDF_IMAGE_PIXELS = 25_000_000


def _pdf_anchor_candidates(raw_text: str) -> list[str]:
    """Anker-Kandidaten einer Seite: 80 Zeichen ab Zeile 1, 2, 3 ..."""
    lines = [" ".join(line.split()) for line in raw_text.splitlines() if line.strip()]
    return [" ".join(lines[k:])[:_ANCHOR_CHARS] for k in range(len(lines))]


def extract_pdf_images(data: bytes, max_images: int = MAX_IMAGES_PER_SOURCE) -> list[dict]:
    """Eingebettete Bilder eines PDFs als {data, page (1-basiert), anchor}.
    Verworfen: unter 200 px, über 25 Megapixel, auf >= 3 Seiten wiederholt
    (Logos/Kopfzeilen), >= 90 % der Seite (Scans), Seiten ohne Text (kein
    Anker). Seitentext wird nur für Seiten mit Bildern gelesen; der Anker
    ist je Bildseite eindeutig (sonst weiter unten auf der Seite). Fehler -> []."""
    try:
        import fitz

        reader = PdfReader(io.BytesIO(data))
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return []
    try:
        image_pages: dict[int, list] = {}
        pages_of: dict[int, set[int]] = {}
        for index, page in enumerate(doc):
            listed = page.get_images()
            if listed:
                image_pages[index] = listed
            for img in listed:
                pages_of.setdefault(img[0], set()).add(index)
        candidates: dict[int, list[str]] = {}
        for index in image_pages:
            try:
                candidates[index] = _pdf_anchor_candidates(reader.pages[index].extract_text() or "")
            except Exception:
                continue
        result, seen_xrefs = [], set()
        for index, listed in image_pages.items():
            if not candidates.get(index):
                continue
            others = {
                norm_anchor(c) for other, cands in candidates.items() if other != index for c in cands
            }
            anchor = next((c for c in candidates[index] if norm_anchor(c) not in others), candidates[index][0])
            page = doc[index]
            page_area = page.rect.get_area() or 1
            for img in listed:
                xref = img[0]
                if len(pages_of[xref]) >= 3 or xref in seen_xrefs:
                    continue
                if img[2] * img[3] > _MAX_PDF_IMAGE_PIXELS or min(img[2], img[3]) < _MIN_PDF_IMAGE_PX:
                    continue
                try:
                    if any(r.get_area() / page_area >= 0.9 for r in page.get_image_rects(xref)):
                        continue
                    info = doc.extract_image(xref)
                except Exception:
                    continue
                if not info:
                    continue
                seen_xrefs.add(xref)
                result.append({"data": info["image"], "page": index + 1, "anchor": anchor})
                if len(result) >= max_images:
                    return result
        return result
    except Exception:
        return []
    finally:
        doc.close()
