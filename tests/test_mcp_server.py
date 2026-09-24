"""MCP-Zugang zum Kreativ-Modus (app/mcp_server.py, app/mcp_keys.py) - echte
MCP-Anfragen (JSON-RPC über Streamable HTTP) gegen den echten SDK-Server,
nur die KI und der Retrieval-Kontext sind simuliert."""
import contextlib

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

from app import jsonstore, llm, mcp_keys, mcp_server, question_log, usage, users
from app import main as main_module

OWNER = "mcp@test.local"
FAKE_USAGE = {
    "model": "claude-sonnet-5",
    "input_tokens": 1000,
    "output_tokens": 500,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 0,
    "web_search_requests": 1,
}


class _FakeStream:
    def __init__(self, text, usage_dict):
        self._text = text
        self.real_web_urls = {"https://web.example/a"}
        self.model = "claude-sonnet-5"
        self.usage = None
        self._usage_dict = usage_dict

    def __iter__(self):
        yield self._text
        self.usage = self._usage_dict


@pytest.fixture(scope="module")
def mcp_client():
    # Der SDK-Sitzungs-Manager lässt sich pro Prozess nur einmal starten -
    # deshalb ein gemeinsamer Client für alle Tests dieser Datei.
    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with mcp_server.session_manager.run():
            yield

    app = Starlette(routes=[Route(mcp_server.MCP_PATH, endpoint=mcp_server.asgi_app)], lifespan=lifespan)
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(users, "USERS_FILE", tmp_path / "users.json")
    monkeypatch.setattr(mcp_keys, "MCP_KEYS_FILE", tmp_path / "mcp_keys.json")
    monkeypatch.setattr(usage, "USAGE_FILE", tmp_path / "usage_log.json")
    monkeypatch.setattr(usage, "FX_FILE", tmp_path / "fx_rate.json")
    monkeypatch.setattr(usage, "_fetch_ecb_rate", lambda: (0.9, "2026-09-23"))
    monkeypatch.setattr(question_log, "QUESTION_LOG_FILE", tmp_path / "question_log.json")
    monkeypatch.setattr(main_module, "IS_DEV_ENVIRONMENT", False)
    monkeypatch.setattr(
        main_module,
        "_creative_context",
        lambda instruction, document, lang: (
            [],
            [{"title": "Beta-Kodex", "authors": ["Niels Pflaeging"], "date": "2011-01-01", "url": None, "url_reachable": None}],
        ),
    )
    calls = []

    def fake_stream(instruction, document, chunks, lang="de", section=None, web_search=True):
        calls.append({"instruction": instruction, "document": document, "lang": lang, "web_search": web_search})
        text = "# Titel\n\nText über Beta.\n\n---SOURCES---\n[Web]: Web A – https://web.example/a\n"
        return _FakeStream(text, FAKE_USAGE)

    monkeypatch.setattr(llm, "stream_creative_response", fake_stream)
    users.invite_user(OWNER, users.MCP_NUTZER, invited_by="root@test.local")
    return calls


def _rpc(client, method, params, key):
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return client.post(
        mcp_server.MCP_PATH, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )


def _call(client, key, name, arguments):
    return _rpc(client, "tools/call", {"name": name, "arguments": arguments}, key)


def test_request_without_key_is_rejected(mcp_client):
    response = _rpc(mcp_client, "tools/list", {}, None)
    assert response.status_code == 401
    assert "Bearer" in response.headers["www-authenticate"]


def test_revoked_key_and_removed_role_are_rejected(mcp_client):
    key, secret = mcp_keys.create_key(OWNER, "Laptop")
    assert _rpc(mcp_client, "tools/list", {}, secret).status_code == 200

    users.set_roles(OWNER, [users.QUELLEN_PFLEGER])
    assert _rpc(mcp_client, "tools/list", {}, secret).status_code == 401

    users.set_roles(OWNER, [users.MCP_NUTZER])
    mcp_keys.revoke_key(key["id"])
    assert _rpc(mcp_client, "tools/list", {}, secret).status_code == 401


def test_tools_list_offers_create_and_revise(mcp_client):
    _, secret = mcp_keys.create_key(OWNER, "Laptop")
    tools = _rpc(mcp_client, "tools/list", {}, secret).json()["result"]["tools"]
    assert {t["name"] for t in tools} == {"create_text", "revise_text"}


def test_create_text_returns_document_with_sources_and_records_usage(mcp_client, _isolate):
    key, secret = mcp_keys.create_key(OWNER, "Laptop")

    result = _call(mcp_client, secret, "create_text", {"instruction": "Schreib über Beta."}).json()["result"]

    assert result.get("isError") is not True
    text = result["content"][0]["text"]
    assert text.startswith("# Titel\n\nText über Beta.")
    assert "- BetaCodex: Beta-Kodex (Niels Pflaeging, 2011)" in text
    assert "- Web: Web A https://web.example/a" in text
    assert "---SOURCES---" not in text
    assert _isolate == [{"instruction": "Schreib über Beta.", "document": "", "lang": "de", "web_search": True}]
    entry = usage.list_entries()[0]
    assert (entry["channel"], entry["key_id"], entry["email"]) == ("mcp", key["id"], OWNER)
    log = question_log.list_entries()[0]
    assert log["event_types"] == ["mcp"] and "email" not in log


def test_revise_text_passes_document_language_and_web_search(mcp_client, _isolate):
    _, secret = mcp_keys.create_key(OWNER, "Laptop")

    _call(
        mcp_client,
        secret,
        "revise_text",
        {"document": "Alter Text.", "instruction": "Kürzer.", "language": "en", "web_search": False},
    )

    assert _isolate == [{"instruction": "Kürzer.", "document": "Alter Text.", "lang": "en", "web_search": False}]
    assert usage.list_entries()[0]["web_search_enabled"] is False


def test_daily_limit_blocks_further_calls(mcp_client, _isolate):
    key, secret = mcp_keys.create_key(OWNER, "Laptop")
    mcp_keys.set_limits(key["id"], daily_call_limit=1, monthly_eur_limit=5.0)

    _call(mcp_client, secret, "create_text", {"instruction": "Eins."})
    second = _call(mcp_client, secret, "create_text", {"instruction": "Zwei."}).json()["result"]

    assert second["isError"] is True
    assert "Tageslimit" in second["content"][0]["text"]
    assert len(_isolate) == 1


def test_monthly_budget_blocks_calls(mcp_client, _isolate):
    key, secret = mcp_keys.create_key(OWNER, "Laptop")
    mcp_keys.set_limits(key["id"], daily_call_limit=30, monthly_eur_limit=0.0)

    result = _call(mcp_client, secret, "create_text", {"instruction": "Eins."}).json()["result"]

    assert result["isError"] is True
    assert "Monatsbudget" in result["content"][0]["text"]
    assert _isolate == []


def test_key_is_stored_only_as_hash():
    key, secret = mcp_keys.create_key(OWNER, "Laptop")
    stored = jsonstore.load(mcp_keys.MCP_KEYS_FILE, {})[key["id"]]

    assert secret not in str(stored)
    assert "key_hash" not in key
    assert mcp_keys.authenticate(secret)["id"] == key["id"]
    assert mcp_keys.authenticate(secret + "x") is None
