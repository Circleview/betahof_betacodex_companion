from app import users


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")


def test_unknown_user_has_no_roles(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert users.get_roles("does-not-exist@test.local") == []


def test_none_email_has_no_roles(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    assert users.get_roles(None) == []


def test_invite_user_creates_invited_entry(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    entry = users.invite_user("Lena@Test.local", users.QUELLEN_PFLEGER, invited_by="root@test.local")

    assert entry["email"] == "lena@test.local"
    assert entry["roles"] == [users.QUELLEN_PFLEGER]
    assert entry["status"] == "invited"
    assert users.get_user("lena@test.local") is not None


def test_invite_user_is_idempotent_and_merges_roles(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    users.invite_user("lena@test.local", users.QUELLEN_PFLEGER, invited_by="root@test.local")
    users.invite_user("lena@test.local", users.USER_ADMIN, invited_by="root@test.local")

    entry = users.get_user("lena@test.local")
    assert set(entry["roles"]) == {users.QUELLEN_PFLEGER, users.USER_ADMIN}
    assert len(users.list_users()) == 1


def test_has_role_true_for_matching_role(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    users.invite_user("lena@test.local", users.QUELLEN_PFLEGER, invited_by="root@test.local")

    assert users.has_role("lena@test.local", users.QUELLEN_PFLEGER) is True


def test_has_role_false_for_non_matching_role(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    users.invite_user("uwe@test.local", users.USER_ADMIN, invited_by="root@test.local")

    assert users.has_role("uwe@test.local", users.QUELLEN_PFLEGER) is False


def test_system_admin_has_every_role(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    users.invite_user("root@test.local", users.SYSTEM_ADMIN, invited_by="bootstrap")

    assert users.has_role("root@test.local", users.QUELLEN_PFLEGER) is True
    assert users.has_role("root@test.local", users.USER_ADMIN) is True


def test_mark_logged_in_updates_status_and_timestamp(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    users.invite_user("lena@test.local", users.QUELLEN_PFLEGER, invited_by="root@test.local")

    users.mark_logged_in("lena@test.local")

    entry = users.get_user("lena@test.local")
    assert entry["status"] == "active"
    assert entry["last_login_at"] is not None


def test_ensure_bootstrap_admin_creates_system_admin(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    users.ensure_bootstrap_admin("root@test.local")

    assert users.has_role("root@test.local", users.SYSTEM_ADMIN) is True


def test_ensure_bootstrap_admin_is_idempotent(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    users.ensure_bootstrap_admin("root@test.local")
    users.ensure_bootstrap_admin("root@test.local")

    assert len(users.list_users()) == 1
    assert users.get_user("root@test.local")["roles"] == [users.SYSTEM_ADMIN]


def test_ensure_bootstrap_admin_does_nothing_when_empty(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    users.ensure_bootstrap_admin("")

    assert users.list_users() == []


def test_load_ignores_legacy_entries_without_valid_email_or_roles(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    users.USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    users.USERS_FILE.write_text(
        '{"anon": {"name": "Anonym", "roles": []}, '
        '"lena.pflegerin": {"name": "Lena", "roles": ["quellen_pfleger"]}}'
    )

    # "anon" hat keine gültige E-Mail (kein "@"), "lena.pflegerin" ebenso -
    # beide alten Dev-Stub-Einträge werden beim Laden verworfen statt einen
    # Absturz auszulösen.
    assert users.list_users() == []
    assert users.get_roles("lena.pflegerin") == []
