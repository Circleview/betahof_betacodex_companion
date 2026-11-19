# Idee 313ad93d: aus app/main.py ausgelagert (Verhalten unverändert).

import itertools
import json
import logging
import queue
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from app import (
    author_photos,
    author_profiles,
    authors,
    chunking,
    embeddings,
    extraction,
    i18n,
    image_review,
    monitoring,
    question_log,
    source_discovery,
    source_images,
    source_suggestions,
    terms,
    vectorstore,
    web_allowlist,
)

from app import main
from app.source_processing import (
    _detect_and_store_language,
    _existing_audio_file,
    _existing_pdf_file,
    _generate_summary_background,
    _save_sources,
    _source_in_from_entry,
    _sources_write_lock,
    _store_chunks,
    _store_pdf_images,
    _track_background_job,
    _vectorstore_write_lock,
)

# Backlog #113: Audio-Transkriptionen liefen bisher völlig unbegrenzt
# parallel (jeder add_source-Request startete sofort seinen eigenen
# Hintergrund-Job) - beim gleichzeitigen Import vieler Audios (23 auf
# einmal, realer Vorfall 2026-07-28) sendet das entsprechend viele
# gleichzeitige, kostenpflichtige OpenAI-Aufrufe los und kann das Budget
# aufbrauchen, bevor auch nur eine einzige Datei fertig transkribiert ist.
#
# Nachtrag: statt eines einzelnen Workers (strikt sequenziell) verarbeitet
# eine kleine FESTE Anzahl an Workern dieselbe Warteschlange - Transkription
# wird pro Audio-Minute abgerechnet, nicht pro gleichzeitiger Anfrage, die
# GESAMTKOSTEN ändern sich durch Parallelität also nicht, nur die
# Wanduhrzeit sinkt etwa um den Faktor AUDIO_TRANSCRIPTION_WORKER_COUNT.
# Eine feste, kleine Zahl (statt wieder unbegrenzt) hält das ursprüngliche
# Risiko (Budget-/Rate-Limit-Burst) weiterhin klein. Eine noch nicht dran
# gekommene Quelle bleibt einfach auf ihrem bereits bestehenden "pending"-
# Status (siehe _create_pending_source), bis einer der Worker sie
# tatsächlich aufgreift und auf "running" setzt. PDF-Texterkennung ist
# bewusst NICHT betroffen (nicht Teil des gemeldeten Vorfalls, weiterhin
# über background_tasks wie zuvor).
AUDIO_TRANSCRIPTION_WORKER_COUNT = 3
_audio_transcription_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()


def _audio_transcription_worker() -> None:
    while True:
        source_id, lang = _audio_transcription_queue.get()
        try:
            with _track_background_job(source_id):
                main._process_audio_transcription(source_id, lang)
        except Exception:
            # Ein unerwarteter Fehler hier darf den Worker nicht beenden -
            # sonst bliebe die gesamte restliche Warteschlange für den Rest
            # der Prozess-Laufzeit stehen. _run_deferred_text_extraction
            # fängt reguläre Fehler (z.B. OpenAI-Kontingent) bereits selbst
            # ab und setzt "error" - dies ist nur das allerletzte Netz.
            pass
        finally:
            _audio_transcription_queue.task_done()


# Fix (2026-08-23): bewusst NICHT in _start_background_workers() (siehe dort/
# lifespan oben) - anders als die übrigen Worker tickt dieser Pool nicht
# sofort gegen echte Daten, sondern blockiert rein reaktiv auf .get(), bis
# irgendwo add_source() etwas einreiht (immer erst NACH einem echten Request,
# also nie beim bloßen Modul-Import). Ohne laufende Worker bliebe außerdem
# jeder Test, der wie _create_deferred_audio_source() auf
# _audio_transcription_queue.join() wartet, für immer hängen - der Pool darf
# also unabhängig vom echten Server-Start immer laufen.
for _ in range(AUDIO_TRANSCRIPTION_WORKER_COUNT):
    threading.Thread(target=_audio_transcription_worker, daemon=True).start()


# Backlog (2026-08-02): Nutzerwunsch nach regelmäßiger statt nur
# bedarfsweiser Link-Prüfung (vorher: app/monitoring.check_url nur live
# beim Öffnen der Quellenübersicht, siehe Git-Historie). Läuft in JEDEM
# Prozess (auch bei Blue/Green also potenziell doppelt) - bewusst in Kauf
# genommen, da die Prüfung selbst harmlos ist (nur HTTP HEAD/GET) und eine
# Koordination zwischen den beiden Slots unnötige Komplexität wäre.
URL_HEALTH_CHECK_INTERVAL_SECONDS = 7 * 24 * 3600

# Backlog (2026-08-02, Nutzerwunsch): Ergebnisse nicht erst nach dem
# kompletten Durchlauf speichern, sondern alle 10 geprüften Quellen -
# das Quellenverzeichnis soll noch deutlich wachsen, ein Lauf mit vielen
# Quellen dauert dann entsprechend länger (sequenziell, bis zu
# monitoring.TIMEOUT_SECONDS pro Quelle). Bricht der Prozess mittendrin ab
# (Neustart, Deploy, Absturz), geht so höchstens der Fortschritt der
# aktuellen Zehnergruppe verloren statt des gesamten bisherigen Laufs.
URL_HEALTH_CHECK_BATCH_SIZE = 10


