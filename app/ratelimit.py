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
