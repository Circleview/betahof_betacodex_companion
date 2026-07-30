import socket
import ssl
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 5

# Manche Server (Bot-/Hotlink-Schutz) lehnen Requests ohne "Accept"-Header
# mit HTTP 406 ab, selbst mit plausiblem User-Agent - ein echter Browser
# schickt diesen Header immer mit (siehe gleiches Problem/Fix in
# app/extraction.py:_REQUEST_HEADERS).
_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "*/*",
}


def _request(url: str, method: str) -> dict:
    req = urllib.request.Request(url, method=method, headers=_REQUEST_HEADERS)
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        reachable = resp.status < 400
        return {
            "reachable": reachable,
            "status_code": resp.status,
            "reason_code": None if reachable else "http_error",
        }


def _classify_http_error(err: urllib.error.HTTPError) -> dict:
    if err.code in (403, 429):
        # Viele Seiten (z. B. academia.edu) blockieren automatisierte
        # HEAD/GET-Anfragen pauschal mit 403, obwohl die Seite im Browser
        # normal erreichbar ist - das werten wir nicht als defekten Link.
        # LinkedIn (hinter Cloudflare) antwortet auf solche Anfragen sogar
        # mit 429 + Bot-Challenge-Seite, unabhängig davon, ob der Artikel
        # tatsächlich existiert - ebenfalls kein echter Broken Link.
        return {"reachable": True, "status_code": err.code, "reason_code": None}
    reachable = err.code < 400
    return {
        "reachable": reachable,
        "status_code": err.code,
        "reason_code": None if reachable else "http_error",
    }


# Backlog #163: Quellen-Pfleger:innen/Admins sollen den konkreten Grund
# sehen, nicht nur "nicht erreichbar" - urllib wickelt Verbindungsfehler
# (Timeout, DNS, SSL, Refused) in URLError.reason ein, dessen konkreter
# Typ hier auf einen stabilen, im Frontend übersetzten reason_code
# abgebildet wird (gleiches Muster wie models.SourceOut.processing_status).
def _classify_url_error(err: urllib.error.URLError) -> dict:
    reason = err.reason
    if isinstance(reason, (socket.timeout, TimeoutError)):
        reason_code = "timeout"
    elif isinstance(reason, socket.gaierror):
        reason_code = "dns_error"
    elif isinstance(reason, ssl.SSLError):
        reason_code = "ssl_error"
    elif isinstance(reason, OSError):
        reason_code = "connection_error"
    else:
        reason_code = "unknown_error"
    return {"reachable": False, "status_code": None, "reason_code": reason_code}


def check_url(url: str) -> dict:
    try:
        return _request(url, "HEAD")
    except urllib.error.HTTPError as err:
        if err.code == 405:
            try:
                return _request(url, "GET")
            except urllib.error.HTTPError as get_err:
                return _classify_http_error(get_err)
            except urllib.error.URLError as get_url_err:
                return _classify_url_error(get_url_err)
            except socket.timeout:
                return {"reachable": False, "status_code": None, "reason_code": "timeout"}
            except Exception:
                return {"reachable": False, "status_code": None, "reason_code": "unknown_error"}
        return _classify_http_error(err)
    except socket.timeout:
        return {"reachable": False, "status_code": None, "reason_code": "timeout"}
    except urllib.error.URLError as err:
        return _classify_url_error(err)
    except Exception:
        return {"reachable": False, "status_code": None, "reason_code": "unknown_error"}