def _persist_url_health_results(results: dict) -> None:
    checked_at = datetime.now(timezone.utc).isoformat()
    with _sources_write_lock:
        # Frisch neu laden statt einer zuvor gelesenen Kopie - eine Quelle
        # könnte während der (potenziell mehrere Sekunden dauernden) Checks
        # bearbeitet oder gelöscht worden sein.
        sources = main._load_sources()
        for source_id, result in results.items():
            entry = sources.get(source_id)
            if not entry or entry.get("deleted_at"):
                continue
            entry["url_reachable"] = result["reachable"]
            entry["url_reason_code"] = result.get("reason_code")
            entry["url_status_code"] = result.get("status_code")
            entry["url_checked_at"] = checked_at
        _save_sources(sources)


def _run_url_health_check_once() -> None:
    with _sources_write_lock:
        sources = main._load_sources()
    to_check = {
        source_id: entry["url"]
        for source_id, entry in sources.items()
        if entry.get("url") and not entry.get("deleted_at")
    }
    # Die eigentlichen Netzwerk-Checks laufen BEWUSST außerhalb des Locks -
    # sonst würde ein einzelner Lauf mit vielen/langsamen Quellen (bis zu
    # monitoring.TIMEOUT_SECONDS pro Quelle) jeden anderen gleichzeitigen
    # Schreibzugriff auf sources.json für die gesamte Laufzeit blockieren.
    pending_results: dict = {}
    for source_id, url in to_check.items():
        pending_results[source_id] = monitoring.check_url(url)
        if len(pending_results) >= URL_HEALTH_CHECK_BATCH_SIZE:
            _persist_url_health_results(pending_results)
            pending_results = {}
    if pending_results:
        _persist_url_health_results(pending_results)


def _run_periodic(run_once_fn, interval_seconds: float) -> None:
    """Generische Sleep-Loop für die INTERVALL-basierten Hintergrund-Worker
    unten: läuft sofort einmal beim Prozessstart, danach im festen Takt. Ein
    Fehlschlag im aktuellen Durchlauf (z.B. defektes sources.json) beendet
    den Worker nicht dauerhaft, sondern wird erst beim nächsten Takt erneut
    versucht."""
    while True:
        try:
            run_once_fn()
        except Exception:
            pass
        time.sleep(interval_seconds)


# Nutzerwunsch (2026-08-22): die Quellenlage soll nicht nur wachsen, wenn
# jemand von Hand eine URL einreicht - der Companion soll selbst im
# offenen Web nach passenden neuen Text-Quellen suchen (app/
# source_discovery.py, Claudes Web-Search-Tool) und sie als kleine
# Vorschlagsliste ablegen (app/source_suggestions.py). Läuft nach demselben
# Sleep-Loop-Muster wie der URL-Gesundheits-Check oben.
# Nutzerwunsch (2026-08-23): die Liste im Frontend soll IMMER 5 sichtbare
# Vorschläge zeigen und beim Annehmen/Ablehnen sofort (ohne auf eine neue,
# mehrere Sekunden dauernde Websuche zu warten) aus bereits vorhandenem
# Vorrat nachrücken - SOURCE_SUGGESTION_QUEUE_TARGET ist deshalb bewusst
# GRÖSSER als die im Frontend sichtbaren 5 (siehe
# SOURCE_SUGGESTIONS_VISIBLE_COUNT in import.js), damit dieser Vorrat
# überhaupt existiert. Der tägliche Lauf hier befüllt nur diesen
# Hintergrund-Vorrat, das Nachrücken selbst ist reine Frontend-Logik ohne
# weiteren Backend-Aufruf.
# Nutzerwunsch (Nachtrag): Vorrat auf 100 erhöht und Takt von wöchentlich
# auf täglich verkürzt, damit er "sich immer wieder füllt, solange das Web
# noch gute Vorschläge bereithält" - kostet trotzdem nichts Zusätzliches an
# den meisten Tagen, da _run_source_suggestion_discovery_once() sofort ohne
# jede Websuche abbricht, sobald der Vorrat das Ziel schon erreicht hat
# (nur die Prüfung selbst läuft täglich, echte - kostenpflichtige -
# Websuchen nur bei tatsächlichem Bedarf). Die bereits bestehende
# Autor:innen-Durchmischung (pick_next_authors/zip_longest weiter unten,
# siehe deren eigene Kommentare) verhindert dabei weiterhin, dass ein
# einzelner vielschreibender Autor den Vorrat dominiert.
SOURCE_SUGGESTION_INTERVAL_SECONDS = 24 * 3600
# Wie viele bekannte Autor:innen pro Lauf zusätzlich zur themenbasierten
# Suche befragt werden.
# Nutzerfeedback (2026-08-23): mit ursprünglich 2 wuchs der Vorrat viel
# langsamer, als er sich durch Annehmen/Ablehnen leeren lässt - ein
# einzelner Pfleger konnte den gesamten Tagesertrag (2 Autor:innen + 1
# Themensuche, je bis zu 5 Treffer) in wenigen Minuten aufbrauchen und
# stand dann bis zum nächsten Tageslauf vor einer leeren Liste. Höher
# gesetzt, damit der tägliche Automatismus spürbar schneller in Richtung
# SOURCE_SUGGESTION_QUEUE_TARGET wächst - kostet proportional mehr
# (kostenpflichtige) Websuche-Calls pro Tag, bleibt aber ein einmaliger,
# fester Tages-Mehrpreis statt eines häufigeren Takts.
SOURCE_SUGGESTION_AUTHORS_PER_RUN = 6


def _build_source_suggestion_topic_seed() -> str:
    sources = main._load_sources()
    lines = []
    for entry in list(sources.values())[:30]:
        if entry.get("deleted_at"):
            continue
        terms_de = entry.get("key_terms_de") or []
        lines.append(f"- {entry.get('title', '')} ({', '.join(terms_de)})")
    return "\n".join(lines)


