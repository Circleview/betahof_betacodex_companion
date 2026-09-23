import io
from unittest.mock import MagicMock, patch

from PIL import Image

from app import author_photos, extraction


def _fake_image_bytes(size=(300, 200)):
    image = Image.new("RGB", size, color=(200, 50, 50))
    buf = io.BytesIO()
    image.save(buf, format="JPEG")
    return buf.getvalue()


def _mock_urlopen(data: bytes):
    response = MagicMock()
    response.read.return_value = data
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _resolve_to(ip: str):
    return lambda host, *args, **kwargs: [(2, 1, 6, "", (ip, 0))]


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(author_photos, "AUTHOR_PHOTOS_DIR", tmp_path)
    monkeypatch.setattr(author_photos, "MANIFEST_FILE", tmp_path / "_manifest.json")
    # SSRF-Prüfung ohne echte DNS-Anfrage (siehe _getaddrinfo in
    # app/extraction.py) - öffentliche Test-IP für jeden Hostnamen.
    monkeypatch.setattr(extraction, "_getaddrinfo", _resolve_to("93.184.216.34"))


def test_cache_photo_refuses_private_address(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    for ip in ("169.254.169.254", "127.0.0.1", "10.0.0.5"):
        monkeypatch.setattr(extraction, "_getaddrinfo", _resolve_to(ip))
        with patch("app.extraction._safe_opener.open", return_value=_mock_urlopen(_fake_image_bytes())) as urlopen:
            result = author_photos.cache_photo("Test Autor", "http://metadata.example/foto.jpg")
        assert result is False
        urlopen.assert_not_called()
    assert not author_photos.has_cached_photo("Test Autor", "small")


def test_cache_photo_refuses_non_http_scheme(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("app.extraction._safe_opener.open") as urlopen:
        assert author_photos.cache_photo("Test Autor", "file:///etc/passwd") is False
    urlopen.assert_not_called()


def test_cache_photo_creates_both_sizes(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("app.extraction._safe_opener.open", return_value=_mock_urlopen(_fake_image_bytes())):
        result = author_photos.cache_photo("Test Autor", "https://example.org/foto.jpg")

    assert result is True
    assert author_photos.has_cached_photo("Test Autor", "small")
    assert author_photos.has_cached_photo("Test Autor", "large")
    small = Image.open(author_photos.photo_path("Test Autor", "small"))
    assert small.size == (160, 160)
    large = Image.open(author_photos.photo_path("Test Autor", "large"))
    assert large.size == (480, 480)


def test_cache_photo_records_source_url_in_manifest(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("app.extraction._safe_opener.open", return_value=_mock_urlopen(_fake_image_bytes())):
        author_photos.cache_photo("Test Autor", "https://example.org/foto.jpg")

    assert author_photos.cached_source_url("Test Autor") == "https://example.org/foto.jpg"


def test_cache_photo_returns_false_on_download_failure(tmp_path, monkeypatch):
    """Regressionstest: eine tote/unerreichbare URL (genau das Ausgangs-
    problem - z.B. abgelaufene LinkedIn-CDN-Links) darf cache_photo nie zum
    Absturz bringen, nur ein stilles False liefern (Fail-leise-Konvention
    wie app/source_discovery.py)."""
    _isolate(tmp_path, monkeypatch)
    with patch("app.extraction._safe_opener.open", side_effect=RuntimeError("boom")):
        result = author_photos.cache_photo("Test Autor", "https://example.org/tot.jpg")

    assert result is False
    assert not author_photos.has_cached_photo("Test Autor")


def test_cache_photo_returns_false_on_invalid_image_data(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("app.extraction._safe_opener.open", return_value=_mock_urlopen(b"not-an-image")):
        result = author_photos.cache_photo("Test Autor", "https://example.org/kaputt.jpg")

    assert result is False
    assert not author_photos.has_cached_photo("Test Autor")


def test_has_cached_photo_false_when_nothing_cached(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert author_photos.has_cached_photo("Unbekannt") is False


def test_cached_source_url_none_when_nothing_cached(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    assert author_photos.cached_source_url("Unbekannt") is None


def test_rename_moves_cached_files_and_manifest_entry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("app.extraction._safe_opener.open", return_value=_mock_urlopen(_fake_image_bytes())):
        author_photos.cache_photo("Alter Name", "https://example.org/foto.jpg")

    author_photos.rename("Alter Name", "Neuer Name")

    assert not author_photos.has_cached_photo("Alter Name")
    assert author_photos.has_cached_photo("Neuer Name")
    assert author_photos.cached_source_url("Neuer Name") == "https://example.org/foto.jpg"
    assert author_photos.cached_source_url("Alter Name") is None


def test_rename_is_a_noop_when_only_case_or_whitespace_differs(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    with patch("app.extraction._safe_opener.open", return_value=_mock_urlopen(_fake_image_bytes())):
        author_photos.cache_photo("Max Muster", "https://example.org/foto.jpg")

    author_photos.rename("Max Muster", "  max   muster  ")

    assert author_photos.has_cached_photo("Max Muster")


def test_rename_without_existing_cache_does_nothing(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    author_photos.rename("Nie Gecacht", "Anderer Name")
    assert not author_photos.has_cached_photo("Anderer Name")


def test_resize_and_crop_square_center_crops_non_square_images(tmp_path, monkeypatch):
    """Ein Breitbild-Original darf nicht verzerrt werden - Mittenzuschnitt
    auf ein Quadrat vor dem Skalieren."""
    _isolate(tmp_path, monkeypatch)
    with patch(
        "app.extraction._safe_opener.open",
        return_value=_mock_urlopen(_fake_image_bytes(size=(400, 100))),
    ):
        author_photos.cache_photo("Breitbild Autor", "https://example.org/breit.jpg")

    small = Image.open(author_photos.photo_path("Breitbild Autor", "small"))
    assert small.size == (160, 160)
