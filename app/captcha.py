import json
import os
import urllib.parse
import urllib.request

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_SECONDS = 5


def verify_turnstile_token(token: str, remote_ip: str | None = None) -> bool:
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "")
    if not secret:
        # Turnstile ist (noch) nicht konfiguriert (z.B. lokale Entwicklung) -
        # der Schutz kann dann nicht greifen, die App bleibt aber nutzbar.
        return True
    if not token:
        return False

    data = {"secret": secret, "response": token}
    if remote_ip:
        data["remoteip"] = remote_ip

    try:
        req = urllib.request.Request(
            VERIFY_URL,
            data=urllib.parse.urlencode(data).encode("utf-8"),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return bool(result.get("success"))
    except Exception:
        return False
