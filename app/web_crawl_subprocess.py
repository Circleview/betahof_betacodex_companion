"""Nutzerwunsch (nach real reproduziertem Fund): app/web_crawler.py:
index_entry() kann für einzelne Websites in einem Python-Thread unbegrenzt
hängen bleiben, selbst mit Timeout-Schutz per ThreadPoolExecutor (nachge-
stellt für sichtart.at: derselbe trafilatura.sitemaps.sitemap_search()-Auf-
ruf kehrt im Hauptthread eines Prozesses sofort zurück, hängt aber in einem
simplen threading.Thread unbegrenzt - vermutlich eine Threading-Eigenheit
der zugrunde liegenden Netzwerk-Bibliotheken bei bestimmten Websites). Ein
Timeout INNERHALB desselben Prozesses verschiebt das Problem nur eine Ebene
tiefer. Ein eigener Betriebssystem-Prozess hat dagegen immer einen echten
Hauptthread UND lässt sich (anders als ein hängender Thread) vom Eltern-
prozess zuverlässig per subprocess.run(timeout=...) abbrechen - siehe
app/main.py:_run_web_crawl_subprocess/_index_web_allowlist_entry_with_status,
die dort auch den indexing_status setzen (nicht hier, damit ein Timeout im
Elternprozess ebenfalls korrekt zu "error" führt, statt dass dieser Prozess
beim gewaltsamen Beenden keine Zeit mehr dafür hätte).

Bewusst ein MINIMALES, eigenständiges Skript statt z.B. `python -m
app.main` im Kindprozess: ein Import von app.main würde im Kindprozess
sämtliche dortigen Modul-Ebene-Hintergrund-Threads (wöchentlicher Sweep,
Audio-Warteschlange, Wiederherstellung unterbrochener Jobs, ...) ein
zweites Mal starten - unnötig und riskant (doppelte Verarbeitung).

Aufruf: python -m app.web_crawl_subprocess <entry_id> <url_prefix> <max_pages>
Exit-Code 0 bei Erfolg, 1 bei einer unerwarteten Ausnahme."""
import sys

from app import web_crawler


def main(argv: list[str]) -> int:
    entry_id, url_prefix, max_pages_str = argv[0], argv[1], argv[2]
    try:
        web_crawler.index_entry(entry_id, url_prefix, int(max_pages_str))
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
