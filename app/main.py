import contextlib
import hashlib
import hmac
import itertools
import json
import logging
import os
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import networkx as nx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.routing import Route

load_dotenv()

from app import (
    audit,
    auth,
    author_photos,
    author_profiles,
    authors,
    captcha,
    chunking,
    conversation_handoff,
    embeddings,
    extraction,
    i18n,
    image_review,
    jsonstore,
    llm,
    mail,
    mcp_keys,
    mcp_server,
    monitoring,
    question_log,
    ratelimit,
    source_discovery,
    source_images,
    source_suggestions,
    summarization,
    terms,
    transcription_hints,
    tts,
    usage,
    users,
    vectorstore,
    web_allowlist,
    web_candidates,
    web_crawler,
    web_index,
)
from app.models import (
    DevVergleichIn,
    ImageRef,
    AdminUserOut,
    AnswerFeedbackIn,
    AuditLogEntryOut,
    AuthorOut,
    AuthorProfileIn,
    BioOut,
    AuthorBioPreviewIn,
    BrokenLinksCountOut,
    RenameAuthorIn,
    ChunkRef,
    ConversationHandoffIn,
    CreativeRequestIn,
    EarlyAccessIn,
    ExtractedSource,
    ExtractedUpload,
    FeedbackIn,
    GraphEdge,
    GraphNode,
    ImportJobOut,
    InviteIn,
    KeyTermsOut,
    KeyTermsPreviewIn,
    KnowledgeGraphOut,
    MessageOut,
    QuestionIn,
    QuestionLogEntryOut,
    RequestLinkIn,
    SourceIn,
    SourceOut,
    SourceSuggestionOut,
    SpeechIn,
    LanguageDetectionOut,
    SummaryOut,
    TermMergeIn,
    TermMergeOut,
    TermMergeSuggestionsIn,
    TermOut,
    TermsDeleteIn,
    TurnstileConfigOut,
    UpdateUserNameIn,
    UpdateUserRolesIn,
    McpKeyCreateIn,
    McpKeyCreatedOut,
    McpKeyLimitsIn,
    McpKeyOut,
    UrlCheckOut,
    UrlIn,
    VersionOut,
    WebAllowlistEntryIn,
    WebAllowlistEntryOut,
    WebCandidateOut,
    WebIndexPageOut,
    WhoAmIOut,
)

# "development": Cookies werden ohne "Secure"-Flag gesetzt, damit Logins auch
# über http://localhost funktionieren (siehe .env.example).
IS_DEV_ENVIRONMENT = os.environ.get("ENVIRONMENT", "").strip().lower() == "development"

# Der Site-Key ist (anders als TURNSTILE_SECRET_KEY) öffentlich und für den
# Turnstile-Mechanismus ausdrücklich dafür gedacht, im Frontend zu landen -
# über /api/turnstile-config statt fest ins JS einkompiliert, damit Dev/Stabil/
# Produktion unterschiedliche, zum jeweiligen Hostnamen passende Keys nutzen
# können (ein Produktions-Site-Key akzeptiert z.B. kein localhost - siehe
# .env.example für Cloudflares offizielle Test-Keys für die lokale Entwicklung).
TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")


def _get_current_user_email(request: Request) -> str | None:
    return auth.verify_session_token(request.cookies.get(auth.SESSION_COOKIE_NAME))


def require_role(role: str):
    def check(request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
        email = _get_current_user_email(request)
        if not users.has_role(email, role):
            raise HTTPException(
                403,
                i18n.get_message("role_required", x_lang, role=role, user=email or "anon"),
            )
        return email

    return check


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SOURCES_FILE = DATA_DIR / "sources.json"
STATIC_DIR = BASE_DIR / "static"
PDF_DIR = DATA_DIR / "pdfs"
PDF_UPLOAD_STAGING_DIR = DATA_DIR / "pdf_uploads"
AUDIO_DIR = DATA_DIR / "audio"
SOURCE_IMAGES_DIR = DATA_DIR / "source_images"
IMAGE_STAGING_DIR = DATA_DIR / "image_staging"
AUDIO_UPLOAD_STAGING_DIR = DATA_DIR / "audio_uploads"

DATA_DIR.mkdir(exist_ok=True)


def _get_version() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "describe", "--tags", "--abbrev=0"],
                cwd=BASE_DIR,
                stderr=subprocess.DEVNULL,
                timeout=2,
            )
            .decode()
            .strip()
        )
    except Exception:
        return "dev"


APP_VERSION = _get_version()


# Fix (2026-08-23, realer Datenverlust auf Dev): alle Hintergrund-Threads
# (Audio-Transkription, URL-Gesundheits-Check, Web-Allowlist-Crawl,
# Quellen-Vorschlag-Suche, Zusammenfassungs-Nachzug) sowie die Einmal-
# Aufräumarbeiten beim Start liefen bisher UNBEDINGT beim bloßen Import
# dieses Moduls - nicht erst bei einem echten Server-Start. Jedes
# `python3 -c "from app import main"` (z.B. für einen schnellen Syntax-
# Check) UND sogar der Import durch die Test-Suite selbst (test_api.py:
# `from app import main as main_module`) haben dadurch echte Hintergrund-
# Threads mit echten Netzwerk-/API-Aufrufen auf die ECHTEN Dev-Daten
# gestartet, lange bevor irgendein Test-Mock oder tmp_path-Monkeypatch
# greifen konnte - deckt sich mit dem im Code selbst dokumentierten realen
# Vorfall vom 2026-07-28 (nebenläufige, unsynchronisierte Hintergrund-
# Threads, "Lost Update" auf sources.json). Über das ASGI-Lifespan-Protokoll
# starten diese Threads jetzt nur noch bei einem ECHTEN Server-Start
# (uvicorn) - ein bloßer Modul-Import (Skripte, Tests) hat ab jetzt keine
# Seiteneffekte mehr. Siehe _start_background_workers() weiter unten für die
# eigentliche Liste.
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    _start_background_workers()
    # MCP-Endpunkt (app/mcp_server.py): der Sitzungs-Manager des SDK muss
    # im Lebenszyklus der App laufen, eingehängte Unter-Apps bekommen
    # keinen eigenen Lifespan.
    async with mcp_server.session_manager.run():
        yield
    _wait_for_background_jobs_on_shutdown()


