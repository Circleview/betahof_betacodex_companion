import urllib.error
import urllib.request

TIMEOUT_SECONDS = 5


def _request(url: str, method: str) -> dict:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return {"reachable": resp.status < 400, "status_code": resp.status}


def _classify_http_error(err: urllib.error.HTTPError) -> dict:
    if err.code == 403:
        # Viele Seiten (z. B. academia.edu) blockieren automatisierte
        # HEAD/GET-Anfragen pauschal mit 403, obwohl die Seite im Browser
        # normal erreichbar ist - das werten wir nicht als defekten Link.
        return {"reachable": True, "status_code": err.code}
    return {"reachable": err.code < 400, "status_code": err.code}


def check_url(url: str) -> dict:
    try:
        return _request(url, "HEAD")
    except urllib.error.HTTPError as err:
        if err.code == 405:
            try:
                return _request(url, "GET")
            except urllib.error.HTTPError as get_err:
                return _classify_http_error(get_err)
            except Exception:
                return {"reachable": False, "status_code": None}
        return _classify_http_error(err)
    except Exception:
        return {"reachable": False, "status_code": None}