def _run_source_suggestion_discovery_once() -> None:
    pending = source_suggestions.list_suggestions(status="pending")
    if len(pending) >= main.SOURCE_SUGGESTION_QUEUE_TARGET:
        return
    known = {
        entry["url"] for entry in main._load_sources().values() if entry.get("url")
    } | source_suggestions.known_urls()
    excluded_domains = source_suggestions.blocked_domains()

    groups: list[list[dict]] = []
    author_names = [a["name"] for a in authors.list_authors()]
    for author in source_suggestions.pick_next_authors(author_names, SOURCE_SUGGESTION_AUTHORS_PER_RUN):
        groups.append(source_discovery.discover_by_author(author, known, excluded_domains))
    groups.append(
        source_discovery.discover_by_topic(_build_source_suggestion_topic_seed(), known, excluded_domains)
    )
    # Nutzerfeedback (2026-08-23): Autor:innen mit sehr vielen
    # Veröffentlichungen (z.B. Alfie Kohn) können mit einer einzigen Anfrage
    # schon die ganze Warteschlange füllen, ohne dass sich die Quellenlage
    # in der Breite verbessert. Reihum je einen Kandidaten aus jeder Gruppe
    # (jede angefragte Autorin/jeder Autor + die Themensuche) statt eine
    # Gruppe komplett auszuschöpfen, bevor die nächste überhaupt zum Zug
    # kommt - bei begrenzten remaining_slots (siehe unten) kommt so
    # garantiert eine Mischung an, nicht nur die ergiebigste Einzelquelle.
    found = [c for round_ in itertools.zip_longest(*groups) for c in round_ if c is not None]

    discovered_at = datetime.now(timezone.utc).isoformat()
    remaining_slots = main.SOURCE_SUGGESTION_QUEUE_TARGET - len(pending)
    seen_urls: set[str] = set()
    added = 0
    for candidate in found:
        if added >= remaining_slots:
            break
        url = candidate.get("url")
        if not url or url in known or url in seen_urls:
            continue
        seen_urls.add(url)
        source_suggestions.add_suggestion(candidate, discovered_at)
        added += 1


# Nutzerwunsch (2026-08-03): fehlende Zusammenfassungen (egal ob durch die
# Retries in _generate_summary_background immer noch nicht gelungen, oder
# aus der Zeit vor diesem Fix) automatisch nachziehen - laeuft nach
# demselben Muster wie der obige woechentliche URL-Gesundheits-Check, sofort
# einmal beim Prozessstart und danach in festem Takt.
SUMMARY_BACKFILL_INTERVAL_SECONDS = 24 * 3600


def _backfill_missing_summaries_once() -> None:
    sources = main._load_sources()
    missing = {
        sid: entry["text"]
        for sid, entry in sources.items()
        if not entry.get("deleted_at")
        and entry.get("text", "").strip()
        and not entry.get("summary_de")
        and not entry.get("summary_en")
    }
    for source_id, text in missing.items():
        with _track_background_job(source_id):
            _generate_summary_background(source_id, text)


# Idee 134c868a: Textsprache + englischer Titel für Bestandsquellen nachziehen
# - idempotent (nur Quellen ohne text_lang), ändert weder Zusammenfassung noch
# Titel. Nach 5 Fehlschlägen in Folge Abbruch (KI down: nicht 375 Aufrufe
# verbrennen), der nächste Tageslauf versucht es neu.
LANGUAGE_BACKFILL_MAX_CONSECUTIVE_FAILURES = 5


def _backfill_source_language_once() -> None:
    sources = main._load_sources()
    todo = [
        (sid, entry.get("title", ""), entry["text"])
        for sid, entry in sources.items()
        if not entry.get("deleted_at")
        and entry.get("text", "").strip()
        and not entry.get("text_lang")
        # von Hand geleert/gepflegt: kein täglicher Nachzug
        and entry.get("text_lang_ai_generated") is not False
    ]
    failures = 0
    for source_id, title, text in todo:
        stored = _detect_and_store_language(source_id, title, text)
        if stored:
            failures = 0
        elif stored is False:
            failures += 1
            if failures >= LANGUAGE_BACKFILL_MAX_CONSECUTIVE_FAILURES:
                return


def _backfill_summaries_and_language_once() -> None:
    # Ein Worker-Thread, Sprache direkt nach den Zusammenfassungen.
    try:
        main._backfill_missing_summaries_once()
    finally:
        main._backfill_source_language_once()


# Nutzerwunsch (2026-08-23): externe Autor:innen-Fotos sterben regelmäßig
# weg (v.a. LinkedIn-CDN-URLs mit eingebautem Ablaufdatum, siehe app/
# author_photos.py) - dieser tägliche Lauf holt für jede Autorin/jeden
# Autor mit gesetzter photo_url, die noch nicht (oder nicht mehr aktuell)
# lokal gecacht ist, das Bild einmalig nach. Deckt automatisch sowohl den
# initialen Rückstand bereits bestehender Profile als auch künftig neu
# gesetzte URLs ab, ohne dass jemand manuell einen Backfill anstoßen muss -
# auch auf Produktion, wo genau dasselbe Problem existiert.
AUTHOR_PHOTO_CACHE_INTERVAL_SECONDS = 24 * 3600


def _cache_missing_author_photos_once() -> None:
    for author in authors.list_authors():
        photo_url = author_profiles.get_profile(author["name"]).get("photo_url")
        if not photo_url:
            continue
        if author_photos.cached_source_url(author["name"]) == photo_url and author_photos.has_cached_photo(
            author["name"]
        ):
            continue
        author_photos.cache_photo(author["name"], photo_url)


