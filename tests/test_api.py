import concurrent.futures
import json
import threading
import time
import uuid

import anthropic
import pytest
from fastapi.testclient import TestClient

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
    llm,
    mail,
    monitoring,
    question_log,
    ratelimit,
    source_discovery,
    source_suggestions,
    summarization,
    terms,
    transcription_hints,
    tts,
    users,
    vectorstore,
    web_allowlist,
    web_candidates,
    web_crawler,
    web_index,
)
from app import main as main_module

PFLEGER = "lena.pflegerin@test.local"


def login(test_client, email, role=None):
    """Loggt einen TestClient über den echten Magic-Link-Verify-Pfad ein -
    dessen Cookie-Jar merkt sich das gesetzte Session-Cookie für alle
    folgenden Requests, genau wie ein echter Browser."""
    if role:
        users.invite_user(email, role, invited_by="test-bootstrap")
    token = auth.create_magic_link_token(email, auth.LOGIN_LINK_MAX_AGE_SECONDS)
    test_client.get(f"/api/auth/verify?token={token}", follow_redirects=False)


def wait_until(predicate, timeout=5.0, interval=0.02):
    """Pollt predicate() bis True statt eine feste Wartezeit zu verstreichen
    zu lassen (Bug, 2026-08-20: ein fixes time.sleep(0.5) nach einem
    absichtlich verzögerten Hintergrund-Thread (time.sleep(0.3)) reichte auf
    einem ausgelasteten CI-Runner nicht - der eigentlich fertige Thread war
    zum Zeitpunkt der Prüfung noch nicht durchgelaufen, der Test schlug
    dadurch scheinbar zufällig fehl, obwohl das Feature selbst funktioniert.
    Reagiert auf einen schnell fertigen Thread sofort, statt immer die volle
    Wartezeit auszusitzen, und toleriert einen langsamen Runner bis zum
    timeout - die letzte, fehlschlagende Auswertung liefert dann den echten
    AssertionError samt Kontext."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(interval)
    assert predicate()


def ask_result(response):
    """Testhilfe (Backlog 2026-07-29, Streaming-Antworten): /api/ask liefert
    seitdem NDJSON (eine JSON-Zeile pro Event) statt einer einzelnen JSON-
    Antwort. Liest den kompletten Stream und baut daraus dieselbe Form nach,
    die früher response.json() lieferte ({"answer": ..., "sources": ...}),
    damit der Großteil der bestehenden Tests unverändert lesbar bleibt.
    streamed_text sammelt zusätzlich alle delta-Fragmente in Sende-
    Reihenfolge - für Tests, die gezielt das Streaming-Verhalten selbst
    prüfen (z.B. dass der ---QUOTES---Block nie an den Client geht). Der
    fertige Antworttext kommt seit Backlog 2026-07-31 in einem eigenen,
    FRÜHEREN "answer"-Event statt im "done"-Event - das trägt seitdem nur
    noch die (u.U. langsamer berechneten) Quellen/Highlights, damit z.B. der
    Vorlesen-Button auf die nicht warten muss."""
    lines = [line for line in response.text.split("\n") if line.strip()]
    events = [json.loads(line) for line in lines]
    answer_event = next(e for e in events if e["type"] == "answer")
    done = next(e for e in events if e["type"] == "done")
    streamed_text = "".join(e["text"] for e in events if e["type"] == "delta")
    return {
        "answer": answer_event["answer"],
        "sources": done["sources"],
        "streamed_text": streamed_text,
        "events": events,
    }


def creative_result(response):
    """Wie ask_result, für /api/creative (siehe dort): sammelt "delta"-
    Fragmente, liest das frühe "document"-Event und die nach
    Vertrauensstufe getrennte Quellenliste aus dem "done"-Event."""
    lines = [line for line in response.text.split("\n") if line.strip()]
    events = [json.loads(line) for line in lines]
    document_event = next(e for e in events if e["type"] == "document")
    done = next(e for e in events if e["type"] == "done")
    streamed_text = "".join(e["text"] for e in events if e["type"] == "delta")
    return {
        "document": document_event["document"],
        "sources": done["sources"],
        "streamed_text": streamed_text,
        "events": events,
    }


class _FakeCreativeStream:
    """Testhilfe: mimt app/llm.py:CreativeStream (iterierbarer Text-Delta-
    Generator + .real_web_urls + .model), ohne einen echten Anthropic-Call
    auszuführen - Standard-Mock in der client-Fixture unten."""

    def __init__(self, chunks, real_web_urls=frozenset(), model="claude-haiku-4-5-20251001"):
        self._chunks = chunks
        self.real_web_urls = real_web_urls
        self.model = model

    def __iter__(self):
        return iter(self._chunks)


@pytest.fixture(scope="session", autouse=True)
def _shared_vectorstore_client(tmp_path_factory):
    """Fix (2026-08-25, siehe ausführlicher Kommentar in app/vectorstore.py:
    _get_client()): DB_PATH einmal für die gesamte Session auf ein festes
    Verzeichnis setzen, damit vectorstore._client (ein nativer
    chromadb.PersistentClient) über alle Tests hinweg EIN EINZIGES Mal
    erzeugt und wiederverwendet wird, statt pro Test neu (das kostete
    zuletzt tausende nie freigegebene Betriebssystem-Threads). Isolation
    zwischen Tests kommt seitdem nicht mehr über einen eigenen DB_PATH pro
    Test, sondern über einen eigenen Collection-Namen (siehe client-Fixture
    unten)."""
    vectorstore.DB_PATH = tmp_path_factory.mktemp("shared_chroma")


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Fix (2026-08-25, Suite brauchte zuletzt ~20min statt ~1min): jede
    # TestClient(main_module.app)-Instanziierung durchläuft das echte
    # ASGI-Lifespan (siehe app/main.py:lifespan) und startet darüber
    # _start_background_workers() - 5 EWIGE "while True"-Threads (URL-
    # Gesundheits-Check, Vorschlags-Vorrat, Zusammenfassungs-Nachzug,
    # Foto-Cache, Web-Allowlist-Crawl), die nie von selbst enden. Das
    # bestehende Thread-Tracking unten (started_threads/tracking_start)
    # joint sie zwar mit Timeout, KANN sie aber nicht wirklich beenden - sie
    # laufen als Daemon-Threads einfach weiter. Bei ~350 Tests in dieser
    # Datei sammelten sich dadurch >1500 gleichzeitig laufende Threads an
    # (mit "ps -M"/"top -stats th" bestätigt), die sich gegenseitig beim
    # Zugriff auf die (pro Test frische) Chroma-Vectorstore-Instanz
    # blockierten, bis die Suite praktisch stehen blieb. Jede einzelne
    # Funktion, die _start_background_workers() aufruft, hat bereits eigene,
    # direkte Tests (_run_source_suggestion_discovery_once, _recover_
    # interrupted_*, users.ensure_bootstrap_admin in test_users.py) - der
    # Aufruf von _start_background_workers() SELBST wird nirgends geprüft,
    # kann also gefahrlos stillgelegt werden.
    monkeypatch.setattr(main_module, "_start_background_workers", lambda: None)
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_module, "SOURCES_FILE", tmp_path / "sources.json")
    monkeypatch.setattr(main_module, "PDF_DIR", tmp_path / "pdfs")
    monkeypatch.setattr(main_module, "PDF_UPLOAD_STAGING_DIR", tmp_path / "pdf_uploads")
    monkeypatch.setattr(main_module, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(main_module, "AUDIO_UPLOAD_STAGING_DIR", tmp_path / "audio_uploads")

    # Fix (2026-08-25): Isolation zwischen Tests jetzt über einen pro Test
    # eindeutigen Collection-Namen statt über einen eigenen DB_PATH/Client
    # (siehe _shared_vectorstore_client oben + app/vectorstore.py:
    # _get_client()) - vectorstore._client bleibt für die gesamte Session
    # bestehen, nur _collection/_web_collection werden zurückgesetzt, damit
    # get_or_create_collection() für DIESEN Test eine frische, leere
    # Collection auf dem gemeinsamen Client öffnet.
    unique_suffix = uuid.uuid4().hex
    monkeypatch.setattr(vectorstore, "COLLECTION_NAME", f"test_{unique_suffix}")
    monkeypatch.setattr(vectorstore, "WEB_FALLBACK_COLLECTION_NAME", f"test_web_{unique_suffix}")
    monkeypatch.setattr(vectorstore, "_collection", None)
    monkeypatch.setattr(vectorstore, "_web_collection", None)
    monkeypatch.setattr(web_allowlist, "WEB_ALLOWLIST_FILE", tmp_path / "web_allowlist.json")
    monkeypatch.setattr(web_index, "WEB_INDEX_FILE", tmp_path / "web_index.json")
    monkeypatch.setattr(web_candidates, "WEB_CANDIDATES_FILE", tmp_path / "web_candidates.json")
    monkeypatch.setattr(
        source_suggestions, "SOURCE_SUGGESTIONS_FILE", tmp_path / "source_suggestions.json"
    )
    monkeypatch.setattr(
        source_suggestions,
        "SOURCE_SUGGESTION_WEIGHTS_FILE",
        tmp_path / "source_suggestion_weights.json",
    )
    # POST /api/web-allowlist stößt seit dem Sofort-Crawl-Fix einen echten
    # Hintergrund-Thread an (_index_new_web_allowlist_entry in app/main.py).
    # Der eigentliche Crawl läuft seit dem Unterprozess-Fix (manche Websites
    # hängen sonst unbegrenzt in einem Python-Thread, siehe app/web_crawler.py-
    # Kommentar) nicht mehr in-process, sondern über
    # main_module._run_web_crawl_subprocess() - genau DAS wird hier gemockt,
    # nicht mehr web_crawler.index_entry direkt (das läuft ja jetzt im
    # Kindprozess, den ein Mock von index_entry im Testprozess gar nicht mehr
    # erreichen würde). Ohne dieses Mock würde JEDER Test, der einen
    # Allowlist-Eintrag über die API anlegt, einen echten Unterprozess mit
    # echter Netzwerkanfrage auslösen - langsam, flaky und im Extremfall ein
    # Risiko für echte Produktionsdaten, genau wie beim Audio-Transkriptions-
    # Vorfall vom 2026-07-28 (siehe Kommentar weiter unten). Tests, die den
    # Sofort-Crawl selbst gezielt prüfen, überschreiben dieses Mock lokal.
    monkeypatch.setattr(main_module, "_run_web_crawl_subprocess", lambda entry_id, url_prefix, max_pages: 0)

    # Der tägliche Vorschlags-Vorrat-Worker (_source_suggestion_discovery_worker)
    # läuft seit seiner Einführung sofort einmal beim Start jedes echten
    # ASGI-Prozesses (_start_background_workers), also auch bei JEDER
    # TestClient(main_module.app)-Instanziierung hier. _run_source_suggestion_
    # discovery_once() bricht nur ab, wenn der Vorrat schon SOURCE_SUGGESTION_
    # QUEUE_TARGET (100) erreicht hat - bei einem frischen tmp_path ist der
    # Vorrat aber immer leer, ruft also bei praktisch jedem einzelnen Test
    # echte, kostenpflichtige Anthropic-Websuche-Aufrufe auf (discover_by_topic
    # läuft sogar unabhängig von vorhandenen Autor:innen). Das machte die
    # gesamte Suite real netzwerkabhängig und massiv langsam. Tests, die
    # dieses Verhalten selbst gezielt prüfen, überschreiben diese Mocks lokal.
    monkeypatch.setattr(source_discovery, "discover_by_author", lambda author, known, excluded: [])
    monkeypatch.setattr(source_discovery, "discover_by_topic", lambda seed, known, excluded: [])

    # Sicherheitsnetz (Vorfall 2026-08-23: der Vorschlags-Worker oben hat
    # unbemerkt bei praktisch jedem Test eine echte, kostenpflichtige
    # Anthropic-Anfrage ausgelöst, weil ein einzelner Aufrufpfad ungemockt
    # blieb). Statt darauf zu vertrauen, dass jede Funktion, die intern einen
    # Anthropic-Client braucht (app/extraction.py, app/summarization.py,
    # app/llm.py, app/source_discovery.py - alle über ein lazygecachtes
    # `_client = anthropic.Anthropic()`), einzeln gemockt wird, blockiert
    # dies den echten Client-Konstruktor selbst: ein fehlender Mock führt
    # dadurch zu einem sofortigen, lauten Testfehler statt einer stillen,
    # echten (langsamen/teuren) Netzwerkanfrage. Tests, die eine dieser
    # Funktionen gezielt prüfen, mocken ohnehin schon den jeweiligen
    # `_get_client`/`_get_anthropic_client` und rufen den echten Konstruktor
    # dadurch nie auf - für sie ändert dieses Sicherheitsnetz nichts.
    def _fail_on_real_anthropic_client(*args, **kwargs):
        raise RuntimeError(
            "Echter anthropic.Anthropic()-Client in einem Test angefordert - "
            "fehlt ein Mock für die aufrufende Funktion? (siehe Kommentar in "
            "der client-Fixture, Vorfall 2026-08-23)"
        )

    monkeypatch.setattr(anthropic, "Anthropic", _fail_on_real_anthropic_client)

    # Dasselbe Sicherheitsnetz für OpenAI (app/extraction.py: Audio-
    # Transkription/PDF-Vision) - ein fehlender Mock würde hier sonst nicht
    # nur eine echte Anfrage auslösen, sondern zusätzlich in
    # _transcribe_chunk_with_retries auf einen (bei fehlendem/ungültigem
    # API-Key wahrscheinlichen) Fehler mit bis zu 30+90 Sekunden echtem
    # time.sleep() zwischen den Wiederholungen laufen - genau das hat die
    # Suite bei mehreren betroffenen Tests spürbar über Minuten verlangsamt.
    # extraction.py bindet die Klasse per "from openai import OpenAI" lokal
    # (nicht per "import openai" + spätem Attributzugriff wie beim
    # Anthropic-Fall oben) - gepatcht werden muss deshalb der lokale Name
    # extraction.OpenAI, nicht openai.OpenAI.
    def _fail_on_real_openai_client(*args, **kwargs):
        raise RuntimeError(
            "Echter openai.OpenAI()-Client in einem Test angefordert - fehlt "
            "ein Mock für die aufrufende Funktion? (siehe Kommentar in der "
            "client-Fixture, Vorfall 2026-08-23)"
        )

    monkeypatch.setattr(extraction, "OpenAI", _fail_on_real_openai_client)

    monkeypatch.setattr(authors, "AUTHORS_FILE", tmp_path / "authors.json")
    monkeypatch.setattr(author_profiles, "AUTHOR_PROFILES_FILE", tmp_path / "author_profiles.json")
    monkeypatch.setattr(author_photos, "AUTHOR_PHOTOS_DIR", tmp_path / "author_photos")
    monkeypatch.setattr(author_photos, "MANIFEST_FILE", tmp_path / "author_photos" / "_manifest.json")
    # PUT /api/authors/{name} stößt seit dem Foto-Cache-Fix (2026-08-23) bei
    # geänderter photo_url einen echten Hintergrund-Thread an (siehe
    # update_author_profile in app/main.py), der die URL herunterlädt - ohne
    # dieses Mock würde JEDER Test, der eine photo_url setzt, eine echte
    # Netzwerkanfrage auslösen (langsam/flaky). Tests, die das Caching selbst
    # gezielt prüfen, überschreiben dieses Mock lokal.
    monkeypatch.setattr(author_photos, "cache_photo", lambda name, url: False)
    # PUT /api/sources/{id} stößt seit dem Auto-Übersetzungs-Fix (2026-08-23)
    # bei jeder gesetzten summary einen echten Hintergrund-Übersetzungs-
    # Aufruf an (_translate_summary_background in app/main.py) - ohne dieses
    # Mock würde JEDER Test, der eine Quelle mit summary speichert, eine
    # echte Anthropic-Anfrage auslösen. Tests, die die Übersetzung selbst
    # gezielt prüfen, überschreiben dieses Mock lokal.
    monkeypatch.setattr(summarization, "translate_summary", lambda text, target_lang="de": "")
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(terms, "TERMS_FILE", tmp_path / "terms.json")
    monkeypatch.setattr(audit, "AUDIT_LOG_FILE", tmp_path / "audit_log.json")
    monkeypatch.setattr(question_log, "QUESTION_LOG_FILE", tmp_path / "question_log.json")

    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [1.0, 0.0])
    # Performance-Fix (Backlog 2026-07-31): Satz-Embeddings für lokales
    # Highlighting werden serverweit über einen Text-Hash gecacht (siehe
    # _CHUNK_SENTENCE_EMBEDDING_CACHE in app/main.py) - der Cache lebt
    # modulweit und würde sonst über Tests hinweg bestehen bleiben.
    monkeypatch.setattr(main_module, "_CHUNK_SENTENCE_EMBEDDING_CACHE", {})
    # /api/ask ruft seit dem Streaming-Umbau (Backlog 2026-07-29)
    # stream_answer_question statt answer_question auf - der Mock muss ein
    # Iterable liefern (wie der echte Generator), kein fertiges String.
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda question, chunks, lang="de", author_bios=None, history=None: iter(["Testantwort [1]."]),
    )
    # /api/creative (Kreativ-Modus, 2026-08-26) - Standard-Mock analog zu
    # stream_answer_question oben, liefert ein CreativeStream-förmiges
    # Objekt (siehe _FakeCreativeStream) statt eines echten Anthropic-Calls.
    monkeypatch.setattr(
        llm,
        "stream_creative_response",
        lambda instruction, document, chunks, lang="de", section=None: _FakeCreativeStream(["Testdokument."]),
    )
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "", "key_terms": []},
            "en": {"summary": "", "key_terms": []},
        },
    )
    # Das Standard-Mock oben liefert absichtlich ein leeres Ergebnis - das
    # loest seit dem Retry-Fix (2026-08-03, siehe _generate_summary_with_
    # retries in app/main.py) mehrere Versuche mit echtem time.sleep()
    # dazwischen aus. Ohne dies wuerde JEDER Test, der eine Quelle anlegt,
    # durch die Test-Suite hindurch spuerbar langsamer werden.
    monkeypatch.setattr(main_module, "SUMMARY_RETRY_DELAY_SECONDS", 0)
    # Ohne dieses Mock würde jede neue Person beim Import einen echten
    # API-Call für die automatische Vita auslösen (Backlog: "jede:r Autor:in
    # soll von Anfang an eine Vita haben"). Tests, die dieses Verhalten
    # gezielt prüfen, überschreiben das Mock lokal.
    monkeypatch.setattr(summarization, "generate_author_bio", lambda name, texts, lang="de": "")

    # /api/ask ist durch Rate-Limiting + Captcha-Prüfung abgesichert - für die
    # meisten Tests hier standardmäßig deaktiviert, damit sie sich weiterhin
    # nur um ihr jeweiliges Verhalten kümmern müssen. Eigene Tests für das
    # Schutzverhalten selbst überschreiben diese Mocks gezielt.
    monkeypatch.setattr(captcha, "verify_turnstile_token", lambda token, remote_ip=None: True)
    monkeypatch.setattr(ratelimit, "_request_log", {})
    monkeypatch.setattr(conversation_handoff, "_store", {})
    monkeypatch.setattr(auth, "_consumed_jti", {})
    # TestClient spricht "http://testserver" - ein "Secure"-Cookie würde vom
    # Cookie-Jar sonst nie zurückgeschickt, der Login-Test-Client bliebe
    # scheinbar ausgeloggt.
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", True)

    # add_source() startet für "langsame" Importe (siehe SLOW_IMPORT_TIMEOUT_SECONDS)
    # einen ECHTEN Hintergrund-Thread (_finish_synchronous_import), der nach
    # done_event.set() noch die Zusammenfassung anstößt. Ohne das folgende
    # Tracking+Join könnte so ein Thread noch laufen, wenn monkeypatch am
    # Testende SOURCES_FILE/DATA_DIR/... wieder auf die ECHTEN Produktionspfade
    # zurücksetzt - der Thread würde dann versehentlich in die echten
    # Nutzerdaten schreiben. Genau das ist bei der Entwicklung eines
    # Concurrency-Tests real passiert (2026-07-28, sources.json verlor dabei
    # den Großteil seines Inhalts). Deshalb: JEDEN in diesem Test gestarteten
    # Thread einsammeln und vor dem restlichen Teardown fertig werden lassen.
    started_threads: list[threading.Thread] = []
    original_thread_start = threading.Thread.start

    def tracking_start(self):
        started_threads.append(self)
        return original_thread_start(self)

    monkeypatch.setattr(threading.Thread, "start", tracking_start)

    # Standard-Testrolle: Quellen-Pfleger:in, damit bestehende Tests nicht jeden
    # Request einzeln einloggen müssen.
    test_client = TestClient(main_module.app)
    login(test_client, PFLEGER, users.QUELLEN_PFLEGER)
    yield test_client

    for t in started_threads:
        t.join(timeout=10)


@pytest.fixture
def anon_client(client):
    # Teilt sich die von `client` bereits vorgenommenen Monkeypatches (gleiche
    # tmp_path/Module), hat aber keinen Session-Cookie - simuliert einen
    # Besuch ganz ohne Login.
    return TestClient(main_module.app)


# Backlog #114: Early-Access-Passwort für die Produktivumgebung. Ohne
# gesetztes EARLY_ACCESS_PASSWORD (Standardfall, entspricht Dev/Stabil) bleibt
# die App komplett unangetastet - das deckt sich implizit mit ALLEN anderen
# Tests in dieser Datei, die diesen Wert nie setzen. Die folgenden Tests
# prüfen gezielt das Verhalten, wenn der Wert gesetzt ist.


def test_early_access_inactive_by_default_leaves_app_fully_accessible(anon_client):
    assert anon_client.get("/").status_code == 200
    assert anon_client.get("/api/sources").status_code == 200


def test_early_access_blocks_pages_when_password_set(anon_client, monkeypatch):
    monkeypatch.setenv("EARLY_ACCESS_PASSWORD", "geheim123")

    response = anon_client.get("/")

    assert response.status_code == 200
    assert 'id="early-access-form"' in response.text


def test_early_access_exempts_gate_assets(anon_client, monkeypatch):
    # Ohne diese Ausnahmen wuerde die Middleware auch fuer diese Assets die
    # Gate-Seite (HTML) statt ihres eigentlichen Inhalts ausliefern - das
    # Freischalt-Formular selbst waere dann funktionslos (kaputtes JS/CSS/i18n).
    monkeypatch.setenv("EARLY_ACCESS_PASSWORD", "geheim123")

    js_response = anon_client.get("/early-access.js")
    assert js_response.status_code == 200
    assert "early-access-form" in js_response.text
    assert "<html" not in js_response.text.lower()

    css_response = anon_client.get("/style.css")
    assert css_response.status_code == 200
    assert ".error-page" in css_response.text

    i18n_response = anon_client.get("/i18n/de.json")
    assert i18n_response.status_code == 200
    assert i18n_response.json()["earlyAccess.heading"] == "Geschlossener Testzugang"


def test_early_access_wrong_password_is_rejected(anon_client, monkeypatch):
    monkeypatch.setenv("EARLY_ACCESS_PASSWORD", "geheim123")

    response = anon_client.post("/api/early-access", json={"password": "falsch"})

    assert response.status_code == 401


def test_early_access_correct_password_unlocks_subsequent_requests(anon_client, monkeypatch):
    monkeypatch.setenv("EARLY_ACCESS_PASSWORD", "geheim123")

    unlock_response = anon_client.post("/api/early-access", json={"password": "geheim123"})
    assert unlock_response.status_code == 204

    # Dieselbe TestClient-Instanz behält das gesetzte Cookie über den
    # nächsten Request hinweg bei - genau das Verhalten eines echten Browsers.
    response = anon_client.get("/")
    assert response.status_code == 200
    assert 'id="early-access-form"' not in response.text


def test_early_access_rate_limits_repeated_wrong_attempts(anon_client, monkeypatch):
    monkeypatch.setenv("EARLY_ACCESS_PASSWORD", "geheim123")

    for _ in range(5):
        response = anon_client.post("/api/early-access", json={"password": "falsch"})
        assert response.status_code == 401

    response = anon_client.post("/api/early-access", json={"password": "falsch"})

    assert response.status_code == 429


def test_early_access_exempts_magic_link_verification(anon_client, monkeypatch):
    """Regression-Schutz (2026-08-02): ohne diese Ausnahme fing die Early-
    Access-Sperre auch /api/auth/verify ab, BEVOR der Token geprueft wurde -
    wer noch kein Early-Access-Cookie hatte (praktisch jeder erste Klick auf
    einen frisch verschickten Login-/Einladungslink) bekam statt der echten
    Anmeldung die Passwort-Gate-Seite gezeigt, waehrend die URL weiterhin den
    Auth-Token als Query-Parameter enthielt - ein Muster, das Chromes
    Safe-Browsing-Heuristik als Phishing eingestuft hat."""
    users.invite_user("neu@example.org", users.QUELLEN_PFLEGER, invited_by="test-bootstrap")
    token = auth.create_magic_link_token("neu@example.org", auth.LOGIN_LINK_MAX_AGE_SECONDS)
    monkeypatch.setenv("EARLY_ACCESS_PASSWORD", "geheim123")

    response = anon_client.get(f"/api/auth/verify?token={token}", follow_redirects=False)

    assert response.status_code == 307
    assert auth.SESSION_COOKIE_NAME in anon_client.cookies


def test_add_source_creates_chunks(client):
    response = client.post(
        "/api/sources",
        json={
            "title": "Testquelle",
            "authors": ["Autor X"],
            "date": "2024-01-01",
            "url": "https://example.org",
            "text": "Ein kurzer Beispieltext für den Test.",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Testquelle"
    assert data["chunk_count"] == 1


def test_add_source_rejects_empty_text(client):
    response = client.post("/api/sources", json={"title": "Leer", "text": "   "})
    assert response.status_code == 400


# Backlog (2026-08-03): serverseitiger Duplikat-Schutz - das Frontend prüft
# schon vor dem Absenden gegen den zuletzt geladenen Quellenstand, aber nur
# ein Backend-Check schützt auch vor gleichzeitigen Imports oder direkten
# API-Aufrufen ohne UI.


def test_add_source_rejects_duplicate_url(client):
    first = client.post(
        "/api/sources",
        json={"title": "Original", "url": "https://example.org/artikel", "text": "Erster Text."},
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/api/sources",
        json={"title": "Duplikat", "url": "https://example.org/artikel", "text": "Zweiter Text."},
    )
    assert duplicate.status_code == 400
    assert "Original" in duplicate.json()["detail"]


def test_add_source_rejects_duplicate_url_ignoring_trailing_slash_and_case(client):
    first = client.post(
        "/api/sources",
        json={"title": "Original", "url": "https://Example.org/Artikel/", "text": "Erster Text."},
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/api/sources",
        json={"title": "Duplikat", "url": "https://example.org/artikel", "text": "Zweiter Text."},
    )
    assert duplicate.status_code == 400


def test_add_source_rejects_duplicate_youtube_url_in_different_formats(client):
    first = client.post(
        "/api/sources",
        json={
            "title": "Original",
            "url": "https://www.youtube.com/watch?v=abc123XYZ_",
            "text": "Erster Text.",
        },
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/api/sources",
        json={"title": "Duplikat", "url": "https://youtu.be/abc123XYZ_", "text": "Zweiter Text."},
    )
    assert duplicate.status_code == 400


def test_add_source_rejects_duplicate_url_ignoring_tracking_params(client):
    first = client.post(
        "/api/sources",
        json={"title": "Original", "url": "https://example.org/artikel-3", "text": "Erster Text."},
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/api/sources",
        json={
            "title": "Duplikat",
            "url": "https://example.org/artikel-3?utm_source=twitter&utm_medium=social&fbclid=abc123",
            "text": "Zweiter Text.",
        },
    )
    assert duplicate.status_code == 400


def test_add_source_strips_tracking_params_from_stored_url(client):
    response = client.post(
        "/api/sources",
        json={
            "title": "Quelle mit Tracking-Anhang",
            "url": "https://example.org/artikel-4?utm_source=newsletter&gclid=xyz789",
            "text": "Text.",
        },
    )
    assert response.status_code == 200
    assert response.json()["url"] == "https://example.org/artikel-4"


def test_add_source_allows_same_url_after_original_was_deleted(client):
    first = client.post(
        "/api/sources",
        json={"title": "Original", "url": "https://example.org/artikel-2", "text": "Erster Text."},
    )
    assert first.status_code == 200
    source_id = first.json()["id"]

    delete_response = client.delete(f"/api/sources/{source_id}")
    assert delete_response.status_code == 204

    recreated = client.post(
        "/api/sources",
        json={"title": "Neu", "url": "https://example.org/artikel-2", "text": "Neuer Text."},
    )
    assert recreated.status_code == 200


def test_add_source_returns_pending_when_embedding_is_slow(client, monkeypatch):
    # Fix: sehr große Dateien (viele Chunks -> langes lokales Embedding)
    # blockierten bisher den kompletten Request. Timeout künstlich sehr klein
    # setzen und embed_passages künstlich verzögern, um den "Datei zu groß"-
    # Fall ohne echtes Warten zu simulieren.
    monkeypatch.setattr(main_module, "SLOW_IMPORT_TIMEOUT_SECONDS", 0.05)

    def slow_embed(chunks):
        time.sleep(0.3)
        return [[0.0, 0.0, 0.0] for _ in chunks]

    monkeypatch.setattr(embeddings, "embed_passages", slow_embed)

    response = client.post(
        "/api/sources", json={"title": "Große Quelle", "text": "Ein langer Beispieltext."}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["processing_status"] == "pending"
    assert data["text"] == ""
    assert data["chunk_count"] == 0

    def entry():
        return next(s for s in client.get("/api/sources").json() if s["id"] == data["id"])

    wait_until(lambda: entry()["processing_status"] is None)
    result = entry()
    assert result["chunk_count"] > 0
    assert result["text"] == "Ein langer Beispieltext."


def test_add_source_slow_import_still_generates_summary(client, monkeypatch):
    monkeypatch.setattr(main_module, "SLOW_IMPORT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        embeddings,
        "embed_passages",
        lambda chunks: (time.sleep(0.3), [[0.0, 0.0, 0.0] for _ in chunks])[1],
    )
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "Zusammenfassung nach langsamem Import.", "key_terms": ["X"]},
            "en": {"summary": "Summary after slow import.", "key_terms": ["X"]},
        },
    )

    response = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = response.json()["id"]

    def entry():
        return next(s for s in client.get("/api/sources").json() if s["id"] == source_id)

    wait_until(lambda: entry()["summary"] == "Zusammenfassung nach langsamem Import.")


def test_add_source_marks_error_when_slow_embedding_fails(client, monkeypatch):
    monkeypatch.setattr(main_module, "SLOW_IMPORT_TIMEOUT_SECONDS", 0.05)

    def slow_failing_embed(chunks):
        time.sleep(0.3)
        raise RuntimeError("boom")

    monkeypatch.setattr(embeddings, "embed_passages", slow_failing_embed)

    response = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = response.json()["id"]
    assert response.json()["processing_status"] == "pending"

    def entry():
        return next(s for s in client.get("/api/sources").json() if s["id"] == source_id)

    wait_until(lambda: entry()["processing_status"] == "error")
    assert entry()["processing_error"]


def test_add_source_slow_import_appears_in_import_jobs(client, monkeypatch):
    monkeypatch.setattr(main_module, "SLOW_IMPORT_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        embeddings,
        "embed_passages",
        lambda chunks: (time.sleep(1), [[0.0, 0.0, 0.0] for _ in chunks])[1],
    )

    response = client.post("/api/sources", json={"title": "Große Quelle", "text": "Text."})
    source_id = response.json()["id"]

    jobs = client.get("/api/import-jobs").json()
    assert source_id in {job["id"] for job in jobs}
    time.sleep(1.2)


def test_add_source_fast_embedding_failure_still_raises_immediately(client, monkeypatch):
    # Läuft die Einbettung SCHNELL, aber fehlerhaft, soll add_source weiterhin
    # sofort mit einem Fehler antworten statt ihn stillschweigend in die
    # Warteschlange zu schieben (nur echte Zeitüberschreitung führt zum
    # asynchronen Pfad, siehe test_add_source_marks_error_when_slow_embedding_fails).
    monkeypatch.setattr(
        embeddings, "embed_passages", lambda chunks: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    with pytest.raises(RuntimeError):
        client.post("/api/sources", json={"title": "Quelle", "text": "Text."})


def test_concurrent_add_source_calls_do_not_lose_data(client):
    # Regressionstest für ein reales Datenverlust-Vorkommnis (2026-07-28):
    # sources.json fiel von 127 auf 3 Quellen, nachdem mehrere gleichzeitige
    # Hintergrund-Threads (siehe _create_pending_source/_finish_synchronous_import)
    # ohne Synchronisierung read-modify-write auf dieselbe Datei ausgeführt
    # hatten - der jeweils zuletzt schreibende Thread überschrieb die
    # Änderungen der anderen (Lost Update), zusätzlich verschärft durch einen
    # gemeinsam genutzten Temp-Dateinamen in _save_sources() (siehe dort).
    # Legt hier absichtlich viele Quellen ECHT PARALLEL an (ThreadPoolExecutor,
    # kein Mock) und prüft, dass am Ende wirklich ALLE angekommen sind.
    count = 20

    def create_one(i):
        return client.post("/api/sources", json={"title": f"Quelle {i}", "text": f"Text der Quelle {i}."})

    with concurrent.futures.ThreadPoolExecutor(max_workers=count) as executor:
        responses = list(executor.map(create_one, range(count)))

    assert all(r.status_code == 200 for r in responses)
    titles = {s["title"] for s in client.get("/api/sources").json()}
    expected_titles = {f"Quelle {i}" for i in range(count)}
    assert expected_titles <= titles


def _create_deferred_audio_source(
    client, monkeypatch, title="Podcast-Folge", url="https://cdn.example.org/episode.mp3", authors=None
):
    """Legt eine Audio-URL-Quelle mit leerem Text an, OHNE dass der
    eingeplante Hintergrund-Job dabei wirklich läuft. Wichtig: seit Backlog
    #113 landet der Job nicht mehr über BackgroundTasks (die der TestClient
    synchron VOR der Rückkehr von client.post() ausführen würde), sondern in
    main_module._audio_transcription_queue, die ein einziger, dauerhaft
    laufender Worker-Thread abarbeitet - ohne den .join() unten könnte der
    Worker den Eintrag ERST NACH dem Zurücksetzen des No-Op-Stubs abholen und
    dabei einen echten, unbeabsichtigten Aufruf von extraction.transcribe_audio
    auslösen."""
    monkeypatch.setattr(extraction, "looks_like_audio", lambda u: True)
    monkeypatch.setattr(extraction, "download_audio_bytes", lambda u: b"fake-mp3-bytes")

    # Nur WÄHREND dieses einen Requests (inkl. des anschließenden .join())
    # stubben, danach sofort wieder auf die echte Funktion zurücksetzen -
    # sonst würde auch ein späterer Reprocess-Aufruf im selben Test lautlos
    # den No-Op statt der echten Verarbeitung einplanen.
    real_process = main_module._process_audio_transcription
    monkeypatch.setattr(main_module, "_process_audio_transcription", lambda *a, **kw: None)
    response = client.post(
        "/api/sources", json={"title": title, "text": "", "url": url, "authors": authors or []}
    )
    main_module._audio_transcription_queue.join()
    monkeypatch.setattr(main_module, "_process_audio_transcription", real_process)
    return response


def test_add_source_defers_audio_url_with_missing_text(client, monkeypatch):
    response = _create_deferred_audio_source(client, monkeypatch)

    assert response.status_code == 200
    data = response.json()
    assert data["text"] == ""
    assert data["chunk_count"] == 0
    assert data["processing_status"] == "pending"


def test_process_audio_transcription_fills_text_and_indexes(client, monkeypatch):
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("Nachträglich transkribierter Text.", None))
    main_module._process_audio_transcription(source_id)

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["text"] == "Nachträglich transkribierter Text."
    assert entry["chunk_count"] > 0
    assert entry["processing_status"] is None

    answer = client.post("/api/ask", json={"question": "Was steht in der Folge?"})
    assert answer.status_code == 200


def test_process_audio_transcription_passes_known_authors_as_transcription_prompt(client, monkeypatch):
    """Regressionstest (Nutzerfeedback 2026-08-23): die für die Quelle
    bereits eingetragenen Autor:innen sollen als Vokabular-Hinweis an die
    Transkription weitergereicht werden, damit deren Namen mit größerer
    Wahrscheinlichkeit richtig geschrieben erkannt werden."""
    monkeypatch.setattr(transcription_hints, "get_hints", lambda lang: ["Beta-Kodex"])
    create_res = _create_deferred_audio_source(client, monkeypatch, authors=["Niels Pflaeging", "Silke Hermann"])
    source_id = create_res.json()["id"]
    calls = []
    monkeypatch.setattr(
        extraction, "transcribe_audio", lambda path, **kw: calls.append(kw.get("known_names")) or ("Text.", None)
    )

    main_module._process_audio_transcription(source_id)

    assert calls == [["Niels Pflaeging", "Silke Hermann", "Beta-Kodex"]]


def test_process_audio_transcription_adds_english_vocabulary_hint_for_english_lang(client, monkeypatch):
    """Nutzerwunsch (2026-08-24): feste Begriffe des BetaCodex-Vokabulars
    (Schreibweise je nach Sprache unterschiedlich, siehe app/
    transcription_hints.json) sollen zusätzlich zu den Autor:innen-Namen als
    Vokabular-Hinweis mitgegeben werden."""
    monkeypatch.setattr(transcription_hints, "get_hints", lambda lang: {"en": ["BetaCodex"]}.get(lang, []))
    create_res = _create_deferred_audio_source(client, monkeypatch, authors=["Niels Pflaeging"])
    source_id = create_res.json()["id"]
    calls = []
    monkeypatch.setattr(
        extraction, "transcribe_audio", lambda path, **kw: calls.append(kw.get("known_names")) or ("Text.", None)
    )

    main_module._process_audio_transcription(source_id, lang="en")

    assert calls == [["Niels Pflaeging", "BetaCodex"]]


def test_process_audio_transcription_adds_vocabulary_hint_without_authors(client, monkeypatch):
    monkeypatch.setattr(transcription_hints, "get_hints", lambda lang: ["Beta-Kodex"])
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]
    calls = []
    monkeypatch.setattr(
        extraction, "transcribe_audio", lambda path, **kw: calls.append(kw.get("known_names")) or ("Text.", None)
    )

    main_module._process_audio_transcription(source_id)

    assert calls == [["Beta-Kodex"]]


def test_process_audio_transcription_deduplicates_names_in_transcription_prompt(client, monkeypatch):
    """Wenn eine Autorin/ein Autor sowohl für diese Quelle eingetragen als
    auch bereits in transcription_hints.json gelistet ist, soll der Name
    nicht doppelt im Prompt landen."""
    monkeypatch.setattr(transcription_hints, "get_hints", lambda lang: ["Niels Pflaeging", "Beta-Kodex"])
    create_res = _create_deferred_audio_source(client, monkeypatch, authors=["Niels Pflaeging"])
    source_id = create_res.json()["id"]
    calls = []
    monkeypatch.setattr(
        extraction, "transcribe_audio", lambda path, **kw: calls.append(kw.get("known_names")) or ("Text.", None)
    )

    main_module._process_audio_transcription(source_id)

    assert calls == [["Niels Pflaeging", "Beta-Kodex"]]


def test_process_audio_transcription_triggers_summary_generation(client, monkeypatch):
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("Nachträglich transkribierter Text.", None))
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "Zusammenfassung nach Transkription.", "key_terms": ["Podcast"]},
            "en": {"summary": "Summary after transcription.", "key_terms": ["Podcast"]},
        },
    )
    main_module._process_audio_transcription(source_id)

    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["summary"] == "Zusammenfassung nach Transkription."


def test_process_audio_transcription_marks_error_when_transcription_fails(client, monkeypatch):
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("", "Abschnitt 1/1: RuntimeError: boom"))
    main_module._process_audio_transcription(source_id)

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["processing_status"] == "error"
    assert "Abschnitt 1/1" in entry["processing_error"]


def test_process_audio_transcription_keeps_successful_segments_for_next_attempt(client, monkeypatch):
    # Kostenschutz (2026-07-29): scheitert die Transkription, müssen bereits
    # erfolgreiche Abschnitte (processing_segments) erhalten bleiben, damit
    # ein erneuter Versuch sie nicht nochmal bezahlt.
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    def fake_transcribe(path, known_segments=None, on_segment_success=None, known_names=None):
        on_segment_success(0, 2, "Abschnitt 1 (erfolgreich)")
        return "", "Abschnitt 2/2: RateLimitError: zu viele Anfragen"

    monkeypatch.setattr(extraction, "transcribe_audio", fake_transcribe)
    main_module._process_audio_transcription(source_id)

    raw = main_module._load_sources()[source_id]
    assert raw["processing_status"] == "error"
    assert raw["processing_segments"] == {"0": "Abschnitt 1 (erfolgreich)"}

    def fake_transcribe_retry(path, known_segments=None, on_segment_success=None, known_names=None):
        assert known_segments == {0: "Abschnitt 1 (erfolgreich)"}
        return "--- Teil 1 ---\n\nAbschnitt 1 (erfolgreich)\n\n--- Teil 2 ---\n\nAbschnitt 2 (jetzt auch)", None

    monkeypatch.setattr(extraction, "transcribe_audio", fake_transcribe_retry)
    main_module._process_audio_transcription(source_id)

    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["processing_status"] is None
    assert "Abschnitt 2 (jetzt auch)" in entry["text"]


def test_import_jobs_lists_pending_and_error_but_not_done(client, monkeypatch):
    pending_res = _create_deferred_audio_source(
        client, monkeypatch, title="Läuft noch", url="https://cdn.example.org/a.mp3"
    )
    pending_id = pending_res.json()["id"]

    done_res = _create_deferred_audio_source(
        client, monkeypatch, title="Fertig", url="https://cdn.example.org/b.mp3"
    )
    done_id = done_res.json()["id"]
    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("Text.", None))
    main_module._process_audio_transcription(done_id)

    jobs = client.get("/api/import-jobs").json()
    job_ids = {job["id"] for job in jobs}
    assert pending_id in job_ids
    assert done_id not in job_ids


def test_import_jobs_excludes_soft_deleted_sources(client, monkeypatch):
    """Regressionstest (Bug 2026-08-23, per Nutzerfeedback): delete_source()
    setzt beim weichen Löschen nur deleted_at, lässt einen zuvor
    fehlgeschlagenen processing_status aber unverändert stehen - eine
    gelöschte, fehlgeschlagene Quelle blieb dadurch für immer in der
    Fehler-Warteschlange/dem Jobs-Badge sichtbar."""
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]
    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("", "boom"))
    main_module._process_audio_transcription(source_id)
    assert source_id in {job["id"] for job in client.get("/api/import-jobs").json()}

    client.delete(f"/api/sources/{source_id}")

    assert source_id not in {job["id"] for job in client.get("/api/import-jobs").json()}


def test_reprocess_source_retries_and_can_then_succeed(client, monkeypatch):
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("", "Abschnitt 1/1: RuntimeError: boom"))
    main_module._process_audio_transcription(source_id)
    assert client.get("/api/sources").json()[0]["processing_status"] == "error"

    # Reprocess reiht den Job in _audio_transcription_queue ein (Backlog
    # #113) statt ihn über BackgroundTasks synchron mitlaufen zu lassen -
    # VORHER auf ein erfolgreiches Transkript umstellen und danach per
    # .join() auf den Worker-Thread warten, um den vollen Erfolgspfad
    # deterministisch zu prüfen.
    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("Beim zweiten Versuch erfolgreich.", None))
    response = client.post(f"/api/sources/{source_id}/reprocess")
    assert response.status_code == 200
    main_module._audio_transcription_queue.join()

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["processing_status"] is None
    assert entry["processing_error"] is None
    assert entry["text"] == "Beim zweiten Versuch erfolgreich."


def test_audio_transcriptions_are_processed_with_bounded_concurrency(client, monkeypatch):
    """Backlog #113 (Nachtrag): mehrere gleichzeitig importierte Audios
    dürfen zwar parallel transkribiert werden (Gesamtkosten ändern sich
    dadurch nicht, siehe Kommentar bei _audio_transcription_queue), aber NIE
    mehr als AUDIO_TRANSCRIPTION_WORKER_COUNT gleichzeitig - der reale
    Vorfall am 2026-07-28 (23 parallel gestartete Transkriptionen, Budget
    aufgebraucht bevor auch nur eine Datei fertig war) darf sich nicht in
    abgeschwächter Form wiederholen."""
    monkeypatch.setattr(extraction, "looks_like_audio", lambda u: True)
    monkeypatch.setattr(extraction, "download_audio_bytes", lambda u: b"fake-mp3-bytes")

    active = []
    max_concurrent = []
    lock = threading.Lock()

    def fake_transcribe(path, **kw):
        with lock:
            active.append(1)
            max_concurrent.append(len(active))
        time.sleep(0.05)
        with lock:
            active.pop()
        return "Transkribierter Text.", None

    monkeypatch.setattr(extraction, "transcribe_audio", fake_transcribe)

    source_ids = [
        client.post(
            "/api/sources",
            json={"title": f"Folge {i}", "text": "", "url": f"https://cdn.example.org/{i}.mp3"},
        ).json()["id"]
        for i in range(8)
    ]
    main_module._audio_transcription_queue.join()

    assert max(max_concurrent) <= main_module.AUDIO_TRANSCRIPTION_WORKER_COUNT
    for source_id in source_ids:
        entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
        assert entry["text"] == "Transkribierter Text."
        assert entry["processing_status"] is None


def test_recover_interrupted_processing_jobs_marks_running_as_error(client):
    source_id = client.post("/api/sources", json={"title": "Quelle", "text": "Text."}).json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["processing_status"] = "running"
    sources[source_id]["processing_step"] = "transcribe"
    main_module._save_sources(sources)

    main_module._recover_interrupted_processing_jobs()

    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["processing_status"] == "error"
    assert entry["processing_error"]


def test_recover_interrupted_processing_jobs_requeues_pending_audio(client, monkeypatch):
    """Backlog #113 (Ergänzung): die In-Memory-Warteschlange überlebt einen
    Serverneustart nicht - eine noch nicht begonnene ("pending") Audio-
    Transkription muss beim (hier simulierten) Neustart automatisch neu
    eingereiht werden, statt für immer unbemerkt auf "pending" stehen zu
    bleiben."""
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]
    assert client.get("/api/sources").json()[0]["processing_status"] == "pending"

    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("Nach Neustart erfolgreich transkribiert.", None))
    main_module._recover_interrupted_processing_jobs()
    main_module._audio_transcription_queue.join()

    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["text"] == "Nach Neustart erfolgreich transkribiert."
    assert entry["processing_status"] is None


def test_recover_interrupted_processing_jobs_ignores_pending_pdf(client, monkeypatch):
    """Abgrenzung zum Audio-Fall oben: eine pending PDF-Quelle wird NICHT
    automatisch neu eingereiht (Backlog #113 betrifft ausschließlich Audio-
    Transkriptionen, siehe Kommentar bei _audio_transcription_queue)."""
    create_res = _create_deferred_pdf_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    main_module._recover_interrupted_processing_jobs()

    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["processing_status"] == "pending"


def test_recover_interrupted_processing_jobs_resumes_audio_interrupted_by_deploy(client, monkeypatch):
    """Nutzerwunsch (2026-08-03): eine Audio-Transkription, die der
    Shutdown-Hook als "interrupted_by_deploy" markiert hat (Wartezeit
    reichte nicht), muss automatisch neu eingereiht werden statt in einem
    dauerhaften Fehlerzustand zu landen."""
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["processing_status"] = "running"
    sources[source_id]["interrupted_by_deploy"] = True
    main_module._save_sources(sources)

    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("Nach Deploy erfolgreich transkribiert.", None))
    main_module._recover_interrupted_processing_jobs()
    main_module._audio_transcription_queue.join()

    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["text"] == "Nach Deploy erfolgreich transkribiert."
    assert entry["processing_status"] is None


def test_recover_interrupted_processing_jobs_resumes_pdf_interrupted_by_deploy(client, monkeypatch):
    create_res = _create_deferred_pdf_source(client, monkeypatch)
    source_id = create_res.json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["processing_status"] = "running"
    sources[source_id]["interrupted_by_deploy"] = True
    main_module._save_sources(sources)

    monkeypatch.setattr(extraction, "ocr_pdf_with_ai", lambda data: "Nach Deploy erkannter Text.")
    main_module._recover_interrupted_processing_jobs()

    entry = None
    for _ in range(20):
        entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
        if entry["processing_status"] is None:
            break
        time.sleep(0.1)
    assert entry["text"] == "Nach Deploy erkannter Text."


def test_recover_interrupted_processing_jobs_still_errors_running_audio_without_deploy_flag(client, monkeypatch):
    """Abgrenzung: eine vorhandene Audiodatei allein reicht nicht fuers
    Auto-Resume - fehlt das interrupted_by_deploy-Merkmal (z.B. echter
    Absturz statt Deploy), bleibt es beim bisherigen manuellen
    Fehler-Verhalten."""
    create_res = _create_deferred_audio_source(client, monkeypatch)
    source_id = create_res.json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["processing_status"] = "running"
    main_module._save_sources(sources)

    main_module._recover_interrupted_processing_jobs()

    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["processing_status"] == "error"
    assert entry["processing_error"]


def test_reprocess_source_without_audio_file_returns_400(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    response = client.post(f"/api/sources/{source_id}/reprocess")
    assert response.status_code == 400


def _create_deferred_pdf_source(client, monkeypatch, title="Gescanntes PDF", url="https://cdn.example.org/scan.pdf"):
    """Legt eine PDF-URL-Quelle mit leerem Text an (gescannte PDF ohne
    Text-Ebene, siehe extraction.extract_pdf), OHNE dass der eingeplante
    Hintergrund-Job dabei wirklich läuft - gleiches Muster wie
    _create_deferred_audio_source."""
    monkeypatch.setattr(extraction, "looks_like_audio", lambda u: False)
    monkeypatch.setattr(extraction, "looks_like_pdf", lambda u: True)
    monkeypatch.setattr(extraction, "download_pdf_bytes", lambda u: b"fake-pdf-bytes")

    real_process = main_module._process_pdf_ocr
    monkeypatch.setattr(main_module, "_process_pdf_ocr", lambda *a, **kw: None)
    response = client.post("/api/sources", json={"title": title, "text": "", "url": url})
    monkeypatch.setattr(main_module, "_process_pdf_ocr", real_process)
    return response


def test_add_source_defers_scanned_pdf_url_with_missing_text(client, monkeypatch):
    response = _create_deferred_pdf_source(client, monkeypatch)

    assert response.status_code == 200
    data = response.json()
    assert data["text"] == ""
    assert data["chunk_count"] == 0
    assert data["processing_status"] == "pending"


def test_process_pdf_ocr_fills_text_and_indexes(client, monkeypatch):
    create_res = _create_deferred_pdf_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    monkeypatch.setattr(extraction, "ocr_pdf_with_ai", lambda data: "Per KI erkannter Seitentext.")
    main_module._process_pdf_ocr(source_id)

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["text"] == "Per KI erkannter Seitentext."
    assert entry["chunk_count"] > 0
    assert entry["processing_status"] is None

    answer = client.post("/api/ask", json={"question": "Was steht im Scan?"})
    assert answer.status_code == 200


def test_process_pdf_ocr_triggers_summary_generation(client, monkeypatch):
    # Fix: die Zusammenfassung wurde bisher nur bei normalem Text-Import und
    # nach Audio-Transkription automatisch angestoßen, nicht nach PDF-OCR -
    # beide Hintergrund-Jobs laufen über denselben _run_deferred_text_extraction-
    # Ablauf, der _generate_summary_background am Ende aufruft.
    create_res = _create_deferred_pdf_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    monkeypatch.setattr(extraction, "ocr_pdf_with_ai", lambda data: "Per KI erkannter Seitentext.")
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "Zusammenfassung nach Texterkennung.", "key_terms": ["Scan"]},
            "en": {"summary": "Summary after text recognition.", "key_terms": ["Scan"]},
        },
    )
    main_module._process_pdf_ocr(source_id)

    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["summary"] == "Zusammenfassung nach Texterkennung."


def test_process_pdf_ocr_marks_error_when_ocr_fails(client, monkeypatch):
    create_res = _create_deferred_pdf_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    monkeypatch.setattr(extraction, "ocr_pdf_with_ai", lambda data: "")
    main_module._process_pdf_ocr(source_id)

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["processing_status"] == "error"
    assert entry["processing_error"]


def test_reprocess_source_picks_pdf_job_when_no_audio_file(client, monkeypatch):
    create_res = _create_deferred_pdf_source(client, monkeypatch)
    source_id = create_res.json()["id"]

    monkeypatch.setattr(extraction, "ocr_pdf_with_ai", lambda data: "")
    main_module._process_pdf_ocr(source_id)
    assert client.get("/api/sources").json()[0]["processing_status"] == "error"

    monkeypatch.setattr(extraction, "ocr_pdf_with_ai", lambda data: "Beim zweiten Versuch erfolgreich.")
    response = client.post(f"/api/sources/{source_id}/reprocess")
    assert response.status_code == 200

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["processing_status"] is None
    assert entry["processing_error"] is None
    assert entry["text"] == "Beim zweiten Versuch erfolgreich."


def test_list_sources_returns_imported_sources(client):
    client.post("/api/sources", json={"title": "Quelle A", "text": "Text A"})
    response = client.get("/api/sources")
    assert response.status_code == 200
    titles = [s["title"] for s in response.json()]
    assert "Quelle A" in titles


def test_ask_without_sources_returns_400(client):
    response = client.post("/api/ask", json={"question": "Was ist der BetaCodex?"})
    assert response.status_code == 400


def test_speech_returns_audio_without_login(anon_client, monkeypatch):
    monkeypatch.setattr(
        tts, "synthesize_speech", lambda text, lang="de", speaking_rate=1.0: b"fake-mp3-bytes"
    )

    response = anon_client.post("/api/speech", json={"text": "Hallo Welt"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"fake-mp3-bytes"


def test_speech_passes_current_language_to_synthesize(anon_client, monkeypatch):
    captured = {}

    def fake_synthesize(text, lang="de", speaking_rate=1.0):
        captured["text"] = text
        captured["lang"] = lang
        captured["speaking_rate"] = speaking_rate
        return b"audio"

    monkeypatch.setattr(tts, "synthesize_speech", fake_synthesize)

    response = anon_client.post(
        "/api/speech", json={"text": "Hello"}, headers={"X-Lang": "en"}
    )

    assert response.status_code == 200
    assert captured == {"text": "Hello", "lang": "en", "speaking_rate": 1.0}


def test_speech_passes_requested_rate_to_synthesize(anon_client, monkeypatch):
    # Regression-Test (2026-07-31): das Vorlesetempo muss an Google TTS selbst
    # weitergereicht werden (Synthese in Zielgeschwindigkeit), statt es erst
    # nachträglich im Client zu resampeln oder per <audio>-Element-Wechsel
    # abzuspielen - beides verursachte eigene Nebenwirkungen (Tonhöhen-
    # verzerrung bzw. Knacken zwischen Sätzen, siehe Git-Historie).
    captured = {}

    def fake_synthesize(text, lang="de", speaking_rate=1.0):
        captured["speaking_rate"] = speaking_rate
        return b"audio"

    monkeypatch.setattr(tts, "synthesize_speech", fake_synthesize)

    response = anon_client.post("/api/speech", json={"text": "Hallo", "rate": 1.75})

    assert response.status_code == 200
    assert captured["speaking_rate"] == 1.75


def test_speech_rejects_empty_text(anon_client):
    response = anon_client.post("/api/speech", json={"text": "   "})
    assert response.status_code == 400


def test_speech_returns_502_when_synthesis_fails(anon_client, monkeypatch):
    def raise_error(text, lang="de", speaking_rate=1.0):
        raise tts.SpeechSynthesisError("boom")

    monkeypatch.setattr(tts, "synthesize_speech", raise_error)

    response = anon_client.post("/api/speech", json={"text": "Hallo"})

    assert response.status_code == 502


def test_ask_rejects_when_captcha_verification_fails(client, monkeypatch):
    client.post("/api/sources", json={"title": "Quelle", "text": "Ein Text."})
    monkeypatch.setattr(captcha, "verify_turnstile_token", lambda token, remote_ip=None: False)

    response = client.post("/api/ask", json={"question": "Frage?"})

    assert response.status_code == 400


def test_ask_rejects_after_rate_limit_exceeded(client):
    client.post("/api/sources", json={"title": "Quelle", "text": "Ein Text."})

    for _ in range(ratelimit.MAX_REQUESTS):
        response = client.post("/api/ask", json={"question": "Frage?"})
        assert response.status_code == 200

    response = client.post("/api/ask", json={"question": "Frage?"})

    assert response.status_code == 429


# --- Kreativ-Modus (2026-08-26) ---


def test_creative_rejects_when_captcha_verification_fails(client, monkeypatch):
    monkeypatch.setattr(captcha, "verify_turnstile_token", lambda token, remote_ip=None: False)

    response = client.post("/api/creative", json={"document": "", "instruction": "Schreibe etwas."})

    assert response.status_code == 400


def test_creative_rejects_after_rate_limit_exceeded(client):
    for _ in range(main_module.CREATIVE_RATE_LIMIT_MAX_REQUESTS):
        response = client.post("/api/creative", json={"document": "", "instruction": "Schreibe etwas."})
        assert response.status_code == 200

    response = client.post("/api/creative", json={"document": "", "instruction": "Schreibe etwas."})

    assert response.status_code == 429


def test_creative_rejects_empty_instruction(client):
    response = client.post("/api/creative", json={"document": "", "instruction": "   "})
    assert response.status_code == 400


def test_creative_rejects_instruction_over_length_limit(client):
    too_long = "x" * (main_module.CREATIVE_MAX_INSTRUCTION_CHARS + 1)
    response = client.post("/api/creative", json={"document": "", "instruction": too_long})
    assert response.status_code == 400


def test_creative_rejects_document_over_length_limit(client):
    too_long = "x" * (main_module.CREATIVE_MAX_DOCUMENT_CHARS + 1)
    response = client.post("/api/creative", json={"document": too_long, "instruction": "Kürze das."})
    assert response.status_code == 400


def test_creative_works_without_any_curated_sources(client):
    """Bewusste Abweichung von /api/ask: der Kreativ-Modus soll auch ohne
    kuratierte Quellen funktionieren (z.B. reine Workshop-Methodik, gestützt
    auf Websuche/allgemeines Wissen statt der kuratierten Sammlung)."""
    response = client.post(
        "/api/creative", json={"document": "", "instruction": "Schlage drei Icebreaker vor."}
    )
    assert response.status_code == 200


def test_creative_streams_delta_and_document_events_without_leaking_sources_marker(client, monkeypatch):
    raw = "Erster Teil. ---SOURCES---\n[Web]: Titel — https://example.org/a\n"
    monkeypatch.setattr(
        llm, "stream_creative_response", lambda *a, **k: _FakeCreativeStream(list(raw))
    )

    response = client.post("/api/creative", json={"document": "", "instruction": "Schreibe etwas."})

    result = creative_result(response)
    assert result["document"] == "Erster Teil."
    assert "---SOURCES---" not in result["streamed_text"]
    assert all("---SOURCES---" not in json.dumps(e) for e in result["events"])


def test_creative_uses_document_argument_correctly_for_first_draft_and_revision(client, monkeypatch):
    calls = []

    def fake_stream(instruction, document, chunks, lang="de", section=None):
        calls.append(document)
        return _FakeCreativeStream(["Text."])

    monkeypatch.setattr(llm, "stream_creative_response", fake_stream)

    client.post("/api/creative", json={"document": "", "instruction": "Erster Entwurf."})
    client.post("/api/creative", json={"document": "Bestehender Text.", "instruction": "Kürze das."})

    assert calls == ["", "Bestehender Text."]


def test_creative_passes_section_through_to_stream_creative_response(client, monkeypatch):
    # Nutzerwunsch (2026-08-30): abschnittsweises Überarbeiten - ist im
    # Request-Body ein section-Feld gesetzt, muss es unverändert bei
    # llm.stream_creative_response ankommen (dort entscheidet es über den
    # CREATIVE_SECTION_SYSTEM_PROMPTS-Pfad, siehe app/llm.py). Ohne section
    # bleibt es None (Rückwärtskompatibilität zum Ganzdokument-Pfad).
    calls = []

    def fake_stream(instruction, document, chunks, lang="de", section=None):
        calls.append(section)
        return _FakeCreativeStream(["Text."])

    monkeypatch.setattr(llm, "stream_creative_response", fake_stream)

    client.post(
        "/api/creative",
        json={
            "document": "# Erster Abschnitt\n\nAlter Text.\n\n# Zweiter Abschnitt\n\nWeiterer Text.",
            "instruction": "Kürze das.",
            "section": "# Erster Abschnitt\n\nAlter Text.\n\n",
        },
    )
    client.post("/api/creative", json={"document": "", "instruction": "Erster Entwurf."})

    assert calls == ["# Erster Abschnitt\n\nAlter Text.\n\n", None]


def test_creative_betacodex_sources_come_from_retrieved_curated_chunks(client, monkeypatch):
    client.post(
        "/api/sources",
        json={"title": "Zellstrukturdesign", "text": "Ein Text über Zentrumszellen.", "authors": ["Autor X"]},
    )
    monkeypatch.setattr(
        llm,
        "stream_creative_response",
        lambda instruction, document, chunks, lang="de", section=None: _FakeCreativeStream(
            ["Ein völlig anderer Text, der die Quelle gar nicht erwähnt."]
        ),
    )

    response = client.post(
        "/api/creative", json={"document": "", "instruction": "Schreibe über Zellstrukturdesign."}
    )

    result = creative_result(response)
    assert any(s["title"] == "Zellstrukturdesign" for s in result["sources"]["betacodex"])


def test_creative_betacodex_sources_deduplicate_multiple_chunks_of_same_source(client, monkeypatch):
    # Lang genug (CHUNK_SIZE = 900 Tokens, siehe app/chunking.py), damit der
    # Import in mehrere Chunks zerlegt wird - bei CREATIVE_TOP_K=6 landen bei
    # nur dieser einen Quelle im Store mehrere ihrer eigenen Chunks unter den
    # Top-Treffern, was die Quellenliste ohne Deduplizierung mehrfach
    # anzeigen würde (genau das vom Nutzer gemeldete Verhalten).
    long_text = "Zentrumszellen tragen Wertschöpfung im Zellstrukturdesign. " * 250
    client.post(
        "/api/sources",
        json={"title": "Zellstrukturdesign", "text": long_text, "authors": ["Autor X"]},
    )
    monkeypatch.setattr(
        llm,
        "stream_creative_response",
        lambda instruction, document, chunks, lang="de", section=None: _FakeCreativeStream(
            ["Text ohne Erwähnung der Quelle."]
        ),
    )

    response = client.post(
        "/api/creative",
        json={"document": "", "instruction": "Schreibe über Zentrumszellen und Zellstrukturdesign."},
    )

    result = creative_result(response)
    betacodex = result["sources"]["betacodex"]
    assert len(betacodex) >= 1
    assert sum(1 for s in betacodex if s["title"] == "Zellstrukturdesign") == 1


def test_creative_web_sources_are_filtered_to_real_search_results(client, monkeypatch):
    raw = (
        "Der Text.\n\n---SOURCES---\n"
        "[Web]: Erfunden — https://fake.example/nie-gefunden\n"
        "[Web]: Echt — https://real.example/gefunden\n"
    )
    monkeypatch.setattr(
        llm,
        "stream_creative_response",
        lambda instruction, document, chunks, lang="de", section=None: _FakeCreativeStream(
            [raw], real_web_urls={"https://real.example/gefunden"}
        ),
    )

    response = client.post("/api/creative", json={"document": "", "instruction": "Schreibe etwas."})

    result = creative_result(response)
    assert result["sources"]["web"] == [{"title": "Echt", "url": "https://real.example/gefunden"}]


# --- Konversations-Handoff (2026-08-30) ---
# Nutzerwunsch: "Vollständig öffnen"-Icon im Embed-Widget sowie der
# bestehende "Quelle ansehen/bearbeiten"-Link sollen eine laufende
# Konversation in einen neu geöffneten Tab mitnehmen können (sessionStorage
# ist pro Tab und zusätzlich pro Top-Level-Browsing-Context partitioniert,
# siehe app/conversation_handoff.py) - kurzlebiges, einmal abrufbares
# Server-Handoff statt dessen.

_HANDOFF_TURN = {
    "question": "Was ist der Beta-Kodex?",
    "answer": "Ein Betriebssystem für Organisationen.",
    "sources": [],
}


def test_conversation_handoff_get_returns_posted_history(client):
    post_response = client.post("/api/conversation-handoff", json={"history": [_HANDOFF_TURN]})
    assert post_response.status_code == 200
    token = post_response.json()["token"]

    get_response = client.get(f"/api/conversation-handoff/{token}")

    assert get_response.status_code == 200
    assert get_response.json()["history"][0]["question"] == _HANDOFF_TURN["question"]
    assert get_response.json()["history"][0]["answer"] == _HANDOFF_TURN["answer"]


def test_conversation_handoff_token_is_single_use(client):
    token = client.post("/api/conversation-handoff", json={"history": [_HANDOFF_TURN]}).json()["token"]

    client.get(f"/api/conversation-handoff/{token}")
    second_response = client.get(f"/api/conversation-handoff/{token}")

    assert second_response.status_code == 404


def test_conversation_handoff_rejects_unknown_token(client):
    response = client.get("/api/conversation-handoff/does-not-exist")
    assert response.status_code == 404


def test_conversation_handoff_rejects_empty_history(client):
    response = client.post("/api/conversation-handoff", json={"history": []})
    assert response.status_code == 400


def test_conversation_handoff_rejects_too_many_turns(client):
    too_many = [_HANDOFF_TURN] * (main_module.CONVERSATION_HANDOFF_MAX_TURNS + 1)
    response = client.post("/api/conversation-handoff", json={"history": too_many})
    assert response.status_code == 400


def test_conversation_handoff_rejects_after_rate_limit_exceeded(client):
    for _ in range(main_module.CONVERSATION_HANDOFF_RATE_LIMIT_MAX_REQUESTS):
        response = client.post("/api/conversation-handoff", json={"history": [_HANDOFF_TURN]})
        assert response.status_code == 200

    response = client.post("/api/conversation-handoff", json={"history": [_HANDOFF_TURN]})

    assert response.status_code == 429


def test_conversation_handoff_expires_after_ttl(client, monkeypatch):
    fake_now = [0.0]
    monkeypatch.setattr(conversation_handoff, "_now", lambda: fake_now[0])

    token = client.post("/api/conversation-handoff", json={"history": [_HANDOFF_TURN]}).json()["token"]
    fake_now[0] = conversation_handoff.TTL_SECONDS + 1

    response = client.get(f"/api/conversation-handoff/{token}")

    assert response.status_code == 404


# Backlog #97: anonymisiertes Log der ersten Frage einer Konversation. Wird
# bewusst VOR der RAG-Suche geloggt (siehe app/main.py ask()) - ein 400 wegen
# fehlender Quellen ist für diese Tests deshalb unerheblich, kein Setup mit
# echten Quellen/Embeddings nötig.


def test_ask_does_not_log_by_default_even_with_is_first_message(client):
    # Der client-Fixture setzt IS_DEV_ENVIRONMENT bewusst auf True (siehe
    # dortigen Kommentar) - deckt sich mit Dev/Stabil, wo NIE geloggt werden
    # soll. Das gilt implizit für ALLE anderen Tests in dieser Datei.
    client.post("/api/ask", json={"question": "Was ist der BetaCodex?", "is_first_message": True})

    assert question_log.list_entries() == []


def test_ask_logs_first_message_outside_dev_environment(client, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)

    client.post("/api/ask", json={"question": "Was ist der BetaCodex?", "is_first_message": True})

    entries = question_log.list_entries()
    assert len(entries) == 1
    assert entries[0]["text"] == "Was ist der BetaCodex?"
    assert entries[0]["timestamp"]


def test_ask_does_not_log_follow_up_messages(client, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)

    client.post("/api/ask", json={"question": "Folgefrage", "is_first_message": False})

    assert question_log.list_entries() == []


def test_ask_does_not_log_system_admins_own_questions(anon_client, monkeypatch):
    # Reihenfolge wichtig: login() setzt das Session-Cookie mit
    # secure=not IS_DEV_ENVIRONMENT - würde IS_DEV_ENVIRONMENT VORHER auf
    # False gepatcht, wäre es ein "Secure"-Cookie, das der TestClient über
    # das ungesicherte "http://testserver" nie zurückschickt (siehe Kommentar
    # beim client-Fixture) - der Admin bliebe dann scheinbar ausgeloggt.
    login(anon_client, "admin@test.local", users.SYSTEM_ADMIN)
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)

    anon_client.post("/api/ask", json={"question": "Testfrage des Admins", "is_first_message": True})

    assert question_log.list_entries() == []


def test_ask_still_logs_quellen_pfleger_questions(client, monkeypatch):
    # Abgrenzung zum Admin-Ausschluss: die eigene Nutzung von Quellen-
    # Pfleger:innen bleibt ein sinnvolles Signal (vom Nutzer explizit
    # bestätigt) - der client-Fixture ist bereits als PFLEGER eingeloggt.
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)

    client.post("/api/ask", json={"question": "Frage einer Pflegerin", "is_first_message": True})

    entries = question_log.list_entries()
    assert len(entries) == 1
    assert entries[0]["text"] == "Frage einer Pflegerin"


# Backlog #115: X-Robots-Tag darf die echte Produktivinstanz nicht an der
# Suchmaschinen-Indexierung hindern - nur Dev/Stabil (IS_DEV_ENVIRONMENT)
# sollen ihn setzen.


def test_x_robots_tag_present_in_dev_environment(client):
    # client-Fixture setzt IS_DEV_ENVIRONMENT bewusst auf True.
    response = client.get("/api/version")

    assert response.headers["x-robots-tag"] == "noindex, nofollow, noarchive"


def test_x_robots_tag_absent_outside_dev_environment(client, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)

    response = client.get("/api/version")

    assert "x-robots-tag" not in response.headers


def test_get_question_log_requires_pfleger_role(anon_client):
    response = anon_client.get("/api/question-log")
    assert response.status_code == 403


def test_get_question_log_returns_entries_for_pfleger(client, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)
    client.post("/api/ask", json={"question": "Frage einer Pflegerin", "is_first_message": True})

    response = client.get("/api/question-log")

    assert response.status_code == 200
    texts = [entry["text"] for entry in response.json()]
    assert "Frage einer Pflegerin" in texts


def test_question_log_entries_have_first_question_event_type(client, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)
    client.post("/api/ask", json={"question": "Frage einer Pflegerin", "is_first_message": True})

    entries = question_log.list_entries()

    assert entries[0]["event_type"] == "first_question"
    assert entries[0].get("answer") is None
    assert entries[0].get("feedback") is None


def test_question_log_normalizes_legacy_entries_without_event_type(client, monkeypatch):
    # Rückwärtskompatibilität: vor der Einführung mehrerer Ereignistypen
    # gespeicherte Einträge haben noch kein event_type-Feld.
    monkeypatch.setattr(
        question_log,
        "_load",
        lambda: [{"text": "Alte Frage", "timestamp": "2026-01-01T00:00:00+00:00"}],
    )

    entries = question_log.list_entries()

    assert entries[0]["event_type"] == "first_question"


def test_ask_logs_no_answer_event_when_model_says_it_cannot_answer(client, monkeypatch):
    # Nutzerwunsch (2026-09-01, realer Fall "Andreas Schlegel und
    # Zeitorientierung"): die Systemanweisung gibt dem Modell diesen Satz
    # WÖRTLICH vor (siehe app/llm.py SYSTEM_PROMPTS) - ein Substring-Check
    # auf genau diesen Satz reicht deshalb, um den Fall zu erkennen.
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda *a, **k: iter(["Die vorliegende Quellenlage gibt darauf keine Antwort."]),
    )
    client.post("/api/sources", json={"title": "Q", "text": "Text zu einem anderen Thema."})

    client.post("/api/ask", json={"question": "Was ist Andreas Schlegels Sicht auf Zeitorientierung?"})

    entries = question_log.list_entries()
    no_answer_entries = [e for e in entries if e["event_type"] == "no_answer"]
    assert len(no_answer_entries) == 1
    assert no_answer_entries[0]["text"] == "Was ist Andreas Schlegels Sicht auf Zeitorientierung?"
    assert no_answer_entries[0]["answer"] == "Die vorliegende Quellenlage gibt darauf keine Antwort."


def test_ask_does_not_log_no_answer_event_for_a_real_answer(client, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)
    client.post("/api/sources", json={"title": "Q", "text": "Der BetaCodex beschreibt zwölf Prinzipien."})

    client.post("/api/ask", json={"question": "Was ist der BetaCodex?"})

    entries = question_log.list_entries()
    assert [e for e in entries if e["event_type"] == "no_answer"] == []


def test_ask_does_not_log_no_answer_event_in_dev_environment(client, monkeypatch):
    # client-Fixture setzt IS_DEV_ENVIRONMENT bewusst auf True.
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda *a, **k: iter(["Die vorliegende Quellenlage gibt darauf keine Antwort."]),
    )
    client.post("/api/sources", json={"title": "Q", "text": "Text."})

    client.post("/api/ask", json={"question": "Frage ohne Antwort?"})

    assert question_log.list_entries() == []


def test_answer_feedback_logs_entry_with_question_answer_and_value(client, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)

    response = client.post(
        "/api/answer-feedback",
        json={"question": "Was ist der BetaCodex?", "answer": "Antworttext [1].", "feedback": "good"},
    )

    assert response.status_code == 200
    entries = question_log.list_entries()
    assert len(entries) == 1
    assert entries[0] == {
        "event_type": "feedback",
        "text": "Was ist der BetaCodex?",
        "answer": "Antworttext [1].",
        "feedback": "good",
        "timestamp": entries[0]["timestamp"],
    }


def test_answer_feedback_rejects_invalid_value(client, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)

    response = client.post(
        "/api/answer-feedback",
        json={"question": "Frage?", "answer": "Antwort.", "feedback": "meh"},
    )

    assert response.status_code == 400
    assert question_log.list_entries() == []


def test_answer_feedback_does_not_require_captcha(client, monkeypatch):
    # Bewusst analog zu /api/speak: nur nach einer bereits erfolgreich
    # beantworteten /api/ask-Anfrage erreichbar, siehe AnswerFeedbackIn.
    monkeypatch.setattr(captcha, "verify_turnstile_token", lambda token, remote_ip=None: False)
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)

    response = client.post(
        "/api/answer-feedback",
        json={"question": "Frage?", "answer": "Antwort.", "feedback": "bad"},
    )

    assert response.status_code == 200


def test_answer_feedback_not_logged_in_dev_environment(client):
    # client-Fixture setzt IS_DEV_ENVIRONMENT bewusst auf True.
    response = client.post(
        "/api/answer-feedback",
        json={"question": "Frage?", "answer": "Antwort.", "feedback": "good"},
    )

    assert response.status_code == 200
    assert question_log.list_entries() == []


def test_answer_feedback_rejects_after_rate_limit_exceeded(client, monkeypatch):
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)
    for _ in range(30):
        response = client.post(
            "/api/answer-feedback",
            json={"question": "Frage?", "answer": "Antwort.", "feedback": "good"},
        )
        assert response.status_code == 200

    response = client.post(
        "/api/answer-feedback",
        json={"question": "Frage?", "answer": "Antwort.", "feedback": "good"},
    )

    assert response.status_code == 429


def test_feedback_sends_mail_to_admin_and_returns_confirmation(client, monkeypatch):
    monkeypatch.setenv("SYSTEM_ADMIN_EMAIL", "admin@test.local")
    calls = []
    monkeypatch.setattr(mail, "send_mail", lambda to, subject, body: calls.append((to, subject, body)))

    response = client.post(
        "/api/feedback", json={"message": "Tolles Tool!", "email": "nutzer@test.local"}
    )

    assert response.status_code == 200
    assert len(calls) == 1
    to, subject, body = calls[0]
    assert to == "admin@test.local"
    assert "Tolles Tool!" in body
    assert "nutzer@test.local" in body


def test_feedback_uses_placeholder_when_email_omitted(client, monkeypatch):
    monkeypatch.setenv("SYSTEM_ADMIN_EMAIL", "admin@test.local")
    calls = []
    monkeypatch.setattr(mail, "send_mail", lambda to, subject, body: calls.append((to, subject, body)))

    client.post("/api/feedback", json={"message": "Anonymes Feedback."})

    body = calls[0][2]
    assert "(keine Angabe)" in body


def test_feedback_rejects_empty_message(client, monkeypatch):
    calls = []
    monkeypatch.setattr(mail, "send_mail", lambda to, subject, body: calls.append((to, subject, body)))

    response = client.post("/api/feedback", json={"message": "   "})

    assert response.status_code == 400
    assert calls == []


def test_feedback_rejects_when_captcha_verification_fails(client, monkeypatch):
    monkeypatch.setattr(captcha, "verify_turnstile_token", lambda token, remote_ip=None: False)

    response = client.post("/api/feedback", json={"message": "Feedback."})

    assert response.status_code == 400


def test_feedback_rejects_after_rate_limit_exceeded(client):
    for _ in range(3):
        response = client.post("/api/feedback", json={"message": "Feedback."})
        assert response.status_code == 200

    response = client.post("/api/feedback", json={"message": "Feedback."})

    assert response.status_code == 429


def test_ask_returns_answer_with_sources(client):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "date": "2023-05-01",
            "url": "https://example.org/quelle",
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    data = ask_result(response)
    assert data["answer"] == "Testantwort [1]."
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "BetaCodex Quelle"
    assert data["sources"][0]["authors"] == ["Autor Y"]


def test_ask_reranks_by_relevance_score_among_similar_matches(client, monkeypatch):
    """Backlog #51: der Relevanzscore einer Quelle muss das Ranking der
    Top-k-Treffer beeinflussen - eine embedding-mäßig etwas weiter
    entfernte, aber hoch bewertete Quelle soll eine näher liegende, aber
    niedrig bewertete Quelle bei top_k=1 verdrängen können."""
    embedding_by_text = {
        "Näher am Anfrageembedding, aber niedrig bewertete Quelle.": [1.0, 0.0],
        "Etwas weiter entfernt, aber hoch bewertete Quelle.": [0.0, 1.0954],
    }
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [embedding_by_text[t] for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [0.0, 0.0])

    client.post(
        "/api/sources",
        json={
            "title": "Niedrig bewertet, aber näher",
            "authors": ["Autor Nah"],
            "text": "Näher am Anfrageembedding, aber niedrig bewertete Quelle.",
            "relevance_score": 1,
        },
    )
    client.post(
        "/api/sources",
        json={
            "title": "Hoch bewertet, aber weiter entfernt",
            "authors": ["Autor Fern"],
            "text": "Etwas weiter entfernt, aber hoch bewertete Quelle.",
            "relevance_score": 10,
        },
    )

    response = client.post("/api/ask", json={"question": "Frage?", "top_k": 1})

    data = ask_result(response)
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "Hoch bewertet, aber weiter entfernt"


def test_ask_finds_mentioned_authors_source_even_when_embedding_is_farther(client, monkeypatch):
    # Nutzerwunsch (2026-08-31, realer Fall): "Erzähle mir etwas über die
    # Arbeiten von X" ist thematisch zu unspezifisch, um gegen den Rest des
    # Korpus per reiner Vektor-Ähnlichkeit zuverlässig zu gewinnen - wird die
    # Autorin/der Autor wörtlich in der Frage genannt, muss ihre/seine
    # eigene Quelle trotzdem einen Platz bekommen, auch wenn eine andere,
    # unbeteiligte Quelle embedding-mäßig näher am Anfrageembedding liegt.
    embedding_by_text = {
        "Näher am Anfrageembedding, aber von unbeteiligter Autor:in.": [1.0, 0.0],
        "Weiter entfernt, aber tatsächlich von der gefragten Autorin.": [0.0, 1.0954],
    }
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [embedding_by_text[t] for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [0.0, 0.0])

    client.post(
        "/api/sources",
        json={
            "title": "Unbeteiligte Quelle",
            "authors": ["Autor Unbeteiligt"],
            "text": "Näher am Anfrageembedding, aber von unbeteiligter Autor:in.",
        },
    )
    client.post(
        "/api/sources",
        json={
            "title": "Quelle der gefragten Autorin",
            "authors": ["Merrelyn Testperson"],
            "text": "Weiter entfernt, aber tatsächlich von der gefragten Autorin.",
        },
    )

    response = client.post(
        "/api/ask",
        json={"question": "Erzähle mir etwas über die Arbeiten von Merrelyn Testperson.", "top_k": 1},
    )

    data = ask_result(response)
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "Quelle der gefragten Autorin"


def test_ask_does_not_duplicate_authors_source_already_in_generic_results(client, monkeypatch):
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [1.0, 0.0])

    client.post(
        "/api/sources",
        json={
            "title": "Einzige Quelle der Autorin",
            "authors": ["Merrelyn Testperson"],
            "text": "Diese Quelle ist sowohl generisch als auch autor:innen-gefiltert der Top-Treffer.",
        },
    )

    response = client.post(
        "/api/ask",
        json={"question": "Erzähle mir etwas über die Arbeiten von Merrelyn Testperson.", "top_k": 3},
    )

    data = ask_result(response)
    assert len(data["sources"]) == 1


def test_ask_source_keyword_match_beats_closer_but_off_topic_same_author_source(client, monkeypatch):
    """Realer Fall (2026-09-01): "Erzähle mir etwas über Andreas Schlegel
    und Zeitorientierung" fand trotz erkannter Autor:in keine Antwort - die
    tatsächlich einschlägige Quelle lag rein embedding-mäßig WEITER vom
    Anfrageembedding entfernt als eine andere, thematisch unpassende Quelle
    derselben Person (ein reiner Distanz-Rabatt ändert daran nichts, er
    verschiebt beide Quellen nur gleichmäßig, ohne ihre Reihenfolge
    untereinander zu drehen). Ein kuratiertes Schlagwort (key_terms_de/en),
    das wörtlich in der Frage vorkommt, muss diesen Fall trotzdem lösen."""
    embedding_by_text = {
        "Näher am Anfrageembedding, aber falsches Thema.": [1.0, 0.0],
        "Weiter entfernt, aber zum gefragten Thema passend.": [0.0, 1.3],
    }
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [embedding_by_text[t] for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [0.0, 0.0])

    client.post(
        "/api/sources",
        json={
            "title": "Falsches Thema",
            "authors": ["Vielschreiber Testautor"],
            "text": "Näher am Anfrageembedding, aber falsches Thema.",
        },
    )
    passende_id = client.post(
        "/api/sources",
        json={
            "title": "Passendes Thema",
            "authors": ["Vielschreiber Testautor"],
            "text": "Weiter entfernt, aber zum gefragten Thema passend.",
        },
    ).json()["id"]

    sources = main_module._load_sources()
    sources[passende_id]["key_terms_de"] = ["Zeitorientierung"]
    main_module._save_sources(sources)

    response = client.post(
        "/api/ask",
        json={
            "question": "Erzähle mir etwas über Vielschreiber Testautor und Zeitorientierung.",
            "top_k": 1,
        },
    )

    data = ask_result(response)
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "Passendes Thema"


def test_source_matches_question_keywords_checks_both_languages_case_insensitively():
    source = {"key_terms_de": ["Zeitorientierung"], "key_terms_en": ["Time Orientation"]}

    assert main_module._source_matches_question_keywords(
        source, "Was denkst du über zeitorientierung?"
    )
    assert main_module._source_matches_question_keywords(
        source, "What do you think about TIME ORIENTATION?"
    )
    assert not main_module._source_matches_question_keywords(
        source, "Was denkst du über Selbstorganisation?"
    )


def test_ask_keeps_pure_distance_order_when_relevance_scores_are_equal(client, monkeypatch):
    """Gegenprobe zu obigem Test: bei gleichem (Default-)Relevanzscore
    ändert sich am reinen Distanz-Ranking nichts - die näher liegende
    Quelle gewinnt weiterhin."""
    embedding_by_text = {
        "Näher am Anfrageembedding, gleich bewertete Quelle A.": [1.0, 0.0],
        "Weiter entfernt, gleich bewertete Quelle B.": [0.0, 1.0954],
    }
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [embedding_by_text[t] for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [0.0, 0.0])

    client.post(
        "/api/sources",
        json={
            "title": "Näher, Quelle A",
            "authors": ["Autor A"],
            "text": "Näher am Anfrageembedding, gleich bewertete Quelle A.",
        },
    )
    client.post(
        "/api/sources",
        json={
            "title": "Weiter, Quelle B",
            "authors": ["Autor B"],
            "text": "Weiter entfernt, gleich bewertete Quelle B.",
        },
    )

    response = client.post("/api/ask", json={"question": "Frage?", "top_k": 1})

    data = ask_result(response)
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "Näher, Quelle A"


def test_ask_stream_emits_delta_events_in_order_before_done_event(client, monkeypatch):
    monkeypatch.setattr(
        llm, "stream_answer_question", lambda *a, **k: iter(["Erster Teil ", "zweiter Teil [1]."])
    )
    client.post("/api/sources", json={"title": "Q", "text": "Text."})

    response = client.post("/api/ask", json={"question": "Frage?"})
    result = ask_result(response)

    assert result["events"][-1]["type"] == "done"
    assert result["events"][-2]["type"] == "answer"
    assert result["events"][0]["type"] == "sources"
    assert all(e["type"] == "delta" for e in result["events"][1:-2])
    assert result["streamed_text"] == result["answer"]


def test_ask_stream_emits_early_sources_event_with_empty_highlights(client):
    """Nutzerwunsch (2026-08-03): Titel/Autor:in/Link jeder Quelle stehen
    schon vor dem LLM-Aufruf fest - ein frühes "sources"-Event soll das
    sofort mitschicken (mit noch leeren highlighted_texts), statt bis zum
    "done"-Event zu warten, damit "[n]"-Verweise im Frontend sofort
    klickbar werden."""
    client.post("/api/sources", json={"title": "Näher, Quelle A", "text": "Text."})

    response = client.post("/api/ask", json={"question": "Frage?"})
    events = ask_result(response)["events"]

    sources_index = next(i for i, e in enumerate(events) if e["type"] == "sources")
    answer_index = next(i for i, e in enumerate(events) if e["type"] == "answer")
    assert sources_index == 0
    assert sources_index < answer_index
    early_source = events[sources_index]["sources"][0]
    assert early_source["title"] == "Näher, Quelle A"
    assert early_source["highlighted_texts"] == []


def test_ask_stream_emits_exactly_one_answer_event_when_quotes_marker_present(client, monkeypatch):
    """Nutzerwunsch (2026-08-03): das "answer"-Event feuert jetzt schon,
    sobald der ---QUOTES---Marker im Puffer auftaucht (siehe answer_sent-
    Flag in _ask_event_stream), statt erst am Streamende - es darf dabei
    trotzdem nur genau EIN "answer"-Event pro Antwort geben, kein
    zusaetzliches am Ende."""
    raw = 'Aussage mit Beleg [1].\n\n---QUOTES---\n[1]: "Ein Zitat."\n'
    monkeypatch.setattr(llm, "stream_answer_question", lambda *a, **k: iter(list(raw)))
    client.post("/api/sources", json={"title": "Q", "text": "Text."})

    response = client.post("/api/ask", json={"question": "Frage?"})
    events = ask_result(response)["events"]

    answer_events = [e for e in events if e["type"] == "answer"]
    assert len(answer_events) == 1
    assert answer_events[0]["answer"] == "Aussage mit Beleg [1]."


def test_ask_answer_event_precedes_done_event_and_done_carries_no_answer(client):
    """Backlog (2026-07-31): der fertige Antworttext kommt in einem eigenen,
    FRÜHEREN "answer"-Event - das "done"-Event trägt seitdem nur noch die
    Quellen/Highlights, deren Berechnung spürbar länger dauern kann (siehe
    _compute_occurrence_highlights/_best_local_sentence), damit z.B. der
    Vorlesen-Button im Frontend nicht darauf warten muss."""
    client.post("/api/sources", json={"title": "Q", "text": "Text."})

    response = client.post("/api/ask", json={"question": "Frage?"})
    events = ask_result(response)["events"]

    answer_index = next(i for i, e in enumerate(events) if e["type"] == "answer")
    done_index = next(i for i, e in enumerate(events) if e["type"] == "done")
    assert answer_index < done_index
    assert "answer" not in events[done_index]


def test_ask_stream_never_leaks_quotes_marker_even_when_split_across_chunks(client, monkeypatch):
    # Der ---QUOTES---Block ist rein interne Beleg-Information fuer die
    # Hervorhebungen und darf nie an die Nutzer:in gestreamt werden - auch
    # nicht, wenn der Marker (oder der Zitat-Inhalt dahinter) ungluecklich
    # ueber mehrere Chunks der Anthropic-Antwort verteilt ankommt. Zeichen-
    # weises Yielden erzwingt genau diesen Fall.
    raw = 'Aussage mit Beleg [1].\n\n---QUOTES---\n[1]: "Niemals sichtbares Zitat."\n'
    monkeypatch.setattr(llm, "stream_answer_question", lambda *a, **k: iter(list(raw)))
    client.post("/api/sources", json={"title": "Q", "text": "Text."})

    response = client.post("/api/ask", json={"question": "Frage?"})
    result = ask_result(response)

    assert "---QUOTES---" not in result["streamed_text"]
    assert "Niemals sichtbares Zitat" not in result["streamed_text"]
    assert result["answer"] == "Aussage mit Beleg [1]."


def test_ask_replaces_creative_link_placeholder_with_encoded_instruction_url(client, monkeypatch):
    # Nutzerwunsch (2026-08-28): erkennt das Modell eine Generierungsanfrage
    # statt einer Faktenfrage (siehe Regel in llm.SYSTEM_PROMPTS), verweist
    # es per {{CREATIVE_LINK}}-Platzhalter auf den Kreativ-Modus - die echte,
    # korrekt URL-kodierte Ziel-URL (inkl. der Original-Frage als
    # vorausgefüllte Anweisung) wird deterministisch server-seitig
    # eingesetzt, nicht vom Modell selbst kodiert.
    from urllib.parse import quote

    raw = f"Das lässt sich im Kreativ-Modus umsetzen: [Kreativ-Modus]({llm.CREATIVE_LINK_PLACEHOLDER})"
    monkeypatch.setattr(llm, "stream_answer_question", lambda *a, **k: iter([raw]))
    client.post("/api/sources", json={"title": "Q", "text": "Text."})

    question = "Schreibe einen Blogartikel über Teamautonomie"
    response = client.post("/api/ask", json={"question": question})
    result = ask_result(response)

    expected_url = f"/creative.html?instruction={quote(question)}"
    assert llm.CREATIVE_LINK_PLACEHOLDER not in result["streamed_text"]
    assert f"[Kreativ-Modus]({expected_url})" in result["answer"]


def test_ask_replaces_creative_link_placeholder_even_when_split_across_chunks(client, monkeypatch):
    # Wie test_ask_stream_never_leaks_quotes_marker_even_when_split_across_
    # chunks oben, nur für den neuen Platzhalter - zeichenweises Yielden
    # erzwingt, dass er über viele einzelne Streaming-Chunks verteilt
    # ankommt, ohne dass ein unvollständiges Fragment sichtbar wird.
    from urllib.parse import quote

    raw = f"Nutze den [Kreativ-Modus]({llm.CREATIVE_LINK_PLACEHOLDER}) dafür."
    monkeypatch.setattr(llm, "stream_answer_question", lambda *a, **k: iter(list(raw)))
    client.post("/api/sources", json={"title": "Q", "text": "Text."})

    question = "Entwirf ein Workshop-Konzept zu Selbstorganisation"
    response = client.post("/api/ask", json={"question": question})
    result = ask_result(response)

    expected_url = f"/creative.html?instruction={quote(question)}"
    assert "{{" not in result["streamed_text"]
    assert "CREATIVE_LINK" not in result["streamed_text"]
    assert expected_url in result["streamed_text"]


def test_ask_stream_strips_answer_label_atomically_without_leaking_partial_prefix(client, monkeypatch):
    # Das "Antwort:"-Label darf nicht zeichenweise an die Nutzer:in
    # durchgereicht werden, bevor feststeht, ob es entfernt werden muss -
    # sonst wuerde kurz "A", "An", "Ant", ... aufblitzen. Zeichenweises
    # Yielden prueft, dass das erste gesendete Delta das Label bereits
    # vollstaendig entfernt hat.
    raw = "Antwort: Der BetaCodex ist ein Organisationsmodell fuer Unternehmen [1]."
    monkeypatch.setattr(llm, "stream_answer_question", lambda *a, **k: iter(list(raw)))
    client.post("/api/sources", json={"title": "Q", "text": "Text."})

    response = client.post("/api/ask", json={"question": "Frage?"})
    result = ask_result(response)

    delta_texts = [e["text"] for e in result["events"] if e["type"] == "delta"]
    assert delta_texts
    assert not delta_texts[0].lower().startswith("ant")
    assert "Antwort:" not in "".join(delta_texts)
    assert result["answer"] == "Der BetaCodex ist ein Organisationsmodell fuer Unternehmen [1]."


def test_ask_passes_author_bio_when_question_mentions_registered_author(client, monkeypatch):
    # Bug vom 2026-07-29: "Wer ist X?"-Fragen fanden nie die gepflegte
    # Autor:innen-Vita, da die Suche rein auf Chunk-Inhalten basiert und
    # Autor:innen-Namen dort nie als durchsuchbarer Text vorkommen.
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Peter Pröll"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )
    author_profiles.set_profile("Peter Pröll", bio_de="Berater und Autor zum Beta-Kodex.")

    captured = {}

    def fake_answer(question, chunks, lang="de", author_bios=None, history=None):
        captured["author_bios"] = author_bios
        return iter(["Testantwort [1]."])

    monkeypatch.setattr(llm, "stream_answer_question", fake_answer)

    client.post("/api/ask", json={"question": "Wer ist Peter Pröll?"})

    assert captured["author_bios"] == [
        {"name": "Peter Pröll", "bio": "Berater und Autor zum Beta-Kodex."}
    ]


def test_ask_passes_no_author_bio_when_question_does_not_mention_author(client, monkeypatch):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Peter Pröll"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )
    author_profiles.set_profile("Peter Pröll", bio_de="Berater und Autor zum Beta-Kodex.")

    captured = {}

    def fake_answer(question, chunks, lang="de", author_bios=None, history=None):
        captured["author_bios"] = author_bios
        return iter(["Testantwort [1]."])

    monkeypatch.setattr(llm, "stream_answer_question", fake_answer)

    client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert captured["author_bios"] is None


# Backlog (2026-08-03): der Chatbot wiederholte sich im Konversationsmodus,
# weil jede Frage isoliert ohne Kenntnis vorheriger Turns beantwortet wurde.


def test_ask_passes_history_to_llm(client, monkeypatch):
    client.post(
        "/api/sources",
        json={"title": "Q", "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."},
    )
    captured = {}

    def fake_answer(question, chunks, lang="de", author_bios=None, history=None):
        captured["history"] = history
        return iter(["Testantwort [1]."])

    monkeypatch.setattr(llm, "stream_answer_question", fake_answer)

    client.post(
        "/api/ask",
        json={
            "question": "Und wie sieht es mit Vertrauen aus?",
            "history": [
                {"question": "Was ist der BetaCodex?", "answer": "Ein Prinzipien-Set [1]."}
            ],
        },
    )

    assert captured["history"] == [
        {"question": "Was ist der BetaCodex?", "answer": "Ein Prinzipien-Set [1]."}
    ]


def test_ask_caps_history_to_last_turns_even_if_client_sends_more(client, monkeypatch):
    client.post(
        "/api/sources",
        json={"title": "Q", "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."},
    )
    captured = {}

    def fake_answer(question, chunks, lang="de", author_bios=None, history=None):
        captured["history"] = history
        return iter(["Testantwort [1]."])

    monkeypatch.setattr(llm, "stream_answer_question", fake_answer)
    monkeypatch.setattr(main_module, "ASK_HISTORY_MAX_TURNS", 2)

    client.post(
        "/api/ask",
        json={
            "question": "Frage 4?",
            "history": [
                {"question": "Frage 1?", "answer": "Antwort 1."},
                {"question": "Frage 2?", "answer": "Antwort 2."},
                {"question": "Frage 3?", "answer": "Antwort 3."},
            ],
        },
    )

    assert captured["history"] == [
        {"question": "Frage 2?", "answer": "Antwort 2."},
        {"question": "Frage 3?", "answer": "Antwort 3."},
    ]


def test_ask_uses_rewritten_query_for_history_follow_up(client, monkeypatch):
    client.post(
        "/api/sources",
        json={"title": "Q", "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."},
    )
    captured = {}
    monkeypatch.setattr(
        embeddings,
        "embed_query",
        lambda text: captured.setdefault("query_text", text) and [1.0, 0.0] or [1.0, 0.0],
    )
    monkeypatch.setattr(
        llm, "rewrite_followup_query", lambda question, history, lang: "BetaCodex und Vertrauen"
    )

    client.post(
        "/api/ask",
        json={
            "question": "Und wie sieht es mit Vertrauen aus?",
            "history": [{"question": "Was ist der BetaCodex?", "answer": "Ein Prinzipien-Set [1]."}],
        },
    )

    assert captured["query_text"] == "BetaCodex und Vertrauen"


def test_ask_falls_back_to_concatenation_when_rewrite_fails(client, monkeypatch):
    """Fix (2026-08-20): schlägt der Rewrite-Call fehl (z.B. Anthropic-
    Störung), darf die Anfrage nicht komplett blockiert werden - stattdessen
    greift die einfache Verkettung aus letzter Frage + aktueller Frage."""
    client.post(
        "/api/sources",
        json={"title": "Q", "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."},
    )
    captured = {}
    monkeypatch.setattr(
        embeddings,
        "embed_query",
        lambda text: captured.setdefault("query_text", text) and [1.0, 0.0] or [1.0, 0.0],
    )
    monkeypatch.setattr(llm, "rewrite_followup_query", lambda question, history, lang: None)

    client.post(
        "/api/ask",
        json={
            "question": "Und wie sieht es mit Vertrauen aus?",
            "history": [{"question": "Was ist der BetaCodex?", "answer": "Ein Prinzipien-Set [1]."}],
        },
    )

    assert captured["query_text"] == "Was ist der BetaCodex? Und wie sieht es mit Vertrauen aus?"


def test_ask_without_history_uses_plain_question_for_embedding_query(client, monkeypatch):
    client.post(
        "/api/sources",
        json={"title": "Q", "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."},
    )
    captured = {}
    monkeypatch.setattr(
        embeddings,
        "embed_query",
        lambda text: captured.setdefault("query_text", text) and [1.0, 0.0] or [1.0, 0.0],
    )

    client.post("/api/ask", json={"question": "Was ist der BetaCodex?"})

    assert captured["query_text"] == "Was ist der BetaCodex?"


def test_ask_includes_source_summary(client):
    create_res = client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )
    source_id = create_res.json()["id"]
    # add_source() generiert die Zusammenfassung selbst im Hintergrund - hier
    # stattdessen direkt über das Bearbeiten-Endpoint setzen, ohne auf den
    # (in Tests gemockten) KI-Hintergrundlauf angewiesen zu sein.
    client.put(
        f"/api/sources/{source_id}",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
            "summary": "Kurzfassung der Quelle.",
        },
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    assert ask_result(response)["sources"][0]["summary"] == "Kurzfassung der Quelle."


def test_ask_reports_null_summary_when_source_has_none(client):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle ohne Zusammenfassung",
            "authors": ["Autor Y"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    assert ask_result(response)["sources"][0]["summary"] is None


def test_ask_sets_highlighted_texts_from_local_fallback_without_quote_block(client):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    assert ask_result(response)["sources"][0]["highlighted_texts"] == [
        "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."
    ]


def test_ask_uses_llm_quote_when_it_matches_the_chunk(client, monkeypatch):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "text": (
                "Erster Satz zur Einordnung. Der BetaCodex beschreibt Prinzipien "
                "dezentraler Organisation. Ein dritter Satz als Abschluss."
            ),
        },
    )
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda question, chunks, lang="de", author_bios=None, history=None: iter([
            "Aussage [1].\n\n---QUOTES---\n"
            '[1]: "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."\n'
        ]),
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    data = ask_result(response)
    assert data["answer"] == "Aussage [1]."
    assert data["sources"][0]["highlighted_texts"] == [
        "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."
    ]


def test_ask_falls_back_to_local_highlight_when_llm_quote_not_found_in_chunk(client, monkeypatch):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda question, chunks, lang="de", author_bios=None, history=None: iter([
            "Antwort [1].\n\n---QUOTES---\n"
            '[1]: "Dieser Satz kommt in der Quelle so gar nicht vor."\n'
        ]),
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    # Fällt auf das lokale Highlight zurück, statt das halluzinierte Zitat
    # zu übernehmen (Verifikation gegen den echten Chunk-Text greift).
    assert ask_result(response)["sources"][0]["highlighted_texts"] == [
        "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."
    ]


def test_ask_uses_original_chunk_whitespace_not_llm_quote_for_highlight(client, monkeypatch):
    """Regressionstest (Bug 2026-08-20, per Screenshot gemeldet): das
    "wörtliche" LLM-Zitat normalisiert Formatierungs-Eigenheiten des
    Originals leicht (hier: ein geschütztes Leerzeichen \xa0 - typisch bei
    aus Websites gecrawltem Text - wird zu einem normalen Leerzeichen).
    Der exakte String-Vergleich im Frontend (findHighlightRange) fand das
    LLM-Zitat dadurch nicht mehr im Chunk-Text. highlighted_texts muss die
    TATSÄCHLICHE Textspanne aus dem Chunk liefern (inkl. \xa0), nicht die
    vom Modell leicht geglättete Fassung."""
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "text": "Jede Liste besitzt einen\xa0List-Owner. Diese Rolle endet mit der Liste.",
        },
    )
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda question, chunks, lang="de", author_bios=None, history=None: iter([
            "Antwort [1].\n\n---QUOTES---\n"
            # Das Modell gibt ein normales statt des geschützten Leerzeichens
            # wieder - genau der real beobachtete Fall.
            '[1]: "Jede Liste besitzt einen List-Owner."\n'
        ]),
    )

    response = client.post("/api/ask", json={"question": "Was ist ein List-Owner?"})

    assert response.status_code == 200
    highlight = ask_result(response)["sources"][0]["highlighted_texts"][0]
    assert highlight == "Jede Liste besitzt einen\xa0List-Owner."
    assert "\xa0" in highlight


def test_ask_skips_eager_local_highlight_computation_for_cited_chunks(client, monkeypatch):
    """Performance-Regression: _best_local_sentence wurde bislang EAGER für
    JEDEN zurückgegebenen Chunk aufgerufen (mehrere Sekunden zusätzliches
    lokales Modell-Inference pro Anfrage, gemessen ~2s bei 5 Chunks) - auch
    wenn der Chunk ohnehin per [n] zitiert und damit schon anderweitig
    (per KI-Zitat oder dem eigenen Lazy-Fallback von
    _compute_occurrence_highlights) gehighlightet wurde. Jetzt darf der
    Aufruf nur noch für tatsächlich UNZITIERTE Chunks passieren - hier gibt
    es nur einen einzigen, zitierten Chunk, also darf er gar nicht fallen."""
    call_count = {"n": 0}
    original = main_module._best_local_sentence

    def counting(*args, **kwargs):
        call_count["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(main_module, "_best_local_sentence", counting)

    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    assert call_count["n"] == 0


def test_local_highlight_sentence_embeddings_are_cached_across_requests(client, monkeypatch):
    """Performance-Fix (Backlog 2026-07-31): Satz-Embeddings eines Chunks
    hängen nur von dessen TEXT ab, nicht von der gestellten Frage - werden
    deshalb über einen Hash des Texts gecacht (_get_chunk_sentence_embeddings
    in app/main.py) statt bei jeder Frage erneut vom lokalen Modell berechnet
    zu werden. Zwei verschiedene Fragen, die denselben mehrsätzigen,
    unzitierten Chunk lazy highlighten (siehe
    test_ask_gives_uncited_chunk_a_lazy_local_highlight_fallback), dürfen
    embed_passages für dessen Sätze deshalb nur beim ERSTEN Mal aufrufen."""
    client.post(
        "/api/sources",
        json={"title": "Quelle A", "authors": ["Autor A"], "text": "Erster Satz über den BetaCodex."},
    )
    client.post(
        "/api/sources",
        json={
            "title": "Quelle B",
            "authors": ["Autor B"],
            "text": "Zweiter Satz über Organisation. Dritter Satz über Struktur.",
        },
    )
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda question, chunks, lang="de", author_bios=None, history=None: iter(["Antwort [1]."]),
    )

    # Erst NACH dem Anlegen der Quellen mitzählen - deren eigene Indizierung
    # ruft embed_passages ebenfalls auf, das soll hier nicht mitgezählt werden.
    call_count = {"n": 0}
    original = embeddings.embed_passages

    def counting(texts):
        call_count["n"] += 1
        return original(texts)

    monkeypatch.setattr(embeddings, "embed_passages", counting)

    client.post("/api/ask", json={"question": "Erste Frage?"})
    assert call_count["n"] == 1

    client.post("/api/ask", json={"question": "Zweite, ganz andere Frage?"})
    assert call_count["n"] == 1


def test_local_highlight_cache_ignores_stale_entry_after_source_edit(client, monkeypatch):
    """Absicherung gegen einen naheliegenden Cache-Bug: die chunk_id bleibt
    beim Bearbeiten einer Quelle unverändert (f"{source_id}::{i}", siehe
    _store_chunks), obwohl sich der Text ändert - ein über die chunk_id statt
    über den Text geschlüsselter Cache würde nach einer Bearbeitung veraltete
    Satz-Embeddings für den NEUEN Text ausliefern. Hier geprüft, indem
    dieselbe (unzitierte) Quelle vor und nach einer Bearbeitung jeweils ihr
    zum AKTUELLEN Text passendes Highlight liefert. Quelle A bleibt bewusst
    UNZITIERT (Zitat zeigt auf [2] = Quelle B), damit ihr Highlight über den
    zu prüfenden Lazy-Fallback (_best_local_sentence) berechnet wird."""
    create_res = client.post(
        "/api/sources",
        json={"title": "Quelle A", "authors": ["Autor A"], "text": "Alter erster Satz. Alter zweiter Satz."},
    )
    source_id = create_res.json()["id"]
    client.post(
        "/api/sources",
        json={"title": "Quelle B", "authors": ["Autor B"], "text": "Zitierter Satz."},
    )
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda question, chunks, lang="de", author_bios=None, history=None: iter(["Antwort [2]."]),
    )

    first = ask_result(client.post("/api/ask", json={"question": "Frage eins?"}))
    uncited_before = next(s for s in first["sources"] if s["title"] == "Quelle A")
    assert uncited_before["highlighted_texts"] == ["Alter erster Satz."]

    client.put(
        f"/api/sources/{source_id}",
        json={
            "title": "Quelle A",
            "authors": ["Autor A"],
            "text": "Neuer erster Satz. Neuer zweiter Satz.",
        },
    )

    second = ask_result(client.post("/api/ask", json={"question": "Frage zwei?"}))
    uncited_after = next(s for s in second["sources"] if s["title"] == "Quelle A")
    assert uncited_after["highlighted_texts"] == ["Neuer erster Satz."]


def test_ask_gives_uncited_chunk_a_lazy_local_highlight_fallback(client, monkeypatch):
    """Letzter Ausweg: eine zurückgegebene, aber im Antworttext gar nicht
    per [n] referenzierte Quelle bekommt trotzdem ein Highlight statt gar
    keins - jetzt lazy NACH dem Streaming berechnet statt vorab für jeden
    Chunk (siehe test_ask_skips_eager_local_highlight_computation..., das
    genau diese Verschiebung als Performance-Fix prüft)."""
    client.post(
        "/api/sources",
        json={"title": "Quelle A", "authors": ["Autor A"], "text": "Erster Satz über den BetaCodex."},
    )
    client.post(
        "/api/sources",
        json={"title": "Quelle B", "authors": ["Autor B"], "text": "Zweiter Satz über Selbstorganisation."},
    )
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda question, chunks, lang="de", author_bios=None, history=None: iter(["Antwort [1]."]),
    )

    response = client.post("/api/ask", json={"question": "Frage?"})

    assert response.status_code == 200
    sources = ask_result(response)["sources"]
    assert len(sources) == 2
    cited, uncited = sources[0], sources[1]
    assert cited["highlighted_texts"]
    assert uncited["highlighted_texts"] == [uncited["text"]]


def test_ask_uses_different_highlight_per_occurrence_of_the_same_source(client, monkeypatch):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "text": (
                "Der BetaCodex beschreibt Prinzipien dezentraler Organisation. "
                "Teams organisieren sich in Zellen ohne zentrale Weisung."
            ),
        },
    )
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda question, chunks, lang="de", author_bios=None, history=None: iter([
            "Aussage A [1]. Aussage B [1].\n\n---QUOTES---\n"
            '[1]: "Der BetaCodex beschreibt Prinzipien dezentraler Organisation."\n'
            '[1]: "Teams organisieren sich in Zellen ohne zentrale Weisung."\n'
        ]),
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    assert ask_result(response)["sources"][0]["highlighted_texts"] == [
        "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        "Teams organisieren sich in Zellen ohne zentrale Weisung.",
    ]


def test_reindex_sources_requires_pfleger_role(anon_client):
    response = anon_client.post("/api/admin/reindex-sources")
    assert response.status_code == 403


def test_reindex_sources_replaces_chunks_with_new_chunking(client, monkeypatch):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "authors": ["Autor Y"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )

    # Simuliert eine geänderte Chunking-Logik (z.B. das Satzgrenzen-Snapping) -
    # nach der Neu-Indizierung müssen die NEUEN Chunk-Inhalte im Vektorspeicher
    # landen, nicht mehr die beim ursprünglichen Import erzeugten.
    monkeypatch.setattr(chunking, "chunk_text", lambda text, **kwargs: ["Neu gechunkter Inhalt."])

    response = client.post("/api/admin/reindex-sources")
    assert response.status_code == 200

    ask_response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})
    assert ask_result(ask_response)["sources"][0]["text"] == "Neu gechunkter Inhalt."


def test_reindex_sources_skips_broken_records_without_aborting(client, monkeypatch):
    client.post(
        "/api/sources",
        json={
            "title": "Gute Quelle",
            "authors": ["Autor Y"],
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )

    def _broken_chunk_text(text, **kwargs):
        raise ValueError("kaputter Datensatz")

    monkeypatch.setattr(chunking, "chunk_text", _broken_chunk_text)

    response = client.post("/api/admin/reindex-sources")

    assert response.status_code == 200


def test_extract_url_endpoint_returns_extracted_fields(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {
            "title": "Extrahierter Titel",
            "authors": ["Autor Z"],
            "date": "2024-02-02",
            "text": "Extrahierter Text.",
            "extracted": True,
        },
    )
    monkeypatch.setattr(extraction, "looks_like_audio", lambda url: False)

    response = client.post("/api/extract-url", json={"url": "https://example.org/blogpost"})

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Extrahierter Titel"
    assert data["date"] == "2024-02-02"
    assert data["extracted"] is True
    assert data["is_audio"] is False


def test_extract_url_endpoint_reports_failed_extraction(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {"title": "", "authors": [], "date": "", "text": "", "extracted": False},
    )
    monkeypatch.setattr(extraction, "looks_like_audio", lambda url: False)

    response = client.post("/api/extract-url", json={"url": "https://example.org/nicht-lesbar"})

    assert response.status_code == 200
    assert response.json()["extracted"] is False


def test_extract_url_endpoint_reports_is_audio_true_for_audio_url(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {"title": "Folge 1", "authors": [], "date": "", "text": "", "extracted": False},
    )
    monkeypatch.setattr(extraction, "looks_like_audio", lambda url: True)

    response = client.post("/api/extract-url", json={"url": "https://cdn.example.org/episode.mp3"})

    assert response.status_code == 200
    assert response.json()["is_audio"] is True


def test_extract_url_endpoint_reports_is_pdf_true_for_pdf_url(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {"title": "Scan", "authors": [], "date": "", "text": "", "extracted": False},
    )
    monkeypatch.setattr(extraction, "looks_like_audio", lambda url: False)
    monkeypatch.setattr(extraction, "looks_like_pdf", lambda url: True)

    response = client.post("/api/extract-url", json={"url": "https://cdn.example.org/scan.pdf"})

    assert response.status_code == 200
    assert response.json()["is_pdf"] is True


def test_add_source_registers_author(client):
    client.post(
        "/api/sources",
        json={"title": "Quelle 1", "authors": ["Jane Doe"], "text": "Erster Text."},
    )
    client.post(
        "/api/sources",
        json={"title": "Quelle 2", "authors": ["jane   doe"], "text": "Zweiter Text."},
    )

    response = client.get("/api/authors")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Jane Doe"
    assert data[0]["source_count"] == 2


def test_add_source_with_multiple_authors_registers_all(client):
    create_res = client.post(
        "/api/sources",
        json={
            "title": "Gemeinsame Quelle",
            "authors": ["Jane Doe", "John Roe"],
            "text": "Gemeinsamer Text.",
        },
    )

    assert create_res.json()["authors"] == ["Jane Doe", "John Roe"]

    author_names = {a["name"] for a in client.get("/api/authors").json()}
    assert author_names == {"Jane Doe", "John Roe"}

    response = client.post("/api/ask", json={"question": "Worum geht es?"})
    assert ask_result(response)["sources"][0]["authors"] == ["Jane Doe", "John Roe"]


def test_add_source_without_author_does_not_appear_in_directory(client):
    client.post("/api/sources", json={"title": "Ohne Autor", "text": "Text ohne Autor."})

    response = client.get("/api/authors")

    assert response.status_code == 200
    assert response.json() == []


def test_update_source_changes_metadata_and_rechunks(client):
    create_res = client.post(
        "/api/sources",
        json={
            "title": "Alter Titel",
            "authors": ["Alt Autor"],
            "date": "2020-01-01",
            "text": "Alter Text.",
        },
    )
    source_id = create_res.json()["id"]

    update_res = client.put(
        f"/api/sources/{source_id}",
        json={
            "title": "Neuer Titel",
            "authors": ["Neu Autor"],
            "date": "2021-01-01",
            "url": "https://example.org",
            "text": "Neuer Text mit anderem Inhalt.",
        },
    )

    assert update_res.status_code == 200
    data = update_res.json()
    assert data["title"] == "Neuer Titel"
    assert data["authors"] == ["Neu Autor"]
    assert data["text"] == "Neuer Text mit anderem Inhalt."

    list_res = client.get("/api/sources")
    assert list_res.json()[0]["title"] == "Neuer Titel"


def test_update_source_clears_error_state_on_successful_edit(client):
    """Nutzerwunsch (2026-08-03): ein manueller Edit ist die Reparatur fuer
    eine Quelle, deren automatischer Import fehlgeschlagen ist - danach darf
    sie nicht mehr als "error" markiert bleiben."""
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["processing_status"] = "error"
    sources[source_id]["processing_step"] = None
    sources[source_id]["processing_error"] = "Verarbeitung durch Server-Neustart unterbrochen."
    main_module._save_sources(sources)

    update_res = client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "text": "Von Hand nachgetragener Text."},
    )

    assert update_res.status_code == 200
    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["processing_status"] is None


def test_update_source_returns_404_for_unknown_id(client):
    response = client.put("/api/sources/does-not-exist", json={"title": "X", "text": "Text"})
    assert response.status_code == 404


def test_update_source_rejects_empty_text_without_touching_existing_data(client):
    create_res = client.post(
        "/api/sources",
        json={"title": "Titel", "authors": ["Autor"], "text": "Ursprünglicher Text."},
    )
    source_id = create_res.json()["id"]

    response = client.put(
        f"/api/sources/{source_id}",
        json={"title": "Titel", "authors": ["Autor"], "text": "   "},
    )

    assert response.status_code == 400

    list_res = client.get("/api/sources")
    source = list_res.json()[0]
    assert source["text"] == "Ursprünglicher Text."
    assert source["chunk_count"] == 1

    result = vectorstore.query([1.0, 0.0], top_k=5)
    assert result["metadatas"][0][0]["source_id"] == source_id


def test_update_source_moves_author_registration(client):
    create_res = client.post(
        "/api/sources", json={"title": "Titel", "authors": ["Alter Autor"], "text": "Text."}
    )
    source_id = create_res.json()["id"]

    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Titel", "authors": ["Neuer Autor"], "text": "Text."},
    )

    author_names = {a["name"] for a in client.get("/api/authors").json()}
    assert author_names == {"Neuer Autor"}


def test_add_source_without_role_is_forbidden(anon_client):
    response = anon_client.post(
        "/api/sources",
        json={"title": "Quelle", "text": "Text."},
    )
    assert response.status_code == 403


def test_add_source_with_unrelated_role_is_forbidden(anon_client):
    login(anon_client, "uwe.admin@test.local", users.USER_ADMIN)
    response = anon_client.post(
        "/api/sources",
        json={"title": "Quelle", "text": "Text."},
    )
    assert response.status_code == 403


def test_add_source_as_system_admin_is_allowed(anon_client):
    login(anon_client, "root@test.local", users.SYSTEM_ADMIN)
    response = anon_client.post(
        "/api/sources",
        json={"title": "Quelle", "text": "Text."},
    )
    assert response.status_code == 200


def test_update_source_without_role_is_forbidden(client, anon_client):
    create_res = client.post("/api/sources", json={"title": "Titel", "text": "Text."})
    source_id = create_res.json()["id"]

    response = anon_client.put(
        f"/api/sources/{source_id}",
        json={"title": "Neu", "text": "Neuer Text."},
    )
    assert response.status_code == 403


def test_extract_url_without_role_is_forbidden(anon_client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {"title": "T", "authors": [], "date": "", "text": "Text", "extracted": True},
    )
    response = anon_client.post(
        "/api/extract-url",
        json={"url": "https://example.org"},
    )
    assert response.status_code == 403


def test_ask_and_list_sources_work_without_any_role(client, anon_client):
    client.post("/api/sources", json={"title": "Quelle", "text": "Text zum Fragen."})

    assert anon_client.get("/api/sources").status_code == 200
    assert anon_client.post("/api/ask", json={"question": "Frage?"}).status_code == 200


def test_add_source_rejects_empty_text_in_english(client):
    response = client.post(
        "/api/sources",
        json={"title": "Empty", "text": "   "},
        headers={"X-Lang": "en"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Text must not be empty."


def test_role_required_message_in_english(anon_client):
    response = anon_client.post(
        "/api/sources",
        json={"title": "X", "text": "Text"},
        headers={"X-Lang": "en"},
    )
    assert response.status_code == 403
    assert "requires the role" in response.json()["detail"]


def test_ask_uses_requested_language(client, monkeypatch):
    captured = {}

    def fake_answer(question, chunks, lang="de", author_bios=None, history=None):
        captured["lang"] = lang
        return iter(["Answer"])

    monkeypatch.setattr(llm, "stream_answer_question", fake_answer)
    client.post("/api/sources", json={"title": "Q", "text": "Text for asking."})

    response = client.post("/api/ask", json={"question": "Q?"}, headers={"X-Lang": "en"})

    assert response.status_code == 200
    assert captured["lang"] == "en"


def test_whoami_reports_anonymous_by_default(anon_client):
    response = anon_client.get("/api/auth/whoami")
    assert response.status_code == 200
    assert response.json() == {"email": None, "roles": [], "name": None}


def test_whoami_reports_logged_in_user(client):
    response = client.get("/api/auth/whoami")
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == PFLEGER
    assert data["roles"] == [users.QUELLEN_PFLEGER]
    assert data["name"] is None


def test_whoami_reports_name_when_set(client):
    users.set_name(PFLEGER, "Lena Pflegerin")
    response = client.get("/api/auth/whoami")
    assert response.status_code == 200
    assert response.json()["name"] == "Lena Pflegerin"


def test_whoami_tolerates_legacy_user_entry_without_name_key(client):
    # Reale Produktions-Daten (Stable, vor #98) enthalten Einträge ganz ohne
    # "name"-Schlüssel, nicht nur mit name=None - direktes user["name"] hätte
    # dort einen KeyError geworfen (2026-07-29 auf Stable aufgetreten).
    raw = json.loads(users.USERS_FILE.read_text())
    del raw[PFLEGER]["name"]
    users.USERS_FILE.write_text(json.dumps(raw))

    response = client.get("/api/auth/whoami")
    assert response.status_code == 200
    assert response.json()["name"] is None


def test_request_link_returns_generic_message_for_unknown_email(anon_client):
    response = anon_client.post("/api/auth/request-link", json={"email": "ghost@test.local"})
    assert response.status_code == 200
    assert response.json()["detail"]


def test_request_link_is_rate_limited(anon_client):
    for _ in range(5):
        anon_client.post("/api/auth/request-link", json={"email": "ghost@test.local"})
    response = anon_client.post("/api/auth/request-link", json={"email": "ghost@test.local"})
    assert response.status_code == 429


def test_verify_with_valid_token_grants_access(anon_client):
    users.invite_user("tester@test.local", users.QUELLEN_PFLEGER, invited_by="root@test.local")
    token = auth.create_magic_link_token("tester@test.local", auth.LOGIN_LINK_MAX_AGE_SECONDS)

    verify_res = anon_client.get(f"/api/auth/verify?token={token}", follow_redirects=False)
    assert verify_res.status_code in (302, 307)

    whoami_res = anon_client.get("/api/auth/whoami")
    assert whoami_res.json()["email"] == "tester@test.local"


def test_verify_with_invalid_token_redirects_without_cookie(anon_client):
    response = anon_client.get("/api/auth/verify?token=not-a-real-token", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "auth=expired" in response.headers["location"]
    assert anon_client.get("/api/auth/whoami").json()["email"] is None


def test_verify_token_cannot_be_reused(anon_client):
    users.invite_user("tester@test.local", users.QUELLEN_PFLEGER, invited_by="root@test.local")
    token = auth.create_magic_link_token("tester@test.local", auth.LOGIN_LINK_MAX_AGE_SECONDS)
    anon_client.get(f"/api/auth/verify?token={token}", follow_redirects=False)

    second_attempt = anon_client.get(f"/api/auth/verify?token={token}", follow_redirects=False)
    assert "auth=expired" in second_attempt.headers["location"]


def test_logout_clears_session(client):
    assert client.get("/api/auth/whoami").json()["email"] == PFLEGER
    client.post("/api/auth/logout")
    assert client.get("/api/auth/whoami").json()["email"] is None
    assert client.post("/api/sources", json={"title": "X", "text": "Y"}).status_code == 403


def test_invite_by_user_admin_creates_invited_user(anon_client):
    login(anon_client, "admin@test.local", users.USER_ADMIN)

    response = anon_client.post(
        "/api/auth/invite", json={"email": "new@test.local", "role": users.QUELLEN_PFLEGER}
    )

    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@test.local"
    assert data["roles"] == [users.QUELLEN_PFLEGER]
    assert data["status"] == "invited"


def test_invite_forbids_user_admin_from_granting_system_admin(anon_client):
    login(anon_client, "admin@test.local", users.USER_ADMIN)

    response = anon_client.post(
        "/api/auth/invite", json={"email": "new@test.local", "role": users.SYSTEM_ADMIN}
    )

    assert response.status_code == 403


def test_invite_allows_system_admin_to_grant_any_role(anon_client):
    login(anon_client, "root@test.local", users.SYSTEM_ADMIN)

    response = anon_client.post(
        "/api/auth/invite", json={"email": "new@test.local", "role": users.USER_ADMIN}
    )

    assert response.status_code == 201


def test_invite_rejects_unknown_role(anon_client):
    login(anon_client, "admin@test.local", users.USER_ADMIN)

    response = anon_client.post(
        "/api/auth/invite", json={"email": "new@test.local", "role": "not-a-role"}
    )

    assert response.status_code == 400


def test_list_invited_users_requires_user_admin(anon_client):
    login(anon_client, "someone@test.local", users.QUELLEN_PFLEGER)
    response = anon_client.get("/api/auth/users")
    assert response.status_code == 403


def test_list_invited_users_returns_entries_for_admin(anon_client):
    login(anon_client, "admin@test.local", users.USER_ADMIN)
    anon_client.post(
        "/api/auth/invite", json={"email": "new@test.local", "role": users.QUELLEN_PFLEGER}
    )

    response = anon_client.get("/api/auth/users")

    assert response.status_code == 200
    emails = {u["email"] for u in response.json()}
    assert "new@test.local" in emails


def test_invite_stores_optional_name(anon_client):
    login(anon_client, "admin@test.local", users.USER_ADMIN)

    response = anon_client.post(
        "/api/auth/invite",
        json={"email": "new@test.local", "role": users.QUELLEN_PFLEGER, "name": "Nora Neu"},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "Nora Neu"


def test_set_user_name_updates_existing_user(anon_client):
    login(anon_client, "admin@test.local", users.USER_ADMIN)
    anon_client.post("/api/auth/invite", json={"email": "new@test.local", "role": users.QUELLEN_PFLEGER})

    response = anon_client.put("/api/auth/users/new@test.local/name", json={"name": "Nora Neu"})

    assert response.status_code == 200
    assert response.json()["name"] == "Nora Neu"
    emails = {u["email"]: u["name"] for u in anon_client.get("/api/auth/users").json()}
    assert emails["new@test.local"] == "Nora Neu"


def test_set_user_name_requires_user_admin(anon_client):
    login(anon_client, "someone@test.local", users.QUELLEN_PFLEGER)

    response = anon_client.put("/api/auth/users/someone@test.local/name", json={"name": "X"})

    assert response.status_code == 403


def test_set_user_name_returns_404_for_unknown_user(anon_client):
    login(anon_client, "admin@test.local", users.USER_ADMIN)

    response = anon_client.put("/api/auth/users/nope@test.local/name", json={"name": "X"})

    assert response.status_code == 404


def test_audit_log_records_source_created(client):
    client.post("/api/sources", json={"title": "Auditierte Quelle", "text": "Text."})

    response = client.get("/api/audit-log")

    assert response.status_code == 200
    entries = response.json()
    assert any(
        e["action"] == "source_created" and e["target_label"] == "Auditierte Quelle" and e["actor_email"] == PFLEGER
        for e in entries
    )


def test_audit_log_records_source_update_and_delete(client):
    create_res = client.post("/api/sources", json={"title": "Zu ändern", "text": "Text."})
    source_id = create_res.json()["id"]

    client.put(f"/api/sources/{source_id}", json={"title": "Geändert", "text": "Neuer Text."})
    client.delete(f"/api/sources/{source_id}")

    actions = [e["action"] for e in client.get("/api/audit-log").json()]
    assert "source_updated" in actions
    assert "source_deleted" in actions


def test_audit_log_requires_quellen_pfleger(anon_client):
    login(anon_client, "someone@test.local")

    response = anon_client.get("/api/audit-log")

    assert response.status_code == 403


def test_delete_source_removes_it(client):
    create_res = client.post("/api/sources", json={"title": "Löschmich", "text": "Text."})
    source_id = create_res.json()["id"]

    response = client.delete(f"/api/sources/{source_id}")

    assert response.status_code == 204
    titles = [s["title"] for s in client.get("/api/sources").json()]
    assert "Löschmich" not in titles


def test_delete_source_cleans_up_chunks_and_author(client):
    create_res = client.post(
        "/api/sources", json={"title": "Löschmich", "authors": ["Jane Doe"], "text": "Text."}
    )
    source_id = create_res.json()["id"]

    client.delete(f"/api/sources/{source_id}")

    assert client.get("/api/authors").json() == []
    result = vectorstore.query([1.0, 0.0], top_k=5)
    assert result["ids"][0] == []


def test_delete_source_returns_404_for_unknown_id(client):
    response = client.delete("/api/sources/does-not-exist")
    assert response.status_code == 404


def test_delete_source_without_role_is_forbidden(client, anon_client):
    create_res = client.post("/api/sources", json={"title": "Bleibt", "text": "Text."})
    source_id = create_res.json()["id"]

    response = anon_client.delete(f"/api/sources/{source_id}")

    assert response.status_code == 403
    titles = [s["title"] for s in client.get("/api/sources").json()]
    assert "Bleibt" in titles


def test_restricted_source_hides_text_from_anon(client, anon_client):
    client.post(
        "/api/sources",
        json={"title": "Geschützt", "text": "Urheberrechtlich geschützter Inhalt.", "restricted": True},
    )

    sources = anon_client.get("/api/sources").json()

    assert sources[0]["restricted"] is True
    assert sources[0]["text"] == ""


def test_restricted_source_shows_full_text_to_pfleger(client):
    client.post(
        "/api/sources",
        json={"title": "Geschützt", "text": "Urheberrechtlich geschützter Inhalt.", "restricted": True},
    )

    sources = client.get("/api/sources").json()

    assert sources[0]["restricted"] is True
    assert sources[0]["text"] == "Urheberrechtlich geschützter Inhalt."


def test_list_sources_with_include_text_false_omits_text(client):
    client.post("/api/sources", json={"title": "Quelle", "text": "Ein längerer Volltext."})

    sources = client.get("/api/sources?include_text=false").json()

    assert sources[0]["title"] == "Quelle"
    assert sources[0]["text"] == ""


def test_list_sources_include_text_false_still_hides_restricted_relevance_fields(client, anon_client):
    client.post(
        "/api/sources",
        json={"title": "Geschützt", "text": "Geheim.", "restricted": True, "relevance_score": 8},
    )

    sources = anon_client.get("/api/sources?include_text=false").json()

    assert sources[0]["text"] == ""
    assert sources[0]["relevance_score"] is None


def test_list_sources_defaults_to_include_text_true(client):
    client.post("/api/sources", json={"title": "Quelle", "text": "Ein längerer Volltext."})

    sources = client.get("/api/sources").json()

    assert sources[0]["text"] == "Ein längerer Volltext."


def test_restricted_source_still_used_for_answers(client):
    client.post(
        "/api/sources",
        json={"title": "Geschützt", "text": "Urheberrechtlich geschützter Inhalt.", "restricted": True},
    )

    response = client.post("/api/ask", json={"question": "Frage?"})

    assert response.status_code == 200
    assert ask_result(response)["sources"][0]["text"] == "Urheberrechtlich geschützter Inhalt."


def test_update_restricted_source_with_empty_text_keeps_stored_text(client):
    create_res = client.post(
        "/api/sources",
        json={"title": "Alt", "text": "Geheimer Originaltext.", "restricted": True},
    )
    source_id = create_res.json()["id"]

    update_res = client.put(
        f"/api/sources/{source_id}",
        json={"title": "Neu", "text": "", "restricted": True},
    )

    assert update_res.status_code == 200
    assert update_res.json()["title"] == "Neu"
    assert update_res.json()["text"] == "Geheimer Originaltext."

    result = vectorstore.query([1.0, 0.0], top_k=5)
    assert result["documents"][0][0] == "Geheimer Originaltext."


def test_update_restricted_source_with_new_text_replaces_it(client):
    create_res = client.post(
        "/api/sources",
        json={"title": "Alt", "text": "Alter Text.", "restricted": True},
    )
    source_id = create_res.json()["id"]

    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Alt", "text": "Ersetzter Text.", "restricted": True},
    )

    result = vectorstore.query([1.0, 0.0], top_k=5)
    assert result["documents"][0][0] == "Ersetzter Text."


def test_generate_source_summary_returns_ai_result(client, monkeypatch):
    create_res = client.post(
        "/api/sources",
        json={"title": "Ohne Zusammenfassung", "text": "Ein längerer Quelltext."},
    )
    source_id = create_res.json()["id"]

    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "KI-Zusammenfassung.", "key_terms": ["Begriff A", "Begriff B"]},
            "en": {"summary": "AI summary.", "key_terms": ["Term A", "Term B"]},
        },
    )

    response = client.post(f"/api/sources/{source_id}/generate-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "KI-Zusammenfassung."
    assert data["key_terms"] == ["Begriff A", "Begriff B"]

    response_en = client.post(
        f"/api/sources/{source_id}/generate-summary", headers={"X-Lang": "en"}
    )
    assert response_en.json()["summary"] == "AI summary."
    assert response_en.json()["key_terms"] == ["Term A", "Term B"]


def test_generate_source_summary_requires_pfleger_role(client, anon_client):
    create_res = client.post(
        "/api/sources",
        json={"title": "Quelle", "text": "Text."},
    )
    source_id = create_res.json()["id"]

    response = anon_client.post(f"/api/sources/{source_id}/generate-summary")

    assert response.status_code == 403


def test_generate_source_summary_unknown_source_returns_404(client):
    response = client.post("/api/sources/does-not-exist/generate-summary")
    assert response.status_code == 404


def test_update_source_summary_edit_marks_language_as_not_ai_generated(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "text": "Text.", "summary": "Von Hand überarbeitet."},
    )

    stored = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert stored["summary"] == "Von Hand überarbeitet."
    assert stored["summary_ai_generated"] is False


def test_update_source_summary_edit_triggers_background_translation(client, monkeypatch):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    calls = []
    monkeypatch.setattr(
        summarization, "translate_summary", lambda text, target_lang="de": calls.append((text, target_lang)) or "Translated."
    )

    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "text": "Text.", "summary": "Von Hand überarbeitet."},
    )

    assert calls == [("Von Hand überarbeitet.", "en")]
    stored_en = client.get("/api/sources", headers={"X-Lang": "en"}).json()
    stored_en = next(s for s in stored_en if s["id"] == source_id)
    assert stored_en["summary"] == "Translated."
    assert stored_en["summary_ai_generated"] is False


def test_update_source_summary_edit_does_not_translate_when_summary_unset(client, monkeypatch):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    calls = []
    monkeypatch.setattr(summarization, "translate_summary", lambda text, target_lang="de": calls.append(text))

    client.put(f"/api/sources/{source_id}", json={"title": "Neuer Titel", "text": "Text."})

    assert calls == []


def test_update_source_summary_edit_skips_translation_when_result_empty(client, monkeypatch):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    monkeypatch.setattr(summarization, "translate_summary", lambda text, target_lang="de": "")

    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "text": "Text.", "summary": "Von Hand überarbeitet."},
    )

    stored_en = next(
        s for s in client.get("/api/sources", headers={"X-Lang": "en"}).json() if s["id"] == source_id
    )
    assert stored_en["summary"] == ""
    assert stored_en["summary_ai_generated"] is True


def test_translate_summary_background_does_not_overwrite_newer_manual_edit(client, monkeypatch):
    """Race-Schutz: läuft die Übersetzung noch, während die Zielsprache
    inzwischen selbst von Hand überarbeitet wurde, darf die Übersetzung die
    frische manuelle Fassung nicht kommentarlos überschreiben."""
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    main_module._translate_summary_background(source_id, "Alte Übersetzungsgrundlage.", "en")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(summarization, "translate_summary", lambda text, target_lang="de": "Verspätete Übersetzung.")
        # Zielsprache "en" wurde inzwischen (simuliert) von Hand überarbeitet.
        client.put(
            f"/api/sources/{source_id}",
            json={"title": "Quelle", "text": "Text.", "summary": "Frisch von Hand auf Englisch."},
            headers={"X-Lang": "en"},
        )
        main_module._translate_summary_background(source_id, "Alte Übersetzungsgrundlage.", "en")

    stored_en = next(
        s for s in client.get("/api/sources", headers={"X-Lang": "en"}).json() if s["id"] == source_id
    )
    assert stored_en["summary"] == "Frisch von Hand auf Englisch."
    assert stored_en["summary_ai_generated"] is False


def test_generate_source_summary_skips_manually_edited_language(client, monkeypatch):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "text": "Text.", "summary": "Von Hand überarbeitet (Deutsch)."},
    )
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "Neue KI-Zusammenfassung.", "key_terms": ["Neu"]},
            "en": {"summary": "New AI summary.", "key_terms": ["New"]},
        },
    )

    response_de = client.post(f"/api/sources/{source_id}/generate-summary")
    response_en = client.post(f"/api/sources/{source_id}/generate-summary", headers={"X-Lang": "en"})

    assert response_de.json()["summary"] == "Von Hand überarbeitet (Deutsch)."
    assert response_en.json()["summary"] == "New AI summary."
    stored = client.get("/api/sources").json()
    stored = next(s for s in stored if s["id"] == source_id)
    assert stored["summary_ai_generated"] is False


def test_generate_source_summary_skips_api_call_when_both_languages_protected(client, monkeypatch):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "text": "Text.", "summary": "Deutsch von Hand."},
    )
    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "text": "Text.", "summary": "English by hand."},
        headers={"X-Lang": "en"},
    )

    def fail_if_called(text):
        raise AssertionError("generate_bilingual_summary hätte nicht aufgerufen werden dürfen")

    monkeypatch.setattr(summarization, "generate_bilingual_summary", fail_if_called)

    response = client.post(f"/api/sources/{source_id}/generate-summary")

    assert response.status_code == 200
    assert response.json()["summary"] == "Deutsch von Hand."


def test_list_authors_includes_empty_profile_fields_by_default(client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    response = client.get("/api/authors")

    assert response.status_code == 200
    entry = next(a for a in response.json() if a["name"] == "Jane Doe")
    assert entry["bio"] == ""
    assert entry["photo_url"] == ""
    assert entry["website"] == ""
    assert entry["social_links"] == []


def test_update_author_profile_requires_pfleger_role(client, anon_client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    response = anon_client.put("/api/authors/Jane Doe", json={"bio": "Vita."})

    assert response.status_code == 403


def test_update_author_profile_unknown_author_returns_404(client):
    response = client.put("/api/authors/Does Not Exist", json={"bio": "Vita."})
    assert response.status_code == 404


def test_update_author_profile_updates_bio_and_links(client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    response = client.put(
        "/api/authors/Jane Doe",
        json={
            "bio": "Kurze Vita.",
            "photo_url": "https://example.org/foto.jpg",
            "website": "https://example.org",
            "social_links": [{"platform": "LinkedIn", "url": "https://linkedin.com/in/jane"}],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["bio"] == "Kurze Vita."
    assert data["photo_url"] == "https://example.org/foto.jpg"
    assert data["website"] == "https://example.org"
    assert data["social_links"] == [{"platform": "LinkedIn", "url": "https://linkedin.com/in/jane"}]

    listed = next(a for a in client.get("/api/authors").json() if a["name"] == "Jane Doe")
    assert listed["bio"] == "Kurze Vita."


def test_update_author_profile_partial_update_preserves_other_fields(client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})
    client.put("/api/authors/Jane Doe", json={"bio": "Erste Vita.", "website": "https://jane.example"})

    response = client.put("/api/authors/Jane Doe", json={"bio": "Aktualisierte Vita."})

    assert response.status_code == 200
    data = response.json()
    assert data["bio"] == "Aktualisierte Vita."
    assert data["website"] == "https://jane.example"


def test_rename_author_updates_sources_and_registry(client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})
    client.put("/api/authors/Jane Doe", json={"bio": "Vita von Jane."})

    response = client.post("/api/authors/Jane Doe/rename", json={"new_name": "Jane Smith"})

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Jane Smith"
    assert data["bio"] == "Vita von Jane."

    names = {a["name"] for a in client.get("/api/authors").json()}
    assert "Jane Smith" in names
    assert "Jane Doe" not in names

    source = client.get("/api/sources").json()[0]
    assert source["authors"] == ["Jane Smith"]


def test_rename_author_preserves_coauthors(client):
    client.post(
        "/api/sources",
        json={"title": "Quelle", "authors": ["Jane Doe", "John Roe"], "text": "Text."},
    )

    client.post("/api/authors/Jane Doe/rename", json={"new_name": "Jane Smith"})

    source = client.get("/api/sources").json()[0]
    assert set(source["authors"]) == {"Jane Smith", "John Roe"}


def test_rename_author_deduplicates_when_merging_into_existing_coauthor(client):
    client.post(
        "/api/sources",
        json={"title": "Quelle", "authors": ["Jane Doe", "Jane Smith"], "text": "Text."},
    )

    client.post("/api/authors/Jane Doe/rename", json={"new_name": "Jane Smith"})

    source = client.get("/api/sources").json()[0]
    assert source["authors"] == ["Jane Smith"]


def test_rename_author_requires_pfleger_role(client, anon_client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    response = anon_client.post("/api/authors/Jane Doe/rename", json={"new_name": "Jane Smith"})

    assert response.status_code == 403


def test_rename_author_unknown_author_returns_404(client):
    response = client.post("/api/authors/Does Not Exist/rename", json={"new_name": "New Name"})
    assert response.status_code == 404


def test_rename_author_rejects_empty_new_name(client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    response = client.post("/api/authors/Jane Doe/rename", json={"new_name": "   "})

    assert response.status_code == 400


def test_generate_author_bio_returns_ai_result(client, monkeypatch):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})
    monkeypatch.setattr(
        summarization, "generate_author_bio", lambda name, texts, lang="de": "KI-Vita."
    )

    response = client.post("/api/authors/Jane Doe/generate-bio")

    assert response.status_code == 200
    assert response.json()["bio"] == "KI-Vita."
    listed = next(a for a in client.get("/api/authors").json() if a["name"] == "Jane Doe")
    assert listed["bio"] == "KI-Vita."
    assert listed["bio_ai_generated"] is True


def test_update_author_profile_clears_ai_flag_when_bio_text_changes(client, monkeypatch):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})
    monkeypatch.setattr(
        summarization, "generate_author_bio", lambda name, texts, lang="de": "KI-Vita."
    )
    client.post("/api/authors/Jane Doe/generate-bio")

    response = client.put("/api/authors/Jane Doe", json={"bio": "Von Hand überarbeitete Vita."})

    assert response.status_code == 200
    assert response.json()["bio_ai_generated"] is False


def test_list_authors_resolves_bio_per_language(client, monkeypatch):
    # Backlog-Fix: die Vita ist seit der Sprachumschaltung bilingual
    # gespeichert (bio_de/bio_en) - GET /api/authors muss je nach X-Lang die
    # jeweils passende Sprachversion (plus deren eigenes bio_ai_generated-Flag)
    # zurückgeben, nicht immer dieselbe.
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})
    client.put(
        "/api/authors/Jane Doe", json={"bio": "Deutsche Vita."}, headers={"X-Lang": "de"}
    )
    client.put(
        "/api/authors/Jane Doe", json={"bio": "English bio."}, headers={"X-Lang": "en"}
    )

    listed_de = next(a for a in client.get("/api/authors", headers={"X-Lang": "de"}).json() if a["name"] == "Jane Doe")
    listed_en = next(a for a in client.get("/api/authors", headers={"X-Lang": "en"}).json() if a["name"] == "Jane Doe")

    assert listed_de["bio"] == "Deutsche Vita."
    assert listed_en["bio"] == "English bio."


def test_update_author_profile_writes_only_current_language_bio(client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    client.put("/api/authors/Jane Doe", json={"bio": "Deutsche Vita."}, headers={"X-Lang": "de"})
    response = client.put("/api/authors/Jane Doe", json={"bio": "English bio."}, headers={"X-Lang": "en"})

    assert response.json()["bio"] == "English bio."
    listed_de = next(a for a in client.get("/api/authors", headers={"X-Lang": "de"}).json() if a["name"] == "Jane Doe")
    assert listed_de["bio"] == "Deutsche Vita."


def test_generate_author_bio_endpoint_writes_only_current_language(client, monkeypatch):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})
    monkeypatch.setattr(
        summarization,
        "generate_author_bio",
        lambda name, texts, lang="de": f"Vita ({lang}).",
    )

    client.post("/api/authors/Jane Doe/generate-bio", headers={"X-Lang": "en"})

    listed_de = next(a for a in client.get("/api/authors", headers={"X-Lang": "de"}).json() if a["name"] == "Jane Doe")
    listed_en = next(a for a in client.get("/api/authors", headers={"X-Lang": "en"}).json() if a["name"] == "Jane Doe")
    assert listed_de["bio"] == ""
    assert listed_en["bio"] == "Vita (en)."
    assert listed_en["bio_ai_generated"] is True


def test_generate_author_bio_background_generates_both_languages(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        summarization,
        "generate_author_bio",
        lambda name, texts, lang="de": calls.append(lang) or f"Vita ({lang}).",
    )

    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    assert sorted(calls) == ["de", "en"]
    listed_de = next(a for a in client.get("/api/authors", headers={"X-Lang": "de"}).json() if a["name"] == "Jane Doe")
    listed_en = next(a for a in client.get("/api/authors", headers={"X-Lang": "en"}).json() if a["name"] == "Jane Doe")
    assert listed_de["bio"] == "Vita (de)."
    assert listed_en["bio"] == "Vita (en)."


def test_generate_author_bio_requires_pfleger_role(client, anon_client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    response = anon_client.post("/api/authors/Jane Doe/generate-bio")

    assert response.status_code == 403


def test_generate_author_bio_unknown_author_returns_404(client):
    response = client.post("/api/authors/Does Not Exist/generate-bio")
    assert response.status_code == 404


def test_generate_author_bio_preview_works_for_unregistered_author(client, monkeypatch):
    # Backlog #86: KI-Vita-Vorschlag für eine gerade erst im Formular
    # eingetragene, noch nicht gespeicherte Person - _find_author kennt sie
    # noch nicht, der Vorschlag stützt sich stattdessen auf den aktuell im
    # Formular stehenden Text.
    monkeypatch.setattr(
        summarization,
        "generate_author_bio",
        lambda name, texts, lang="de": f"Vita für {name} aus: {texts[0]}",
    )

    response = client.post(
        "/api/authors/generate-bio-preview",
        json={"name": "Neue Person", "text": "Titel: Zusammenfassung."},
    )

    assert response.status_code == 200
    assert response.json()["bio"] == "Vita für Neue Person aus: Titel: Zusammenfassung."


def test_generate_author_bio_preview_does_not_persist_profile(client, monkeypatch):
    monkeypatch.setattr(
        summarization, "generate_author_bio", lambda name, texts, lang="de": "KI-Vita."
    )

    client.post(
        "/api/authors/generate-bio-preview",
        json={"name": "Neue Person", "text": "Text."},
    )

    assert all(a["name"] != "Neue Person" for a in client.get("/api/authors").json())


def test_generate_author_bio_preview_requires_pfleger_role(anon_client):
    response = anon_client.post(
        "/api/authors/generate-bio-preview",
        json={"name": "Neue Person", "text": "Text."},
    )

    assert response.status_code == 403


def test_generate_key_terms_preview_derives_from_given_text(client, monkeypatch):
    # Backlog: Begriffsliste soll aus dem aktuell im Formular stehenden
    # (ggf. von Hand überarbeiteten) Zusammenfassungstext ableitbar sein,
    # ohne die gespeicherte Quelle oder deren Zusammenfassung anzurühren.
    monkeypatch.setattr(
        summarization,
        "extract_key_terms",
        lambda text, lang="de": [f"Begriff aus: {text}"],
    )

    response = client.post(
        "/api/sources/generate-key-terms-preview",
        json={"text": "Eine von Hand geschriebene Zusammenfassung."},
    )

    assert response.status_code == 200
    assert response.json()["key_terms"] == ["Begriff aus: Eine von Hand geschriebene Zusammenfassung."]


def test_generate_key_terms_preview_does_not_persist_anything(client, monkeypatch):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "text": "Text.", "summary": "Alte Zusammenfassung.", "key_terms": ["Alt"]},
    )
    monkeypatch.setattr(summarization, "extract_key_terms", lambda text, lang="de": ["Neu"])

    client.post(
        "/api/sources/generate-key-terms-preview",
        json={"text": "Andere Zusammenfassung."},
    )

    stored = client.get("/api/sources").json()
    source = next(s for s in stored if s["id"] == source_id)
    assert source["summary"] == "Alte Zusammenfassung."
    assert source["key_terms"] == ["Alt"]


def test_generate_key_terms_preview_requires_pfleger_role(anon_client):
    response = anon_client.post(
        "/api/sources/generate-key-terms-preview",
        json={"text": "Text."},
    )

    assert response.status_code == 403


def test_add_source_auto_generates_bio_for_new_author(client, monkeypatch):
    monkeypatch.setattr(
        summarization, "generate_author_bio", lambda name, texts, lang="de": "Automatische Vita."
    )

    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    listed = next(a for a in client.get("/api/authors").json() if a["name"] == "Jane Doe")
    assert listed["bio"] == "Automatische Vita."
    assert listed["bio_ai_generated"] is True


def test_generate_author_bio_background_does_not_overwrite_bio_saved_during_ai_call(client, monkeypatch):
    # Regressionstest für Backlog #86: das "Autorenprofil pflegen"-Panel im
    # Anlegen-Formular sendet direkt nach dem Anlegen der Quelle ein PUT mit
    # der von Hand eingegebenen Vita. Der KI-Aufruf zur automatischen
    # Vita-Generierung läuft im selben Moment im Hintergrund und dauert
    # länger - schreibt er NACH dem manuellen PUT, darf er die von Hand
    # gepflegte Vita nicht mehr überschreiben (siehe zweite Prüfung in
    # _generate_author_bio_background unmittelbar vor dem Schreiben).
    def fake_generate_author_bio(name, texts, lang="de"):
        client.put(f"/api/authors/{name}", json={"bio": "Manuell gepflegte Vita."})
        return "Automatische Vita."

    monkeypatch.setattr(summarization, "generate_author_bio", fake_generate_author_bio)

    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})

    listed = next(a for a in client.get("/api/authors").json() if a["name"] == "Jane Doe")
    assert listed["bio"] == "Manuell gepflegte Vita."
    assert listed["bio_ai_generated"] is not True


def test_add_source_does_not_regenerate_bio_for_already_known_author(client, monkeypatch):
    # Seit der bilingualen Vita wird pro neuer Person zweimal generiert
    # (einmal je Sprache, siehe _generate_author_bio_background) - die
    # zweite Quelle mit derselben, bereits bekannten Person darf aber
    # keinen weiteren Aufruf auslösen.
    calls = []
    monkeypatch.setattr(
        summarization,
        "generate_author_bio",
        lambda name, texts, lang="de": calls.append(name) or "Automatische Vita.",
    )

    client.post("/api/sources", json={"title": "Erste Quelle", "authors": ["Jane Doe"], "text": "Text."})
    client.post("/api/sources", json={"title": "Zweite Quelle", "authors": ["Jane Doe"], "text": "Text."})

    assert calls == ["Jane Doe", "Jane Doe"]


def test_add_source_does_not_generate_bio_for_empty_author_name(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        summarization,
        "generate_author_bio",
        lambda name, texts, lang="de": calls.append(name) or "Vita.",
    )

    client.post("/api/sources", json={"title": "Quelle", "authors": [""], "text": "Text."})

    assert calls == []


def test_update_source_auto_generates_bio_only_for_newly_added_author(client, monkeypatch):
    calls = []
    monkeypatch.setattr(
        summarization,
        "generate_author_bio",
        lambda name, texts, lang="de": calls.append(name) or "Vita.",
    )
    create_res = client.post(
        "/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."}
    )
    source_id = create_res.json()["id"]
    calls.clear()

    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "authors": ["Jane Doe", "Neue Person"], "text": "Text."},
    )

    assert calls == ["Neue Person", "Neue Person"]


def test_update_source_does_not_treat_authors_sole_source_edit_as_new(client, monkeypatch):
    # Regressionstest: unregister_source() (vor dem Neu-Registrieren in
    # update_source) löscht den Registry-Eintrag einer Person kurzzeitig,
    # wenn dies ihre einzige Quelle war - das darf nicht dazu führen, dass
    # eine bereits vorhandene Vita durch eine neu generierte überschrieben wird.
    monkeypatch.setattr(
        summarization, "generate_author_bio", lambda name, texts, lang="de": "Sollte nicht erscheinen."
    )
    create_res = client.post(
        "/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."}
    )
    source_id = create_res.json()["id"]
    client.put("/api/authors/Jane Doe", json={"bio": "Von Hand gepflegte Vita."})

    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Aktualisierter Titel", "authors": ["Jane Doe"], "text": "Text."},
    )

    listed = next(a for a in client.get("/api/authors").json() if a["name"] == "Jane Doe")
    assert listed["bio"] == "Von Hand gepflegte Vita."


def test_extract_pdf_upload_returns_extracted_fields(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_pdf",
        lambda data: {
            "title": "PDF-Titel",
            "authors": ["PDF-Autor"],
            "date": "2023-01-01",
            "text": "PDF-Inhalt.",
            "extracted": True,
        },
    )

    response = client.post(
        "/api/extract-pdf-upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "PDF-Titel"
    assert data["extracted"] is True
    assert data["upload_id"]


def test_extract_pdf_upload_without_role_is_forbidden(anon_client):
    response = anon_client.post(
        "/api/extract-pdf-upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert response.status_code == 403


def test_add_source_with_pdf_upload_id_persists_file(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_pdf",
        lambda data: {
            "title": "PDF-Titel",
            "authors": [],
            "date": "",
            "text": "PDF-Inhalt.",
            "extracted": True,
        },
    )
    upload_res = client.post(
        "/api/extract-pdf-upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    upload_id = upload_res.json()["upload_id"]

    create_res = client.post(
        "/api/sources",
        json={"title": "Aus PDF", "text": "PDF-Inhalt.", "pdf_upload_id": upload_id},
    )

    source_id = create_res.json()["id"]
    assert (main_module.PDF_DIR / f"{source_id}.pdf").exists()
    assert not (main_module.PDF_UPLOAD_STAGING_DIR / f"{upload_id}.pdf").exists()

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["has_pdf"] is True


def test_add_source_rejects_pdf_upload_id_with_missing_staged_file(client):
    """Regressionstest (Bug 2026-08-23, per realem Produktions-Vorfall): ein
    pdf_upload_id, dessen hochgeladene Datei nicht mehr existiert (z.B.
    bereits verwendeter/veralteter Wert), führte bisher klaglos zu einer
    angelegten Quelle, deren Hintergrund-OCR-Job garantiert scheitert - mit
    der irreführenden Meldung "Texterkennung fehlgeschlagen", obwohl die
    KI-Texterkennung nie aufgerufen wurde. add_source() muss das synchron
    UND FRÜH ablehnen, statt eine zum Scheitern verurteilte Quelle
    anzulegen."""
    response = client.post(
        "/api/sources",
        json={"title": "Aus PDF", "text": "", "pdf_upload_id": "nie-hochgeladen"},
    )

    assert response.status_code == 400
    assert client.get("/api/sources").json() == []


def test_add_source_with_pdf_upload_id_and_manual_text_still_validates_upload(client):
    """Die Prüfung greift unabhängig davon, ob gleichzeitig schon Text
    manuell eingegeben wurde (dann wäre die Quelle selbst nicht "deferred",
    die PDF-Datei würde aber trotzdem nie existieren)."""
    response = client.post(
        "/api/sources",
        json={"title": "Aus PDF", "text": "Von Hand eingegeben.", "pdf_upload_id": "nie-hochgeladen"},
    )

    assert response.status_code == 400


def test_extract_audio_upload_returns_immediately_without_transcribing(client, monkeypatch):
    # Transkription kann Minuten dauern und läuft deshalb erst als
    # Hintergrund-Job nach dem Anlegen der Quelle - die Upload-Vorschau
    # darf transcribe_audio gar nicht erst aufrufen.
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("transcribe_audio darf beim Upload-Preview nicht aufgerufen werden")

    monkeypatch.setattr(extraction, "transcribe_audio", _fail_if_called)

    response = client.post(
        "/api/extract-audio-upload",
        files={"file": ("episode.mp3", b"fake-mp3-bytes", "audio/mpeg")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Episode"
    assert data["text"] == ""
    assert data["extracted"] is False
    assert data["upload_id"]


def test_extract_audio_upload_without_role_is_forbidden(anon_client):
    response = anon_client.post(
        "/api/extract-audio-upload",
        files={"file": ("episode.mp3", b"fake-mp3-bytes", "audio/mpeg")},
    )
    assert response.status_code == 403


def test_add_source_with_audio_upload_id_persists_file(client, monkeypatch):
    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("Transkribierter Text.", None))
    upload_res = client.post(
        "/api/extract-audio-upload",
        files={"file": ("episode.mp3", b"fake-mp3-bytes", "audio/mpeg")},
    )
    upload_id = upload_res.json()["upload_id"]

    create_res = client.post(
        "/api/sources",
        json={"title": "Aus Audio", "text": "Transkribierter Text.", "audio_upload_id": upload_id},
    )

    source_id = create_res.json()["id"]
    stored = list(main_module.AUDIO_DIR.glob(f"{source_id}.*"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == b"fake-mp3-bytes"
    assert not list(main_module.AUDIO_UPLOAD_STAGING_DIR.glob(f"{upload_id}.*"))

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["has_audio"] is True


def test_get_source_audio_returns_file_content(client, monkeypatch):
    monkeypatch.setattr(extraction, "transcribe_audio", lambda path, **kw: ("Transkribierter Text.", None))
    upload_res = client.post(
        "/api/extract-audio-upload",
        files={"file": ("episode.mp3", b"fake-mp3-bytes", "audio/mpeg")},
    )
    upload_id = upload_res.json()["upload_id"]
    create_res = client.post(
        "/api/sources",
        json={"title": "Aus Audio", "text": "Transkribierter Text.", "audio_upload_id": upload_id},
    )
    source_id = create_res.json()["id"]

    response = client.get(f"/api/sources/{source_id}/audio")

    assert response.status_code == 200
    assert response.content == b"fake-mp3-bytes"
    assert response.headers["content-type"] == "audio/mpeg"


def test_get_source_audio_requires_pfleger_role(client, anon_client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    response = anon_client.get(f"/api/sources/{source_id}/audio")

    assert response.status_code == 403


def test_get_source_audio_returns_404_without_audio_file(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    response = client.get(f"/api/sources/{source_id}/audio")

    assert response.status_code == 404


def test_source_without_pdf_reports_has_pdf_false(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["has_pdf"] is False


def test_get_source_pdf_returns_file_content(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_pdf",
        lambda data: {"title": "PDF-Titel", "authors": [], "date": "", "text": "PDF-Inhalt.", "extracted": True},
    )
    upload_res = client.post(
        "/api/extract-pdf-upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    upload_id = upload_res.json()["upload_id"]
    create_res = client.post(
        "/api/sources",
        json={"title": "Aus PDF", "text": "PDF-Inhalt.", "pdf_upload_id": upload_id},
    )
    source_id = create_res.json()["id"]

    response = client.get(f"/api/sources/{source_id}/pdf")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 fake"
    assert response.headers["content-type"] == "application/pdf"


def test_get_source_pdf_requires_pfleger_role(client, anon_client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    response = anon_client.get(f"/api/sources/{source_id}/pdf")

    assert response.status_code == 403


def test_get_source_pdf_returns_404_when_no_pdf_stored(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    response = client.get(f"/api/sources/{source_id}/pdf")

    assert response.status_code == 404


def test_check_source_url_reports_reachability(client, monkeypatch):
    create_res = client.post(
        "/api/sources",
        json={"title": "Mit URL", "url": "https://example.org", "text": "Text."},
    )
    source_id = create_res.json()["id"]

    monkeypatch.setattr(
        monitoring,
        "check_url",
        lambda url: {"reachable": False, "status_code": 404, "reason_code": "http_error"},
    )

    response = client.get(f"/api/sources/{source_id}/check-url")

    assert response.status_code == 200
    data = response.json()
    assert data["has_url"] is True
    assert data["reachable"] is False
    assert data["status_code"] == 404
    assert data["reason_code"] == "http_error"


def test_check_source_url_without_url_reports_has_url_false(client):
    create_res = client.post("/api/sources", json={"title": "Ohne URL", "text": "Text."})
    source_id = create_res.json()["id"]

    response = client.get(f"/api/sources/{source_id}/check-url")

    assert response.status_code == 200
    assert response.json() == {
        "has_url": False,
        "reachable": None,
        "status_code": None,
        "reason_code": None,
    }


def test_check_source_url_without_role_is_forbidden(client, anon_client):
    create_res = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]

    response = anon_client.get(f"/api/sources/{source_id}/check-url")

    assert response.status_code == 403


def _mark_source_link_broken(source_id: str) -> None:
    sources = main_module._load_sources()
    sources[source_id]["url_reachable"] = False
    sources[source_id]["url_reason_code"] = "http_error"
    sources[source_id]["url_status_code"] = 404
    sources[source_id]["url_checked_at"] = "2026-01-01T00:00:00+00:00"
    main_module._save_sources(sources)


def test_verify_source_link_marks_broken_link_as_reachable(client):
    # Nutzerwunsch (2026-09-01, real gemeldet): der automatische Link-Check
    # meldet gelegentlich fälschlich einen funktionierenden Link als nicht
    # erreichbar - Quellen-Pfleger:innen können ihn nach eigener manueller
    # Prüfung selbst wieder als in Ordnung markieren.
    source_id = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    ).json()["id"]
    _mark_source_link_broken(source_id)

    response = client.post(f"/api/sources/{source_id}/verify-link")

    assert response.status_code == 200
    entry = main_module._load_sources()[source_id]
    assert entry["url_reachable"] is True
    assert entry["url_reason_code"] is None
    assert entry["url_status_code"] is None


def test_verify_source_link_rejects_when_link_not_currently_broken(client):
    source_id = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    ).json()["id"]

    response = client.post(f"/api/sources/{source_id}/verify-link")

    assert response.status_code == 400


def test_verify_source_link_requires_pfleger_role(client, anon_client):
    source_id = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    ).json()["id"]
    _mark_source_link_broken(source_id)

    response = anon_client.post(f"/api/sources/{source_id}/verify-link")

    assert response.status_code == 403


def test_verify_source_link_returns_404_for_unknown_source(client):
    response = client.post("/api/sources/does-not-exist/verify-link")

    assert response.status_code == 404


def test_verify_source_link_logs_revertible_audit_entry(client):
    source_id = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    ).json()["id"]
    _mark_source_link_broken(source_id)

    client.post(f"/api/sources/{source_id}/verify-link")

    entries = audit.list_entries()
    assert entries[0]["action"] == "source_link_manually_verified"
    assert entries[0]["entity_type"] == "source"
    assert entries[0]["entity_id"] == source_id
    assert entries[0]["revertible"] is True
    assert entries[0]["changes"]["url_reachable"] == {"old": False, "new": True}


def test_verify_source_link_can_be_reverted(client):
    source_id = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    ).json()["id"]
    _mark_source_link_broken(source_id)
    client.post(f"/api/sources/{source_id}/verify-link")
    entry_id = audit.list_entries()[0]["id"]

    response = client.post(f"/api/audit-log/{entry_id}/revert")

    assert response.status_code == 200
    entry = main_module._load_sources()[source_id]
    assert entry["url_reachable"] is False
    assert entry["url_reason_code"] == "http_error"
    assert entry["url_status_code"] == 404


def test_get_version_returns_a_string(client):
    response = client.get("/api/version")
    assert response.status_code == 200
    assert isinstance(response.json()["version"], str)
    assert response.json()["version"]


# Backlog #75: Embed-Snippet für die Konversationsansicht. Ohne gesetztes
# EMBED_ENABLED (Standardfall) bleibt /embed.html unerreichbar und der Footer-
# Link unsichtbar - analog zum Early-Access-Muster. Die "...by_default"-Tests
# unten setzen den Wert bewusst per monkeypatch.delenv explizit auf "nicht
# gesetzt", statt sich (wie ursprünglich) auf eine zufällig leere Ambient-
# Umgebungsvariable zu verlassen - Bug (2026-08-29): schlug plötzlich fehl,
# nachdem EMBED_ENABLED=true lokal in .env aktiviert wurde, da os.environ.get
# das reale Prozess-Environment liest, nicht nur die Testkonfiguration.


def test_version_reports_embed_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("EMBED_ENABLED", raising=False)
    response = client.get("/api/version")
    assert response.json()["embed_enabled"] is False


def test_version_reports_embed_enabled_when_flag_set(client, monkeypatch):
    monkeypatch.setenv("EMBED_ENABLED", "true")
    response = client.get("/api/version")
    assert response.json()["embed_enabled"] is True


def test_embed_page_returns_404_by_default(anon_client, monkeypatch):
    monkeypatch.delenv("EMBED_ENABLED", raising=False)
    response = anon_client.get("/embed.html")
    assert response.status_code == 404


def test_embed_page_reachable_when_flag_set(anon_client, monkeypatch):
    monkeypatch.setenv("EMBED_ENABLED", "true")
    response = anon_client.get("/embed.html")
    assert response.status_code == 200
    assert 'id="question-form"' in response.text


def test_embed_page_allows_framing_only_when_flag_set(anon_client, monkeypatch):
    monkeypatch.setenv("EMBED_ENABLED", "true")
    response = anon_client.get("/embed.html")
    assert "X-Frame-Options" not in response.headers
    assert "frame-ancestors *" in response.headers["Content-Security-Policy"]


def test_embed_page_stays_denied_when_flag_unset_even_if_file_requested(anon_client, monkeypatch):
    # /embed.html liefert zwar 404, aber die Sicherheits-Header-Middleware
    # greift trotzdem VOR der Route - stellt sicher, dass ein versehentlich
    # falsch konfigurierter Zustand nie "halb offen" ist.
    monkeypatch.delenv("EMBED_ENABLED", raising=False)
    response = anon_client.get("/embed.html")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_other_pages_stay_denied_even_when_embed_enabled(client, monkeypatch):
    monkeypatch.setenv("EMBED_ENABLED", "true")
    response = client.get("/")
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]


def test_get_turnstile_config_returns_configured_site_key(client, monkeypatch):
    monkeypatch.setattr(main_module, "TURNSTILE_SITE_KEY", "1x00000000000000000000AA")

    response = client.get("/api/turnstile-config")

    assert response.status_code == 200
    assert response.json() == {"site_key": "1x00000000000000000000AA"}


def test_get_turnstile_config_returns_empty_string_when_unset(client, monkeypatch):
    monkeypatch.setattr(main_module, "TURNSTILE_SITE_KEY", "")

    response = client.get("/api/turnstile-config")

    assert response.status_code == 200
    assert response.json() == {"site_key": ""}


def test_check_source_url_returns_404_for_unknown_source(client):
    response = client.get("/api/sources/does-not-exist/check-url")
    assert response.status_code == 404


def test_add_source_generates_summary_in_background_and_registers_terms(client, monkeypatch):
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {
                "summary": "Eine Zusammenfassung.",
                "key_terms": ["BetaCodex", "Dezentralisierung"],
            },
            "en": {"summary": "", "key_terms": []},
        },
    )

    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Ein Text."})

    assert create_res.status_code == 200
    data = create_res.json()
    # Die Zusammenfassung wird im Hintergrund generiert, damit die Antwort auf
    # /api/sources nicht auf den KI-Aufruf warten muss (schnellerer Import).
    assert data["summary"] == ""
    assert data["key_terms"] == []

    source_id = data["id"]
    updated = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert updated["summary"] == "Eine Zusammenfassung."
    assert set(updated["key_terms"]) == {"BetaCodex", "Dezentralisierung"}

    terms_res = client.get("/api/terms").json()
    term_names = {t["term"] for t in terms_res}
    assert term_names == {"BetaCodex", "Dezentralisierung"}


def test_generate_summary_with_retries_retries_on_total_failure(monkeypatch):
    """Vorfall (2026-08-03): generate_bilingual_summary() liefert bei einem
    echten Fehlschlag (API-Fehler, Rate-Limit) bewusst ein leeres Ergebnis
    statt eine Exception zu werfen (siehe app/summarization.py) - das muss
    hier als Fehlschlag erkannt und wiederholt werden, nicht als "nichts zu
    sagen" akzeptiert werden."""
    monkeypatch.setattr(main_module, "SUMMARY_RETRY_DELAY_SECONDS", 0)
    calls = []
    empty = {"de": {"summary": "", "key_terms": []}, "en": {"summary": "", "key_terms": []}}
    success = {
        "de": {"summary": "Erfolgreich.", "key_terms": ["X"]},
        "en": {"summary": "Success.", "key_terms": ["X"]},
    }

    def fake_generate(text):
        calls.append(text)
        return empty if len(calls) < 3 else success

    monkeypatch.setattr(summarization, "generate_bilingual_summary", fake_generate)

    result = main_module._generate_summary_with_retries("Ein Text.")

    assert result == success
    assert len(calls) == 3


