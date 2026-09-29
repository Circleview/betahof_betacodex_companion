from fastapi.testclient import TestClient

from app import main

client = TestClient(main.app)
LIMIT = main.REQUEST_BODY_DEFAULT_LIMIT


def test_content_length_over_limit_is_rejected_before_reading():
    r = client.post("/api/answer-feedback", content=b"x" * (LIMIT + 1),
                    headers={"Content-Type": "application/json", "X-Lang": "en"})
    assert r.status_code == 413
    assert r.json()["detail"] == "The request is too large."


def test_chunked_body_over_limit_is_counted_while_reading():
    def body():
        for _ in range(3):
            yield b"x" * (LIMIT // 2)

    r = client.post("/api/ask", content=body(), headers={"Content-Type": "application/json"})
    assert r.status_code == 413
    assert r.json()["detail"] == "Die Anfrage ist zu groß."


def test_small_body_passes_through():
    r = client.post("/api/ask", content=b"{}", headers={"Content-Type": "application/json"})
    assert r.status_code == 422  # normale Validierung, nicht 413


def test_upload_paths_get_higher_limit():
    # Über dem Standard, unter der Upload-Grenze: nicht 413 (sondern 401, kein Login).
    r = client.post("/api/extract-pdf-upload", files={"file": ("a.pdf", b"x" * (LIMIT + 1))})
    assert r.status_code != 413