# Backlog: LLM/Internet-Fallback bei dünner Quellenlage - Nutzerwunsch, dass
# die erweiterte Suche zur Antwortzeit "sehr schnell" gehen und Nutzer:innen
# vom Fallback "nichts merken" sollen. Deshalb läuft das eigentliche Crawlen/
# Indizieren (Netzwerk-Anfragen, Textextraktion, Embedding) NIE innerhalb
# von ask() (siehe dortige Web-Fallback-Erweiterung), sondern ausschließlich
# hier im Hintergrund, im selben wöchentlichen Rhythmus wie der URL-
# Gesundheits-Check oben - _ask_event_stream fragt zur Laufzeit nur noch die
# fertig indizierte Chroma-Collection ab (vectorstore.query_web), genauso
# schnell wie die normale Quellensuche. Ein neu angelegter Eintrag würde
# sonst bis zu eine Woche auf den nächsten Sweep warten - deshalb stößt
# add_web_allowlist_entry() zusätzlich einen einmaligen Sofort-Crawl NUR für
# diesen einen Eintrag an (_index_new_web_allowlist_entry), ebenfalls in
# einem eigenen Hintergrund-Thread, damit die Antwort auf POST
# /api/web-allowlist selbst weiterhin sofort zurückkommt.
WEB_ALLOWLIST_CRAWL_INTERVAL_SECONDS = 7 * 24 * 3600


# Nutzerfeedback (real reproduziert, siehe app/web_crawler.py-Kommentar):
# manche Websites lassen den Crawl in einem Python-Thread unbegrenzt hängen,
# selbst mit Timeout - der eigentliche Aufruf läuft deshalb in einem
# eigenen Unterprozess (app/web_crawl_subprocess.py), der bei Bedarf
# zuverlässig per Timeout beendet werden kann.
#
# Nutzerfeedback (real reproduziert für sichtart.at/Positivselektion): bei
# 180s lag zu wenig Sicherheitsabstand zu web_crawler.CRAWL_TIME_BUDGET_
# SECONDS (120s) - die Positivselektion braucht pro Kandidat zusätzlich ein
# Embedding + eine Vectorstore-Abfrage gegen den kuratierten Bestand (siehe
# _relevance_score_against_curated_corpus), dazu kommen Modell-Ladezeit und
# der Sitemap-Abruf selbst, die NICHT im 120s-Budget mitgezählt werden. Der
# Unterprozess wurde dadurch regelmäßig vom äußeren Timeout abgewürgt, bevor
# er überhaupt fertig war - mit reichlich Sicherheitsabstand (statt den
# Wert nur knapp zu erhöhen), damit dasselbe nicht bei einer etwas
# langsameren Website erneut passiert.
WEB_ALLOWLIST_SUBPROCESS_TIMEOUT_SECONDS = 300


def _run_web_crawl_subprocess(entry_id: str, url_prefix: str, max_pages: int) -> int:
    """Startet app/web_crawl_subprocess.py als eigenen Unterprozess und gibt
    dessen Exit-Code zurück (0 = Erfolg). Eigene Funktion statt inline in
    _index_web_allowlist_entry_with_status, damit Tests genau diese eine
    Stelle durch einen Fake ersetzen können, ohne echte Unterprozesse/
    Netzwerkzugriffe auszulösen (siehe tests/test_api.py)."""
    result = subprocess.run(
        [sys.executable, "-m", "app.web_crawl_subprocess", entry_id, url_prefix, str(max_pages)],
        cwd=str(main.BASE_DIR),
        timeout=WEB_ALLOWLIST_SUBPROCESS_TIMEOUT_SECONDS,
    )
    return result.returncode


def _index_web_allowlist_entry_with_status(entry_id: str, url_prefix: str, max_pages: int) -> None:
    """Nutzerwunsch: Fortschrittsring am Globus-Icon (siehe import.js:
    renderWebAllowlistIcon) - "running" während des Crawls, damit Quellen-
    Pfleger:innen sehen, wann eine Website fertig indiziert ist, statt nur
    an einer sich wöchentlich ändernden Seitenzahl raten zu müssen. Von
    beiden Aufrufstellen genutzt (Sofort-Crawl + wöchentlicher Sweep).

    Nutzerfeedback (real reproduziert): ein Server-Neustart löst sofort
    einen wöchentlichen Sweep-Durchlauf aus (siehe _run_web_allowlist_
    crawl_once via _run_periodic) - läuft zufällig zeitgleich noch ein
    Sofort-Crawl desselben Eintrags (z.B. gerade erst angelegt/manuell
    erneut angestoßen), würden beide unabhängig voneinander dieselben URLs
    entdecken und indizieren -
    doppelte Seiten mit unterschiedlichen page_ids in web_index.py. Ein
    einfacher Status-Check VOR dem Start genügt hier (kein echtes Lock
    nötig): das Risiko eines exakt gleichzeitigen zweiten Check-Aufrufs ist
    verschwindend klein gegenüber der Laufzeit eines ganzen Crawls."""
    current = web_allowlist.get_entry(entry_id)
    if current is not None and current.get("indexing_status") == "running":
        return
    web_allowlist.set_indexing_status(entry_id, "running")
    try:
        returncode = main._run_web_crawl_subprocess(entry_id, url_prefix, max_pages)
    except subprocess.TimeoutExpired:
        web_allowlist.set_indexing_status(entry_id, "error")
        raise
    if returncode != 0:
        web_allowlist.set_indexing_status(entry_id, "error")
        raise RuntimeError(f"web_crawl_subprocess für {entry_id} beendete sich mit Code {returncode}")
    web_allowlist.set_indexing_status(entry_id, None)