def test_generate_summary_with_retries_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr(main_module, "SUMMARY_RETRY_DELAY_SECONDS", 0)
    calls = []
    empty = {"de": {"summary": "", "key_terms": []}, "en": {"summary": "", "key_terms": []}}

    def fake_generate(text):
        calls.append(text)
        return empty

    monkeypatch.setattr(summarization, "generate_bilingual_summary", fake_generate)

    result = main_module._generate_summary_with_retries("Ein Text.")

    assert result == empty
    assert len(calls) == main_module.SUMMARY_RETRY_ATTEMPTS


def test_backfill_missing_summaries_fills_in_gaps(client, monkeypatch):
    """Nutzerwunsch (2026-08-03): eine Quelle mit Text, aber ohne
    Zusammenfassung (z.B. aus der Zeit vor dem Retry-Fix, oder weil alle
    Retries damals fehlschlugen) soll beim naechsten Sweep automatisch
    nachgezogen werden."""
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Ein Text."})
    source_id = create_res.json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["summary_de"] = ""
    sources[source_id]["summary_en"] = ""
    main_module._save_sources(sources)

    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "Nachgezogen.", "key_terms": ["Y"]},
            "en": {"summary": "Backfilled.", "key_terms": ["Y"]},
        },
    )

    main_module._backfill_missing_summaries_once()

    updated = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert updated["summary"] == "Nachgezogen."


