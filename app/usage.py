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


def record(usage: dict, channel: str, web_search: bool, key_id: str | None = None, email: str | None = None) -> dict:
    usd = cost_usd(usage)
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


def monthly_summary(month: str) -> dict:
    """month = "YYYY-MM". Summen je Kanal, je Konto und je Schlüssel."""
    def empty():
        return {"calls": 0, "cost_usd": 0.0, "cost_eur": 0.0, "web_search_requests": 0}

    def add(bucket, e):
        bucket["calls"] += 1
        bucket["cost_usd"] += e["cost_usd"]
        bucket["cost_eur"] += e["cost_eur"]
        bucket["web_search_requests"] += e["web_search_requests"]

    summary = {"month": month, "total": empty(), "by_channel": {}, "by_email": {}, "by_key": {}, "fx": None}
    for e in list_entries():
        if not e["ts"].startswith(month):
            continue
        # Kurs des jüngsten Eintrags im Monat (Einträge sind chronologisch).
        summary["fx"] = {"rate": e["usd_to_eur"], "date": e["fx_date"], "source": e["fx_source"]}
        add(summary["total"], e)
        add(summary["by_channel"].setdefault(e["channel"], empty()), e)
        if e["email"]:
            add(summary["by_email"].setdefault(e["email"], empty()), e)
        if e["key_id"]:
            add(summary["by_key"].setdefault(e["key_id"], empty()), e)
    return summary


CSV_FIELDS = [
    "ts", "channel", "email", "key_id", "model", "web_search_enabled", "input_tokens", "output_tokens",
    "cache_creation_input_tokens", "cache_read_input_tokens", "web_search_requests", "cost_usd", "cost_eur",
    "usd_to_eur", "fx_date", "fx_source",
]


def export_csv(month: str) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for e in list_entries():
        if e["ts"].startswith(month):
            writer.writerow(e)
    return buf.getvalue()