def _run_web_allowlist_crawl_once() -> None:
    for entry_id, entry in web_allowlist.list_entries().items():
        try:
            _index_web_allowlist_entry_with_status(
                entry_id, entry["url_prefix"], entry.get("max_pages", web_allowlist.DEFAULT_MAX_PAGES)
            )
        except Exception:
            # Ein einzelner fehlschlagender Eintrag (z.B. Website gerade
            # nicht erreichbar) darf die übrigen Einträge nicht blockieren.
            continue


def _recover_interrupted_web_allowlist_indexing() -> None:
    """Nach einem Server-Neustart/-Absturz kann kein Eintrag mehr wirklich
    "running" sein (der Hintergrund-Thread, der das gesetzt hat, existiert
    nicht mehr) - ein real beobachteter Fall: ein kurzlebiges Diagnose-
    Skript importierte app.main, startete dadurch selbst einen Crawl-
    Worker-Thread, und wurde beendet, während dieser noch lief. Als
    daemon=True-Thread wird er dabei ohne jede Aufräumung abgewürgt - der
    Fortschrittsring am Globus-Icon (siehe import.js) blieb dadurch
    dauerhaft "drehend" hängen, obwohl gar kein Crawl mehr lief. Setzt jeden
    verwaisten "running"-Status still zurück, BEVOR der eigentliche
    wöchentliche Sweep-Thread startet."""
    for entry_id, entry in web_allowlist.list_entries().items():
        if entry.get("indexing_status") == "running":
            web_allowlist.set_indexing_status(entry_id, None)


def _index_new_web_allowlist_entry(entry_id: str, url_prefix: str, max_pages: int) -> None:
    try:
        _index_web_allowlist_entry_with_status(entry_id, url_prefix, max_pages)
    except Exception:
        # Der wöchentliche Sweep (_run_web_allowlist_crawl_once via
        # _run_periodic) versucht es ohnehin erneut - ein fehlschlagender
        # Sofort-Lauf ist unkritisch.
        pass


def _recover_interrupted_processing_jobs() -> None:
    """Nach einem Server-Neustart läuft kein Hintergrund-Job mehr, dessen
    Quelle noch auf "running" steht. Trägt die Quelle das Merkmal
    "interrupted_by_deploy" (vom Shutdown-Hook gesetzt, siehe
    _wait_for_background_jobs_on_shutdown), ist die Ursache bekannt (Deploy
    hat die Wartezeit überschritten) und die zugrunde liegende Datei liegt
    noch unverändert auf der Platte (Audio/PDF) - dann wird automatisch neu
    eingereiht. Bei einem "echten" Absturz (kein Deploy, Merkmal fehlt) bzw.
    beim synchronen Text-/URL-Import (Text nur im Arbeitsspeicher des toten
    Prozesses, nicht wiederherstellbar) bleibt es beim bisherigen Verhalten:
    klar als Fehler markieren, damit ein Re-Import bewusst manuell
    angestoßen wird (siehe POST /.../reprocess).

    Audio-Quellen, die noch auf "pending" stehen (Backlog #113: warten in
    _audio_transcription_queue, bevor sie überhaupt angefangen haben),
    werden ebenfalls automatisch neu eingereiht - die In-Memory-
    Warteschlange selbst überlebt einen Neustart nicht, ohne dies blieben
    sie sonst unbemerkt für immer auf "pending" stehen, statt (wie vor
    #113) zeitnah von selbst dranzukommen."""
    pending_audio_ids: list[str] = []
    resumed_audio_ids: list[str] = []
    resumed_pdf_ids: list[str] = []
    with _sources_write_lock:
        sources = main._load_sources()
        changed = False
        for source_id, entry in sources.items():
            if entry.get("processing_status") == "running":
                interrupted_by_deploy = entry.pop("interrupted_by_deploy", False)
                changed = True
                if interrupted_by_deploy and _existing_audio_file(source_id):
                    entry["processing_status"] = "pending"
                    entry["processing_step"] = None
                    resumed_audio_ids.append(source_id)
                    continue
                if interrupted_by_deploy and _existing_pdf_file(source_id):
                    entry["processing_status"] = "pending"
                    entry["processing_step"] = None
                    resumed_pdf_ids.append(source_id)
                    continue
                entry["processing_status"] = "error"
                entry["processing_step"] = None
                entry["processing_error"] = i18n.get_message("processing_interrupted", i18n.DEFAULT_LANG)
            elif entry.get("processing_status") == "pending" and _existing_audio_file(source_id):
                pending_audio_ids.append(source_id)
        if changed:
            _save_sources(sources)
    for source_id in pending_audio_ids + resumed_audio_ids:
        _audio_transcription_queue.put((source_id, i18n.DEFAULT_LANG))
    for source_id in resumed_pdf_ids:
        threading.Thread(
            target=main._process_pdf_ocr, args=(source_id, i18n.DEFAULT_LANG), daemon=True
        ).start()


def _warm_up_local_models() -> None:
    embeddings.preload_model()
    vectorstore.preload()


# Backlog: erste Frage nach einem Server-Neustart sollte nicht die Ladezeit
# des lokalen Embedding-Modells (mehrere Sekunden) mittragen müssen - dafür
# aber auch nicht den Server-Start selbst blockieren (Ziel: Neustarts, von
# denen Nutzer:innen im besten Fall gar nichts merken). Läuft deshalb im
# Hintergrund weiter, während der Server schon Anfragen annimmt - trifft
# eine echte Anfrage zufällig genau die kurze Warm-up-Phase, wartet sie
# dank des Locks in embeddings._get_model/vectorstore._get_collection auf
# genau dieses eine Laden, statt selbst ein zweites zu starten.


