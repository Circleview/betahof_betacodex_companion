import concurrent.futures
import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app import (
    audit,
    auth,
    author_profiles,
    authors,
    captcha,
    chunking,
    embeddings,
    extraction,
    llm,
    mail,
    monitoring,
    ratelimit,
    summarization,
    terms,
    tts,
    users,
    vectorstore,
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


def ask_result(response):
    """Testhilfe (Backlog 2026-07-29, Streaming-Antworten): /api/ask liefert
    seitdem NDJSON (eine JSON-Zeile pro Event) statt einer einzelnen JSON-
    Antwort. Liest den kompletten Stream und baut daraus dieselbe Form nach,
    die früher response.json() lieferte ({"answer": ..., "sources": ...}),
    damit der Großteil der bestehenden Tests unverändert lesbar bleibt.
    streamed_text sammelt zusätzlich alle delta-Fragmente in Sende-
    Reihenfolge - für Tests, die gezielt das Streaming-Verhalten selbst
    prüfen (z.B. dass der ---QUOTES---Block nie an den Client geht)."""
    lines = [line for line in response.text.split("\n") if line.strip()]
    events = [json.loads(line) for line in lines]
    done = next(e for e in events if e["type"] == "done")
    streamed_text = "".join(e["text"] for e in events if e["type"] == "delta")
    return {"answer": done["answer"], "sources": done["sources"], "streamed_text": streamed_text, "events": events}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_module, "SOURCES_FILE", tmp_path / "sources.json")
    monkeypatch.setattr(main_module, "PDF_DIR", tmp_path / "pdfs")
    monkeypatch.setattr(main_module, "PDF_UPLOAD_STAGING_DIR", tmp_path / "pdf_uploads")
    monkeypatch.setattr(main_module, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(main_module, "AUDIO_UPLOAD_STAGING_DIR", tmp_path / "audio_uploads")

    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_client", None)
    monkeypatch.setattr(vectorstore, "_collection", None)

    monkeypatch.setattr(authors, "AUTHORS_FILE", tmp_path / "authors.json")
    monkeypatch.setattr(author_profiles, "AUTHOR_PROFILES_FILE", tmp_path / "author_profiles.json")
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(terms, "TERMS_FILE", tmp_path / "terms.json")
    monkeypatch.setattr(audit, "AUDIT_LOG_FILE", tmp_path / "audit_log.json")

    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [1.0, 0.0])
    # /api/ask ruft seit dem Streaming-Umbau (Backlog 2026-07-29)
    # stream_answer_question statt answer_question auf - der Mock muss ein
    # Iterable liefern (wie der echte Generator), kein fertiges String.
    monkeypatch.setattr(
        llm,
        "stream_answer_question",
        lambda question, chunks, lang="de", author_bios=None: iter(["Testantwort [1]."]),
    )
    monkeypatch.setattr(
        summarization,
        "generate_bilingual_summary",
        lambda text: {
            "de": {"summary": "", "key_terms": []},
            "en": {"summary": "", "key_terms": []},
        },
    )
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

    time.sleep(0.5)
    entry = next(s for s in client.get("/api/sources").json() if s["id"] == data["id"])
    assert entry["processing_status"] is None
    assert entry["chunk_count"] > 0
    assert entry["text"] == "Ein langer Beispieltext."


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

    time.sleep(0.5)
    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["summary"] == "Zusammenfassung nach langsamem Import."


def test_add_source_marks_error_when_slow_embedding_fails(client, monkeypatch):
    monkeypatch.setattr(main_module, "SLOW_IMPORT_TIMEOUT_SECONDS", 0.05)

    def slow_failing_embed(chunks):
        time.sleep(0.3)
        raise RuntimeError("boom")

    monkeypatch.setattr(embeddings, "embed_passages", slow_failing_embed)

    response = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = response.json()["id"]
    assert response.json()["processing_status"] == "pending"

    time.sleep(0.5)
    entry = next(s for s in client.get("/api/sources").json() if s["id"] == source_id)
    assert entry["processing_status"] == "error"
    assert entry["processing_error"]


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


def _create_deferred_audio_source(client, monkeypatch, title="Podcast-Folge", url="https://cdn.example.org/episode.mp3"):
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
    response = client.post("/api/sources", json={"title": title, "text": "", "url": url})
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

    def fake_transcribe(path, known_segments=None, on_segment_success=None):
        on_segment_success(0, 2, "Abschnitt 1 (erfolgreich)")
        return "", "Abschnitt 2/2: RateLimitError: zu viele Anfragen"

    monkeypatch.setattr(extraction, "transcribe_audio", fake_transcribe)
    main_module._process_audio_transcription(source_id)

    raw = main_module._load_sources()[source_id]
    assert raw["processing_status"] == "error"
    assert raw["processing_segments"] == {"0": "Abschnitt 1 (erfolgreich)"}

    def fake_transcribe_retry(path, known_segments=None, on_segment_success=None):
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


