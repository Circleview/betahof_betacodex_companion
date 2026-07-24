import pytest
from fastapi.testclient import TestClient

from app import authors, embeddings, extraction, llm, monitoring, summarization, terms, users, vectorstore
from app import main as main_module

PFLEGER = "lena.pflegerin"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main_module, "SOURCES_FILE", tmp_path / "sources.json")
    monkeypatch.setattr(main_module, "PDF_DIR", tmp_path / "pdfs")
    monkeypatch.setattr(main_module, "PDF_UPLOAD_STAGING_DIR", tmp_path / "pdf_uploads")
    monkeypatch.setattr(main_module, "AUDIO_DIR", tmp_path / "audio")

    monkeypatch.setattr(vectorstore, "DB_PATH", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_client", None)
    monkeypatch.setattr(vectorstore, "_collection", None)

    monkeypatch.setattr(authors, "AUTHORS_FILE", tmp_path / "authors.json")
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(terms, "TERMS_FILE", tmp_path / "terms.json")

    monkeypatch.setattr(embeddings, "embed_passages", lambda texts: [[1.0, 0.0] for _ in texts])
    monkeypatch.setattr(embeddings, "embed_query", lambda text: [1.0, 0.0])
    monkeypatch.setattr(
        llm, "answer_question", lambda question, chunks, lang="de": "Testantwort [1]."
    )
    monkeypatch.setattr(
        summarization,
        "generate_summary",
        lambda text, lang="de": {"summary": "", "key_terms": []},
    )

    # Standard-Testrolle: Quellen-Pfleger:in, damit bestehende Tests nicht jeden
    # Request einzeln mit einem Rollen-Header versehen müssen.
    return TestClient(main_module.app, headers={"X-Dev-User": PFLEGER})


def test_add_source_creates_chunks(client):
    response = client.post(
        "/api/sources",
        json={
            "title": "Testquelle",
            "author": "Autor X",
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


def test_list_sources_returns_imported_sources(client):
    client.post("/api/sources", json={"title": "Quelle A", "text": "Text A"})
    response = client.get("/api/sources")
    assert response.status_code == 200
    titles = [s["title"] for s in response.json()]
    assert "Quelle A" in titles


def test_ask_without_sources_returns_400(client):
    response = client.post("/api/ask", json={"question": "Was ist der BetaCodex?"})
    assert response.status_code == 400


def test_ask_returns_answer_with_sources(client):
    client.post(
        "/api/sources",
        json={
            "title": "BetaCodex Quelle",
            "author": "Autor Y",
            "date": "2023-05-01",
            "url": "https://example.org/quelle",
            "text": "Der BetaCodex beschreibt Prinzipien dezentraler Organisation.",
        },
    )

    response = client.post("/api/ask", json={"question": "Was beschreibt der BetaCodex?"})

    assert response.status_code == 200
    data = response.json()
    assert data["answer"] == "Testantwort [1]."
    assert len(data["sources"]) == 1
    assert data["sources"][0]["title"] == "BetaCodex Quelle"


def test_extract_url_endpoint_returns_extracted_fields(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {
            "title": "Extrahierter Titel",
            "author": "Autor Z",
            "date": "2024-02-02",
            "text": "Extrahierter Text.",
            "extracted": True,
        },
    )

    response = client.post("/api/extract-url", json={"url": "https://example.org/blogpost"})

    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Extrahierter Titel"
    assert data["date"] == "2024-02-02"
    assert data["extracted"] is True


def test_extract_url_endpoint_reports_failed_extraction(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {"title": "", "author": "", "date": "", "text": "", "extracted": False},
    )

    response = client.post("/api/extract-url", json={"url": "https://example.org/nicht-lesbar"})

    assert response.status_code == 200
    assert response.json()["extracted"] is False


def test_add_source_registers_author(client):
    client.post(
        "/api/sources",
        json={"title": "Quelle 1", "author": "Jane Doe", "text": "Erster Text."},
    )
    client.post(
        "/api/sources",
        json={"title": "Quelle 2", "author": "jane   doe", "text": "Zweiter Text."},
    )

    response = client.get("/api/authors")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["name"] == "Jane Doe"
    assert data[0]["source_count"] == 2


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
            "author": "Alt Autor",
            "date": "2020-01-01",
            "text": "Alter Text.",
        },
    )
    source_id = create_res.json()["id"]

    update_res = client.put(
        f"/api/sources/{source_id}",
        json={
            "title": "Neuer Titel",
            "author": "Neu Autor",
            "date": "2021-01-01",
            "url": "https://example.org",
            "text": "Neuer Text mit anderem Inhalt.",
        },
    )

    assert update_res.status_code == 200
    data = update_res.json()
    assert data["title"] == "Neuer Titel"
    assert data["author"] == "Neu Autor"
    assert data["text"] == "Neuer Text mit anderem Inhalt."

    list_res = client.get("/api/sources")
    assert list_res.json()[0]["title"] == "Neuer Titel"


def test_update_source_returns_404_for_unknown_id(client):
    response = client.put("/api/sources/does-not-exist", json={"title": "X", "text": "Text"})
    assert response.status_code == 404


def test_update_source_rejects_empty_text_without_touching_existing_data(client):
    create_res = client.post(
        "/api/sources",
        json={"title": "Titel", "author": "Autor", "text": "Ursprünglicher Text."},
    )
    source_id = create_res.json()["id"]

    response = client.put(
        f"/api/sources/{source_id}",
        json={"title": "Titel", "author": "Autor", "text": "   "},
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
        "/api/sources", json={"title": "Titel", "author": "Alter Autor", "text": "Text."}
    )
    source_id = create_res.json()["id"]

    client.put(
        f"/api/sources/{source_id}",
        json={"title": "Titel", "author": "Neuer Autor", "text": "Text."},
    )

    author_names = {a["name"] for a in client.get("/api/authors").json()}
    assert author_names == {"Neuer Autor"}


def test_add_source_without_role_is_forbidden(client):
    response = client.post(
        "/api/sources",
        json={"title": "Quelle", "text": "Text."},
        headers={"X-Dev-User": "anon"},
    )
    assert response.status_code == 403


def test_add_source_with_unrelated_role_is_forbidden(client):
    response = client.post(
        "/api/sources",
        json={"title": "Quelle", "text": "Text."},
        headers={"X-Dev-User": "uwe.admin"},
    )
    assert response.status_code == 403


def test_add_source_as_system_admin_is_allowed(client):
    response = client.post(
        "/api/sources",
        json={"title": "Quelle", "text": "Text."},
        headers={"X-Dev-User": "root"},
    )
    assert response.status_code == 200


def test_update_source_without_role_is_forbidden(client):
    create_res = client.post("/api/sources", json={"title": "Titel", "text": "Text."})
    source_id = create_res.json()["id"]

    response = client.put(
        f"/api/sources/{source_id}",
        json={"title": "Neu", "text": "Neuer Text."},
        headers={"X-Dev-User": "anon"},
    )
    assert response.status_code == 403


def test_extract_url_without_role_is_forbidden(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_from_url",
        lambda url: {"title": "T", "author": "", "date": "", "text": "Text", "extracted": True},
    )
    response = client.post(
        "/api/extract-url",
        json={"url": "https://example.org"},
        headers={"X-Dev-User": "anon"},
    )
    assert response.status_code == 403


def test_ask_and_list_sources_work_without_any_role(client):
    client.post("/api/sources", json={"title": "Quelle", "text": "Text zum Fragen."})

    no_role_headers = {"X-Dev-User": "anon"}
    assert client.get("/api/sources", headers=no_role_headers).status_code == 200
    assert (
        client.post(
            "/api/ask", json={"question": "Frage?"}, headers=no_role_headers
        ).status_code
        == 200
    )


def test_add_source_rejects_empty_text_in_english(client):
    response = client.post(
        "/api/sources",
        json={"title": "Empty", "text": "   "},
        headers={"X-Lang": "en"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Text must not be empty."


def test_role_required_message_in_english(client):
    response = client.post(
        "/api/sources",
        json={"title": "X", "text": "Text"},
        headers={"X-Dev-User": "anon", "X-Lang": "en"},
    )
    assert response.status_code == 403
    assert "requires the role" in response.json()["detail"]


def test_ask_uses_requested_language(client, monkeypatch):
    captured = {}

    def fake_answer(question, chunks, lang="de"):
        captured["lang"] = lang
        return "Answer"

    monkeypatch.setattr(llm, "answer_question", fake_answer)
    client.post("/api/sources", json={"title": "Q", "text": "Text for asking."})

    response = client.post("/api/ask", json={"question": "Q?"}, headers={"X-Lang": "en"})

    assert response.status_code == 200
    assert captured["lang"] == "en"


def test_dev_list_users_returns_seeded_roles(client):
    response = client.get("/api/dev/users")
    assert response.status_code == 200
    data = {u["id"]: u["roles"] for u in response.json()}
    assert data["anon"] == []
    assert data["lena.pflegerin"] == ["quellen_pfleger"]
    assert data["uwe.admin"] == ["user_admin"]
    assert data["root"] == ["system_admin"]


def test_delete_source_removes_it(client):
    create_res = client.post("/api/sources", json={"title": "Löschmich", "text": "Text."})
    source_id = create_res.json()["id"]

    response = client.delete(f"/api/sources/{source_id}")

    assert response.status_code == 204
    titles = [s["title"] for s in client.get("/api/sources").json()]
    assert "Löschmich" not in titles


def test_delete_source_cleans_up_chunks_and_author(client):
    create_res = client.post(
        "/api/sources", json={"title": "Löschmich", "author": "Jane Doe", "text": "Text."}
    )
    source_id = create_res.json()["id"]

    client.delete(f"/api/sources/{source_id}")

    assert client.get("/api/authors").json() == []
    result = vectorstore.query([1.0, 0.0], top_k=5)
    assert result["ids"][0] == []


def test_delete_source_returns_404_for_unknown_id(client):
    response = client.delete("/api/sources/does-not-exist")
    assert response.status_code == 404


def test_delete_source_without_role_is_forbidden(client):
    create_res = client.post("/api/sources", json={"title": "Bleibt", "text": "Text."})
    source_id = create_res.json()["id"]

    response = client.delete(f"/api/sources/{source_id}", headers={"X-Dev-User": "anon"})

    assert response.status_code == 403
    titles = [s["title"] for s in client.get("/api/sources").json()]
    assert "Bleibt" in titles


def test_restricted_source_hides_text_from_anon(client):
    client.post(
        "/api/sources",
        json={"title": "Geschützt", "text": "Urheberrechtlich geschützter Inhalt.", "restricted": True},
    )

    sources = client.get("/api/sources", headers={"X-Dev-User": "anon"}).json()

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
    assert response.json()["sources"][0]["text"] == "Urheberrechtlich geschützter Inhalt."


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
        "generate_summary",
        lambda text, lang="de": {"summary": "KI-Zusammenfassung.", "key_terms": ["Begriff A", "Begriff B"]},
    )

    response = client.post(f"/api/sources/{source_id}/generate-summary")

    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "KI-Zusammenfassung."
    assert data["key_terms"] == ["Begriff A", "Begriff B"]


def test_generate_source_summary_requires_pfleger_role(client):
    create_res = client.post(
        "/api/sources",
        json={"title": "Quelle", "text": "Text."},
    )
    source_id = create_res.json()["id"]

    response = client.post(
        f"/api/sources/{source_id}/generate-summary",
        headers={"X-Dev-User": "anon"},
    )

    assert response.status_code == 403


def test_generate_source_summary_unknown_source_returns_404(client):
    response = client.post("/api/sources/does-not-exist/generate-summary")
    assert response.status_code == 404


def test_extract_pdf_upload_returns_extracted_fields(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_pdf",
        lambda data: {
            "title": "PDF-Titel",
            "author": "PDF-Autor",
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


def test_extract_pdf_upload_without_role_is_forbidden(client):
    response = client.post(
        "/api/extract-pdf-upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake", "application/pdf")},
        headers={"X-Dev-User": "anon"},
    )
    assert response.status_code == 403


def test_add_source_with_pdf_upload_id_persists_file(client, monkeypatch):
    monkeypatch.setattr(
        extraction,
        "extract_pdf",
        lambda data: {
            "title": "PDF-Titel",
            "author": "",
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


def test_check_source_url_without_role_is_forbidden(client):
    create_res = client.post(
        "/api/sources", json={"title": "Mit URL", "url": "https://example.org", "text": "Text."}
    )
    source_id = create_res.json()["id"]

    response = client.get(
        f"/api/sources/{source_id}/check-url", headers={"X-Dev-User": "anon"}
    )

    assert response.status_code == 403


def test_get_version_returns_a_string(client):
    response = client.get("/api/version")
    assert response.status_code == 200
    assert isinstance(response.json()["version"], str)
    assert response.json()["version"]


def test_check_source_url_returns_404_for_unknown_source(client):
    response = client.get("/api/sources/does-not-exist/check-url")
    assert response.status_code == 404


def test_add_source_generates_summary_in_background_and_registers_terms(client, monkeypatch):
    monkeypatch.setattr(
        summarization,
        "generate_summary",
        lambda text, lang="de": {
            "summary": "Eine Zusammenfassung.",
            "key_terms": ["BetaCodex", "Dezentralisierung"],
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


def test_update_source_can_edit_summary_and_key_terms(client, monkeypatch):
    monkeypatch.setattr(
        summarization,
        "generate_summary",
        lambda text, lang="de": {"summary": "Alte Zusammenfassung.", "key_terms": ["Alt"]},
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
        "generate_summary",
        lambda text, lang="de": {"summary": "Ursprüngliche Zusammenfassung.", "key_terms": ["Alt"]},
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
        "generate_summary",
        lambda text, lang="de": {"summary": "S.", "key_terms": ["EinzigerBegriff"]},
    )
    create_res = client.post("/api/sources", json={"title": "Quelle", "text": "Text."})
    source_id = create_res.json()["id"]

    client.delete(f"/api/sources/{source_id}")

    assert client.get("/api/terms").json() == []


def test_listen_url_persists_and_appears_in_ask_citation(client, monkeypatch):
    captured = {}

    def fake_answer(question, chunks, lang="de"):
        captured["lang"] = lang
        return "Testantwort [1]."

    monkeypatch.setattr(llm, "answer_question", fake_answer)

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
    source = response.json()["sources"][0]
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