def _normalize_pflaeging_spelling_once() -> None:
    """Einmalige Datenkorrektur (Nutzerwunsch 2026-08-25): "Niels Pfläging"
    weicht in vorhandenen KI-Zusammenfassungen/Schlagworten von der
    registrierten Autor:innen-Schreibweise "Niels Pflaeging" ab (siehe
    data/authors.json) - dadurch griff der Keyword-Autor:innen-Merge im
    Explore-Netzwerk (_build_knowledge_graph) für ihn nicht, anders als z.B.
    bei "Jos de Blok". Läuft bei jedem Start, idempotent (ohne verbleibende
    Treffer ein No-op) - bewusst als Startup-Schritt statt als manuelles
    Einmal-Skript wie bei der Beta-Kodex-Schreibweise in v0.52.1, damit die
    Korrektur automatisch über den normalen Deploy auf allen Umgebungen
    ankommt, ohne direkten Datei-Zugriff auf die Produktionsdaten zu
    benötigen. Ändert bewusst NUR summary_*/key_terms_* - der rohe
    Quellentext/Titel bleibt unangetastet, das war nicht Teil des
    Nutzerwunschs."""
    OLD_SPELLING = "Pfläging"
    NEW_SPELLING = "Pflaeging"
    sources = main._load_sources()
    changed_source_ids = []
    for source_id, entry in sources.items():
        touched = False
        for field in ("summary_de", "summary_en"):
            value = entry.get(field)
            if value and OLD_SPELLING in value:
                entry[field] = value.replace(OLD_SPELLING, NEW_SPELLING)
                touched = True
        for field in ("key_terms_de", "key_terms_en"):
            value = entry.get(field)
            if value:
                new_value = [term.replace(OLD_SPELLING, NEW_SPELLING) for term in value]
                if new_value != value:
                    entry[field] = new_value
                    touched = True
        if touched:
            changed_source_ids.append(source_id)
    if not changed_source_ids:
        return
    _save_sources(sources)
    for source_id in changed_source_ids:
        main._register_all_terms(source_id, sources[source_id])


# Nutzerwunsch (2026-09-25): im Deutschen "Beta-Kodex", im Englischen
# "BetaCodex". Eigennamen ("BetaCodex Chat", "BetaCodex Network") bleiben.
_BETACODEX_IN_GERMAN_RE = re.compile(r"BetaCodex(?! (?:Chat|Network))")


def _normalize_beta_kodex_spelling_once() -> None:
    """Einmalige Datenkorrektur (wie _normalize_pflaeging_spelling_once):
    KI-Zusammenfassungen/Schlagworte in der jeweils richtigen Schreibweise.
    Titel und Volltext bleiben unangetastet (Originalinhalt). Idempotent."""
    fixers = {
        "de": lambda value: _BETACODEX_IN_GERMAN_RE.sub("Beta-Kodex", value),
        "en": lambda value: value.replace("Beta-Kodex", "BetaCodex"),
    }
    sources = main._load_sources()
    changed_source_ids = []
    for source_id, entry in sources.items():
        touched = False
        for lang, fix in fixers.items():
            value = entry.get(f"summary_{lang}")
            if value and fix(value) != value:
                entry[f"summary_{lang}"] = fix(value)
                touched = True
            value = entry.get(f"key_terms_{lang}")
            if value and [fix(term) for term in value] != value:
                entry[f"key_terms_{lang}"] = [fix(term) for term in value]
                touched = True
        if touched:
            changed_source_ids.append(source_id)
    if not changed_source_ids:
        return
    _save_sources(sources)
    for source_id in changed_source_ids:
        main._register_all_terms(source_id, sources[source_id])


def _repair_char_split_key_terms_once() -> None:
    """Einmalige Datenkorrektur (Idee 3c32da30): lieferte das Modell
    key_terms_* als String statt Liste, entstand eine Liste einzelner
    Buchstaben (Ursache in summarization.py behoben). Die Begriffe lassen sich
    daraus nicht sicher zurückgewinnen (Leerzeichen fehlen) - das Feld wird
    geleert; die Zusammenfassungs-Nachholung füllt es bei Bedarf neu. Läuft bei
    jedem Start, idempotent."""
    sources = main._load_sources()
    changed = []
    for source_id, entry in sources.items():
        for field in ("key_terms_de", "key_terms_en"):
            value = entry.get(field)
            if isinstance(value, list) and len(value) >= 3 and all(isinstance(t, str) and len(t) == 1 for t in value):
                entry[field] = []
                if source_id not in changed:
                    changed.append(source_id)
    if not changed:
        return
    _save_sources(sources)
    for source_id in changed:
        main._register_all_terms(source_id, sources[source_id])


def _backfill_term_languages_once() -> None:
    """Einmalige Datenkorrektur (Nutzerwunsch 2026-09-22): terms.json
    unterschied bisher nicht nach Sprache - deutsche und englische
    Schlagworte landeten im selben Topf, wodurch die Tag-Vorschläge (siehe
    static/import.js) beim Bearbeiten einer deutschsprachigen Quelle auch
    englische Begriffe vorschlugen (und umgekehrt). register_term() bekommt
    die Sprache jetzt mit (siehe _register_all_terms) - bestehende, noch
    unmarkierte Einträge werden hier einmalig aus den Quellen neu aufgebaut.
    Läuft bei jedem Start, idempotent (kein unmarkierter Eintrag mehr -> No-op)."""
    if not any(not entry["langs"] for entry in terms.list_terms()):
        return
    sources = main._load_sources()
    for source_id, entry in sources.items():
        if not entry.get("deleted_at"):
            main._register_all_terms(source_id, entry)