def test_backfill_missing_summaries_ignores_sources_without_text(client, monkeypatch):
    # z.B. eine noch textlose Audio-/PDF-Quelle, deren Verarbeitung noch
    # aussteht - fuer die gibt es (noch) nichts zu summarisieren.
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["text"] = ""
    sources[source_id]["summary_de"] = ""
    sources[source_id]["summary_en"] = ""
    main_module._save_sources(sources)

    calls = []
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: calls.append(text) or {"de": {"summary": "X", "key_terms": []}, "en": {"summary": "X", "key_terms": []}},
    )

    main_module._backfill_missing_summaries_once()

    assert calls == []


def test_backfill_missing_summaries_ignores_deleted_sources(client, monkeypatch):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["summary_de"] = ""
    sources[source_id]["summary_en"] = ""
    sources[source_id]["deleted_at"] = "2026-08-03T00:00:00+00:00"
    main_module._save_sources(sources)

    calls = []
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: calls.append(text) or {"de": {"summary": "X", "key_terms": []}, "en": {"summary": "X", "key_terms": []}},
    )

    main_module._backfill_missing_summaries_once()

    assert calls == []


def test_summary_is_served_in_the_requested_language(client, monkeypatch):
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "Deutsche Zusammenfassung.", "key_terms": ["BetaCodex"]},
            "en": {"summary": "English summary.", "key_terms": ["BetaCodex EN"]},
        },
    )
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Ein Text."})
    source_id = create_res.json()["id"]

    de_sources = client.get("/api/sources", headers={"X-Lang": "de"}).json()
    en_sources = client.get("/api/sources", headers={"X-Lang": "en"}).json()
    de_entry = next(s for s in de_sources if s["id"] == source_id)
    en_entry = next(s for s in en_sources if s["id"] == source_id)

    assert de_entry["summary"] == "Deutsche Zusammenfassung."
    assert de_entry["key_terms"] == ["BetaCodex"]
    assert en_entry["summary"] == "English summary."
    assert en_entry["key_terms"] == ["BetaCodex EN"]

    term_names = {t["term"] for t in client.get("/api/terms").json()}
    assert term_names == {"BetaCodex", "BetaCodex EN"}


