import ipaddress
import math
import time

WINDOW_SECONDS = 60
MAX_REQUESTS = 10

# Einfacher In-Memory Sliding-Window-Zähler pro Schlüssel (i.d.R. Client-IP).
# Für die Größenordnung dieses Projekts (ein Prozess, kein Cluster) reicht
# das - kein Redis o.ä. nötig.
_request_log: dict[str, list[float]] = {}
_windows: dict[str, int] = {}
# Zeichenbudget (Zeitpunkt, Zeichen) je Schlüssel, z. B. für TTS-Kosten.
_char_log: dict[str, list[tuple[float, int]]] = {}
_char_windows: dict[str, int] = {}
_last_sweep = 0.0
SWEEP_INTERVAL_SECONDS = 60


def ip_key(ip: str) -> str:
    """IPv6 auf das /64-Präfix kürzen (ein Anschluss hat ein ganzes /64);
    IPv4 und Nicht-IP-Werte (z. B. "unknown") bleiben unverändert."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    addr = getattr(addr, "ipv4_mapped", None) or addr
    if addr.version == 4:
        return str(addr)
    return str(ipaddress.ip_network(f"{addr}/64", strict=False).network_address) + "/64"


def _sweep(now: float) -> None:
    """Abgelaufene Schlüssel entfernen, höchstens einmal je Intervall."""
    global _last_sweep
    if now - _last_sweep < SWEEP_INTERVAL_SECONDS:
        return
    _last_sweep = now
    for key in [k for k, t in _request_log.items() if not t or t[-1] < now - _windows.get(k, WINDOW_SECONDS)]:
        del _request_log[key]
        _windows.pop(key, None)
    for key in [k for k, t in _char_log.items() if not t or t[-1][0] < now - _char_windows.get(k, 0)]:
        del _char_log[key]
        _char_windows.pop(key, None)


def is_char_budget_exceeded(key: str, chars: int, max_chars: int, window_seconds: int) -> bool:
    """True, wenn chars das Budget im gleitenden Fenster sprengen würden (dann
    nichts gezählt); sonst werden chars verbucht und False geliefert."""
    now = time.monotonic()
    _sweep(now)
    entries = _char_log.setdefault(key, [])
    _char_windows[key] = window_seconds
    cutoff = now - window_seconds
    while entries and entries[0][0] < cutoff:
        entries.pop(0)
    if sum(n for _, n in entries) + chars > max_chars:
        return True
    entries.append((now, chars))
    return False


def is_rate_limited(
    key: str, max_requests: int = MAX_REQUESTS, window_seconds: int = WINDOW_SECONDS
) -> bool:
    now = time.monotonic()
    _sweep(now)
    timestamps = _request_log.setdefault(key, [])
    _windows[key] = window_seconds
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
