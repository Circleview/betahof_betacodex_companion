import io
import json
import re

from PIL import Image

from app import source_images


def _jpeg(size=(1600, 1000), color=(200, 60, 60), exif=False) -> bytes:
    buf = io.BytesIO()
    image = Image.new("RGB", size, color)
    if exif:
        data = Image.Exif()
        data[0x010E] = "Geheime Beschreibung"
        image.save(buf, format="JPEG", exif=data)
    else:
        image.save(buf, format="JPEG")
    return buf.getvalue()


def _item(data, page=3, anchor="Anker"):
    return {"data": data, "page": page, "anchor": anchor}


def test_store_images_writes_webp_with_max_800px_and_random_name(tmp_path):
    entries = source_images.store_images(tmp_path, "src-1", [_item(_jpeg((1600, 1000)))])

    assert len(entries) == 1
    entry = entries[0]
    assert entry["kind"] == "file" and entry["page"] == 3 and entry["anchor"] == "Anker"
    assert re.fullmatch(r"[0-9a-f]{32}\.webp", entry["file"])
    image = Image.open(tmp_path / "src-1" / entry["file"])
    assert image.format == "WEBP"
    assert max(image.size) == 800 and image.size == (800, 500)


def test_store_images_does_not_enlarge_small_images(tmp_path):
    entry = source_images.store_images(tmp_path, "s", [_item(_jpeg((300, 200)))])[0]

    assert Image.open(tmp_path / "s" / entry["file"]).size == (300, 200)


def test_store_images_strips_metadata(tmp_path):
    entry = source_images.store_images(tmp_path, "s", [_item(_jpeg((400, 300), exif=True))])[0]

    image = Image.open(tmp_path / "s" / entry["file"])
    assert not image.info.get("exif") and not image.getexif()


def test_store_images_skips_undecodable_bytes(tmp_path):
    entries = source_images.store_images(tmp_path, "s", [_item(b"kein bild"), _item(_jpeg((300, 300)))])

    assert len(entries) == 1


def test_store_images_limits_count_to_30(tmp_path):
    entries = source_images.store_images(tmp_path, "s", [_item(_jpeg((200, 200))) for _ in range(35)])

    assert len(entries) == 30


def test_store_images_limits_total_size(tmp_path, monkeypatch):
    noisy = Image.effect_noise((400, 400), 80).convert("RGB")
    buf = io.BytesIO()
    noisy.save(buf, format="PNG")
    probe = source_images.store_images(tmp_path / "probe", "p", [_item(buf.getvalue())])[0]
    one = (tmp_path / "probe" / "p" / probe["file"]).stat().st_size
    monkeypatch.setattr(source_images, "MAX_BYTES_PER_SOURCE", int(one * 2.5))

    entries = source_images.store_images(tmp_path / "real", "s", [_item(buf.getvalue()) for _ in range(4)])

    assert len(entries) == 2


def test_image_path_accepts_only_valid_names(tmp_path):
    entry = source_images.store_images(tmp_path, "src-1", [_item(_jpeg((300, 300)))])[0]

    assert source_images.image_path(tmp_path, "src-1", entry["file"]) == tmp_path / "src-1" / entry["file"]
    for bad_source, bad_name in (
        ("src-1", "../x.webp"),
        ("src-1", entry["file"].upper()),
        ("src-1", entry["file"][:-5] + ".png"),
        ("src-1", "a" * 31 + ".webp"),
        ("..", entry["file"]),
        ("src-1/../src-1", entry["file"]),
        ("src-2", entry["file"]),
        ("src-1", "0" * 32 + ".webp"),
    ):
        assert source_images.image_path(tmp_path, bad_source, bad_name) is None


def test_delete_source_images_removes_folder(tmp_path):
    source_images.store_images(tmp_path, "s", [_item(_jpeg((300, 300)))])

    source_images.delete_source_images(tmp_path, "s")

    assert not (tmp_path / "s").exists()
    source_images.delete_source_images(tmp_path, "s")  # idempotent


def test_staging_roundtrip_requires_identical_url(tmp_path):
    images = [{"kind": "url", "url": "https://img.example.org/a.jpg", "alt": "A", "anchor": "Anker"}]
    token = source_images.stage_web_images(tmp_path, "https://example.org/a", images)

    assert source_images.take_staged_web_images(tmp_path, token, "https://example.org/fremd") is None
    assert source_images.take_staged_web_images(tmp_path, token, "https://example.org/a") == images
    assert source_images.take_staged_web_images(tmp_path, "../../etc/passwd", "https://example.org/a") is None
    assert source_images.take_staged_web_images(tmp_path, "0" * 32, "https://example.org/a") is None


def test_staging_sanitizes_images_again_on_take(tmp_path):
    token = source_images.stage_web_images(tmp_path, "https://example.org/a", [])
    (tmp_path / f"{token}.json").write_text(
        json.dumps(
            {
                "url": "https://example.org/a",
                "images": [
                    {"kind": "url", "url": "http://img.example.org/a.jpg", "alt": "x", "anchor": "A"},
                    {"kind": "url", "url": "javascript:alert(1)", "alt": "x", "anchor": "A"},
                    {"kind": "file", "file": "0" * 32 + ".webp", "alt": "x", "anchor": "A"},
                    {"kind": "url", "url": "https://img.example.org/ok.jpg", "alt": "y" * 500, "anchor": "A"},
                ],
            }
        )
    )

    result = source_images.take_staged_web_images(tmp_path, token, "https://example.org/a")

    assert [i["url"] for i in result] == ["https://img.example.org/ok.jpg"]
    assert len(result[0]["alt"]) == 300


def test_staging_empty_list_is_valid_but_not_none(tmp_path):
    token = source_images.stage_web_images(tmp_path, "https://example.org/a", [])

    assert source_images.take_staged_web_images(tmp_path, token, "https://example.org/a") == []


def test_store_images_skips_images_above_pixel_limit(tmp_path):
    # 1-Bit-PNG: winzige Datei, aber 36 Megapixel - darf nie dekodiert werden.
    buf = io.BytesIO()
    Image.new("1", (6000, 6000)).save(buf, format="PNG")

    assert source_images.store_images(tmp_path, "s", [_item(buf.getvalue())]) == []
