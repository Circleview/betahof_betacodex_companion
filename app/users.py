import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
USERS_FILE = BASE_DIR / "data" / "users.json"

QUELLEN_PFLEGER = "quellen_pfleger"
USER_ADMIN = "user_admin"
SYSTEM_ADMIN = "system_admin"
ALL_ROLES = [QUELLEN_PFLEGER, USER_ADMIN, SYSTEM_ADMIN]


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _load() -> dict:
    if not USERS_FILE.exists():
        return {}
    try:
        data = json.loads(USERS_FILE.read_text())
    except Exception:
        return {}
    # Defensiv: eine veraltete/vergessene users.json (z.B. aus dem alten
    # Dev-Rollen-Stub) soll nie zum Absturz führen - Einträge ohne die
    # erwartete Form (kein gültiger E-Mail-Key, keine "roles"-Liste) werden
    # einfach ignoriert statt einen KeyError zu werfen.
    return {
        email: entry
        for email, entry in data.items()
        if isinstance(entry, dict) and "@" in email and isinstance(entry.get("roles"), list)
    }


def _save(users: dict) -> None:
    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, ensure_ascii=False, indent=2))


def get_user(email: str) -> dict | None:
    users = _load()
    return users.get(_normalize_email(email))


def list_users() -> list[dict]:
    users = _load()
    return sorted(users.values(), key=lambda u: u["email"])


def get_roles(email: str | None) -> list[str]:
    if not email:
        return []
    user = get_user(email)
    return user["roles"] if user else []


def has_role(email: str | None, role: str) -> bool:
    roles = get_roles(email)
    return SYSTEM_ADMIN in roles or role in roles


def invite_user(email: str, role: str, invited_by: str) -> dict:
    email = _normalize_email(email)
    users = _load()
    now = datetime.now(timezone.utc).isoformat()
    entry = users.get(email)
    if entry is None:
        entry = {
            "email": email,
            "roles": [],
            "status": "invited",
            "invited_by": invited_by,
            "invited_at": now,
            "last_login_at": None,
        }
    if role not in entry["roles"]:
        entry["roles"].append(role)
    users[email] = entry
    _save(users)
    return entry


def mark_logged_in(email: str) -> None:
    email = _normalize_email(email)
    users = _load()
    entry = users.get(email)
    if entry is None:
        return
    entry["status"] = "active"
    entry["last_login_at"] = datetime.now(timezone.utc).isoformat()
    users[email] = entry
    _save(users)


def ensure_bootstrap_admin(email: str) -> None:
    email = _normalize_email(email)
    if not email:
        return
    users = _load()
    entry = users.get(email)
    if entry is not None and SYSTEM_ADMIN in entry.get("roles", []):
        return
    invite_user(email, SYSTEM_ADMIN, invited_by="bootstrap")
