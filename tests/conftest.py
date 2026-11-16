import pytest

from app import usage, vectorstore


# 2026-09-26: Kostenmessung läuft an allen Claude-/TTS-/Transkriptions-
# Aufrufen - in Tests nie in die echte data/usage_log.json schreiben und
# nie den Wechselkurs aus dem Netz holen.
@pytest.fixture(autouse=True)
def _isolate_usage_log(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "USAGE_FILE", tmp_path / "usage_log.json")
    monkeypatch.setattr(usage, "FX_FILE", tmp_path / "fx_rate.json")
    monkeypatch.setattr(usage, "_fetch_ecb_rate", lambda: (0.9, "2026-01-01"))


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
