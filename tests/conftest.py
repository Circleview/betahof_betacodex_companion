import pytest

from app import usage


# 2026-09-26: Kostenmessung läuft an allen Claude-/TTS-/Transkriptions-
# Aufrufen - in Tests nie in die echte data/usage_log.json schreiben und
# nie den Wechselkurs aus dem Netz holen.
@pytest.fixture(autouse=True)
def _isolate_usage_log(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "USAGE_FILE", tmp_path / "usage_log.json")
    monkeypatch.setattr(usage, "FX_FILE", tmp_path / "fx_rate.json")
    monkeypatch.setattr(usage, "_fetch_ecb_rate", lambda: (0.9, "2026-01-01"))