# Aufbewahrungsfrist des Fragen-Logs (Nutzerwunsch): Einträge werden nach zwei
# Jahren automatisch gelöscht (siehe Datenschutzerklärung). Läuft wie die
# übrigen periodischen Worker sofort beim Start und danach täglich.
QUESTION_LOG_RETENTION_DAYS = 730
QUESTION_LOG_PURGE_INTERVAL_SECONDS = 24 * 3600


def _purge_expired_question_log_entries_once() -> None:
    question_log.purge_older_than(QUESTION_LOG_RETENTION_DAYS)


def _reindex_one_source(source_id: str, data: dict, only_changed: bool) -> bool:
    """Gibt True zurück, wenn neu eingebettet wurde."""
    text = data.get("text", "")
    new_chunks = chunking.chunk_text(text.strip()) if text.strip() else []
    if not new_chunks:
        return False
    if only_changed:
        existing = vectorstore.get_source_chunk_texts(source_id)
        if existing and existing == new_chunks:
            return False
    chunk_embeddings = embeddings.embed_passages(new_chunks)  # langsam, ohne Sperre
    with _sources_write_lock:
        sources = main._load_sources()
        current = sources.get(source_id)
        if current is None or current.get("deleted_at") or current.get("text", "") != text:
            return False
        source = _source_in_from_entry(current)  # aktuelle Metadaten, nicht den Stand vor dem Einbetten
        with _vectorstore_write_lock:
            vectorstore.delete_source_chunks(source_id)
            current["chunk_count"] = _store_chunks(
                source_id, source, new_chunks, chunk_embeddings, current.get("images")
            )
        _save_sources(sources)
    return True


def _is_audio_or_video_source(source_id: str, url: str) -> bool:
    return (
        extraction._is_youtube_url(url)
        or _existing_audio_file(source_id) is not None
        or url.lower().split("?")[0].endswith(extraction.AUDIO_EXTENSIONS)
    )


# Fix v0.94.1: Bildsuchen vor diesem Stichtag, die 0 Bilder ergaben, werden
# einmal wiederholt (Seiten bekamen seitdem Bilder/Alt-Texte, z. B.
# betacodex.org/welcome-to-the-betaworld). Danach liegt images_checked_at
# nach dem Stichtag - idempotent, kein Dauer-Abruf.
IMAGES_RECHECK_BEFORE = "2026-11-16T12:00:00+00:00"


def _needs_image_check(entry: dict) -> bool:
    checked = entry.get("images_checked_at")
    if not checked:
        return True
    return not entry.get("images") and datetime.fromisoformat(checked) < datetime.fromisoformat(IMAGES_RECHECK_BEFORE)


def _backfill_images(source_id: str) -> bool:
    """Holt Bilder für eine ältere Quelle nach (Idee ff895248, nur über den
    Admin-Reindex). Schreibt unter Sperre NUR `images`/`images_checked_at` und
    die Bild-Metadaten der vorhandenen Chunks - Text, Zusammenfassung,
    Schlagworte und KI-Flags bleiben unberührt, es gibt keinen KI-Aufruf.
    Ein Fehlschlag setzt nichts (nächster Lauf versucht es erneut).
    Gibt True zurück, wenn die Quelle nun als geprüft gilt."""
    entry = main._load_sources().get(source_id)
    if not entry or entry.get("deleted_at") or not _needs_image_check(entry):
        return False
    url = entry.get("url") or ""
    pdf_file = _existing_pdf_file(source_id)
    if pdf_file is not None:
        images = _store_pdf_images(source_id, pdf_file.read_bytes())
    elif url and not _is_audio_or_video_source(source_id, url) and not url.lower().split("?")[0].endswith(".pdf"):
        result = extraction.extract_from_url(url)
        if not result.get("extracted"):
            return False
        images = source_images.sanitize_web_images(result.get("images"))
    else:
        return False
    with _sources_write_lock:
        sources = main._load_sources()
        current = sources.get(source_id)
        if current is None or current.get("deleted_at"):
            source_images.delete_source_images(main.SOURCE_IMAGES_DIR, source_id)
            return False
        current["images"] = images
        current["images_checked_at"] = datetime.now(timezone.utc).isoformat()
        _reassign_chunk_images(source_id, images)
        _save_sources(sources)
    return True


IMAGE_REVIEW_WORKERS = 4


_image_key = source_images.image_key


def _reassign_chunk_images(source_id: str, images: list[dict]) -> None:
    """Bild-Metadaten der vorhandenen Chunks neu setzen (Text bleibt). Aufrufer hält _sources_write_lock."""
    with _vectorstore_write_lock:
        ids, docs, metas = vectorstore.get_source_chunks(source_id)
        for meta, chunk_images in zip(metas, chunking.assign_images(docs, images)):
            meta["images_json"] = json.dumps(chunk_images, ensure_ascii=False)
        vectorstore.update_chunk_metadatas(ids, metas)


def _review_input(source_id: str, image: dict) -> dict | None:
    if image.get("kind") == "file":
        path = source_images.image_path(main.SOURCE_IMAGES_DIR, source_id, image.get("file") or "")
        return image_review.file_source(path.read_bytes()) if path else None
    if image.get("kind") == "url" and source_images.is_safe_https(image.get("url")):
        return image_review.url_source(image["url"])
    return None


