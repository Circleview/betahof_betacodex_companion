import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
USERS_FILE = BASE_DIR / "data" / "users.json"

QUELLEN_PFLEGER = "quellen_pfleger"
USER_ADMIN = "user_admin"
SYSTEM_ADMIN = "system_admin"

DEFAULT_USERS = {
    "anon": {"name": "Anonym (kein Login)", "roles": []},
    "lena.pflegerin": {"name": "Lena (Quellen-Pfleger:in)", "roles": [QUELLEN_PFLEGER]},
    "uwe.admin": {"name": "Uwe (User-Admin)", "roles": [USER_ADMIN]},
    "root": {"name": "Root (System-Admin)", "roles": [SYSTEM_ADMIN]},
}


def _load() -> dict:
    if not USERS_FILE.exists():
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        USERS_FILE.write_text(json.dumps(DEFAULT_USERS, ensure_ascii=False, indent=2))
        return json.loads(json.dumps(DEFAULT_USERS))
    return json.loads(USERS_FILE.read_text())


def list_users() -> list[dict]:
    users = _load()
    return [{"id": uid, "name": u["name"], "roles": u["roles"]} for uid, u in users.items()]


def get_roles(user_id: str) -> list[str]:
    users = _load()
    user = users.get(user_id)
    return user["roles"] if user else []


def has_role(user_id: str, role: str) -> bool:
    roles = get_roles(user_id)
    return SYSTEM_ADMIN in roles or role in roles