def test_update_source_can_edit_summary_and_key_terms(client, monkeypatch):
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "Alte Zusammenfassung.", "key_terms": ["Alt"]},
            "en": {"summary": "", "key_terms": []},
        },
    )
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    update_res = client.put(
        f"/api/sources/{source_id}",
        json={
            "title": "Quelle",
            "text": "Text.",
            "summary": "Korrigierte Zusammenfassung.",
            "key_terms": ["Neu"],
        },
    )

    assert update_res.status_code == 200
    assert update_res.json()["summary"] == "Korrigierte Zusammenfassung."
    assert update_res.json()["key_terms"] == ["Neu"]

    term_names = {t["term"] for t in client.get("/api/terms").json()}
    assert term_names == {"Neu"}


def test_update_source_without_summary_field_keeps_existing_summary(client, monkeypatch):
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "Ursprüngliche Zusammenfassung.", "key_terms": ["Alt"]},
            "en": {"summary": "", "key_terms": []},
        },
    )
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    update_res = client.put(
        f"/api/sources/{source_id}",
        json={"title": "Neuer Titel", "text": "Text."},
    )

    assert update_res.json()["summary"] == "Ursprüngliche Zusammenfassung."
    assert update_res.json()["key_terms"] == ["Alt"]


def test_delete_source_removes_terms(client, monkeypatch):
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "S.", "key_terms": ["EinzigerBegriff"]},
            "en": {"summary": "", "key_terms": []},
        },
    )
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    client.delete(f"/api/sources/{source_id}")

    assert client.get("/api/terms").json() == []


