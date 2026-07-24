import urllib.error
import urllib.request

TIMEOUT_SECONDS = 5


def _request(url: str, method: str) -> dict:
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
        return {"reachable": resp.status < 400, "status_code": resp.status}


def check_url(url: str) -> dict:
    try:
        return _request(url, "HEAD")
    except urllib.error.HTTPError as err:
        if err.code == 405:
            try:
                return _request(url, "GET")
            except Exception:
                return {"reachable": False, "status_code": None}
        return {"reachable": err.code < 400, "status_code": err.code}
    except Exception:
        return {"reachable": False, "status_code": None}
