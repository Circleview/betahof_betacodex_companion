"""Exportiert die Quellenliste der Produktion als Markdown (DE + EN) und JSON.

Läuft wöchentlich per GitHub Actions (.github/workflows/export-sources.yml).
Liest nur die öffentliche API und übernimmt ausschließlich die Felder aus
FIELDS - Volltexte landen nie in der Ausgabe, auch falls die API einmal
welche liefern sollte.

Lizenz der Ausgabe: CC BY-NC-SA 4.0, siehe docs/sources/LICENSE.md.

Aufruf: python scripts/export_sources.py [API-Basis-URL]
"""

import json
import sys
import unicodedata
import urllib.request
from pathlib import Path

API = "https://chat.betacodex.org"
OUT_DIR = Path(__file__).resolve().parent.parent / "docs" / "sources"
FIELDS = ("id", "title", "authors", "date", "url", "summary", "summary_ai_generated", "key_terms")
LICENSE = "CC BY-NC-SA 4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/"
ATTRIBUTION = "BetaCodex Chat (https://chat.betacodex.org)"

LANGS = {
    "de": {
        "file": "QUELLEN.md",
        "other": ("SOURCES.md", "English version"),
        "heading": "Quellen des BetaCodex Chat",
        "intro": "Alle kuratierten Quellen, sortiert nach Nachname der (ersten) Autor:in. "
        "Volltexte werden hier bewusst nicht veröffentlicht.",
        "license": f"Lizenz: [{LICENSE}]({LICENSE_URL}), Namensnennung „{ATTRIBUTION}“ – "
        "siehe [LICENSE.md](LICENSE.md). Maschinenlesbar: [sources.json](sources.json).",
        "count": "Anzahl Quellen",
        "date": "Datum",
        "link": "Link",
        "ai": "Zusammenfassung (KI-generiert)",
        "manual": "Zusammenfassung (von Hand verfasst)",
        "no_summary": "Keine Zusammenfassung vorhanden.",
        "unknown_author": "Unbekannt",
    },
    "en": {
        "file": "SOURCES.md",
        "other": ("QUELLEN.md", "Deutsche Fassung"),
        "heading": "BetaCodex Chat sources",
        "intro": "All curated sources, sorted by the (first) author's last name. "
        "Full texts are deliberately not published here.",
        "license": f"License: [{LICENSE}]({LICENSE_URL}), attribution “{ATTRIBUTION}” – "
        "see [LICENSE.md](LICENSE.md). Machine-readable: [sources.json](sources.json).",
        "count": "Number of sources",
        "date": "Date",
        "link": "Link",
        "ai": "Summary (AI-generated)",
        "manual": "Summary (written by hand)",
        "no_summary": "No summary available.",
        "unknown_author": "Unknown",
    },
}


def fetch(api: str, lang: str) -> list[dict]:
    req = urllib.request.Request(
        f"{api}/api/sources?include_text=false",
        headers={"X-Lang": lang, "User-Agent": "betacodex-sources-export"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    # Nur fertig verarbeitete Quellen; Papierkorb liefert die API gar nicht erst.
    return [{k: s.get(k) for k in FIELDS} for s in data if not s.get("processing_status")]


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().casefold()


def sort_key(source: dict) -> tuple:
    # Nachname = letztes Namenswort ("Jos de Blok" -> Blok); Organisationen
    # wie "Wikipedia" bestehen nur aus einem Wort und sortieren danach.
    first = (source["authors"] or [""])[0]
    return (_fold(first.split()[-1]) if first.strip() else "~", _fold(first), _fold(source["title"] or ""))


def format_author(name: str) -> str:
    parts = name.split()
    return name if len(parts) < 2 else f"{parts[-1]}, {' '.join(parts[:-1])}"


def render(sources: list[dict], lang: str) -> str:
    t = LANGS[lang]
    sources = sorted(sources, key=sort_key)
    lines = [
        f"# {t['heading']}",
        "",
        f"[{t['other'][1]}]({t['other'][0]})",
        "",
        t["intro"],
        "",
        t["license"],
        "",
        f"{t['count']}: {len(sources)}",
        "",
    ]
    for s in sources:
        authors = s["authors"] or []
        who = "; ".join([format_author(authors[0]), *authors[1:]]) if authors else t["unknown_author"]
        lines += [f"### {who} – {s['title']}", ""]
        meta = [f"{t['date']}: {s['date'] or '–'}"]
        if s["url"]:
            meta.append(f"{t['link']}: <{s['url']}>")
        lines += [" · ".join(meta), ""]
        summary = (s["summary"] or "").strip()
        if summary:
            lines += [f"**{t['ai'] if s['summary_ai_generated'] else t['manual']}:**", ""]
            lines += [f"> {line}".rstrip() for line in summary.splitlines()]
        else:
            lines.append(f"_{t['no_summary']}_")
        lines.append("")
    return "\n".join(lines)


def render_json(by_lang: dict[str, list[dict]]) -> str:
    # Ein Eintrag je Quelle, Zusammenfassung/Schlagworte je Sprache; Sortierung
    # wie in den Markdown-Listen.
    en = {s["id"]: s for s in by_lang["en"]}
    sources = [
        {
            "id": s["id"],
            "title": s["title"],
            "authors": s["authors"] or [],
            "date": s["date"],
            "url": s["url"],
            "summary": {"de": s["summary"] or "", "en": en.get(s["id"], {}).get("summary") or ""},
            "summary_ai_generated": {
                "de": s["summary_ai_generated"],
                "en": en.get(s["id"], {}).get("summary_ai_generated", True),
            },
            "key_terms": {"de": s["key_terms"] or [], "en": en.get(s["id"], {}).get("key_terms") or []},
        }
        for s in sorted(by_lang["de"], key=sort_key)
    ]
    data = {
        "schema_version": 1,
        "license": LICENSE,
        "license_url": LICENSE_URL,
        "attribution": ATTRIBUTION,
        "sources": sources,
    }
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def main(api: str = API) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    by_lang = {lang: fetch(api, lang) for lang in LANGS}
    # Schutz gegen eine kaputte/leere API-Antwort: nicht die Liste leeren.
    json_path = OUT_DIR / "sources.json"
    previous = len(json.loads(json_path.read_text())["sources"]) if json_path.exists() else 0
    for lang, sources in by_lang.items():
        if len(sources) < previous // 2:
            sys.exit(f"{lang}: nur {len(sources)} statt bisher {previous} Quellen - Abbruch")
    for lang, t in LANGS.items():
        (OUT_DIR / t["file"]).write_text(render(by_lang[lang], lang))
    json_path.write_text(render_json(by_lang))
    print(f"{len(by_lang['de'])} Quellen exportiert")


if __name__ == "__main__":
    main(*sys.argv[1:])