def test_listen_url_persists_and_appears_in_ask_citation(client, monkeypatch):
    captured = {}

    def fake_answer(question, chunks, lang="de", author_bios=None, history=None):
        captured["lang"] = lang
        return iter(["Testantwort [1]."])

    monkeypatch.setattr(llm, "stream_answer_question", fake_answer)

    create_res = client.post(
        "/api/sources",
        json={
            "title": "Podcast-Folge",
            "url": "https://cdn.example.org/episode.mp3",
            "listen_url": "https://podcasts.example.org/episode-1",
            "text": "Inhalt der Folge.",
        },
    )
    assert create_res.json()["listen_url"] == "https://podcasts.example.org/episode-1"

    response = client.post("/api/ask", json={"question": "Worum geht es?"})
    assert response.status_code == 200
    source = ask_result(response)["sources"][0]
    assert source["listen_url"] == "https://podcasts.example.org/episode-1"
    assert source["url"] == "https://cdn.example.org/episode.mp3"


def test_add_source_with_audio_url_stores_audio_file(client, monkeypatch, tmp_path):
    monkeypatch.setattr(extraction, "looks_like_audio", lambda url: True)
    monkeypatch.setattr(extraction, "looks_like_pdf", lambda url: False)
    monkeypatch.setattr(extraction, "download_audio_bytes", lambda url: b"ID3-fake-audio-data")

    create_res = client.post(
        "/api/sources",
        json={
            "title": "Podcast-Folge",
            "url": "https://cdn.example.org/episode.mp3",
            "text": "Inhalt der Folge.",
        },
    )
    source_id = create_res.json()["id"]

    stored = list((main_module.AUDIO_DIR).glob(f"{source_id}.*"))
    assert len(stored) == 1
    assert stored[0].read_bytes() == b"ID3-fake-audio-data"


