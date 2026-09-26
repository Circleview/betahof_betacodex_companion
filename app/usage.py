"""Verbrauchsprotokoll für den Kreativ-Modus (Nutzerwunsch 2026-09-24):
jeder Aufruf - aus der Oberfläche ("ui") wie über MCP ("mcp", app/mcp_keys.py)
- landet mit Tokens, Websuchen und Kosten in data/usage_log.json.

Kosten werden beim Aufruf fest berechnet und mitgespeichert (USD wie von der
Claude-API abgerechnet, EUR zum tagesaktuellen EZB-Kurs samt Kurs, Kursdatum
und Quelle) - eine spätere Preis- oder Kursänderung verfälscht alte Einträge
also nicht. Die Einträge pro Schlüssel
sind bewusst so aufgebaut, dass ein späteres Bezahlmodell (Monats-Kontingent,
Guthaben, nutzungsbasiert) ohne Umbau darauf aufsetzen kann (siehe CSV-Export).

Aufbewahrung: Einträge älter als RETENTION_DAYS fallen beim nächsten
Schreiben weg (gleiche Frist wie das Fragen-Log, app/question_log.py)."""
import csv
import io
import json
import logging
import threading
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import jsonstore

BASE_DIR = Path(__file__).resolve().parent.parent
USAGE_FILE = BASE_DIR / "data" / "usage_log.json"
RETENTION_DAYS = 730

# USD je 1 Mio. Tokens (Eingabe, Ausgabe) - Anthropic-Listenpreise, Stand
# 2026-09. Bei neuen Modellen/Preisen hier nachziehen.
PRICES_USD_PER_MTOK = {
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5-20251001": (1.00, 5.00),
}
CACHE_WRITE_FACTOR = 1.25  # 5-Minuten-Cache
CACHE_READ_FACTOR = 0.10
WEB_SEARCH_USD = 0.01  # 10 USD je 1.000 Suchen

# Nutzerwunsch (2026-09-26): Kostenübersicht über ALLE kostenpflichtigen
# Dienste, nicht nur den Kreativ-Modus. Nicht-Anthropic-Dienste rechnen je
# Einheit ab - Listenpreise Stand 2026-09, ohne Freikontingente.
SERVICE_PRICES_USD = {
    # Google Cloud Text-to-Speech, Chirp 3 HD: 30 USD je 1 Mio. Zeichen
    "google-tts-chirp3-hd": (30.0 / 1_000_000, "chars"),
    # OpenAI-Transkription: 0,006 USD je Minute
    "whisper-1": (0.006 / 60, "seconds"),
    "gpt-4o-transcribe-diarize": (0.006 / 60, "seconds"),
}

# Umrechnung USD -> EUR (Nutzerwunsch 2026-09-24): tagesaktueller EZB-
# Referenzkurs über den kostenlosen, schlüssellosen Dienst Frankfurter
# (frankfurter.dev). Höchstens ein Abruf pro Tag, zwischengespeichert in
# FX_FILE; fällt der Dienst aus, gilt der zuletzt bekannte Kurs, und erst
# eine Stunde später wird es erneut versucht. Nur wenn noch NIE ein Kurs
# abgerufen werden konnte, greift FALLBACK_USD_TO_EUR (Quelle "fallback").
# Jeder Protokolleintrag speichert den verwendeten Kurs mit Datum und Quelle.
FX_FILE = BASE_DIR / "data" / "fx_rate.json"
FX_URL = "https://api.frankfurter.dev/v1/latest?base=USD&symbols=EUR"
FX_TIMEOUT_SECONDS = 3
FX_RETRY_AFTER = timedelta(hours=1)
FALLBACK_USD_TO_EUR = 0.86

_lock = threading.Lock()
_fx_lock = threading.Lock()


def _fetch_ecb_rate() -> tuple[float, str]:
    # Eigener User-Agent: Frankfurter (hinter Cloudflare) lehnt den
    # Standard-Agent "Python-urllib" mit 403 ab.
    req = urllib.request.Request(FX_URL, headers={"User-Agent": "BetaCodex-Chat/1.0 (+https://chat.betacodex.org)"})
    with urllib.request.urlopen(req, timeout=FX_TIMEOUT_SECONDS) as resp:
        data = json.load(resp)
    return float(data["rates"]["EUR"]), data["date"]


