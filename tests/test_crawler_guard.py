"""Crawler-Schutz (Idee 669405f0): UA-Sperre aus robots.txt, IP-Bremsen für
Gäste, kein Volltext für Gäste, serverseitige Gäste-Suche."""

import logging

import pytest
from fastapi.testclient import TestClient

from app import auth, ratelimit, users
from app import main as main_module

GPT = "Mozilla/5.0 (compatible; GPTBot/1.1; +https://openai.com/gptbot)"
EMAIL = "lena.pflegerin@test.local"


def _src(sid, title, text, **extra):
    return {
        "id": sid, "title": title, "authors": [], "date": None, "url": None,
        "imported_at": "2026-01-01T00:00:00+00:00", "chunk_count": 1, "text": text,
        **extra,
    }


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(main_module, "SOURCES_FILE", tmp_path / "sources.json")
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(ratelimit, "_request_log", {})
    monkeypatch.setattr(ratelimit, "_windows", {})
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", True)
    sources = {
        "a": _src("a", "Alpha", "Das Wort Zebrafink steht nur hier."),
        "b": _src("b", "Beta", "Öl und Äpfel.", authors=["Karl Autor"], summary_de="Kurz Kolibri"),
        "c": _src("c", "Gamma Titel", "Geheimwort Quokka", restricted=True),
        "d": _src("d", "Delta", "Zebrafink gelöscht", deleted_at="2026-02-01T00:00:00+00:00"),
    }
    main_module._save_sources(sources)
    return main_module.app


def client(app, ip="1.2.3.4", ua="Mozilla/5.0 Firefox"):
    return TestClient(app, client=(ip, 50000), headers={"user-agent": ua})


def login(c, email=EMAIL, role=None):
    if role:
        users.invite_user(email, role, invited_by="test")
    c.cookies.set(auth.SESSION_COOKIE_NAME, auth.create_session_token(email))


# --- UA-Sperre ---------------------------------------------------------------

@pytest.mark.parametrize("path", ["/", "/api/sources"])
def test_gptbot_blocked_with_security_headers(env, path):
    for ua in (GPT, "gptbot"):
        r = client(env, ua=ua).get(path)
        assert r.status_code == 403
        assert r.headers["x-content-type-options"] == "nosniff"
        assert "default-src" in r.headers["content-security-policy"]


def test_gptbot_robots_free_and_mcp_reaches_key_check(env):
    c = client(env, ua=GPT)
    assert c.get("/robots.txt").status_code == 200
    assert c.post("/mcp", json={}).status_code == 401


@pytest.mark.parametrize(
    "ua",
    ["ChatGPT-User/1.0", "Claude-User/1.0", "Perplexity-User/1.0", "Googlebot/2.1", "Applebot/0.1",
     "Mozilla/5.0 Firefox", ""],
)
def test_other_agents_pass(env, ua):
    assert client(env, ua=ua).get("/").status_code == 200


def test_blocklist_comes_from_robots_txt():
    names = main_module.load_blocked_agents(main_module.STATIC_DIR / "robots.txt")
    for n in ("gptbot", "ccbot", "claudebot", "meta-externalagent", "oai-searchbot", "claude-searchbot"):
        assert n in names
    assert "chatgpt-user" not in names and "*" not in names


def test_loader_parsing(tmp_path):
    f = tmp_path / "robots.txt"
    f.write_text(
        "\nUser-agent: *\nDisallow: /\nUser-agent: ab\nUser-agent: GPTBot # Kommentar\n"
        "Disallow: /\nuser-agent:   NeuerBot  \n"
    )
    assert main_module.load_blocked_agents(f) == ("gptbot", "neuerbot")
    assert main_module.load_blocked_agents(tmp_path / "fehlt.txt") == ()


def test_new_name_takes_effect_without_code_change(env, monkeypatch, tmp_path):
    f = tmp_path / "robots.txt"
    f.write_text("User-agent: FooCrawler\n")
    monkeypatch.setattr(main_module, "BLOCKED_AGENTS", main_module.load_blocked_agents(f))
    assert client(env, ua="x FooCrawler/1").get("/").status_code == 403
    assert client(env, ua=GPT).get("/").status_code == 200


# --- Kein Volltext für Gäste ---------------------------------------------------

def test_guest_gets_no_full_text(env):
    c = client(env)
    for url in ("/api/sources", "/api/sources?include_text=true&include_text=TRUE"):
        rows = c.get(url).json()
        assert rows and all(s["text"] == "" for s in rows)


def test_logged_in_user_gets_text(env):
    c = client(env)
    login(c, role=users.QUELLEN_PFLEGER)
    rows = {s["id"]: s for s in c.get("/api/sources").json()}
    assert rows["a"]["text"].startswith("Das Wort")