def test_source_with_audio_file_reports_has_audio_true(client, monkeypatch):
    monkeypatch.setattr(extraction, "looks_like_audio", lambda url: True)
    monkeypatch.setattr(extraction, "looks_like_pdf", lambda url: False)
    monkeypatch.setattr(extraction, "download_audio_bytes", lambda url: b"ID3-fake-audio-data")

    create_res = client.post(
        "/api/sources",
        json={
            "title": "Podcast-Folge",
            "url": "https://cdn.example.org/episode.mp3",
            "text": "Inhalt der Folge.",
        },
    )
    source_id = create_res.json()["id"]

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["has_audio"] is True


def test_source_without_audio_reports_has_audio_false(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    sources = client.get("/api/sources").json()
    entry = next(s for s in sources if s["id"] == source_id)
    assert entry["has_audio"] is False


def test_delete_source_keeps_audio_file_for_later_restore(client, monkeypatch):
    # Backlog #45/#99: weiches Löschen - eine angehängte Audiodatei bleibt
    # auf der Platte liegen, damit ein späteres Rückgängig-machen über das
    # Änderungs-Log die Quelle inklusive Datei wiederherstellen kann.
    monkeypatch.setattr(extraction, "looks_like_audio", lambda url: True)
    monkeypatch.setattr(extraction, "looks_like_pdf", lambda url: False)
    monkeypatch.setattr(extraction, "download_audio_bytes", lambda url: b"ID3-fake-audio-data")

    create_res = client.post(
        "/api/sources",
        json={
            "title": "Podcast-Folge",
            "url": "https://cdn.example.org/episode.mp3",
            "text": "Inhalt der Folge.",
        },
    )
    source_id = create_res.json()["id"]
    assert list(main_module.AUDIO_DIR.glob(f"{source_id}.*"))

    client.delete(f"/api/sources/{source_id}")

    assert list(main_module.AUDIO_DIR.glob(f"{source_id}.*"))


def test_security_headers_include_csp(client):
    response = client.get("/api/version")

    assert "Content-Security-Policy" in response.headers
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_unknown_static_path_returns_branded_404_page(client):
    response = client.get("/this-page-does-not-exist")

    assert response.status_code == 404
    assert "text/html" in response.headers["content-type"]
    assert 'data-i18n="error404.heading"' in response.text


def test_api_404_still_returns_json(client):
    response = client.get("/api/this-route-does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


# Backlog #45/#99: weiches Löschen + Änderungs-Log mit Rückgängig-Funktion.


def test_delete_source_soft_deletes_keeps_raw_record(client):
    create_res = client.post("/api/sources", json={"title": "Löschmich", "text": "Text zum Löschen."})
    source_id = create_res.json()["id"]

    client.delete(f"/api/sources/{source_id}")

    raw = json.loads(main_module.SOURCES_FILE.read_text())
    assert raw[source_id]["deleted_at"] is not None
    assert raw[source_id]["text"] == "Text zum Löschen."


def test_deleted_source_excluded_from_ask(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text zum Fragen."})
    source_id = create_res.json()["id"]
    client.delete(f"/api/sources/{source_id}")

    response = client.post("/api/ask", json={"question": "Frage?"})

    assert response.status_code == 400


def test_update_source_logs_only_changed_fields(client):
    create_res = client.post("/api/sources", json={"title": "Alt", "text": "Text.", "date": "2020-01-01"})
    source_id = create_res.json()["id"]

    client.put(f"/api/sources/{source_id}", json={"title": "Neu", "text": "Text.", "date": "2020-01-01"})

    entries = client.get("/api/audit-log").json()
    entry = next(e for e in entries if e["action"] == "source_updated")
    assert entry["changes"] == {"title": {"old": "Alt", "new": "Neu"}}
    assert entry["revertible"] is True
    assert entry["entity_type"] == "source"
    assert entry["entity_id"] == source_id


def test_update_source_with_no_actual_changes_does_not_log(client):
    create_res = client.post("/api/sources", json={"title": "Gleich", "text": "Text."})
    source_id = create_res.json()["id"]
    before_count = len(client.get("/api/audit-log").json())

    client.put(f"/api/sources/{source_id}", json={"title": "Gleich", "text": "Text."})

    assert len(client.get("/api/audit-log").json()) == before_count


def test_delete_source_logs_deleted_at_change(client):
    create_res = client.post("/api/sources", json={"title": "Löschmich", "text": "Text."})
    source_id = create_res.json()["id"]

    client.delete(f"/api/sources/{source_id}")

    entries = client.get("/api/audit-log").json()
    entry = next(e for e in entries if e["action"] == "source_deleted")
    assert entry["changes"]["deleted_at"]["old"] is None
    assert entry["changes"]["deleted_at"]["new"] is not None
    assert entry["revertible"] is True


def test_audit_log_includes_actor_name(client):
    users.set_name(PFLEGER, "Lena Pflegerin")

    client.post("/api/sources", json={"title": "Quelle", "text": "Text."})

    entries = client.get("/api/audit-log").json()
    assert entries[0]["actor_name"] == "Lena Pflegerin"


def test_revert_field_change_restores_old_value(client):
    create_res = client.post("/api/sources", json={"title": "Alt", "text": "Text."})
    source_id = create_res.json()["id"]
    client.put(f"/api/sources/{source_id}", json={"title": "Neu", "text": "Text."})
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "source_updated")

    response = client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 200
    source = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert source["title"] == "Alt"


def test_revert_text_change_rebuilds_chunks(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Einzigartiger Fakt Zyxwvu."})
    source_id = create_res.json()["id"]
    client.put(f"/api/sources/{source_id}", json={"title": "Quelle", "text": "Komplett anderer Inhalt."})
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "source_updated")

    response = client.post(f"/api/audit-log/{entry['id']}/revert")
    assert response.status_code == 200

    source = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert source["text"] == "Einzigartiger Fakt Zyxwvu."

    ask_response = client.post("/api/ask", json={"question": "Frage?"})
    assert ask_result(ask_response)["sources"][0]["text"] == "Einzigartiger Fakt Zyxwvu."


def test_revert_deletion_restores_source_and_file(client, monkeypatch):
    monkeypatch.setattr(extraction, "looks_like_audio", lambda url: True)
    monkeypatch.setattr(extraction, "looks_like_pdf", lambda url: False)
    monkeypatch.setattr(extraction, "download_audio_bytes", lambda url: b"ID3-fake-audio-data")
    create_res = client.post(
        "/api/sources",
        json={"title": "Podcast", "url": "https://cdn.example.org/ep.mp3", "text": "Inhalt der Folge."},
    )
    source_id = create_res.json()["id"]
    client.delete(f"/api/sources/{source_id}")
    assert all(s["id"] != source_id for s in client.get("/api/sources").json())
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "source_deleted")

    response = client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 200
    assert any(s["id"] == source_id for s in client.get("/api/sources").json())
    assert client.get(f"/api/sources/{source_id}/audio").status_code == 200


def test_revert_author_rename(client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})
    client.post("/api/authors/Jane Doe/rename", json={"new_name": "Jane Smith"})
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "author_renamed")

    response = client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 200
    author_names = {a["name"] for a in client.get("/api/authors").json()}
    assert "Jane Doe" in author_names
    assert "Jane Smith" not in author_names


def test_revert_author_profile_change(client):
    client.post("/api/sources", json={"title": "Quelle", "authors": ["Jane Doe"], "text": "Text."})
    client.put("/api/authors/Jane Doe", json={"website": "https://alt.example.org"})
    client.put("/api/authors/Jane Doe", json={"website": "https://neu.example.org"})
    entry = next(
        e
        for e in client.get("/api/audit-log").json()
        if e["action"] == "author_profile_updated" and "website" in (e["changes"] or {})
    )

    response = client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 200
    author = next(a for a in client.get("/api/authors").json() if a["name"] == "Jane Doe")
    assert author["website"] == "https://alt.example.org"


def test_revert_already_reverted_entry_returns_409(client):
    create_res = client.post("/api/sources", json={"title": "Alt", "text": "Text."})
    source_id = create_res.json()["id"]
    client.put(f"/api/sources/{source_id}", json={"title": "Neu", "text": "Text."})
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "source_updated")
    client.post(f"/api/audit-log/{entry['id']}/revert")

    response = client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 409


def test_revert_unknown_entry_returns_404(client):
    response = client.post("/api/audit-log/does-not-exist/revert")

    assert response.status_code == 404


def test_revert_non_revertible_entry_returns_400(client):
    client.post("/api/sources", json={"title": "Neu", "text": "Text."})
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "source_created")

    response = client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 400


def test_revert_requires_pfleger_role(client, anon_client):
    create_res = client.post("/api/sources", json={"title": "Alt", "text": "Text."})
    source_id = create_res.json()["id"]
    client.put(f"/api/sources/{source_id}", json={"title": "Neu", "text": "Text."})
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "source_updated")

    response = anon_client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 403


def test_audit_log_requires_pfleger_role(anon_client):
    response = anon_client.get("/api/audit-log")

    assert response.status_code == 403


# Backlog #51: Relevanz-Score (1-10) - Pflegeinformation für spätere
# KI-Gewichtung, nur für Quellen-Pfleger:innen/System-Admins sichtbar.


def test_new_source_defaults_relevance_score_to_five(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})

    assert create_res.json()["relevance_score"] == 5


def test_relevance_score_hidden_for_anonymous_users(client, anon_client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    sources = anon_client.get("/api/sources").json()
    source = next(s for s in sources if s["id"] == source_id)

    assert source["relevance_score"] is None


def test_relevance_score_visible_for_pfleger(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    sources = client.get("/api/sources").json()
    source = next(s for s in sources if s["id"] == source_id)

    assert source["relevance_score"] == 5


def test_update_source_sets_relevance_score_and_logs_change(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    update_res = client.put(
        f"/api/sources/{source_id}", json={"title": "Quelle", "text": "Text.", "relevance_score": 9}
    )
    assert update_res.json()["relevance_score"] == 9

    entries = client.get("/api/audit-log").json()
    entry = next(e for e in entries if e["action"] == "source_updated")
    assert entry["changes"]["relevance_score"] == {"old": 5, "new": 9}


def test_revert_relevance_score_change_restores_old_value(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]
    client.put(f"/api/sources/{source_id}", json={"title": "Quelle", "text": "Text.", "relevance_score": 9})
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "source_updated")

    response = client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 200
    source = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert source["relevance_score"] == 5


def test_legacy_source_without_relevance_score_defaults_to_five(client):
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    raw = json.loads(main_module.SOURCES_FILE.read_text())
    del raw[source_id]["relevance_score"]
    main_module.SOURCES_FILE.write_text(json.dumps(raw))

    sources = client.get("/api/sources").json()
    source = next(s for s in sources if s["id"] == source_id)
    assert source["relevance_score"] == 5


# Backlog (2026-08-02): wöchentliche Link-Prüfung + Warn-Badge am
# "Quellen"-Menüpunkt statt Live-Prüfung beim Öffnen der Übersicht.


def test_broken_links_count_is_zero_when_no_source_has_a_url(client):
    client.post("/api/sources", json={"title": "Ohne URL", "text": "Text."})

    response = client.get("/api/sources/broken-links-count")

    assert response.status_code == 200
    assert response.json() == {"count": 0}


def test_broken_links_count_reflects_persisted_url_reachable_field(client):
    create_res = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]
    raw = json.loads(main_module.SOURCES_FILE.read_text())
    raw[source_id]["url_reachable"] = False
    main_module.SOURCES_FILE.write_text(json.dumps(raw))

    response = client.get("/api/sources/broken-links-count")

    assert response.json() == {"count": 1}


def test_broken_links_count_ignores_deleted_sources(client):
    create_res = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]
    raw = json.loads(main_module.SOURCES_FILE.read_text())
    raw[source_id]["url_reachable"] = False
    main_module.SOURCES_FILE.write_text(json.dumps(raw))
    client.delete(f"/api/sources/{source_id}")

    response = client.get("/api/sources/broken-links-count")

    assert response.json() == {"count": 0}


def test_broken_links_count_requires_pfleger_role(anon_client):
    response = anon_client.get("/api/sources/broken-links-count")
    assert response.status_code == 403


# Backlog: LLM/Internet-Fallback bei dünner Quellenlage - CRUD für die
# freigegebenen externen Domains/Pfade (app/web_allowlist.py) sowie die
# automatische Ergänzung von /api/ask bei dünner kuratierter Trefferlage.


def test_add_web_allowlist_entry_creates_reviewed_entry(client):
    response = client.post(
        "/api/web-allowlist",
        json={
            "url_prefix": "https://beispiel.org/blog",
            "label": "Beispiel-Blog",
            "reason": "BetaCodex-nahe Redaktion.",
            "max_pages": 30,
        },
    )

    assert response.status_code == 201
    data = response.json()
    assert data["url_prefix"] == "https://beispiel.org/blog"
    assert data["label"] == "Beispiel-Blog"
    assert data["reason"] == "BetaCodex-nahe Redaktion."
    assert data["max_pages"] == 30
    assert data["added_by"] == PFLEGER
    assert data["reviewed_at"] == data["added_at"]
    assert data["page_count"] == 0
    assert data["needs_review"] is False