def current_fx() -> dict:
    """{"rate", "date", "source"} - source "ecb" (Frankfurter) oder
    "fallback"."""
    now = datetime.now(timezone.utc)
    with _fx_lock:
        cache = jsonstore.load(FX_FILE, {})
        fresh = cache.get("fetched_at", "")[:10] == now.date().isoformat()
        last_attempt = cache.get("last_attempt_at")
        may_retry = not last_attempt or now - datetime.fromisoformat(last_attempt) >= FX_RETRY_AFTER
        if not fresh and may_retry:
            cache["last_attempt_at"] = now.isoformat()
            try:
                rate, date = _fetch_ecb_rate()
                cache.update({"rate": rate, "date": date, "source": "ecb", "fetched_at": now.isoformat()})
            except Exception:
                pass  # zuletzt bekannter Kurs bzw. Notwert
            jsonstore.save(FX_FILE, cache)
    if "rate" in cache:
        return {"rate": cache["rate"], "date": cache["date"], "source": cache["source"]}
    return {"rate": FALLBACK_USD_TO_EUR, "date": None, "source": "fallback"}


def cost_usd(usage: dict) -> float:
    price_in, price_out = PRICES_USD_PER_MTOK[usage["model"]]
    tokens_cost = (
        usage["input_tokens"] * price_in
        + usage["cache_creation_input_tokens"] * price_in * CACHE_WRITE_FACTOR
        + usage["cache_read_input_tokens"] * price_in * CACHE_READ_FACTOR
        + usage["output_tokens"] * price_out
    ) / 1_000_000
    return tokens_cost + usage["web_search_requests"] * WEB_SEARCH_USD


def anthropic_usage(model: str, usage) -> dict:
    """Verbrauch eines Claude-Aufrufs (message.usage) als Protokoll-Dict."""
    server_tool_use = getattr(usage, "server_tool_use", None)
    return {
        "model": model,
        "input_tokens": int(usage.input_tokens or 0),
        "output_tokens": int(usage.output_tokens or 0),
        "cache_creation_input_tokens": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
        "cache_read_input_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "web_search_requests": int(getattr(server_tool_use, "web_search_requests", 0) or 0) if server_tool_use else 0,
    }


def track_anthropic(
    model: str, usage, channel: str, email: str | None = None, key_id: str | None = None
) -> None:
    """Kostenmessung für einen Claude-Aufruf - darf die eigentliche Funktion
    nie unterbrechen (Fehler landen nur im Server-Log). email: angemeldetes
    Konto, das den Aufruf ausgelöst hat (None = anonym bzw. System)."""
    try:
        record(anthropic_usage(model, usage), channel=channel, web_search=False, email=email, key_id=key_id)
    except Exception:
        logging.getLogger(__name__).exception("Kostenmessung (%s) fehlgeschlagen", channel)


def track_anthropic_stream(
    model: str, stream, channel: str, email: str | None = None, key_id: str | None = None
) -> None:
    """Wie track_anthropic, aber für einen fertig gelesenen Stream."""
    try:
        final_usage = stream.get_final_message().usage
    except Exception:
        logging.getLogger(__name__).exception("Kostenmessung (%s) fehlgeschlagen", channel)
        return
    track_anthropic(model, final_usage, channel, email, key_id)


def track_service(channel: str, model: str, quantity: float, email: str | None = None) -> None:
    """Kostenmessung für Nicht-Anthropic-Dienste (TTS, Transkription) - Menge
    in der Einheit aus SERVICE_PRICES_USD. Unterbricht nie die Funktion."""
    try:
        price, unit = SERVICE_PRICES_USD[model]
        entry = {
            "model": model,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "web_search_requests": 0,
            "quantity": round(quantity, 2),
            "unit": unit,
        }
        record(entry, channel=channel, web_search=False, email=email, usd=quantity * price)
    except Exception:
        logging.getLogger(__name__).exception("Kostenmessung (%s) fehlgeschlagen", channel)


def record(
    usage: dict,
    channel: str,
    web_search: bool,
    key_id: str | None = None,
    email: str | None = None,
    usd: float | None = None,
) -> dict:
    usd = cost_usd(usage) if usd is None else usd
    fx = current_fx()
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "key_id": key_id,
        "email": email,
        "web_search_enabled": web_search,
        **usage,
        "cost_usd": round(usd, 6),
        "cost_eur": round(usd * fx["rate"], 6),
        "usd_to_eur": fx["rate"],
        "fx_date": fx["date"],
        "fx_source": fx["source"],
    }
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    with _lock:
        entries = [e for e in jsonstore.load(USAGE_FILE, []) if e["ts"] >= cutoff]
        entries.append(entry)
        jsonstore.save(USAGE_FILE, entries)
    return entry


def list_entries() -> list[dict]:
    return jsonstore.load(USAGE_FILE, [])