def test_audio_transcriptions_are_processed_sequentially_not_concurrently(client, monkeypatch):
    """Backlog #113: mehrere gleichzeitig importierte Audios dürfen sich
    beim Transkribieren nicht überholen - realer Vorfall am 2026-07-28, bei
    dem 23 parallel gestartete Transkriptionen das OpenAI-Budget aufgebraucht
    haben, bevor auch nur eine Datei fertig war."""
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
        for i in range(5)
    ]
    main_module._audio_transcription_queue.join()

    assert max(max_concurrent) == 1
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
    monkeypatch.setattr(tts, "synthesize_speech", lambda text, lang="de": b"fake-mp3-bytes")

    response = anon_client.post("/api/speech", json={"text": "Hallo Welt"})

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert response.content == b"fake-mp3-bytes"


def test_speech_passes_current_language_to_synthesize(anon_client, monkeypatch):
    captured = {}

    def fake_synthesize(text, lang="de"):
        captured["text"] = text
        captured["lang"] = lang
        return b"audio"

    monkeypatch.setattr(tts, "synthesize_speech", fake_synthesize)

    response = anon_client.post(
        "/api/speech", json={"text": "Hello"}, headers={"X-Lang": "en"}
    )

    assert response.status_code == 200
    assert captured == {"text": "Hello", "lang": "en"}


def test_speech_rejects_empty_text(anon_client):
    response = anon_client.post("/api/speech", json={"text": "   "})
    assert response.status_code == 400


def test_speech_returns_502_when_synthesis_fails(anon_client, monkeypatch):
    def raise_error(text, lang="de"):
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


def test_ask_stream_emits_delta_events_in_order_before_done_event(client, monkeypatch):
    monkeypatch.setattr(
        llm, "stream_answer_question", lambda *a, **k: iter(["Erster Teil ", "zweiter Teil [1]."])
    )
    client.post("/api/sources", json={"title": "Q", "text": "Text."})

    response = client.post("/api/ask", json={"question": "Frage?"})
    result = ask_result(response)

    assert result["events"][-1]["type"] == "done"
    assert all(e["type"] == "delta" for e in result["events"][:-1])
    assert result["streamed_text"] == result["answer"]


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

    def fake_answer(question, chunks, lang="de", author_bios=None):
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

    def fake_answer(question, chunks, lang="de", author_bios=None):
        captured["author_bios"] = author_bios
        return iter(["Testantwort [1]."])

    monkeypatch.setattr(llm, "stream_answer_question", fake_answer)

    client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert captured["author_bios"] is None


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
        lambda question, chunks, lang="de", author_bios=None: iter([
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
        lambda question, chunks, lang="de", author_bios=None: iter([
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
        lambda question, chunks, lang="de", author_bios=None: iter([
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

    def fake_answer(question, chunks, lang="de", author_bios=None):
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
        monitoring, "check_url", lambda url: {"reachable": False, "status_code": 404}
    )

    response = client.get(f"/api/sources/{source_id}/check-url")

    assert response.status_code == 200
    data = response.json()
    assert data["has_url"] is True
    assert data["reachable"] is False
    assert data["status_code"] == 404


def test_check_source_url_without_url_reports_has_url_false(client):
    create_res = client.post("/api/sources", json={"title": "Ohne URL", "text": "Text."})
    source_id = create_res.json()["id"]

    response = client.get(f"/api/sources/{source_id}/check-url")

    assert response.status_code == 200
    assert response.json() == {"has_url": False, "reachable": None, "status_code": None}


def test_check_source_url_without_role_is_forbidden(client, anon_client):
    create_res = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]

    response = anon_client.get(f"/api/sources/{source_id}/check-url")

    assert response.status_code == 403


def test_get_version_returns_a_string(client):
    response = client.get("/api/version")
    assert response.status_code == 200
    assert isinstance(response.json()["version"], str)
    assert response.json()["version"]


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

    def fake_answer(question, chunks, lang="de", author_bios=None):
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


def test_delete_source_removes_audio_file(client, monkeypatch):
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

    assert not list(main_module.AUDIO_DIR.glob(f"{source_id}.*"))


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
