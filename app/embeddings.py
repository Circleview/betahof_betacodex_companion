import threading

from sentence_transformers import SentenceTransformer

MODEL_NAME = "intfloat/multilingual-e5-base"

_model = None
_model_lock = threading.Lock()


def _get_model() -> SentenceTransformer:
    global _model
    # Lock statt einer nackten None-Prüfung: preload_model() läuft in einem
    # Hintergrund-Thread (siehe app/main.py), eine echte Anfrage kann also
    # währenddessen gleichzeitig hier ankommen. Ohne Lock würden beide
    # parallel je ein eigenes Modell laden (mehrere Sekunden verschwendete
    # Arbeit, kein Geschwindigkeitsgewinn für die wartende Anfrage) - mit
    # Lock wartet die zweite einfach auf das bereits laufende Laden.
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(MODEL_NAME)
    return _model


def preload_model() -> None:
    """Lädt das Modell vorab (siehe app/main.py: läuft dort in einem
    Hintergrund-Thread beim Server-Start, damit der Start selbst nicht
    blockiert) statt lazy bei der ersten echten Anfrage - sonst zahlt
    zufällig die erste Nutzer:in nach einem Neustart die Ladezeit (mehrere
    Sekunden) mit."""
    _get_model()


def embed_passages(texts: list[str]) -> list[list[float]]:
    model = _get_model()
    prefixed = [f"passage: {t}" for t in texts]
    return model.encode(prefixed, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    model = _get_model()
    embedding = model.encode([f"query: {text}"], normalize_embeddings=True)
    return embedding[0].tolist()