def test_session_of_deleted_user_is_guest(env):
    c = client(env)
    login(c, role=users.QUELLEN_PFLEGER)
    users.delete_user(EMAIL)
    assert all(s["text"] == "" for s in c.get("/api/sources").json())


# --- Gäste-Suche ---------------------------------------------------------------

def _ids(c, q, **kw):
    r = c.get("/api/sources/search", params={"q": q}, **kw)
    assert r.status_code == 200
    assert set(r.json()) == {"ids"}
    return r.json()["ids"]


def test_search_full_text_case_umlaut_and_fields(env):
    c = client(env)
    assert _ids(c, "zebrafink") == ["a"]
    assert _ids(c, "ZEBRAFINK") == ["a"]
    assert _ids(c, "ÄPFEL") == ["b"]
    assert _ids(c, "kolibri") == ["b"]
    assert _ids(c, "karl autor") == ["b"]


def test_search_short_or_empty(env):
    c = client(env)
    assert _ids(c, "") == [] and _ids(c, "z") == [] and _ids(c, " z ") == []
    assert c.get("/api/sources/search", params={"q": "x" * 201}).status_code == 422


def test_search_restricted_text_only_for_pfleger(env):
    c = client(env)
    assert _ids(c, "quokka") == []
    assert _ids(c, "gamma") == ["c"]
    login(c, role=users.QUELLEN_PFLEGER)
    assert _ids(c, "quokka") == ["c"]
    assert _ids(c, "zebrafink") == ["a"]  # gelöschte nie


def test_search_english_title(env):
    src = main_module._load_sources()
    src["b"].update(title_en="Moonlight", text_lang="de")
    main_module._save_sources(src)
    c = client(env)
    assert _ids(c, "moonlight", headers={"X-Lang": "en"}) == ["b"]
    assert _ids(c, "moonlight", headers={"X-Lang": "de"}) == []


# --- Bremsen -------------------------------------------------------------------

def _hammer(c, url, n):
    return [c.get(url).status_code for _ in range(n)]


@pytest.mark.parametrize(
    "url,limit",
    [("/api/authors", 400), ("/api/sources/search?q=ab", 150)],
)
def test_limit_plus_one_returns_429(env, url, limit):
    c = client(env)
    codes = _hammer(c, url, limit)
    assert set(codes) == {200}
    r = c.get(url)
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) >= 1
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in r.headers
    # andere IP bleibt frei
    assert client(env, ip="5.6.7.8").get(url).status_code == 200


def test_source_limit_150(env):
    c = client(env)
    assert set(_hammer(c, "/api/sources/a", 150)) == {200}
    assert c.get("/api/sources/a").status_code == 429


def test_window_expires(env, monkeypatch):
    c = client(env)
    _hammer(c, "/api/sources/a", 150)
    assert c.get("/api/sources/a").status_code == 429
    for key, stamps in ratelimit._request_log.items():
        ratelimit._request_log[key] = [t - 700 for t in stamps]
    assert c.get("/api/sources/a").status_code == 200


def test_ipv6_same_64_counts_together(env):
    a, b = client(env, ip="2001:db8:1:2::1"), client(env, ip="2001:db8:1:2::ffff")
    _hammer(a, "/api/sources/a", 150)
    assert b.get("/api/sources/a").status_code == 429
    assert client(env, ip="2001:db8:1:3::1").get("/api/sources/a").status_code == 200


def test_logged_in_never_limited(env):
    c = client(env)
    login(c, role=users.QUELLEN_PFLEGER)
    assert set(_hammer(c, "/api/sources/a", 160)) == {200}


def test_images_photos_and_writes_do_not_count(env):
    c = client(env)
    for _ in range(420):
        c.get("/api/sources/a/images/x.png")
        c.get("/api/authors/Karl/photo/small")
    c.post("/api/sources", json={})
    c.delete("/api/sources/a")
    assert c.get("/api/authors").status_code == 200
    assert c.get("/api/sources/a").status_code == 200


def test_429_log_has_key_and_path_but_no_ip_or_query(env, caplog):
    c = client(env, ip="9.8.7.6")
    _hammer(c, "/api/sources/search?q=geheimsuche", 150)
    with caplog.at_level(logging.WARNING):
        assert c.get("/api/sources/search?q=geheimsuche").status_code == 429
    lines = [r.getMessage() for r in caplog.records if "crawler_guard" in r.getMessage()]
    assert len(lines) == 1
    assert "search-ip" in lines[0] and "/api/sources/search" in lines[0]
    assert "9.8.7.6" not in lines[0] and "geheimsuche" not in lines[0]
