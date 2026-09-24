"""Verbrauchsprotokoll für den Kreativ-Modus (Nutzerwunsch 2026-09-24):
jeder Aufruf - aus der Oberfläche ("ui") wie über MCP ("mcp", app/mcp_keys.py)
- landet mit Tokens, Websuchen und Kosten in data/usage_log.json.

Kosten werden beim Aufruf fest berechnet und mitgespeichert (USD wie von der
Claude-API abgerechnet, EUR zum festen Kurs unten) - eine spätere Preis- oder
Kursänderung verfälscht alte Einträge also nicht. Die Einträge pro Schlüssel
sind bewusst so aufgebaut, dass ein späteres Bezahlmodell (Monats-Kontingent,
Guthaben, nutzungsbasiert) ohne Umbau darauf aufsetzen kann (siehe CSV-Export).

Aufbewahrung: Einträge älter als RETENTION_DAYS fallen beim nächsten
Schreiben weg (gleiche Frist wie das Fragen-Log, app/question_log.py)."""
import csv
import io
import threading
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
# ponytail: fester Umrechnungskurs statt Tageskurs-Abruf - reicht für
# Kostenkontrolle und Kontingente; bei deutlicher Kursbewegung hier anpassen.
USD_TO_EUR = 0.86

_lock = threading.Lock()


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
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "channel": channel,
        "key_id": key_id,
        "email": email,
        "web_search_enabled": web_search,
        **usage,
        "cost_usd": round(usd, 6),
        "cost_eur": round(usd * USD_TO_EUR, 6),
    }
    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
    with _lock:
        entries = [e for e in jsonstore.load(USAGE_FILE, []) if e["ts"] >= cutoff]
        entries.append(entry)
        jsonstore.save(USAGE_FILE, entries)
    return entry


def list_entries() -> list[dict]:
    return jsonstore.load(USAGE_FILE, [])


def _month_start(now: datetime) -> str:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def key_stats(key_id: str, now: datetime | None = None) -> dict:
    """Aufrufe heute (UTC) und Kosten im laufenden Monat - Grundlage der
    Limits in app/mcp_keys.py."""
    now = now or datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month_start = _month_start(now)
    calls_today = 0
    month_eur = 0.0
    month_usd = 0.0
    for e in list_entries():
        if e["key_id"] != key_id:
            continue
        if e["ts"] >= day_start:
            calls_today += 1
        if e["ts"] >= month_start:
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

    summary = {"month": month, "total": empty(), "by_channel": {}, "by_email": {}, "by_key": {}}
    for e in list_entries():
        if not e["ts"].startswith(month):
            continue
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
]


def export_csv(month: str) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for e in list_entries():
        if e["ts"].startswith(month):
            writer.writerow(e)
    return buf.getvalue()