def test_add_web_allowlist_entry_triggers_immediate_background_crawl(client, monkeypatch):
    calls = []
    done = threading.Event()

    def fake_run_web_crawl_subprocess(entry_id, url_prefix, max_pages):
        calls.append((entry_id, url_prefix, max_pages))
        done.set()
        return 0

    monkeypatch.setattr(main_module, "_run_web_crawl_subprocess", fake_run_web_crawl_subprocess)

    response = client.post(
        "/api/web-allowlist",
        json={
            "url_prefix": "https://beispiel.org/blog",
            "label": "Beispiel-Blog",
            "reason": "BetaCodex-nahe Redaktion.",
            "max_pages": 30,
        },
    )
    entry_id = response.json()["id"]

    assert done.wait(timeout=5), "Sofort-Crawl wurde nicht im Hintergrund ausgelöst"
    assert calls == [(entry_id, "https://beispiel.org/blog", 30)]


def test_add_web_allowlist_entry_rejects_invalid_url(client):
    response = client.post(
        "/api/web-allowlist", json={"url_prefix": "not-a-url", "label": "", "reason": "Grund"}
    )
    assert response.status_code == 400


def test_add_web_allowlist_entry_requires_reason(client):
    response = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "   "},
    )
    assert response.status_code == 400


def test_add_web_allowlist_entry_defaults_label_to_url_prefix_when_blank(client):
    response = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "  ", "reason": "Grund"},
    )
    assert response.json()["label"] == "https://beispiel.org"


def test_web_allowlist_list_requires_pfleger_role(anon_client):
    response = anon_client.get("/api/web-allowlist")
    assert response.status_code == 403


def test_web_allowlist_add_requires_pfleger_role(anon_client):
    response = anon_client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "Grund"},
    )
    assert response.status_code == 403


def test_list_web_allowlist_entries_flags_stale_review_as_needing_review(client):
    web_allowlist.add_entry(
        url_prefix="https://beispiel.org",
        label="Beispiel",
        reason="Grund",
        added_by=PFLEGER,
        added_at="2020-01-01T00:00:00+00:00",
    )

    response = client.get("/api/web-allowlist")

    assert response.json()[0]["needs_review"] is True


def test_list_web_allowlist_entries_recent_review_does_not_need_review(client):
    client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "Grund"},
    )

    response = client.get("/api/web-allowlist")

    assert response.json()[0]["needs_review"] is False


def test_list_web_allowlist_entries_reports_indexed_page_count(client):
    create_res = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "Grund"},
    )
    entry_id = create_res.json()["id"]
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id=entry_id,
        url="https://beispiel.org/a",
        title="A",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=3,
    )

    response = client.get("/api/web-allowlist")

    assert response.json()[0]["page_count"] == 1


def test_list_web_allowlist_entries_page_count_excludes_excluded_pages(client):
    # Nutzerwunsch: schließt eine Pfleger:in Seiten aus, soll die angezeigte
    # Seitenzahl entsprechend sinken (40 Seiten, 20 ausgeschlossen -> 20),
    # nicht weiterhin die Gesamtzahl aller je gecrawlten Seiten zeigen.
    create_res = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "Grund"},
    )
    entry_id = create_res.json()["id"]
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id=entry_id,
        url="https://beispiel.org/a",
        title="A",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )
    web_index.upsert_page(
        "page-2",
        allowlist_entry_id=entry_id,
        url="https://beispiel.org/b",
        title="B",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )
    web_index.set_excluded("page-2", True)

    response = client.get("/api/web-allowlist")

    assert response.json()[0]["page_count"] == 1


def test_mark_web_allowlist_entry_reviewed_updates_reviewed_at(client):
    create_res = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "Grund"},
    )
    entry_id = create_res.json()["id"]
    raw = json.loads(web_allowlist.WEB_ALLOWLIST_FILE.read_text())
    raw[entry_id]["reviewed_at"] = "2020-01-01T00:00:00+00:00"
    web_allowlist.WEB_ALLOWLIST_FILE.write_text(json.dumps(raw))

    response = client.post(f"/api/web-allowlist/{entry_id}/mark-reviewed")

    assert response.status_code == 200
    assert response.json()["needs_review"] is False
    assert response.json()["reviewed_at"] != "2020-01-01T00:00:00+00:00"


def test_mark_web_allowlist_entry_reviewed_returns_404_for_unknown_id(client):
    response = client.post("/api/web-allowlist/unknown-id/mark-reviewed")
    assert response.status_code == 404


def test_delete_web_allowlist_entry_removes_it_and_its_indexed_pages(client):
    create_res = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "Grund"},
    )
    entry_id = create_res.json()["id"]
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id=entry_id,
        url="https://beispiel.org/a",
        title="A",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )
    vectorstore.add_web_chunks(
        ["page-1::0"],
        ["Chunk-Text"],
        [[1.0, 0.0]],
        [
            {
                "page_id": "page-1",
                "allowlist_entry_id": entry_id,
                "url": "https://beispiel.org/a",
                "title": "A",
                "position": 0,
            }
        ],
    )

    response = client.delete(f"/api/web-allowlist/{entry_id}")

    assert response.status_code == 204
    assert web_allowlist.list_entries() == {}
    assert web_index.pages_for_entry(entry_id) == {}
    remaining = vectorstore.query_web([1.0, 0.0], top_k=5)
    assert remaining["ids"][0] == []


def test_delete_web_allowlist_entry_returns_404_for_unknown_id(client):
    response = client.delete("/api/web-allowlist/unknown-id")
    assert response.status_code == 404


def _create_web_allowlist_entry_with_page(client, page_id="page-1", excluded=False):
    create_res = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "Grund"},
    )
    entry_id = create_res.json()["id"]
    web_index.upsert_page(
        page_id,
        allowlist_entry_id=entry_id,
        url="https://beispiel.org/a",
        title="Seite A",
        date="2026-02-01",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )
    if excluded:
        web_index.set_excluded(page_id, True)
    return entry_id


def test_list_web_allowlist_pages_returns_pages_for_entry(client):
    entry_id = _create_web_allowlist_entry_with_page(client)

    response = client.get(f"/api/web-allowlist/{entry_id}/pages")

    assert response.status_code == 200
    pages = response.json()
    assert len(pages) == 1
    assert pages[0]["id"] == "page-1"
    assert pages[0]["title"] == "Seite A"
    assert pages[0]["date"] == "2026-02-01"
    assert pages[0]["excluded"] is False


def test_list_web_allowlist_pages_returns_404_for_unknown_entry(client):
    response = client.get("/api/web-allowlist/unknown-entry/pages")
    assert response.status_code == 404


def test_list_web_allowlist_pages_requires_pfleger_role(anon_client):
    response = anon_client.get("/api/web-allowlist/unknown-entry/pages")
    assert response.status_code == 403


def test_exclude_web_allowlist_page_sets_excluded_and_logs_audit_entry(client):
    entry_id = _create_web_allowlist_entry_with_page(client)

    response = client.post(f"/api/web-allowlist/{entry_id}/pages/page-1/exclude")

    assert response.status_code == 200
    assert response.json()["excluded"] is True
    assert web_index.get_page("page-1")["excluded"] is True
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "web_page_excluded")
    assert entry["target_label"] == "Seite A"


def test_include_web_allowlist_page_clears_excluded_and_logs_audit_entry(client):
    entry_id = _create_web_allowlist_entry_with_page(client, excluded=True)

    response = client.post(f"/api/web-allowlist/{entry_id}/pages/page-1/include")

    assert response.status_code == 200
    assert response.json()["excluded"] is False
    assert web_index.get_page("page-1")["excluded"] is False
    assert any(e["action"] == "web_page_included" for e in client.get("/api/audit-log").json())


def test_exclude_web_allowlist_page_returns_404_for_unknown_page(client):
    entry_id = _create_web_allowlist_entry_with_page(client)
    response = client.post(f"/api/web-allowlist/{entry_id}/pages/unknown-page/exclude")
    assert response.status_code == 404


def test_exclude_web_allowlist_page_returns_404_when_page_belongs_to_other_entry(client):
    entry_id = _create_web_allowlist_entry_with_page(client)
    other_entry_id = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://andere.org", "label": "", "reason": "Grund"},
    ).json()["id"]

    response = client.post(f"/api/web-allowlist/{other_entry_id}/pages/page-1/exclude")

    assert response.status_code == 404
    assert web_index.get_page("page-1")["excluded"] is False


def test_add_web_allowlist_entry_defaults_selection_mode_to_negativ(client):
    response = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "Grund"},
    )
    assert response.json()["selection_mode"] == "negativ"


def _create_web_allowlist_entry_with_candidate(client, candidate_score=0.5):
    create_res = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://beispiel.org", "label": "", "reason": "Grund"},
    )
    entry_id = create_res.json()["id"]
    web_candidates.upsert_candidates(
        entry_id,
        [
            {
                "url": "https://beispiel.org/kandidat",
                "title": "Kandidaten-Seite",
                "snippet": "Ein kurzer Textausschnitt.",
                "relevance_score": candidate_score,
            }
        ],
    )
    candidate_id = next(iter(web_candidates.candidates_for_entry(entry_id)))
    return entry_id, candidate_id


def test_list_web_allowlist_candidates_returns_sorted_by_relevance_desc(client):
    entry_id, _ = _create_web_allowlist_entry_with_candidate(client, candidate_score=0.3)
    web_candidates.upsert_candidates(
        entry_id,
        [
            {
                "url": "https://beispiel.org/besser",
                "title": "Besserer Kandidat",
                "snippet": "Text.",
                "relevance_score": 0.9,
            }
        ],
    )

    response = client.get(f"/api/web-allowlist/{entry_id}/candidates")

    assert response.status_code == 200
    titles = [c["title"] for c in response.json()]
    assert titles == ["Besserer Kandidat", "Kandidaten-Seite"]


def test_list_web_allowlist_candidates_returns_404_for_unknown_entry(client):
    response = client.get("/api/web-allowlist/unknown-entry/candidates")
    assert response.status_code == 404


def test_list_web_allowlist_candidates_requires_pfleger_role(anon_client):
    response = anon_client.get("/api/web-allowlist/unknown-entry/candidates")
    assert response.status_code == 403


def test_approve_web_allowlist_candidate_indexes_page_and_logs_audit_entry(client, monkeypatch):
    entry_id, candidate_id = _create_web_allowlist_entry_with_candidate(client)
    monkeypatch.setattr(
        web_crawler, "index_approved_candidate", lambda entry_id, url: web_index.upsert_page(
            "approved-page",
            allowlist_entry_id=entry_id,
            url=url,
            title="Kandidaten-Seite",
            indexed_at="2026-01-01T00:00:00+00:00",
            chunk_count=1,
        ) or True,
    )

    response = client.post(f"/api/web-allowlist/{entry_id}/candidates/{candidate_id}/approve")

    assert response.status_code == 200
    assert response.json()["url"] == "https://beispiel.org/kandidat"
    assert web_candidates.get_candidate(candidate_id) is None
    entry = next(e for e in client.get("/api/audit-log").json() if e["action"] == "web_candidate_approved")
    assert entry["target_label"] == "Kandidaten-Seite"


def test_approve_web_allowlist_candidate_returns_502_on_indexing_failure(client, monkeypatch):
    entry_id, candidate_id = _create_web_allowlist_entry_with_candidate(client)
    monkeypatch.setattr(web_crawler, "index_approved_candidate", lambda entry_id, url: False)

    response = client.post(f"/api/web-allowlist/{entry_id}/candidates/{candidate_id}/approve")

    assert response.status_code == 502
    assert web_candidates.get_candidate(candidate_id) is not None


def test_approve_web_allowlist_candidate_returns_404_for_unknown_candidate(client):
    entry_id, _ = _create_web_allowlist_entry_with_candidate(client)
    response = client.post(f"/api/web-allowlist/{entry_id}/candidates/unknown-id/approve")
    assert response.status_code == 404


def test_approve_web_allowlist_candidate_returns_404_when_candidate_belongs_to_other_entry(client):
    entry_id, candidate_id = _create_web_allowlist_entry_with_candidate(client)
    other_entry_id = client.post(
        "/api/web-allowlist",
        json={"url_prefix": "https://andere.org", "label": "", "reason": "Grund"},
    ).json()["id"]

    response = client.post(f"/api/web-allowlist/{other_entry_id}/candidates/{candidate_id}/approve")

    assert response.status_code == 404


def test_reject_web_allowlist_candidate_marks_rejected_and_logs_audit_entry(client):
    entry_id, candidate_id = _create_web_allowlist_entry_with_candidate(client)

    response = client.post(f"/api/web-allowlist/{entry_id}/candidates/{candidate_id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert web_candidates.candidates_for_entry(entry_id) == {}
    assert any(e["action"] == "web_candidate_rejected" for e in client.get("/api/audit-log").json())


def test_reject_web_allowlist_candidate_returns_404_for_unknown_candidate(client):
    entry_id, _ = _create_web_allowlist_entry_with_candidate(client)
    response = client.post(f"/api/web-allowlist/{entry_id}/candidates/unknown-id/reject")
    assert response.status_code == 404


def _create_source_suggestion(*, url="https://beispiel.org/artikel", author_hint=None):
    suggestion_id = source_suggestions.add_suggestion(
        {
            "url": url,
            "title": "Ein Artikel",
            "reason": "Passt thematisch zur Sammlung.",
            "discovered_via": "author" if author_hint else "topic",
            "author_hint": author_hint,
        },
        "2026-01-01T00:00:00+00:00",
    )
    return suggestion_id


def test_list_source_suggestions_returns_only_pending(client):
    pending_id = _create_source_suggestion(url="https://a.org")
    rejected_id = _create_source_suggestion(url="https://b.org")
    source_suggestions.set_status(rejected_id, "rejected")

    response = client.get("/api/source-suggestions")

    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == [pending_id]


def test_list_source_suggestions_requires_pfleger_role(anon_client):
    response = anon_client.get("/api/source-suggestions")
    assert response.status_code == 403


def test_accept_source_suggestion_only_changes_status_and_weight(client):
    """Nutzerkorrektur: "Annehmen" legt bewusst KEINE Quelle an - das
    Frontend öffnet stattdessen das bestehende URL-Formular. Der Endpunkt
    selbst darf also nur den Status ändern."""
    suggestion_id = _create_source_suggestion(author_hint="Niels Pflaeging")

    response = client.post(f"/api/source-suggestions/{suggestion_id}/accept")

    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert client.get("/api/sources").json() == []
    weights = source_suggestions._load_weights()
    assert weights["authors"]["Niels Pflaeging"] == 1
    assert weights["domains"]["beispiel.org"] == 1
    assert any(e["action"] == "source_suggestion_accepted" for e in client.get("/api/audit-log").json())


def test_accept_source_suggestion_returns_404_for_unknown_id(client):
    response = client.post("/api/source-suggestions/unknown-id/accept")
    assert response.status_code == 404


def test_reject_source_suggestion_marks_rejected_and_lowers_weight(client):
    suggestion_id = _create_source_suggestion(author_hint="Niels Pflaeging")

    response = client.post(f"/api/source-suggestions/{suggestion_id}/reject")

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    weights = source_suggestions._load_weights()
    assert weights["authors"]["Niels Pflaeging"] == -1
    assert any(e["action"] == "source_suggestion_rejected" for e in client.get("/api/audit-log").json())


def test_reject_source_suggestion_returns_404_for_unknown_id(client):
    response = client.post("/api/source-suggestions/unknown-id/reject")
    assert response.status_code == 404


def test_undo_accept_source_suggestion_restores_pending_and_weight(client):
    suggestion_id = _create_source_suggestion(author_hint="Niels Pflaeging")
    client.post(f"/api/source-suggestions/{suggestion_id}/accept")
    entry = next(
        e for e in client.get("/api/audit-log").json() if e["action"] == "source_suggestion_accepted"
    )

    response = client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 200
    assert source_suggestions.get_suggestion(suggestion_id)["status"] == "pending"
    assert source_suggestions._load_weights()["authors"]["Niels Pflaeging"] == 0
    # Der Vorschlag taucht dadurch wieder in der Warteschlange auf.
    assert suggestion_id in {s["id"] for s in client.get("/api/source-suggestions").json()}


def test_undo_reject_source_suggestion_restores_pending_and_weight(client):
    suggestion_id = _create_source_suggestion(author_hint="Niels Pflaeging")
    client.post(f"/api/source-suggestions/{suggestion_id}/reject")
    entry = next(
        e for e in client.get("/api/audit-log").json() if e["action"] == "source_suggestion_rejected"
    )

    response = client.post(f"/api/audit-log/{entry['id']}/revert")

    assert response.status_code == 200
    assert source_suggestions.get_suggestion(suggestion_id)["status"] == "pending"
    assert source_suggestions._load_weights()["authors"]["Niels Pflaeging"] == 0


def test_run_source_suggestion_discovery_once_stops_at_queue_target(client, monkeypatch):
    monkeypatch.setattr(main_module, "SOURCE_SUGGESTION_QUEUE_TARGET", 2)
    monkeypatch.setattr(
        source_discovery,
        "discover_by_author",
        lambda author, known, excluded, max_results=5: [
            {"url": "https://a.org", "title": "A", "reason": "R", "discovered_via": "author", "author_hint": author}
        ],
    )
    monkeypatch.setattr(
        source_discovery,
        "discover_by_topic",
        lambda seed, known, excluded, max_results=5: [
            {"url": "https://b.org", "title": "B", "reason": "R", "discovered_via": "topic", "author_hint": None},
            {"url": "https://c.org", "title": "C", "reason": "R", "discovered_via": "topic", "author_hint": None},
        ],
    )

    main_module._run_source_suggestion_discovery_once()

    pending = source_suggestions.list_suggestions(status="pending")
    assert len(pending) == 2


def test_run_source_suggestion_discovery_once_interleaves_prolific_author_with_topic(client, monkeypatch):
    """Nutzerfeedback (2026-08-23): eine Autorin/ein Autor mit sehr vielen
    Veröffentlichungen (z.B. Alfie Kohn) darf mit einer einzigen Anfrage
    nicht die gesamte Warteschlange füllen - erst reihum je einen Kandidaten
    aus jeder Gruppe nehmen, statt eine Gruppe komplett auszuschöpfen."""
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Vielschreiber"]})
    monkeypatch.setattr(main_module, "SOURCE_SUGGESTION_QUEUE_TARGET", 2)
    monkeypatch.setattr(
        source_suggestions, "pick_next_authors", lambda names, n: ["Vielschreiber"]
    )
    monkeypatch.setattr(
        source_discovery,
        "discover_by_author",
        lambda author, known, excluded, max_results=5: [
            {"url": f"https://viel.org/{i}", "title": f"V{i}", "reason": "R", "discovered_via": "author", "author_hint": author}
            for i in range(5)
        ],
    )
    monkeypatch.setattr(
        source_discovery,
        "discover_by_topic",
        lambda seed, known, excluded, max_results=5: [
            {"url": "https://thema.org/1", "title": "T", "reason": "R", "discovered_via": "topic", "author_hint": None}
        ],
    )

    main_module._run_source_suggestion_discovery_once()

    pending = source_suggestions.list_suggestions(status="pending").values()
    discovered_via = sorted(s["discovered_via"] for s in pending)
    # Bei nur 2 freien Plätzen darf nicht beides von "Vielschreiber" kommen -
    # der Themenvorschlag muss dank Durchmischung mit reinrutschen.
    assert discovered_via == ["author", "topic"]


def test_run_source_suggestion_discovery_once_skips_already_known_urls(client, monkeypatch):
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "url": "https://a.org"})
    monkeypatch.setattr(
        source_discovery,
        "discover_by_author",
        lambda author, known, excluded, max_results=5: [],
    )
    monkeypatch.setattr(
        source_discovery,
        "discover_by_topic",
        lambda seed, known, excluded, max_results=5: [
            {"url": "https://a.org", "title": "A", "reason": "R", "discovered_via": "topic", "author_hint": None}
        ],
    )

    main_module._run_source_suggestion_discovery_once()

    assert source_suggestions.list_suggestions(status="pending") == {}


def test_run_source_suggestion_discovery_once_does_nothing_when_queue_already_full(client, monkeypatch):
    monkeypatch.setattr(main_module, "SOURCE_SUGGESTION_QUEUE_TARGET", 1)
    _create_source_suggestion(url="https://existing.org")
    called = {"n": 0}

    def fail_if_called(*args, **kwargs):
        called["n"] += 1
        return []

    monkeypatch.setattr(source_discovery, "discover_by_author", fail_if_called)
    monkeypatch.setattr(source_discovery, "discover_by_topic", fail_if_called)

    main_module._run_source_suggestion_discovery_once()

    assert called["n"] == 0


def test_delete_web_allowlist_entry_removes_its_candidates(client):
    entry_id, candidate_id = _create_web_allowlist_entry_with_candidate(client)

    response = client.delete(f"/api/web-allowlist/{entry_id}")

    assert response.status_code == 204
    assert web_candidates.get_candidate(candidate_id) is None


def test_ask_includes_web_fallback_chunk_alongside_curated_results(client):
    # Nutzerfeedback (2026-08-15): der Web-Fallback wird seither IMMER
    # mitabgefragt (nicht mehr nur bei "dünner" kuratierter Lage) und fließt
    # direkt mit ins Reranking ein - hier passt beides (top_k=5) locker
    # zusammen rein, unabhängig von der genauen Distanz.
    client.post("/api/sources", json={"title": "Kuratierte Quelle", "text": "Kurzer Text zur Organisation."})
    vectorstore.add_web_chunks(
        ["page-1::0"],
        ["Ergänzender Web-Text zur Führung in Organisationen."],
        [[1.0, 0.0]],
        [
            {
                "page_id": "page-1",
                "allowlist_entry_id": "entry-1",
                "url": "https://beispiel.org/blog/artikel",
                "title": "Web-Artikel",
                "position": 0,
            }
        ],
    )

    response = client.post("/api/ask", json={"question": "Wie funktioniert Führung?"})

    result = ask_result(response)
    web_sources = [s for s in result["sources"] if s["is_web_fallback"]]
    assert len(web_sources) == 1
    assert web_sources[0]["title"] == "Web-Artikel"
    assert web_sources[0]["url"] == "https://beispiel.org/blog/artikel"
    assert web_sources[0]["authors"] == []
    # Nutzerwunsch: Quellen-Pfleger:innen sollen eine unpassende Web-
    # Fallback-Quelle direkt aus der Konversationsansicht ausschließen
    # können (siehe question.js: appendExcludeWebPageButton) - dafür muss
    # die zugehörige web_allowlist-Eintrags-ID mitgeliefert werden.
    assert web_sources[0]["allowlist_entry_id"] == "entry-1"
    curated_sources = [s for s in result["sources"] if not s["is_web_fallback"]]
    assert curated_sources[0]["allowlist_entry_id"] is None


def test_ask_omits_excluded_web_fallback_page(client):
    client.post("/api/sources", json={"title": "Kuratierte Quelle", "text": "Kurzer Text zur Organisation."})
    web_index.upsert_page(
        "page-1",
        allowlist_entry_id="entry-1",
        url="https://beispiel.org/blog/artikel",
        title="Web-Artikel",
        indexed_at="2026-01-01T00:00:00+00:00",
        chunk_count=1,
    )
    web_index.set_excluded("page-1", True)
    vectorstore.add_web_chunks(
        ["page-1::0"],
        ["Ergänzender Web-Text zur Führung in Organisationen."],
        [[1.0, 0.0]],
        [
            {
                "page_id": "page-1",
                "allowlist_entry_id": "entry-1",
                "url": "https://beispiel.org/blog/artikel",
                "title": "Web-Artikel",
                "position": 0,
            }
        ],
    )

    response = client.post("/api/ask", json={"question": "Wie funktioniert Führung?"})

    result = ask_result(response)
    assert all(not s["is_web_fallback"] for s in result["sources"])


def test_ask_ranks_out_less_relevant_web_fallback_chunk_when_curated_is_closer(client, monkeypatch):
    """Gegenstück zum nächsten Test: liegt der kuratierte Treffer eindeutig
    näher am Anfrageembedding als der Web-Treffer, gewinnt bei top_k=1 die
    kuratierte Quelle - der Web-Treffer verliert auf Basis echten
    Reranking-Wettbewerbs, nicht mehr über einen pauschalen Schwellwert."""
    embedding_by_text = {
        "Näher am Anfrageembedding, kuratierte Quelle.": [1.0, 0.0],
        "Weiter entfernt, Web-Fallback-Text.": [0.0, 1.0954],
    }
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [embedding_by_text[t] for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [0.0, 0.0])

    client.post(
        "/api/sources",
        json={"title": "Kuratierte Quelle", "text": "Näher am Anfrageembedding, kuratierte Quelle."},
    )
    vectorstore.add_web_chunks(
        ["page-1::0"],
        ["Weiter entfernt, Web-Fallback-Text."],
        [[0.0, 1.0954]],
        [
            {
                "page_id": "page-1",
                "allowlist_entry_id": "entry-1",
                "url": "https://beispiel.org",
                "title": "Web",
                "position": 0,
            }
        ],
    )

    response = client.post("/api/ask", json={"question": "Frage?", "top_k": 1})

    result = ask_result(response)
    assert len(result["sources"]) == 1
    assert result["sources"][0]["is_web_fallback"] is False


def test_ask_prefers_more_relevant_web_fallback_chunk_over_curated(client, monkeypatch):
    """Regressionstest für einen real gemeldeten Fall: eine auf der
    freigegebenen Website eindeutig vorhandene, passende Aussage wurde nie
    herangezogen, weil der alte Schwellwert-Trigger bei diesem dicht
    gefüllten Korpus praktisch nie ausgelöst hat. Liegt der Web-Treffer
    NÄHER am Anfrageembedding als der kuratierte, muss er ihn bei knappem
    top_k jetzt verdrängen können."""
    embedding_by_text = {
        "Weiter entfernt, kuratierte Quelle.": [0.0, 1.0954],
        "Näher am Anfrageembedding, Web-Fallback-Text.": [1.0, 0.0],
    }
    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [embedding_by_text[t] for t in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [0.0, 0.0])

    client.post(
        "/api/sources",
        json={"title": "Kuratierte Quelle", "text": "Weiter entfernt, kuratierte Quelle."},
    )
    vectorstore.add_web_chunks(
        ["page-1::0"],
        ["Näher am Anfrageembedding, Web-Fallback-Text."],
        [[1.0, 0.0]],
        [
            {
                "page_id": "page-1",
                "allowlist_entry_id": "entry-1",
                "url": "https://beispiel.org/artikel",
                "title": "Passender Web-Artikel",
                "position": 0,
            }
        ],
    )

    response = client.post("/api/ask", json={"question": "Frage?", "top_k": 1})

    result = ask_result(response)
    assert len(result["sources"]) == 1
    assert result["sources"][0]["is_web_fallback"] is True
    assert result["sources"][0]["title"] == "Passender Web-Artikel"


def test_index_web_allowlist_entry_with_status_skips_when_already_running(client, monkeypatch):
    # Nutzerfeedback (real reproduziert): ein Server-Neustart löst sofort
    # einen wöchentlichen Sweep-Durchlauf aus - läuft zufällig zeitgleich
    # noch ein Sofort-Crawl desselben Eintrags, entstanden sonst doppelte
    # Seiten mit unterschiedlichen page_ids (beide Läufe kannten sich
    # gegenseitig nicht).
    entry = web_allowlist.add_entry(
        url_prefix="https://a.org", label="A", reason="R", added_by=PFLEGER, added_at="2026-01-01T00:00:00+00:00"
    )
    web_allowlist.set_indexing_status(entry["id"], "running")
    calls = []
    monkeypatch.setattr(
        main_module, "_run_web_crawl_subprocess", lambda entry_id, url_prefix, max_pages: calls.append(entry_id) or 0
    )

    main_module._index_web_allowlist_entry_with_status(entry["id"], "https://a.org", 50)

    assert calls == []
    assert web_allowlist.get_entry(entry["id"])["indexing_status"] == "running"


def test_run_web_allowlist_crawl_once_indexes_each_entry(client, monkeypatch):
    web_allowlist.add_entry(
        url_prefix="https://a.org",
        label="A",
        reason="R",
        added_by=PFLEGER,
        added_at="2026-01-01T00:00:00+00:00",
    )
    web_allowlist.add_entry(
        url_prefix="https://b.org",
        label="B",
        reason="R",
        added_by=PFLEGER,
        added_at="2026-01-01T00:00:00+00:00",
    )
    calls = []
    monkeypatch.setattr(
        main_module,
        "_run_web_crawl_subprocess",
        lambda entry_id, url_prefix, max_pages: calls.append(url_prefix) or 0,
    )

    main_module._run_web_allowlist_crawl_once()

    assert set(calls) == {"https://a.org", "https://b.org"}


def test_run_web_allowlist_crawl_once_continues_after_one_entry_fails(client, monkeypatch):
    web_allowlist.add_entry(
        url_prefix="https://a.org",
        label="A",
        reason="R",
        added_by=PFLEGER,
        added_at="2026-01-01T00:00:00+00:00",
    )
    web_allowlist.add_entry(
        url_prefix="https://b.org",
        label="B",
        reason="R",
        added_by=PFLEGER,
        added_at="2026-01-01T00:00:00+00:00",
    )
    calls = []

    def fake_run_web_crawl_subprocess(entry_id, url_prefix, max_pages):
        # Nutzerfeedback: der eigentliche Crawl läuft seit dem Unterprozess-
        # Fix in einem separaten Prozess - ein Fehlschlag zeigt sich dort als
        # Exit-Code != 0, nicht mehr als Python-Exception (siehe
        # app/web_crawl_subprocess.py).
        if url_prefix == "https://a.org":
            return 1
        calls.append(url_prefix)
        return 0

    monkeypatch.setattr(main_module, "_run_web_crawl_subprocess", fake_run_web_crawl_subprocess)

    main_module._run_web_allowlist_crawl_once()

    assert calls == ["https://b.org"]


def test_recover_interrupted_web_allowlist_indexing_resets_stale_running_status(client):
    # Realer Vorfall: ein abrupt beendeter Prozess (z.B. daemon=True-Thread,
    # der mitten im Crawl abgewürgt wurde) hinterlässt "running" dauerhaft im
    # Datenbestand, obwohl gar kein Crawl mehr läuft - der Fortschrittsring
    # am Globus-Icon bliebe sonst für immer "drehend" hängen.
    entry = web_allowlist.add_entry(
        url_prefix="https://a.org", label="A", reason="R", added_by=PFLEGER, added_at="2026-01-01T00:00:00+00:00"
    )
    web_allowlist.set_indexing_status(entry["id"], "running")

    main_module._recover_interrupted_web_allowlist_indexing()

    assert web_allowlist.get_entry(entry["id"])["indexing_status"] is None


def test_recover_interrupted_web_allowlist_indexing_leaves_other_statuses_untouched(client):
    entry = web_allowlist.add_entry(
        url_prefix="https://a.org", label="A", reason="R", added_by=PFLEGER, added_at="2026-01-01T00:00:00+00:00"
    )
    web_allowlist.set_indexing_status(entry["id"], "error")

    main_module._recover_interrupted_web_allowlist_indexing()

    assert web_allowlist.get_entry(entry["id"])["indexing_status"] == "error"


def test_ask_ignores_web_fallback_collection_when_empty(client):
    client.post("/api/sources", json={"title": "Kuratierte Quelle", "text": "Kurzer Text."})

    response = client.post("/api/ask", json={"question": "Frage?"})

    result = ask_result(response)
    assert all(not s["is_web_fallback"] for s in result["sources"])


def test_url_reachable_visible_for_anonymous_users_but_reason_hidden(client, anon_client):
    create_res = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]
    raw = json.loads(main_module.SOURCES_FILE.read_text())
    raw[source_id]["url_reachable"] = False
    raw[source_id]["url_reason_code"] = "http_error"
    raw[source_id]["url_status_code"] = 404
    main_module.SOURCES_FILE.write_text(json.dumps(raw))

    sources = anon_client.get("/api/sources").json()
    source = next(s for s in sources if s["id"] == source_id)

    assert source["url_reachable"] is False
    assert source["url_reason_code"] is None
    assert source["url_status_code"] is None


