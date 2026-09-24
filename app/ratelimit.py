import math
import time

WINDOW_SECONDS = 60
MAX_REQUESTS = 10

# Einfacher In-Memory Sliding-Window-Zähler pro Schlüssel (i.d.R. Client-IP).
# Für die Größenordnung dieses Projekts (ein Prozess, kein Cluster) reicht
# das - kein Redis o.ä. nötig.
_request_log: dict[str, list[float]] = {}


def is_rate_limited(
    key: str, max_requests: int = MAX_REQUESTS, window_seconds: int = WINDOW_SECONDS
) -> bool:
    now = time.monotonic()
    timestamps = _request_log.setdefault(key, [])
    cutoff = now - window_seconds
    while timestamps and timestamps[0] < cutoff:
        timestamps.pop(0)
    if len(timestamps) >= max_requests:
        return True
    timestamps.append(now)
    return False


def retry_after_seconds(key: str, window_seconds: int = WINDOW_SECONDS) -> int:
    """Sekunden, bis der älteste gezählte Aufruf aus dem Fenster fällt und
    wieder ein Aufruf frei ist (2026-09-24: Countdown im Kreativ-Modus, als
    Retry-After-Header). Nur nach einem is_rate_limited() == True sinnvoll."""
    timestamps = _request_log.get(key) or []
    if not timestamps:
        return 0
    return max(1, math.ceil(timestamps[0] + window_seconds - time.monotonic()))