def _review_source_images(source_id: str) -> int:
    """KI-Prüfung (Nutzerwunsch 2026-11-19) aller Bilder einer Quelle ohne
    `relevant`. API-Aufrufe ohne Sperre; danach unter Sperre nur `relevant`/
    `alt_de`/`alt_en` der noch vorhandenen Bilder setzen und die Chunk-Bilder
    neu zuordnen (Deko belegt keinen Platz mehr). Idempotent: Geprüftes wird
    nie erneut geschickt. Liefert die Zahl neu geprüfter Bilder."""
    entry = main._load_sources().get(source_id)
    if not entry or entry.get("deleted_at"):
        return 0
    pending = [image for image in entry.get("images") or [] if "relevant" not in image]
    if not pending:
        return 0
    title = entry.get("title") or ""

    def run(image):
        source = _review_input(source_id, image)
        if source is None:  # Datei fehlt/unsichere URL: würde ohnehin nie angezeigt
            return _image_key(image), {"relevant": False, "alt_de": "", "alt_en": ""}
        return _image_key(image), image_review.review_image(
            source, title, image.get("anchor") or "", image.get("alt") or ""
        )

    with ThreadPoolExecutor(IMAGE_REVIEW_WORKERS) as pool:
        results = {key: result for key, result in pool.map(run, pending) if result}
    if not results:
        return 0
    with _sources_write_lock:
        sources = main._load_sources()
        current = sources.get(source_id)
        if current is None or current.get("deleted_at"):
            return 0
        images = current.get("images") or []
        for image in images:
            if "relevant" not in image and _image_key(image) in results:
                image.update(results[_image_key(image)])
        _reassign_chunk_images(source_id, images)
        _save_sources(sources)
    return len(results)


def _review_all_images() -> None:
    """Holt die KI-Bildprüfung für alle Quellen nach (Start, Admin-Reindex)."""
    log = logging.getLogger("app.main")
    total = 0
    for source_id, data in main._load_sources().items():
        if data.get("deleted_at") or all("relevant" in image for image in data.get("images") or []):
            continue
        try:
            total += _review_source_images(source_id)
        except Exception:
            log.exception("Bildprüfung von Quelle %s fehlgeschlagen", source_id)
    log.info("Bildprüfung: %d Bilder neu geprüft", total)


def _reindex_all_sources(only_changed: bool = False, fetch_missing_images: bool = False) -> int:
    """Chunked/embedded Quellen neu (z.B. nach einer Änderung an
    `chunking.chunk_text()`) - `sources.json` bleibt bis auf `chunk_count`
    unangetastet. Mit only_changed werden Quellen übersprungen, deren
    Chunks bereits dem neuen Zuschnitt entsprechen (0 Chunks = geändert).
    Pro Quelle gekapselt, damit ein defekter Datensatz nicht den Lauf
    abbricht. Liefert die Zahl neu indizierter Quellen."""
    count = 0
    fetches = failures = 0
    log = logging.getLogger("app.main")
    for source_id, data in main._load_sources().items():
        if data.get("deleted_at"):
            continue
        try:
            count += _reindex_one_source(source_id, data, only_changed)
        except Exception:
            log.exception("Reindex von Quelle %s fehlgeschlagen", source_id)
        if fetch_missing_images and _needs_image_check(data):
            fetches += 1
            try:
                if not _backfill_images(source_id):
                    failures += 1
            except Exception:
                failures += 1
                log.exception("Bild-Nachladen von Quelle %s fehlgeschlagen", source_id)
    if fetch_missing_images:
        log.info("Bild-Nachladen: %d Versuche, %d ohne Ergebnis", fetches, failures)
    return count


# Wartezeit vor dem Start-Reindex: Blue-Green-Deploy schaltet erst um und
# stoppt die alte Farbe - beide Instanzen sollen nicht gleichzeitig
# einbetten. An die Umschaltzeit von deploy.sh (liegt nur auf dem Server)
# anpassen.
STARTUP_REINDEX_DELAY_SECONDS = 120


def _acquire_reindex_lock():
    """Nicht blockierende Prozess-Sperre; Datei-Objekt (Sperre hält bis close) oder None."""
    import fcntl

    lock_file = open(main.DATA_DIR / "reindex.lock", "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock_file.close()
        return None
    return lock_file


def _startup_reindex(delay: float = STARTUP_REINDEX_DELAY_SECONDS) -> None:
    """Zerlegt beim Start Quellen neu, deren Chunks nicht zum aktuellen
    Chunking passen. Idempotent; wer die Sperre nicht bekommt, lässt aus."""
    log = logging.getLogger("app.main")
    time.sleep(delay)
    try:
        lock_file = _acquire_reindex_lock()
        if lock_file is None:
            log.info("Start-Reindex: Sperre gehalten, ausgelassen")
            return
        with lock_file:
            log.info("Start-Reindex läuft")
            count = main._reindex_all_sources(only_changed=True)
            log.info("Start-Reindex: %d Quellen neu indiziert", count)
            _review_all_images()
    except Exception:
        log.exception("Start-Reindex fehlgeschlagen")


def _reindex_holding_lock(lock_file, only_changed: bool = False, fetch_missing_images: bool = False) -> None:
    with lock_file:
        main._reindex_all_sources(only_changed=only_changed, fetch_missing_images=fetch_missing_images)
        _review_all_images()


def _backfill_images_holding_lock(lock_file) -> None:
    """Fix v0.95.3: nur Bilder nachholen, ohne Neu-Einbetten (Minuten statt
    über eine Stunde; der volle Lauf wurde von Deploys abgebrochen)."""
    log = logging.getLogger("app.main")
    with lock_file:
        done = 0
        for source_id, data in main._load_sources().items():
            if data.get("deleted_at") or not _needs_image_check(data):
                continue
            try:
                done += bool(_backfill_images(source_id))
            except Exception:
                log.exception("Bild-Nachladen von Quelle %s fehlgeschlagen", source_id)
        log.info("Bild-Nachladen (nur Bilder): %d Quellen geprüft", done)
        _review_all_images()