def test_url_reachable_and_reason_both_visible_for_pfleger(client):
    create_res = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]
    raw = json.loads(main_module.SOURCES_FILE.read_text())
    raw[source_id]["url_reachable"] = False
    raw[source_id]["url_reason_code"] = "http_error"
    raw[source_id]["url_status_code"] = 404
    main_module.SOURCES_FILE.write_text(json.dumps(raw))

    sources = client.get("/api/sources").json()
    source = next(s for s in sources if s["id"] == source_id)

    assert source["url_reachable"] is False
    assert source["url_reason_code"] == "http_error"
    assert source["url_status_code"] == 404


def test_new_source_has_no_url_health_status_before_first_check(client):
    create_res = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    )
    assert create_res.json()["url_reachable"] is None
    assert create_res.json()["url_checked_at"] is None


def test_run_url_health_check_once_persists_results_and_skips_deleted_sources(client, monkeypatch):
    reachable_res = client.post(
        "/api/sources", json={"title": "Erreichbar", "url": "https://example.org", "text": "Text."}
    )
    reachable_id = reachable_res.json()["id"]
    broken_res = client.post(
        "/api/sources", json={"title": "Kaputt", "url": "https://broken.example", "text": "Text."}
    )
    broken_id = broken_res.json()["id"]
    deleted_res = client.post(
        "/api/sources", json={"title": "Gelöscht", "url": "https://deleted.example", "text": "Text."}
    )
    deleted_id = deleted_res.json()["id"]
    client.delete(f"/api/sources/{deleted_id}")

    def fake_check_url(url):
        if url == "https://broken.example":
            return {"reachable": False, "status_code": 404, "reason_code": "http_error"}
        return {"reachable": True, "status_code": 200, "reason_code": None}

    monkeypatch.setattr(monitoring, "check_url", fake_check_url)

    main_module._run_url_health_check_once()

    raw = json.loads(main_module.SOURCES_FILE.read_text())
    assert raw[reachable_id]["url_reachable"] is True
    assert raw[reachable_id]["url_checked_at"] is not None
    assert raw[broken_id]["url_reachable"] is False
    assert raw[broken_id]["url_reason_code"] == "http_error"
    assert raw[broken_id]["url_status_code"] == 404
    assert "url_reachable" not in raw[deleted_id] or raw[deleted_id]["url_reachable"] is None

    response = client.get("/api/sources/broken-links-count")
    assert response.json() == {"count": 1}


def test_run_url_health_check_once_persists_in_batches_of_ten(client, monkeypatch):
    """Regression-Schutz (2026-08-02, Nutzerwunsch): bei einem wachsenden
    Quellenverzeichnis kann ein Lauf (sequenzielle Netzwerk-Checks, bis zu
    monitoring.TIMEOUT_SECONDS pro Quelle) lange dauern. Bricht der Prozess
    mittendrin ab (Neustart, Deploy, Absturz), darf nicht die gesamte
    bisherige Arbeit verloren gehen - es wird alle
    URL_HEALTH_CHECK_BATCH_SIZE (10) geprüften Quellen zwischengespeichert."""
    ids = []
    for i in range(12):
        create_res = client.post(
            "/api/sources", json={"title": f"Quelle {i}", "url": f"https://example.org/{i}", "text": "Text."}
        )
        ids.append(create_res.json()["id"])

    call_count = {"n": 0}

    def flaky_check_url(url):
        call_count["n"] += 1
        if call_count["n"] > 10:
            raise RuntimeError("Simulierter Absturz nach der ersten Zehnergruppe")
        return {"reachable": True, "status_code": 200, "reason_code": None}

    monkeypatch.setattr(monitoring, "check_url", flaky_check_url)

    with pytest.raises(RuntimeError):
        main_module._run_url_health_check_once()

    raw = json.loads(main_module.SOURCES_FILE.read_text())
    checked = [sid for sid in ids if raw[sid].get("url_checked_at")]
    assert len(checked) == 10
    unchecked = [sid for sid in ids if not raw[sid].get("url_checked_at")]
    assert len(unchecked) == 2


# Backlog (Nutzerwunsch, 2026-08-02): wer eine als kaputt markierte Quelle
# bearbeitet, soll direkt sehen, ob der Link jetzt wieder erreichbar ist -
# statt bis zu eine Woche auf den naechsten Hintergrund-Lauf warten zu
# muessen (siehe _run_url_health_check_once).


def _mark_url_broken(source_id):
    raw = json.loads(main_module.SOURCES_FILE.read_text())
    raw[source_id]["url_reachable"] = False
    raw[source_id]["url_reason_code"] = "http_error"
    raw[source_id]["url_status_code"] = 404
    main_module.SOURCES_FILE.write_text(json.dumps(raw))


def test_update_source_rechecks_url_immediately_when_previously_broken(client, monkeypatch):
    create_res = client.post(
        "/api/sources", json={"title": "Quelle", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]
    _mark_url_broken(source_id)
    monkeypatch.setattr(
        monitoring, "check_url", lambda url: {"reachable": True, "status_code": 200, "reason_code": None}
    )

    update_res = client.put(
        f"/api/sources/{source_id}",
        json={"title": "Quelle", "url": "https://example.org", "text": "Text."},
    )

    assert update_res.status_code == 200
    assert update_res.json()["url_reachable"] is True
    assert update_res.json()["url_reason_code"] is None

    raw = json.loads(main_module.SOURCES_FILE.read_text())
    assert raw[source_id]["url_reachable"] is True
    assert raw[source_id]["url_checked_at"] is not None


def test_update_source_reports_url_still_broken_after_recheck(client, monkeypatch):
    create_res = client.post(
        "/api/sources", json={"title": "Quelle", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]
    _mark_url_broken(source_id)
    monkeypatch.setattr(
        monitoring,
        "check_url",
        lambda url: {"reachable": False, "status_code": 500, "reason_code": "http_error"},
    )

    update_res = client.put(
        f"/api/sources/{source_id}",
        json={"title": "Aktualisierter Titel", "url": "https://example.org", "text": "Text."},
    )

    assert update_res.json()["url_reachable"] is False
    assert update_res.json()["url_status_code"] == 500


def test_update_source_does_not_recheck_url_when_not_previously_broken(client, monkeypatch):
    create_res = client.post(
        "/api/sources", json={"title": "Quelle", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]

    def fail_if_called(url):
        raise AssertionError("check_url haette hier nicht aufgerufen werden duerfen")

    monkeypatch.setattr(monitoring, "check_url", fail_if_called)

    update_res = client.put(
        f"/api/sources/{source_id}",
        json={"title": "Neuer Titel", "url": "https://example.org", "text": "Text."},
    )

    assert update_res.status_code == 200


def test_update_source_clears_broken_status_when_url_removed(client, monkeypatch):
    create_res = client.post(
        "/api/sources", json={"title": "Quelle", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]
    _mark_url_broken(source_id)

    def fail_if_called(url):
        raise AssertionError("check_url haette hier nicht aufgerufen werden duerfen - keine URL mehr")

    monkeypatch.setattr(monitoring, "check_url", fail_if_called)

    update_res = client.put(
        f"/api/sources/{source_id}", json={"title": "Quelle", "url": "", "text": "Text."}
    )

    assert update_res.json()["url_reachable"] is None
    raw = json.loads(main_module.SOURCES_FILE.read_text())
    assert raw[source_id]["url_reachable"] is None
    assert raw[source_id]["url_reason_code"] is None
    assert raw[source_id]["url_checked_at"] is None


# Backlog (Vorfall 2026-08-03): ein Blue/Green-Deploy sendet dem alten
# Prozess SIGTERM, sobald der neue Slot gesund ist - uvicorns eigenes
# "graceful shutdown" wartet dabei nur auf offene HTTP-Requests, nicht auf
# unsere eigenen Hintergrund-Threads (Embedding+Zusammenfassung, PDF-OCR,
# Audio-Transkription). Ein Import, der genau waehrend eines Deploys noch
# verarbeitet wurde, blieb dadurch fuer immer auf processing_status=
# "pending" stehen (real beobachtet auf Produktion). _track_background_job()
# + der Shutdown-Hook unten sollen das verhindern.


def test_track_background_job_keeps_drained_event_cleared_while_running():
    assert main_module._in_flight_jobs_drained.is_set()

    with main_module._track_background_job("src-1"):
        assert not main_module._in_flight_jobs_drained.is_set()

    assert main_module._in_flight_jobs_drained.is_set()


def test_track_background_job_handles_overlapping_jobs():
    """Zwei gleichzeitig laufende Hintergrund-Jobs duerfen den Drained-
    Status nicht schon setzen, solange noch EINER von beiden laeuft - sonst
    koennte ein Deploy mitten in einen zweiten, noch laufenden Import
    hineinplatzen."""
    started_first = threading.Event()
    release_first = threading.Event()

    def slow_job():
        with main_module._track_background_job("src-1"):
            started_first.set()
            release_first.wait(timeout=5)

    t = threading.Thread(target=slow_job, daemon=True)
    t.start()
    started_first.wait(timeout=5)

    assert not main_module._in_flight_jobs_drained.is_set()
    with main_module._track_background_job("src-2"):
        # zweiter, gleichzeitig laufender Job - Drained darf jetzt erst
        # recht nicht gesetzt sein
        assert not main_module._in_flight_jobs_drained.is_set()

    # Erster Job laeuft noch (release_first noch nicht gesetzt) - Drained
    # muss weiterhin false sein, auch nachdem der zweite fertig ist.
    assert not main_module._in_flight_jobs_drained.is_set()

    release_first.set()
    t.join(timeout=5)
    assert main_module._in_flight_jobs_drained.is_set()


def test_shutdown_hook_returns_quickly_when_nothing_in_flight():
    start = time.monotonic()
    main_module._wait_for_background_jobs_on_shutdown()
    assert time.monotonic() - start < 1


def test_shutdown_hook_waits_for_in_flight_job_to_finish(monkeypatch):
    monkeypatch.setattr(main_module, "BACKGROUND_JOB_SHUTDOWN_GRACE_SECONDS", 5)
    release = threading.Event()

    def slow_job():
        with main_module._track_background_job("src-1"):
            release.wait(timeout=5)

    t = threading.Thread(target=slow_job, daemon=True)
    t.start()
    time.sleep(0.05)  # sicherstellen, dass der Job wirklich laeuft

    def release_soon():
        time.sleep(0.2)
        release.set()

    threading.Thread(target=release_soon, daemon=True).start()

    start = time.monotonic()
    main_module._wait_for_background_jobs_on_shutdown()
    elapsed = time.monotonic() - start

    assert elapsed < 5  # muss NICHT das volle Grace-Timeout ausschoepfen
    assert elapsed >= 0.15
    t.join(timeout=5)


def test_shutdown_hook_marks_source_interrupted_by_deploy_when_grace_expires(client, monkeypatch):
    """Nutzerwunsch (2026-08-03): reicht die Wartezeit nicht (z.B. eine sehr
    lange Audio-Transkription), muss die betroffene Quelle ein Merkmal
    bekommen, damit _recover_interrupted_processing_jobs sie beim naechsten
    Start automatisch neu einreihen kann, statt sie nur als Fehler zu
    markieren."""
    monkeypatch.setattr(main_module, "BACKGROUND_JOB_SHUTDOWN_GRACE_SECONDS", 0.05)
    source_id = client.post("/api/sources", json={"title": "Quelle", "text": "Text."}).json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["processing_status"] = "running"
    main_module._save_sources(sources)

    release = threading.Event()

    def slow_job():
        with main_module._track_background_job(source_id):
            release.wait(timeout=5)

    t = threading.Thread(target=slow_job, daemon=True)
    t.start()
    time.sleep(0.02)  # sicherstellen, dass der Job wirklich laeuft

    main_module._wait_for_background_jobs_on_shutdown()

    entry = main_module._load_sources()[source_id]
    assert entry["interrupted_by_deploy"] is True

    release.set()
    t.join(timeout=5)


def test_shutdown_hook_does_not_mark_source_when_job_finishes_in_time(client):
    source_id = client.post("/api/sources", json={"title": "Quelle", "text": "Text."}).json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["processing_status"] = "running"
    main_module._save_sources(sources)

    with main_module._track_background_job(source_id):
        pass

    main_module._wait_for_background_jobs_on_shutdown()

    entry = main_module._load_sources()[source_id]
    assert "interrupted_by_deploy" not in entry


def _set_key_terms(source_id: str, terms: list[str], lang: str = "de") -> None:
    """Hilfsfunktion für die Explore-Graph-Tests: setzt key_terms_{lang}
    direkt, ohne den vollen update_source()-Zyklus (Chunking/Embeddings)
    durchlaufen zu müssen - gleiches Muster wie andere Tests, die
    main_module._load_sources()/_save_sources() direkt nutzen (siehe z.B.
    test_shutdown_hook_* oben)."""
    sources = main_module._load_sources()
    sources[source_id][f"key_terms_{lang}"] = terms
    main_module._save_sources(sources)


def test_knowledge_graph_includes_authors_and_terms_occurring_at_least_twice(client):
    source_id = client.post(
        "/api/sources", json={"title": "Q1", "text": "Text.", "authors": ["Autor Eins"]}
    ).json()["id"]
    _set_key_terms(source_id, ["Selbstorganisation", "Dezentralisierung"])
    source_id_2 = client.post("/api/sources", json={"title": "Q2", "text": "Text."}).json()["id"]
    _set_key_terms(source_id_2, ["Selbstorganisation", "Beyond Budgeting"])

    data = client.get("/api/knowledge-graph").json()
    node_ids = {n["id"] for n in data["nodes"]}
    assert "author:Autor Eins" in node_ids
    assert "term:Selbstorganisation" in node_ids


def test_knowledge_graph_uses_english_key_terms_when_requested(client):
    """Regressionstest (Nutzerfeedback 2026-08-23): das Explore-Netzwerk
    blieb beim Umschalten auf Englisch weiterhin deutsch, weil der
    Endpoint hart auf key_terms_de verdrahtet war."""
    source_id = client.post("/api/sources", json={"title": "Q1", "text": "Text."}).json()["id"]
    _set_key_terms(source_id, ["Selbstorganisation", "Dezentralisierung"], lang="de")
    _set_key_terms(source_id, ["Self-organization", "Decentralization"], lang="en")
    source_id_2 = client.post("/api/sources", json={"title": "Q2", "text": "Text."}).json()["id"]
    _set_key_terms(source_id_2, ["Selbstorganisation", "Beyond Budgeting"], lang="de")
    _set_key_terms(source_id_2, ["Self-organization", "Beyond Budgeting"], lang="en")

    data_de = client.get("/api/knowledge-graph").json()
    data_en = client.get("/api/knowledge-graph", headers={"X-Lang": "en"}).json()

    de_ids = {n["id"] for n in data_de["nodes"]}
    en_ids = {n["id"] for n in data_en["nodes"]}
    assert "term:Selbstorganisation" in de_ids
    assert "term:Self-organization" not in de_ids
    assert "term:Self-organization" in en_ids
    assert "term:Selbstorganisation" not in en_ids


def test_knowledge_graph_excludes_terms_occurring_only_once(client):
    source_id = client.post("/api/sources", json={"title": "Q1", "text": "Text."}).json()["id"]
    _set_key_terms(source_id, ["Einzelgänger", "Selbstorganisation"])
    source_id_2 = client.post("/api/sources", json={"title": "Q2", "text": "Text."}).json()["id"]
    _set_key_terms(source_id_2, ["Selbstorganisation"])

    data = client.get("/api/knowledge-graph").json()
    node_ids = {n["id"] for n in data["nodes"]}
    assert "term:Einzelgänger" not in node_ids
    assert "term:Selbstorganisation" in node_ids


def test_knowledge_graph_connects_coocurring_terms_with_edge(client):
    source_id = client.post("/api/sources", json={"title": "Q1", "text": "Text."}).json()["id"]
    _set_key_terms(source_id, ["Alpha", "Beta"])
    source_id_2 = client.post("/api/sources", json={"title": "Q2", "text": "Text."}).json()["id"]
    _set_key_terms(source_id_2, ["Alpha", "Beta"])

    data = client.get("/api/knowledge-graph").json()
    edge = next(
        e
        for e in data["edges"]
        if {e["source"], e["target"]} == {"term:Alpha", "term:Beta"}
    )
    assert edge["weight"] == 2


def test_knowledge_graph_connects_author_to_their_terms(client):
    source_id = client.post(
        "/api/sources", json={"title": "Q1", "text": "Text.", "authors": ["Autorin X"]}
    ).json()["id"]
    _set_key_terms(source_id, ["Gamma", "Delta"])
    source_id_2 = client.post("/api/sources", json={"title": "Q2", "text": "Text."}).json()["id"]
    _set_key_terms(source_id_2, ["Gamma", "Delta"])

    data = client.get("/api/knowledge-graph").json()
    edges = {(e["source"], e["target"]) for e in data["edges"]} | {
        (e["target"], e["source"]) for e in data["edges"]
    }
    assert ("author:Autorin X", "term:Gamma") in edges


def test_knowledge_graph_merges_term_equal_to_author_name_into_author_node(client):
    """Nutzerwunsch (2026-08-24): Ein Schlagwort, das namensgleich mit einer
    registrierten Autorin/einem Autor ist (hier "Jos de Blok" als Thema in
    einem FREMDEN Text), bekommt keinen eigenen Schlagwort-Knoten - der
    Text soll stattdessen direkt mit dem Autor-Knoten verbunden sein."""
    client.post("/api/sources", json={"title": "Eigener Text", "text": "Text.", "authors": ["Jos de Blok"]})
    # "Jos de Blok" muss als Schlagwort in mind. 2 Quellen vorkommen, um die
    # Mindesthäufigkeit (_GRAPH_MIN_TERM_OCCURRENCES) zu erreichen - sonst
    # würde er schon vor dem Merge-Schritt als Schlagwort herausgefiltert.
    source_id = client.post(
        "/api/sources", json={"title": "Fremder Text", "text": "Text.", "authors": ["Elisabeth Sechser"]}
    ).json()["id"]
    _set_key_terms(source_id, ["Jos de Blok", "Buurtzorg"])
    source_id_2 = client.post("/api/sources", json={"title": "Q3", "text": "Text."}).json()["id"]
    _set_key_terms(source_id_2, ["Jos de Blok", "Buurtzorg"])

    data = client.get("/api/knowledge-graph").json()
    node_ids = {n["id"] for n in data["nodes"]}
    assert "term:Jos de Blok" not in node_ids
    assert "author:Jos de Blok" in node_ids

    edges = {(e["source"], e["target"]) for e in data["edges"]} | {
        (e["target"], e["source"]) for e in data["edges"]
    }
    assert ("author:Jos de Blok", "term:Buurtzorg") in edges


def test_knowledge_graph_skips_self_loop_when_author_mentions_own_name(client):
    """"Jos de Blok" muss hier in 2 Quellen als Schlagwort auftauchen, damit
    er die Mindesthäufigkeit erreicht und überhaupt gemerged wird - eine
    davon ist seine EIGENE Quelle, in der sein Name als eigenes Schlagwort
    vorkommt (z.B. durch die automatische Schlagwort-Extraktion). Ohne den
    key_a == key_b-Schutz in _bump_edge würde das einen Self-Loop erzeugen."""
    source_id = client.post(
        "/api/sources", json={"title": "Selbstreferenz", "text": "Text.", "authors": ["Jos de Blok"]}
    ).json()["id"]
    _set_key_terms(source_id, ["Jos de Blok", "Buurtzorg"])
    source_id_2 = client.post("/api/sources", json={"title": "Q2", "text": "Text."}).json()["id"]
    _set_key_terms(source_id_2, ["Jos de Blok", "Buurtzorg"])

    response = client.get("/api/knowledge-graph")
    assert response.status_code == 200
    edges = response.json()["edges"]
    assert all(e["source"] != e["target"] for e in edges)


def test_normalize_pflaeging_spelling_once_fixes_summary_and_key_terms(client):
    """Nutzerwunsch (2026-08-25): "Niels Pfläging" wich in vorhandenen
    Zusammenfassungen/Schlagworten von der registrierten Autor:innen-
    Schreibweise "Niels Pflaeging" ab - genau wie beim Jos-de-Blok-Fall
    verhinderte das den Keyword-Autor:innen-Merge im Explore-Netzwerk."""
    source_id = client.post("/api/sources", json={"title": "Q", "text": "Text."}).json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["summary_de"] = "Ein Text von Niels Pfläging."
    sources[source_id]["summary_en"] = "A text by Niels Pfläging."
    sources[source_id]["key_terms_de"] = ["Niels Pfläging", "Selbstorganisation"]
    sources[source_id]["key_terms_en"] = ["Niels Pfläging"]
    main_module._save_sources(sources)
    main_module._register_all_terms(source_id, sources[source_id])

    main_module._normalize_pflaeging_spelling_once()

    fixed = main_module._load_sources()[source_id]
    assert fixed["summary_de"] == "Ein Text von Niels Pflaeging."
    assert fixed["summary_en"] == "A text by Niels Pflaeging."
    assert fixed["key_terms_de"] == ["Niels Pflaeging", "Selbstorganisation"]
    assert fixed["key_terms_en"] == ["Niels Pflaeging"]

    term_names = {t["term"] for t in terms.list_terms()}
    assert "Niels Pflaeging" in term_names
    assert "Niels Pfläging" not in term_names


def test_normalize_pflaeging_spelling_once_leaves_raw_text_and_title_untouched(client):
    source_id = client.post(
        "/api/sources", json={"title": "Niels Pfläging im Titel", "text": "Zitat von Niels Pfläging im Text."}
    ).json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["summary_de"] = "Niels Pfläging erklärt etwas."
    main_module._save_sources(sources)

    main_module._normalize_pflaeging_spelling_once()

    fixed = main_module._load_sources()[source_id]
    assert fixed["summary_de"] == "Niels Pflaeging erklärt etwas."
    assert fixed["title"] == "Niels Pfläging im Titel"
    assert "Niels Pfläging" in fixed["text"]


def test_normalize_pflaeging_spelling_once_is_idempotent(client):
    source_id = client.post("/api/sources", json={"title": "Q", "text": "Text."}).json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["summary_de"] = "Von Niels Pfläging."
    main_module._save_sources(sources)

    main_module._normalize_pflaeging_spelling_once()
    main_module._normalize_pflaeging_spelling_once()

    assert main_module._load_sources()[source_id]["summary_de"] == "Von Niels Pflaeging."


def test_normalize_pflaeging_spelling_once_does_nothing_without_matches(client):
    source_id = client.post("/api/sources", json={"title": "Q", "text": "Text."}).json()["id"]
    sources = main_module._load_sources()
    sources[source_id]["summary_de"] = "Unrelated summary."
    main_module._save_sources(sources)

    main_module._normalize_pflaeging_spelling_once()

    assert main_module._load_sources()[source_id]["summary_de"] == "Unrelated summary."


def test_knowledge_graph_includes_author_photo_url(client):
    client.post("/api/sources", json={"title": "Q1", "text": "Text.", "authors": ["Foto Autor"]})
    client.put("/api/authors/Foto Autor", json={"photo_url": "https://example.org/foto.jpg"})

    data = client.get("/api/knowledge-graph").json()
    node = next(n for n in data["nodes"] if n["id"] == "author:Foto Autor")
    assert node["photo_url"] == "https://example.org/foto.jpg"


def test_knowledge_graph_author_without_photo_has_none(client):
    client.post("/api/sources", json={"title": "Q1", "text": "Text.", "authors": ["Ohne Foto"]})

    data = client.get("/api/knowledge-graph").json()
    node = next(n for n in data["nodes"] if n["id"] == "author:Ohne Foto")
    assert node["photo_url"] is None


def test_knowledge_graph_excludes_soft_deleted_sources(client):
    source_id = client.post("/api/sources", json={"title": "Q1", "text": "Text."}).json()["id"]
    _set_key_terms(source_id, ["Gelöscht Eins", "Gelöscht Zwei"])
    source_id_2 = client.post("/api/sources", json={"title": "Q2", "text": "Text."}).json()["id"]
    _set_key_terms(source_id_2, ["Gelöscht Eins", "Gelöscht Zwei"])
    client.delete(f"/api/sources/{source_id_2}")

    data = client.get("/api/knowledge-graph").json()
    node_ids = {n["id"] for n in data["nodes"]}
    # Nach dem Löschen kommt "Gelöscht Eins"/"Gelöscht Zwei" nur noch in
    # EINER aktiven Quelle vor - unterschreitet die Mindestanzahl von 2.
    assert "term:Gelöscht Eins" not in node_ids


def test_knowledge_graph_cluster_assignment_is_deterministic_across_requests(client):
    source_id = client.post("/api/sources", json={"title": "Q1", "text": "Text."}).json()["id"]
    _set_key_terms(source_id, ["Stabil Eins", "Stabil Zwei"])
    source_id_2 = client.post("/api/sources", json={"title": "Q2", "text": "Text."}).json()["id"]
    _set_key_terms(source_id_2, ["Stabil Eins", "Stabil Zwei"])

    first = client.get("/api/knowledge-graph").json()
    second = client.get("/api/knowledge-graph").json()
    cluster_by_id_first = {n["id"]: n["cluster"] for n in first["nodes"]}
    cluster_by_id_second = {n["id"]: n["cluster"] for n in second["nodes"]}
    assert cluster_by_id_first == cluster_by_id_second


def test_knowledge_graph_is_public_without_authentication(anon_client):
    response = anon_client.get("/api/knowledge-graph")
    assert response.status_code == 200


def test_update_author_profile_caches_new_photo_url_in_background(client, monkeypatch):
    """Regressionstest (Nutzerfeedback 2026-08-23): externe Autor:innen-
    Fotos (v.a. LinkedIn-CDN-Links mit eingebautem Ablaufdatum) sterben
    regelmäßig weg - eine neu gesetzte photo_url wird deshalb einmalig im
    Hintergrund lokal gecacht (siehe app/author_photos.py), ohne den
    Speicher-Request selbst zu verlangsamen/zu blockieren."""
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Foto Autor"]})
    done = threading.Event()
    calls = []

    def fake_cache_photo(name, url):
        calls.append((name, url))
        done.set()
        return True

    monkeypatch.setattr(author_photos, "cache_photo", fake_cache_photo)
    client.put("/api/authors/Foto Autor", json={"photo_url": "https://example.org/foto.jpg"})

    assert done.wait(timeout=5), "Foto-Caching wurde nicht im Hintergrund ausgelöst"
    assert calls == [("Foto Autor", "https://example.org/foto.jpg")]


def test_update_author_profile_skips_caching_when_photo_url_unchanged(client, monkeypatch):
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Foto Autor"]})
    calls = []
    monkeypatch.setattr(author_photos, "cache_photo", lambda name, url: calls.append((name, url)))
    client.put("/api/authors/Foto Autor", json={"photo_url": "https://example.org/foto.jpg"})
    time.sleep(0.1)
    calls.clear()

    # Zweite Aktualisierung OHNE Änderung der photo_url (nur die Vita) darf
    # keinen erneuten Download auslösen.
    client.put(
        "/api/authors/Foto Autor",
        json={"photo_url": "https://example.org/foto.jpg", "bio": "Neue Vita"},
    )
    time.sleep(0.1)
    assert calls == []


def test_update_author_profile_recaches_when_photo_url_changes(client, monkeypatch):
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Foto Autor"]})
    calls = []
    monkeypatch.setattr(author_photos, "cache_photo", lambda name, url: calls.append((name, url)))
    client.put("/api/authors/Foto Autor", json={"photo_url": "https://example.org/alt.jpg"})
    time.sleep(0.1)
    calls.clear()

    client.put("/api/authors/Foto Autor", json={"photo_url": "https://example.org/neu.jpg"})
    time.sleep(0.1)
    assert calls == [("Foto Autor", "https://example.org/neu.jpg")]


def test_rename_author_also_renames_cached_photo(client, monkeypatch):
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Alter Name"]})
    calls = []
    monkeypatch.setattr(author_photos, "rename", lambda old, new: calls.append((old, new)))

    response = client.post("/api/authors/Alter Name/rename", json={"new_name": "Neuer Name"})

    assert response.status_code == 200
    assert calls == [("Alter Name", "Neuer Name")]


def test_get_author_photo_returns_404_when_not_cached(client):
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Ohne Foto"]})
    response = client.get("/api/authors/Ohne Foto/photo/small")
    assert response.status_code == 404


def test_get_author_photo_returns_404_for_invalid_size(client):
    response = client.get("/api/authors/Irgendwer/photo/medium")
    assert response.status_code == 404


def test_get_author_photo_serves_cached_file(client, monkeypatch):
    import io

    from PIL import Image

    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Foto Autor"]})

    def fake_cache_photo(name, url):
        image = Image.new("RGB", (200, 200), color=(10, 20, 30))
        for size_name, dimension in author_photos.SIZES.items():
            resized = image.resize((dimension, dimension))
            author_photos.AUTHOR_PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
            resized.save(author_photos.photo_path(name, size_name), "WEBP")
        return True

    monkeypatch.setattr(author_photos, "cache_photo", fake_cache_photo)
    client.put("/api/authors/Foto Autor", json={"photo_url": "https://example.org/foto.jpg"})
    # cache_photo läuft in einem Hintergrund-Thread (siehe app/main.py) - ein
    # festes time.sleep(0.1) war auf einem ausgelasteten Runner nicht
    # zuverlässig genug (derselbe Bug wie bei wait_until dokumentiert).
    wait_until(lambda: author_photos.has_cached_photo("Foto Autor", "small"))

    response = client.get("/api/authors/Foto Autor/photo/small")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"


def test_list_authors_exposes_photo_small_and_large_when_cached(client, monkeypatch):
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Foto Autor"]})
    monkeypatch.setattr(author_photos, "has_cached_photo", lambda name, size="small": True)

    data = client.get("/api/authors").json()
    entry = next(a for a in data if a["name"] == "Foto Autor")
    assert entry["photo_small"] == "/api/authors/Foto%20Autor/photo/small"
    assert entry["photo_large"] == "/api/authors/Foto%20Autor/photo/large"


def test_list_authors_photo_small_and_large_empty_without_cache(client):
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Ohne Foto"]})

    data = client.get("/api/authors").json()
    entry = next(a for a in data if a["name"] == "Ohne Foto")
    assert entry["photo_small"] == ""
    assert entry["photo_large"] == ""


def test_knowledge_graph_uses_cached_small_photo_when_available(client, monkeypatch):
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Foto Autor"]})
    client.put("/api/authors/Foto Autor", json={"photo_url": "https://example.org/foto.jpg"})
    monkeypatch.setattr(author_photos, "has_cached_photo", lambda name, size="small": True)

    data = client.get("/api/knowledge-graph").json()
    node = next(n for n in data["nodes"] if n["id"] == "author:Foto Autor")
    assert node["photo_url"] == "/api/authors/Foto%20Autor/photo/small"


def test_knowledge_graph_falls_back_to_raw_photo_url_when_not_yet_cached(client):
    client.post("/api/sources", json={"title": "Q", "text": "Text.", "authors": ["Foto Autor"]})
    client.put("/api/authors/Foto Autor", json={"photo_url": "https://example.org/foto.jpg"})

    data = client.get("/api/knowledge-graph").json()
    node = next(n for n in data["nodes"] if n["id"] == "author:Foto Autor")
    assert node["photo_url"] == "https://example.org/foto.jpg"
