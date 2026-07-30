import threading
import time

from app import embeddings


def test_preload_model_loads_the_model_eagerly(monkeypatch):
    """Backlog: das lokale Embedding-Modell soll beim Server-Start geladen
    werden statt lazy bei der ersten echten Anfrage - sonst zahlt zufällig
    die erste Nutzer:in nach einem Neustart die Ladezeit mit."""
    monkeypatch.setattr(embeddings, "_model", None)

    assert embeddings._model is None
    embeddings.preload_model()
    assert embeddings._model is not None


def test_get_model_is_thread_safe_and_loads_only_once(monkeypatch):
    """Regression: preload_model() läuft in einem Hintergrund-Thread (siehe
    app/main.py), eine echte Anfrage kann also gleichzeitig embed_query()/
    embed_passages() aufrufen, während das Modell noch lädt. Ohne Lock
    würden beide parallel je ein eigenes, teures Modell laden."""
    monkeypatch.setattr(embeddings, "_model", None)
    call_count = {"n": 0}

    class SlowFakeModel:
        def __init__(self, *args, **kwargs):
            call_count["n"] += 1
            time.sleep(0.2)

    monkeypatch.setattr(embeddings, "SentenceTransformer", SlowFakeModel)

    threads = [threading.Thread(target=embeddings._get_model) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert call_count["n"] == 1