def key_stats(key_id: str, now: datetime | None = None, month: str | None = None) -> dict:
    """Aufrufe heute (UTC) und Kosten im laufenden - oder, für die
    Admin-Übersicht, im angegebenen ("YYYY-MM") - Monat. Die Limits in
    app/mcp_keys.py nutzen immer den laufenden Monat."""
    now = now or datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month = month or now.strftime("%Y-%m")
    calls_today = 0
    month_eur = 0.0
    month_usd = 0.0
    for e in list_entries():
        if e["key_id"] != key_id:
            continue
        if e["ts"] >= day_start:
            calls_today += 1
        if e["ts"].startswith(month):
            month_eur += e["cost_eur"]
            month_usd += e["cost_usd"]
    return {"calls_today": calls_today, "month_eur": round(month_eur, 4), "month_usd": round(month_usd, 4)}


# Hintergrund-/Pflegearbeiten ohne auslösende Person - in der Übersicht
# "System", alles andere ohne Konto "anonym" (Nutzerwunsch 2026-09-26).
SYSTEM_CHANNELS = ("summary", "ocr", "discovery", "stt")


def account_of(entry: dict) -> str:
    if entry.get("email"):
        return entry["email"]
    return "system" if entry["channel"] in SYSTEM_CHANNELS else "anonymous"


def monthly_summary(month: str, email: str | None = None) -> dict:
    """month = "YYYY-MM". Summen je Kanal, je Konto und je Schlüssel - mit
    email nur die Einträge dieses Kontos ("Meine Kosten")."""
    def empty():
        return {"calls": 0, "cost_usd": 0.0, "cost_eur": 0.0, "web_search_requests": 0}

    def add(bucket, e):
        bucket["calls"] += 1
        bucket["cost_usd"] += e["cost_usd"]
        bucket["cost_eur"] += e["cost_eur"]
        bucket["web_search_requests"] += e["web_search_requests"]

    summary = {"month": month, "total": empty(), "by_channel": {}, "by_email": {}, "by_key": {}, "fx": None}
    for e in list_entries():
        if not e["ts"].startswith(month) or (email and e.get("email") != email):
            continue
        # Kurs des jüngsten Eintrags im Monat (Einträge sind chronologisch).
        summary["fx"] = {"rate": e["usd_to_eur"], "date": e["fx_date"], "source": e["fx_source"]}
        add(summary["total"], e)
        add(summary["by_channel"].setdefault(e["channel"], empty()), e)
        add(summary["by_email"].setdefault(account_of(e), empty()), e)
        if e["key_id"]:
            add(summary["by_key"].setdefault(e["key_id"], empty()), e)
    # Ohne Aufrufe im Monat: aktueller Tageskurs, damit die Übersicht den
    # Kurs immer zeigt (Nutzerwunsch 2026-09-24).
    if summary["fx"] is None:
        summary["fx"] = current_fx()
    return summary


def last_months(count: int, now: datetime | None = None) -> list[str]:
    """Die letzten count Monate ("YYYY-MM"), ältester zuerst, bis inkl. heute."""
    now = now or datetime.now(timezone.utc)
    year, month = now.year, now.month
    months = []
    for _ in range(count):
        months.append(f"{year:04d}-{month:02d}")
        year, month = (year, month - 1) if month > 1 else (year - 1, 12)
    return months[::-1]


def monthly_history(months: list[str], email: str | None = None) -> list[dict]:
    """Nutzerwunsch (2026-09-26): Monatsverlauf als Balkengrafik - Summen je
    Monat (auch leere Monate), dazu je Monat die Kosten nach Kanal für den
    Tooltip. Mit email nur die Einträge dieses Kontos."""
    history = {m: {"month": m, "calls": 0, "cost_usd": 0.0, "cost_eur": 0.0, "by_channel": {}} for m in months}
    for e in list_entries():
        bucket = history.get(e["ts"][:7])
        if bucket is None or (email and e.get("email") != email):
            continue
        bucket["calls"] += 1
        bucket["cost_usd"] += e["cost_usd"]
        bucket["cost_eur"] += e["cost_eur"]
        bucket["by_channel"][e["channel"]] = bucket["by_channel"].get(e["channel"], 0.0) + e["cost_eur"]
    return [history[m] for m in months]


CSV_FIELDS = [
    "ts", "channel", "email", "key_id", "model", "web_search_enabled", "input_tokens", "output_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens", "web_search_requests", "quantity", "unit",
    "cost_usd", "cost_eur",
    "usd_to_eur", "fx_date", "fx_source",
]


def export_csv(month: str, email: str | None = None) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for e in list_entries():
        if e["ts"].startswith(month) and (not email or e.get("email") == email):
            writer.writerow(e)
    return buf.getvalue()
