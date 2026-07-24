from app import users


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")


def test_first_load_seeds_default_users(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    result = users.list_users()

    ids = {u["id"] for u in result}
    assert ids == {"anon", "lena.pflegerin", "uwe.admin", "root"}


def test_anon_has_no_roles(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert users.get_roles("anon") == []


def test_unknown_user_has_no_roles(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert users.get_roles("does-not-exist") == []


def test_has_role_true_for_matching_role(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert users.has_role("lena.pflegerin", users.QUELLEN_PFLEGER) is True


def test_has_role_false_for_non_matching_role(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert users.has_role("uwe.admin", users.QUELLEN_PFLEGER) is False


def test_system_admin_has_every_role(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert users.has_role("root", users.QUELLEN_PFLEGER) is True
    assert users.has_role("root", users.USER_ADMIN) is True