app = FastAPI(title="BetaCodex Wissensassistent", lifespan=lifespan)


# Backlog #58: einzige externe Host, die die App tatsächlich als Ressource
# einbindet, ist Cloudflare Turnstile (Skript + das von ihm erzeugte iFrame).
# img-src erlaubt bewusst beliebige https-Quellen, weil Autor:innen-Fotos
# (photo_url) frei eingetragene externe URLs sind - eine engere Regel würde
# dieses bestehende Feature brechen. Keine Inline-Skripte nötig (siehe
# init-footer.js), daher script-src ohne 'unsafe-inline'.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self' https://challenges.cloudflare.com; "
    "style-src 'self'; "
    "img-src 'self' data: https:; "
    "font-src 'self'; "
    # blob: für die per URL.createObjectURL() erzeugte Audio-Blob-URL beim
    # Abspielen der TTS-Antwort (Backlog #49, siehe static/speech.js) - ohne
    # dieses Directive würde die strikte default-src-Regel das <audio>-
    # Element sonst blockieren.
    "media-src 'self' blob:; "
    "connect-src 'self' https://challenges.cloudflare.com; "
    "frame-src https://challenges.cloudflare.com; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)

# Backlog #75: einzige Seite, die sich absichtlich in einem iframe auf
# fremden Domains einbetten lassen soll (Embed-Widget) - jede andere Seite
# bleibt beim strikten frame-ancestors 'none'/X-Frame-Options: DENY.
EMBED_CONTENT_SECURITY_POLICY = CONTENT_SECURITY_POLICY.replace(
    "frame-ancestors 'none'", "frame-ancestors *"
)
_EMBED_FRAMEABLE_PATHS = {"/embed.html"}


# Idee 669405f0: Crawler-Schutz. Die Sperrliste ist robots.txt (eine Liste,
# keine Ausnahmen im Code). Nur Trainings-/Index-Crawler; Assistenten wie
# ChatGPT-User stehen dort nicht.
def load_blocked_agents(path: Path) -> tuple[str, ...]:
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ()
    names = []
    for line in lines:
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() == "user-agent":
            name = value.split("#", 1)[0].strip().lower()
            if name != "*" and len(name) >= 4:
                names.append(name)
    return tuple(names)


BLOCKED_AGENTS = load_blocked_agents(STATIC_DIR / "robots.txt")

# (Anzahl, Sekunden) je IP, nur für Gäste. Lastfall: 30 Personen hinter einer
# NAT-IP (Entscheidung E2).
CRAWLER_LIMITS = {"content-ip": (400, 300), "source-ip": (150, 600), "search-ip": (150, 60)}
_GUARD_FREE_PATH_RE = re.compile(r"^/api/sources/[^/]+/images/|^/api/authors/[^/]+/photo/")
_GUARD_CONTENT_PREFIXES = ("/api/sources", "/api/authors", "/api/knowledge-graph", "/api/terms")


def _session_user_email(request: Request) -> str | None:
    """Wie _get_current_user_email, aber nur für noch existierende Nutzer:innen
    (eine gültige Sitzung eines gelöschten Nutzers gilt als Gast)."""
    email = _get_current_user_email(request)
    return email if email and users.get_user(email) else None


def _short_ip(ip: str) -> str:
    key = ratelimit.ip_key(ip)
    parts = key.split(".")
    return ".".join(parts[:3] + ["0"]) if len(parts) == 4 else key


def _guard_keys(path: str) -> list[str]:
    if _GUARD_FREE_PATH_RE.match(path):
        return []
    if path == "/api/sources/search":
        return ["search-ip"]
    if not path.startswith(_GUARD_CONTENT_PREFIXES):
        return []
    keys = ["content-ip"]
    if (
        path.startswith("/api/sources/")
        and path.count("/") == 3
        and path != "/api/sources/broken-links-count"
    ):
        keys.append("source-ip")
    return keys


def _guard_response(status: int, key: str, request: Request, ip: str, headers=None, detail=None):
    logging.getLogger(__name__).warning("crawler_guard %s key=%s path=%s ip=%s", status, key, request.url.path, _short_ip(ip))
    return JSONResponse({"detail": detail or "Forbidden"}, status_code=status, headers=headers)


class _HideSearchQuery(logging.Filter):
    """Suchbegriffe nie ins Access-Log (uvicorn: args = IP, Methode, Pfad, ...)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) > 2 and isinstance(args[2], str) \
                and args[2].startswith("/api/sources/search"):
            record.args = (*args[:2], args[2].split("?", 1)[0], *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_HideSearchQuery())


@app.middleware("http")
async def guard_crawlers(request: Request, call_next):
    path = request.url.path
    ip = request.client.host if request.client else "unknown"
    if path != "/robots.txt" and path != mcp_server.MCP_PATH and not path.startswith(mcp_server.MCP_PATH + "/"):
        ua = request.headers.get("user-agent", "").lower()
        if any(name in ua for name in BLOCKED_AGENTS):
            return _guard_response(403, "ua-block", request, ip)
    # ponytail: nur je IP; Turnstile-Gate, falls rotierende IPs abgreifen
    keys = _guard_keys(path) if request.method == "GET" else []
    if keys and not _session_user_email(request):
        for name in keys:
            limit, window = CRAWLER_LIMITS[name]
            key = f"{name}:{ratelimit.ip_key(ip)}"
            if ratelimit.is_rate_limited(key, max_requests=limit, window_seconds=window):
                lang = request.headers.get("x-lang", i18n.DEFAULT_LANG)
                return _guard_response(
                    429, name, request, ip,
                    headers={"Retry-After": str(ratelimit.retry_after_seconds(key, window))},
                    detail=i18n.get_message("rate_limited", lang),
                )
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path in _EMBED_FRAMEABLE_PATHS and os.environ.get("EMBED_ENABLED", "") == "true":
        # X-Frame-Options bewusst NICHT setzen: moderne Browser ignorieren es
        # zugunsten von frame-ancestors, ältere würden trotz gelockertem CSP
        # sonst weiterhin blocken.
        response.headers["Content-Security-Policy"] = EMBED_CONTENT_SECURITY_POLICY
    else:
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    # Backlog #115: nur Dev/Stabil sollen nicht in Suchmaschinen-/KI-Indizes
    # auftauchen - deckt (anders als die HTML-Meta-Tags) auch Nicht-HTML-
    # Antworten ab. Die echte Produktivinstanz setzt ENVIRONMENT nie auf
    # "development" und bleibt damit indexierbar.
    if IS_DEV_ENVIRONMENT:
        response.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return response


# Backlog #114: Pfade, die auch bei aktiver Early-Access-Sperre erreichbar
# bleiben müssen - die Gate-Seite selbst, ihr JS, der Freischalt-Endpoint und
# die für ihre Darstellung nötigen, bereits bestehenden statischen Assets.
# Bewusst eine kleine, feste Liste statt eines Musters/Präfix-Checks - jeder
# zusätzliche Eintrag hier ist eine bewusste Entscheidung, kein Nebeneffekt.
_EARLY_ACCESS_EXEMPT_PATHS = {
    "/early-access.html",
    "/early-access.js",
    "/api/early-access",
    "/style.css",
    "/fonts/fonts.css",
    "/fonts/Inter/inter-latin-400-normal.woff2",
    "/fonts/Inter/inter-latin-600-normal.woff2",
    "/fonts/Inter/inter-latin-700-normal.woff2",
    "/fonts/Inter/inter-latin-ext-400-normal.woff2",
    "/fonts/Inter/inter-latin-ext-600-normal.woff2",
    "/fonts/Inter/inter-latin-ext-700-normal.woff2",
    "/fonts/Oswald/oswald-latin-600-normal.woff2",
    "/fonts/Oswald/oswald-latin-ext-600-normal.woff2",
    "/i18n.js",
    "/i18n/de.json",
    "/i18n/en.json",
    # Nutzerwunsch (2026-09-04): das Einbetten-Widget soll unabhängig vom
    # Aufheben der Early-Access-Sperre nutzbar sein - EMBED_ENABLED
    # entscheidet weiterhin allein, ob /embed.html überhaupt existiert (statt
    # 404, siehe get_embed_page). Liste enthält bewusst NUR, was für die
    # eigentliche Frage-Antwort-Funktion des Widgets nötig ist - das
    # "Vollständig öffnen"-Icon (Backlog #75, conversation-handoff.js) führt
    # für anonyme Embed-Besucher:innen weiterhin zur Early-Access-Gate-Seite
    # von index.html, da /api/conversation-handoff absichtlich NICHT
    # exemptiert ist (createConversationHandoffToken() fängt das bereits
    # ab und navigiert stattdessen ohne Token, siehe dortiger Kommentar).
    "/embed.html",
    "/icons/favicon.png",
    "/icons/favicon.svg",
    "/question.js",
    "/embed-resize.js",
    "/markdown.js",
    "/auth.js",
    "/turnstile.js",
    "/speech.js",
    "/ndjson-stream.js",
    "/conversation-handoff.js",
    "/source-lang.js",
    "/answer-feedback.js",
    "/question-sources.js",
    "/source-edit.js",
    "/source-images-panel.js",
    "/api/ask",
    "/api/turnstile-config",
    "/api/auth/whoami",
    "/api/sources",
    "/api/speech",
    "/api/answer-feedback",
    # Fix (2026-08-02): ohne diese Ausnahme griff die Sperre auch hier - der
    # Magic-Link-Token in der URL wurde nie geprüft, stattdessen bekam jede
    # Person ohne Early-Access-Cookie (also praktisch jeder erste Klick auf
    # einen frisch verschickten Login-/Einladungslink) die Passwort-Gate-
    # Seite gezeigt, während die URL weiterhin den Auth-Token als
    # Query-Parameter enthielt. Diese Kombination (Token-Parameter + bloße
    # Passwortabfrage) wurde von Chrome als Phishing-Muster eingestuft.
    "/api/auth/verify",
}


@app.middleware("http")
async def enforce_early_access(request: Request, call_next):
    # Bewusst pro Anfrage aus os.environ gelesen (nicht als Modul-Konstante
    # beim Start zwischengespeichert) - analog zu captcha.verify_turnstile_token:
    # ohne gesetzten Wert (Dev/Stabil) bleibt die Sperre inaktiv, die App
    # funktioniert exakt wie zuvor. Erst auf dem künftigen Produktiv-Server,
    # wo dieser Wert gesetzt wird, greift sie.
    early_access_password = os.environ.get("EARLY_ACCESS_PASSWORD", "")
    if early_access_password and request.url.path not in _EARLY_ACCESS_EXEMPT_PATHS:
        if not auth.verify_early_access_token(request.cookies.get(auth.EARLY_ACCESS_COOKIE_NAME)):
            return FileResponse(STATIC_DIR / "early-access.html")
    return await call_next(request)


# Backlog (2026-09-20): ohne Obergrenze las der Server jeden Body komplett
# ein, bevor Zeichenlimits oder Rate-Limits griffen. Als reine ASGI-
# Middleware, damit sie auch /mcp und Bodies ohne Content-Length (chunked)
# erfasst - die werden beim Lesen mitgezählt.
REQUEST_BODY_LIMITS = {
    "/api/extract-pdf-upload": 200 * 1024 * 1024,
    "/api/extract-epub-upload": 200 * 1024 * 1024,
    "/api/extract-audio-upload": 200 * 1024 * 1024,
    "/api/sources": 20 * 1024 * 1024,  # Volltexte beim Anlegen/Bearbeiten
}
REQUEST_BODY_DEFAULT_LIMIT = 1024 * 1024


class _BodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope["path"]
        limit = next((v for k, v in REQUEST_BODY_LIMITS.items() if path.startswith(k)), REQUEST_BODY_DEFAULT_LIMIT)
        headers = dict(scope["headers"])
        lang = headers.get(b"x-lang", b"").decode() or i18n.DEFAULT_LANG

        state = {"too_large": False, "started": False, "rejected": False}

        async def reject():
            state["rejected"] = True
            await JSONResponse({"detail": i18n.get_message("request_too_large", lang)}, 413)(scope, receive, send)

        length = headers.get(b"content-length", b"")
        if length.isdigit() and int(length) > limit:
            return await reject()

        received = 0

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    state["too_large"] = True
                    raise _BodyTooLarge()
            return message

        # FastAPI macht aus Fehlern beim Body-Lesen eine eigene 400-Antwort -
        # die wird hier durch die 413 ersetzt.
        async def replacing_send(message):
            if state["too_large"] and not state["started"]:
                if not state["rejected"]:
                    await reject()
                return
            state["started"] = True
            await send(message)

        try:
            await self.app(scope, counting_receive, replacing_send)
        except Exception:
            if not state["too_large"]:
                raise
        if state["too_large"] and not state["started"] and not state["rejected"]:
            await reject()


app.add_middleware(RequestBodyLimitMiddleware)


@app.post("/api/early-access")
def submit_early_access_password(
    body: EarlyAccessIn, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)
):
    # Ein einziges, allen bekanntes Passwort ist ein klassisches Brute-Force-
    # Ziel - deutlich strenger begrenzt als das allgemeine /api/ask-Limit
    # (siehe ratelimit.is_rate_limited), eigener Schlüssel-Namensraum, damit
    # sich beide Limits nicht gegenseitig beeinflussen.
    client_ip = request.client.host if request.client else "unknown"
    if ratelimit.is_rate_limited(f"early-access:{client_ip}", max_requests=5, window_seconds=300):
        raise HTTPException(429, i18n.get_message("early_access_rate_limited", x_lang))

    expected_password = os.environ.get("EARLY_ACCESS_PASSWORD", "")
    if not expected_password or not hmac.compare_digest(body.password, expected_password):
        raise HTTPException(401, i18n.get_message("early_access_wrong_password", x_lang))

    response = Response(status_code=204)
    response.set_cookie(
        auth.EARLY_ACCESS_COOKIE_NAME,
        auth.create_early_access_token(),
        max_age=auth.EARLY_ACCESS_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=not IS_DEV_ENVIRONMENT,
        path="/",
    )
    return response


@app.get("/api/version", response_model=VersionOut)
def get_version():
    return VersionOut(
        version=APP_VERSION,
        embed_enabled=os.environ.get("EMBED_ENABLED", "") == "true",
    )


@app.get("/embed.html")
def get_embed_page():
    # Backlog #75: eigener Schalter statt allein über frame-ancestors/CSP zu
    # steuern - während der aktuellen Early-Access-Testphase soll das
    # öffentlich einbettbare Widget noch gar nicht existieren, nicht nur
    # gesperrt sein. Ohne gesetzten Wert bleibt die Seite unerreichbar.
    if os.environ.get("EMBED_ENABLED", "") != "true":
        raise HTTPException(404)
    return FileResponse(STATIC_DIR / "embed.html")


@app.get("/api/turnstile-config", response_model=TurnstileConfigOut)
def get_turnstile_config():
    return TurnstileConfigOut(site_key=TURNSTILE_SITE_KEY)


# Vorfall (2026-08-03): generate_bilingual_summary() gibt bei JEDEM Fehler
# (API-Timeout, Rate-Limit, kaputte Antwort) bewusst ein leeres Ergebnis
# zurueck statt eine Exception zu werfen (siehe app/summarization.py) - eine
# Quelle blieb dadurch fuer immer ohne Zusammenfassung stehen, ohne dass das
# irgendwo sichtbar wurde (processing_status war zu diesem Zeitpunkt schon
# auf None/"fertig" gesetzt). Ein leeres Ergebnis trotz nicht-leerem
# Eingabetext gilt hier als echter Fehlschlag (nicht "nichts zu sagen") und
# wird mit kurzer Pause wiederholt, bevor aufgegeben wird.
SUMMARY_RETRY_ATTEMPTS = 3
SUMMARY_RETRY_DELAY_SECONDS = 5

# Nutzerwunsch (2026-08-03): 10 Minuten statt der ursprünglichen 4 (240s) -
# deckt auch längere Audio-Transkriptionen ab, ohne den Deploy selbst zu
# verzögern (Traffic wechselt beim Blue/Green-Switch sofort auf den neuen
# Slot, der alte läuft nur noch im Hintergrund zu Ende). Muss unter dem
# TimeoutStopSec der systemd-Unit bleiben (siehe deploy.sh/systemd-Unit-
# Doku), sonst killt systemd den Prozess ohnehin per SIGKILL, bevor dieser
# Hook fertig warten konnte.
BACKGROUND_JOB_SHUTDOWN_GRACE_SECONDS = 600
SOURCE_SUGGESTION_QUEUE_TARGET = 100


def _start_background_workers() -> None:
    """Bündelt die INTERVALL-basierten Hintergrund-Threads + Einmal-
    Aufräumarbeiten beim Start (siehe Kommentar bei lifespan() weiter oben) -
    wird ausschließlich von dort aufgerufen, bei einem echten ASGI-Server-
    Start. Der Audio-Transkriptions-Worker-Pool ist bewusst NICHT hier drin
    (siehe eigener Fix-Kommentar bei dessen Start weiter oben) - er tickt
    rein reaktiv statt sofort gegen echte Daten und muss deshalb immer schon
    laufen. Reihenfolge entspricht der bisherigen, rein zeilenweisen
    Ausführung beim Modul-Import: jede Aufräum-Funktion läuft weiterhin VOR
    dem zugehörigen Sweep-Thread."""
    users.ensure_bootstrap_admin(os.environ.get("SYSTEM_ADMIN_EMAIL", ""))
    _normalize_pflaeging_spelling_once()
    _normalize_beta_kodex_spelling_once()
    _repair_char_split_key_terms_once()
    _backfill_term_languages_once()
    threading.Thread(
        target=_run_periodic, args=(_run_url_health_check_once, URL_HEALTH_CHECK_INTERVAL_SECONDS), daemon=True
    ).start()
    threading.Thread(
        target=_run_periodic,
        args=(_run_source_suggestion_discovery_once, SOURCE_SUGGESTION_INTERVAL_SECONDS),
        daemon=True,
    ).start()
    threading.Thread(
        target=_run_periodic, args=(_backfill_summaries_and_language_once, SUMMARY_BACKFILL_INTERVAL_SECONDS), daemon=True
    ).start()
    threading.Thread(
        target=_run_periodic, args=(_cache_missing_author_photos_once, AUTHOR_PHOTO_CACHE_INTERVAL_SECONDS), daemon=True
    ).start()
    _recover_interrupted_web_allowlist_indexing()
    # Kein Web-Crawl auf Dev (2026-11-16): er startete bei jedem lokalen
    # Serverstart sofort und überlebte als Unterprozess das Beenden des
    # Servers - verwaiste Crawls blockierten /exit. Produktion unverändert.
    if not IS_DEV_ENVIRONMENT:
        threading.Thread(
            target=_run_periodic, args=(_run_web_allowlist_crawl_once, WEB_ALLOWLIST_CRAWL_INTERVAL_SECONDS), daemon=True
        ).start()
    threading.Thread(
        target=_run_periodic,
        args=(_purge_expired_question_log_entries_once, QUESTION_LOG_PURGE_INTERVAL_SECONDS),
        daemon=True,
    ).start()
    _recover_interrupted_processing_jobs()
    threading.Thread(target=_warm_up_local_models, daemon=True).start()
    threading.Thread(target=_startup_reindex, daemon=True).start()


# Fix: Embedding (lokales Modell, CPU-gebunden) kann bei sehr großen Texten
# (viele hundert Chunks) mehrere Sekunden dauern - bisher blockierte
# add_source in diesem Fall den kompletten Request. Statt IMMER zu warten,
# wird nur noch bis zu diesem Timeout gewartet; dauert es länger, antwortet
# add_source sofort mit processing_status="pending" (siehe unten) - exakt
# dieselbe Warteschlangen-Logik wie bei Audio-Transkription/PDF-OCR.
SLOW_IMPORT_TIMEOUT_SECONDS = 5


# Nutzerwunsch (2026-09-22): ein einzelner Analyse-Durchlauf über die
# komplette Begriffsliste einer Sprache (bei ~1000+ Begriffen) ließ die
# Quellen-Pfleger:in lange auf JEDES Ergebnis warten, bevor überhaupt mit dem
# Bearbeiten begonnen werden konnte. Läuft jetzt in alphabetisch sortierten
# Häppchen (dieselbe Sortierung wie ohnehin in find_similar_term_groups) -
# jeder Häppchen-Treffer wird sofort per NDJSON-Stream (gleiches Muster wie
# /api/ask) an die Oberfläche geschickt, statt auf den gesamten Durchlauf zu
# warten. ponytail: ein Varianten-Paar, das zufällig über eine Häppchen-
# Grenze fällt (z.B. "Agility" ganz am Ende eines Häppchens, "Agilität" ganz
# am Anfang des nächsten), wird dadurch nicht gefunden - bei ähnlich
# geschriebenen Begriffen (der Regelfall: Tippfehler, Singular/Plural,
# Wortbildung) liegen beide durch die alphabetische Sortierung fast immer im
# selben oder einem benachbarten Häppchen. Add when: ein realer verpasster
# Fall das zeigt, dann echtes Cross-Häppchen-Matching (z.B. mit Überlappung
# an den Häppchen-Grenzen) nachrüsten.
_TERM_MERGE_BATCH_SIZE = 150
# Der Endpunkt ist ohne Captcha erreichbar und schreibt Frage/Antwort ins
# Fragen-Log - ohne Obergrenze könnte ein Skript das Log (und damit jeden
# Schreibvorgang und die Log-Seite) mit Riesentexten aufblähen. Überlange
# Texte werden gekürzt (mit "…"), das Feedback selbst geht nie verloren.
# Grenzen entsprechen den Kreativ-Limits für Anweisung/Dokument (der
# Kreativ-Text ist der längste legitime Inhalt).
ANSWER_FEEDBACK_MAX_QUESTION_CHARS = 2000
ANSWER_FEEDBACK_MAX_ANSWER_CHARS = 20000


# Performance-Fix (2026-07-31, Produktion auf schwächerer Hetzner-CPU
# spürbar langsam): die Satz-Embeddings eines Chunks hängen nur von dessen
# TEXT ab, nicht von der gestellten Frage - wurden bislang aber bei JEDER
# Frage neu vom lokalen Modell berechnet, obwohl sich derselbe Chunk über
# viele Fragen hinweg meist gar nicht ändert. Hier über einen Hash des
# tatsächlichen Chunk-Texts gecacht (bewusst NICHT über die chunk_id: die
# bleibt beim Bearbeiten einer Quelle unverändert - siehe
# f"{source_id}::{i}" in _store_chunks -, obwohl sich der Text ändert; ein
# über die ID geschlüsselter Cache würde nach einer Bearbeitung veraltete
# Vektoren für den neuen Text ausliefern). Cacht ausdrücklich NUR die
# chunk-eigenen Satz-Vektoren, nicht das Highlight selbst - welcher Satz am
# Ende gewinnt, hängt weiterhin vom jeweils aktuellen Frage-/Antwortsatz ab
# (query_embedding/claim_embedding, beide frisch pro Anfrage) und wird
# durch den Cache nicht beeinflusst. Wächst unbegrenzt mit der Anzahl
# unterschiedlicher jemals zitierter Chunk-Texte - für eine kuratierte
# Quellensammlung dieser Größenordnung unkritisch.
_CHUNK_SENTENCE_EMBEDDING_CACHE: dict[str, tuple[list[str], list[list[float]] | None]] = {}

# Backlog #51: der Relevanzscore (1-10, Slider in der Quellen-Bearbeitung)
# wirkte bislang nur als gespeichertes Metadatum, ohne Einfluss auf die
# Antwort. Damit er tatsächlich etwas bewirkt, wird hier mehr Kandidaten
# geholt als angefragt (RELEVANCE_OVERFETCH_MULTIPLIER) und danach nach
# einer um den Score angepassten Distanz neu sortiert, bevor auf die
# eigentlich angefragte Anzahl gekürzt wird.
RELEVANCE_OVERFETCH_MULTIPLIER = 3
# Multiplikativ statt additiv, damit die Anpassung unabhängig von der
# absoluten Größenordnung der Chroma-Distanzmetrik bleibt. Bei Score 5
# (Default für unbewertete Quellen) ergibt sich Faktor 1.0 - die Reihenfolge
# ändert sich dann exakt nicht, bestehende Ergebnisse bleiben unangetastet.
RELEVANCE_MAX_ADJUSTMENT = 0.15

# Nutzerwunsch (2026-08-31): eine generische "Erzähl mir über die Arbeiten
# von X"-Frage ist thematisch zu unspezifisch, um gegen den Rest des Korpus
# per reiner Vektor-Ähnlichkeit zuverlässig zu gewinnen - die tatsächlich
# passenden Quellen dieser Person fielen dadurch oft aus den Top-K heraus,
# selbst wenn sie existieren (siehe authors.find_mentioned weiter unten, das
# denselben Namensabgleich bereits für die Vita-Ergänzung nutzt). Wird eine
# registrierte Autor:in erkannt, läuft deshalb ZUSÄTZLICH pro Quelle dieser
# Autor:in eine eigene, gefilterte Vektorsuche (vectorstore.query where=...) -
# bleibt innerhalb ihrer Werke weiterhin themensensitiv, statt wahllos die
# ersten N zu nehmen. AUTHOR_MENTION_DISTANCE_FACTOR verschafft diesen
# Treffern vor dem bestehenden Reranking (_rerank_by_relevance, unverändert)
# einen Vorteil, damit sie einen Platz unter den weiterhin unveränderten
# question.top_k Endergebnissen bekommen - KEINE Vergrößerung des
# Kontext-Budgets, sie konkurrieren nur mit einem Vorteil um dieselben
# Plätze wie alle anderen Kandidaten.
AUTHOR_MENTION_DISTANCE_FACTOR = 0.5
# Fix (2026-09-01, siehe Kommentar bei der Verwendung unten): PRO Quelle
# statt einer gemeinsamen top_k-Suche über alle Chunks der Autor:in hinweg -
# damit pro Quelle einzeln (statt nur pro Autor:in insgesamt) entschieden
# werden kann, ob AUTHOR_MENTION_DISTANCE_FACTOR oder der stärkere
# AUTHOR_MENTION_KEYWORD_MATCH_FACTOR gilt. Klein gehalten, da ohnehin nur
# der jeweils beste Treffer je Quelle für die Konkurrenz um die
# Endergebnisse zählt.
AUTHOR_MENTION_TOP_K_PER_SOURCE = 3
# Fix (2026-09-01, realer Fall "Andreas Schlegel und Zeitorientierung", siehe
# oben): selbst pro Quelle gesucht, verlor die tatsächlich einschlägige
# Quelle rein embedding-mäßig gegen zwei lange, LEDIGLICH gleichsprachige
# Podcast-Transkripte derselben Person zu einem ganz anderen Thema - die
# reine Vektor-Distanz allein reicht hier nicht aus. key_terms_de/en werden
# beim Import bereits pro Quelle von einer KI kuratiert (siehe
# app/summarization.py) - taucht einer dieser Begriffe wörtlich in der Frage
# auf ("Zeitorientierung" ist genau so ein hinterlegter Begriff dieser
# Quelle), ist das ein deutlich präziseres Signal als reine Embedding-Nähe
# und bekommt deshalb einen erheblich stärkeren Rabatt als der normale
# Autor:innen-Erwähnungs-Rabatt oben - reicht aus, um selbst gegen thematisch
# unpassende, aber embedding-mäßig nähere Quellen derselben Person zu
# gewinnen.
AUTHOR_MENTION_KEYWORD_MATCH_FACTOR = 0.05

# Backlog (2026-08-03): ohne Konversationsverlauf beantwortete das Modell
# jede Folgefrage isoliert, ohne den bisherigen Gesprächsverlauf zu kennen -
# das wirkte wie ständige Wiederholung, sobald die neue Frage inhaltlich an
# die vorherige anknüpfte. Serverseitig bewusst nochmal gekappt, unabhängig
# davon, wie viele Turns das Frontend mitschickt (QuestionIn.history) - hält
# den Prompt schlank und begrenzt den Schaden eines manipulierten Requests
# ohne UI.
# Idee 24907bf2: 10 Turns, zusätzlich ein Zeichenbudget. Idee 2070893d: 50
# Turns und ein Budget von 200.000 UTF-8-Bytes (ca. 60k Tokens bei Haiku 4.5,
# Kontextfenster 200k); muss zu ASK_HISTORY_MAX_TURNS/ASK_HISTORY_MAX_BYTES in
# static/question.js passen (Test in tests/test_api.py). Invariante: die
# Feldgrenzen in models.HistoryTurnIn (je 8000 Zeichen) garantieren, dass ein
# Turn (2 x 8000 Zeichen x 4 Bytes = 64 KB) immer unter MAX_BYTES bleibt.
ASK_HISTORY_MAX_TURNS = 50
ASK_HISTORY_MAX_BYTES = 200_000
# Gekürzt wird in Blöcken von 10 Turns (zustandslos, Vielfaches von 10 als
# Startindex), damit der Anfang des Verlaufs über viele Folgefragen
# byte-gleich bleibt und der Prompt-Cache (llm.py) trifft.
ASK_HISTORY_CUT_BLOCK = 10
# Die Umformulierung der Suchanfrage braucht nur den jüngsten Kontext.
ASK_REWRITE_HISTORY_TURNS = 3


# Nutzerwunsch (2026-08-26): Kreativ-Modus (siehe app/llm.py:
# stream_creative_response) - eigene, deutlich engere Rate-Grenze als
# /api/ask (Standard 10/60s). Ein Erstentwurf läuft auf claude-sonnet-5
# (rund 5x Haikus Preis pro Token) mit einem 8x höheren max_tokens-Limit
# als /api/ask PLUS bis zu 3 Websuchen (jede erhöht die Eingabe-Tokenzahl
# real spürbar); selbst eine günstige Haiku-Überarbeitung schickt bei
# jedem einzelnen Aufruf das KOMPLETTE Dokument erneut mit (Ganzdokument-
# Ersatz statt Diff, siehe creative() unten), nicht nur ein kurzes Delta
# wie bei einer Ask-Folgefrage. Pro Anfrage entsteht dadurch grob ein bis
# zwei Größenordnungen mehr Kosten als bei /api/ask - 6 Anfragen/10min
# (= 36/Stunde/IP) lässt eine echte Schreibsitzung (Entwurf + mehrere
# Überarbeitungsrunden) komfortabel zu, deckelt das Kosten-Worst-Case pro
# IP aber auf eine mit /api/ask vergleichbare Größenordnung.
CREATIVE_TOP_K = 6
CREATIVE_MAX_INSTRUCTION_CHARS = 2000
CREATIVE_MAX_DOCUMENT_CHARS = 20000
CREATIVE_RATE_LIMIT_MAX_REQUESTS = 6
CREATIVE_RATE_LIMIT_WINDOW_SECONDS = 600


# Nutzerwunsch (2026-09-25, Backlog "zu oft keine Quellen"): die reine
# Vektorsuche gab bei "Was ist {Schlagwort}?" nur in 56 % der Fälle einen
# Ausschnitt weiter, der den Begriff überhaupt enthält (Messung über 82
# Schlagworte, tools/retrieval_eval.py) - u.a. Doppelmanagement, NUMMI,
# John Seddon, Intrinsify fielen durch. Hybrid-Suche: Begriffe aus der Frage
# (Anführungszeichen oder bekannte Schlagworte aus terms.json) bekommen
# garantiert einen Platz, sofern noch kein Ausschnitt sie enthält - jeweils
# der vektor-nächste Chunk, der den Begriff wörtlich enthält.
LEXICAL_MAX_TERMS = 3


# Idee 3c32da30: mehr verschiedene Quellen je Antwort. Die Seitenleiste zeigt
# je Quelle nur einen Eintrag; füllt eine Quelle viele der top_k Plätze,
# bleiben wenige eigenständige Quellen. Regel in _rerank_by_relevance: je
# Quelle höchstens N Plätze, der Überschuss weicht Chunks NEUER Quellen, die
# höchstens 25 % (Env SOURCE_DIVERSITY_MAX_DISTANCE_INCREASE) schlechter liegen
# (Score = quadrierte L2-Distanz). 15 % war zu eng (Idee 78404054).
SOURCE_DIVERSITY_DEFAULT_MAX_PER_SOURCE = 2
SOURCE_DIVERSITY_POOL_MULTIPLIER = 8
SOURCE_DIVERSITY_DEFAULT_DISTANCE_INCREASE = 0.25


def _parse_max_per_source(raw: str | None) -> int:
    """None (Variable fehlt) -> Standard; leer, 0, negativ, ungültig -> 0 (aus)."""
    if raw is None:
        return SOURCE_DIVERSITY_DEFAULT_MAX_PER_SOURCE
    raw = raw.strip()
    if not raw:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        logging.getLogger(__name__).warning(
            "SOURCE_DIVERSITY_MAX_PER_SOURCE=%r ungültig - Quellen-Vielfalt ausgeschaltet", raw
        )
        return 0


SOURCE_DIVERSITY_MAX_PER_SOURCE = _parse_max_per_source(os.environ.get("SOURCE_DIVERSITY_MAX_PER_SOURCE"))


def _parse_distance_increase(raw: str | None) -> float:
    """None -> Standard; Zahl >= 0 übernehmen (0 = keine Tausche); sonst Warnung + Standard."""
    if raw is None:
        return SOURCE_DIVERSITY_DEFAULT_DISTANCE_INCREASE
    try:
        value = float(raw)
        if value >= 0:  # NaN fällt durch
            return value
    except ValueError:
        pass
    logging.getLogger(__name__).warning(
        "SOURCE_DIVERSITY_MAX_DISTANCE_INCREASE=%r ungültig - Standard %s", raw, SOURCE_DIVERSITY_DEFAULT_DISTANCE_INCREASE
    )
    return SOURCE_DIVERSITY_DEFAULT_DISTANCE_INCREASE


SOURCE_DIVERSITY_MAX_DISTANCE_INCREASE = _parse_distance_increase(os.environ.get("SOURCE_DIVERSITY_MAX_DISTANCE_INCREASE"))


# Idee 313ad93d: ausgelagerte Namen, die Tests/Skripte/mcp_server weiter über main lesen oder patchen.
from app.source_processing import (  # noqa: E402,F401
    _generate_summary_background,
    _generate_summary_with_retries,
    _in_flight_jobs_drained,
    _load_sources,
    _process_audio_transcription,
    _process_pdf_ocr,
    _register_all_terms,
    _save_sources,
    _sources_write_lock,
    _track_background_job,
    _translate_summary_background,
    _wait_for_background_jobs_on_shutdown,
)
from app.background import (  # noqa: E402,F401
    AUDIO_TRANSCRIPTION_WORKER_COUNT,
    AUTHOR_PHOTO_CACHE_INTERVAL_SECONDS,
    QUESTION_LOG_PURGE_INTERVAL_SECONDS,
    SOURCE_SUGGESTION_INTERVAL_SECONDS,
    SUMMARY_BACKFILL_INTERVAL_SECONDS,
    URL_HEALTH_CHECK_INTERVAL_SECONDS,
    WEB_ALLOWLIST_CRAWL_INTERVAL_SECONDS,
    _audio_transcription_queue,
    _backfill_images,
    _backfill_missing_summaries_once,
    _backfill_source_language_once,
    _backfill_summaries_and_language_once,
    _backfill_term_languages_once,
    _cache_missing_author_photos_once,
    _index_web_allowlist_entry_with_status,
    _normalize_beta_kodex_spelling_once,
    _normalize_pflaeging_spelling_once,
    _purge_expired_question_log_entries_once,
    _recover_interrupted_processing_jobs,
    _recover_interrupted_web_allowlist_indexing,
    _reassign_chunk_images,
    _reindex_all_sources,
    _repair_char_split_key_terms_once,
    _review_source_images,
    _run_periodic,
    _run_source_suggestion_discovery_once,
    _run_url_health_check_once,
    _run_web_allowlist_crawl_once,
    _run_web_crawl_subprocess,
    _startup_reindex,
    _warm_up_local_models,
)
from app.routes_sources import (  # noqa: E402,F401
    _finish_synchronous_import,
)
from app.routes_admin import (  # noqa: E402,F401
    _send_invite,
)
from app.retrieval import (  # noqa: E402,F401
    LEXICAL_MIN_TERM_LEN,
    NO_ANSWER_EXPLANATIONS,
    NO_ANSWER_PHRASES,
    _apply_chunk_images,
    _best_local_sentence,
    _chunk_images,
    _compute_occurrence_highlights,
    _diversity_key,
    _ensure_term_hits,
    _find_quote_span,
    _keyword_exempt_source_ids,
    _limit_restricted_images,
    _question_terms,
    _redact_restricted_refs,
    _rerank_by_relevance,
    _source_matches_question_keywords,
    _trim_history,
)
from app.routes_ask import (  # noqa: E402,F401
    CONVERSATION_HANDOFF_MAX_BYTES,
    CONVERSATION_HANDOFF_MAX_TURNS,
    CONVERSATION_HANDOFF_RATE_LIMIT_MAX_REQUESTS,
    _ask_context,
    _ask_event_stream,
    _creative_context,
    _creative_event_stream,
)


from app import routes_account, routes_admin, routes_ask, routes_pflege, routes_sources  # noqa: E402

app.include_router(routes_sources.router)
app.include_router(routes_admin.router)
app.include_router(routes_pflege.router)
app.include_router(routes_ask.router)

# --- MCP-Zugang zum Kreativ-Modus (2026-09-24, app/mcp_server.py) ---
# Eigene Route statt app.mount: ein Mount auf /mcp würde /mcp (ohne
# Schrägstrich) nur per Redirect erreichen. Muss VOR dem StaticFiles-Mount
# auf "/" stehen.
app.router.routes.append(Route(mcp_server.MCP_PATH, endpoint=mcp_server.asgi_app))

app.include_router(routes_account.router)



class NoCacheStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


# Backlog #58: die branded 404.html (siehe unten, StaticFiles html=True liefert
# sie automatisch für jeden nicht gefundenen Pfad) soll NUR für echte
# Browser-Navigation greifen, nicht für einen falsch getippten/nicht (mehr)
# existierenden /api/-Pfad - der muss weiterhin JSON liefern, weil das
# Frontend überall err.detail aus der Antwort liest. Ohne dieses Catch-all
# würde ein unbekannter /api/-Pfad sonst ebenfalls bei der StaticFiles-
# Route landen und fälschlich HTML statt JSON bekommen.
@app.api_route("/api/{full_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"], include_in_schema=False)
async def api_not_found(full_path: str):
    raise HTTPException(404, "Not Found")


app.mount("/", NoCacheStaticFiles(directory=str(STATIC_DIR), html=True), name="static")
