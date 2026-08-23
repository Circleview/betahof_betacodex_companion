from unittest.mock import MagicMock, patch

from app import source_discovery


def _fake_client_with_candidates(candidates):
    client = MagicMock()
    tool_use_block = MagicMock(type="tool_use", name="submit_candidates")
    tool_use_block.name = "submit_candidates"
    tool_use_block.input = {"candidates": candidates}
    client.messages.create.return_value = MagicMock(content=[tool_use_block])
    return client


def _fake_client_without_tool_use():
    client = MagicMock()
    text_block = MagicMock(type="text", text="Ich habe nichts gefunden.")
    client.messages.create.return_value = MagicMock(content=[text_block])
    return client


def test_discover_by_author_returns_candidates_with_discovery_metadata():
    candidates = [{"url": "https://a.org/x", "title": "X", "reason": "Passt."}]
    client = _fake_client_with_candidates(candidates)
    with patch.object(source_discovery, "_get_client", return_value=client):
        result = source_discovery.discover_by_author("Niels Pflaeging", set(), set())

    assert result == [
        {
            "url": "https://a.org/x",
            "title": "X",
            "reason": "Passt.",
            "discovered_via": "author",
            "author_hint": "Niels Pflaeging",
        }
    ]


def test_discover_by_topic_returns_candidates_with_discovery_metadata():
    candidates = [{"url": "https://b.org/y", "title": "Y", "reason": "Thematisch nah."}]
    client = _fake_client_with_candidates(candidates)
    with patch.object(source_discovery, "_get_client", return_value=client):
        result = source_discovery.discover_by_topic("Thema X, Thema Y", set(), set())

    assert result == [
        {
            "url": "https://b.org/y",
            "title": "Y",
            "reason": "Thematisch nah.",
            "discovered_via": "topic",
            "author_hint": None,
        }
    ]


def test_discover_by_author_includes_known_urls_and_excluded_domains_in_prompt():
    client = _fake_client_with_candidates([])
    with patch.object(source_discovery, "_get_client", return_value=client):
        source_discovery.discover_by_author(
            "Autor X", {"https://schon-bekannt.org/a"}, {"gesperrt.org"}
        )

    user_content = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "https://schon-bekannt.org/a" in user_content
    assert "gesperrt.org" in user_content


def test_discover_declares_both_web_search_and_submit_candidates_tools():
    client = _fake_client_with_candidates([])
    with patch.object(source_discovery, "_get_client", return_value=client):
        source_discovery.discover_by_topic("Thema", set(), set())

    tools = client.messages.create.call_args.kwargs["tools"]
    tool_types = {t.get("type") for t in tools}
    tool_names = {t.get("name") for t in tools}
    assert "web_search_20250305" in tool_types
    assert "submit_candidates" in tool_names
    # tool_choice bewusst NICHT gesetzt (Default "auto") - sonst würde das
    # Modell direkt submit_candidates erzwungen und nie erst suchen.
    assert "tool_choice" not in client.messages.create.call_args.kwargs


def test_discover_returns_empty_list_when_model_never_calls_submit_candidates():
    client = _fake_client_without_tool_use()
    with patch.object(source_discovery, "_get_client", return_value=client):
        result = source_discovery.discover_by_topic("Thema", set(), set())

    assert result == []


def test_discover_returns_empty_list_when_llm_call_fails():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    with patch.object(source_discovery, "_get_client", return_value=client):
        result = source_discovery.discover_by_author("Autor X", set(), set())

    assert result == []


def test_discover_respects_max_results():
    candidates = [
        {"url": f"https://a.org/{i}", "title": f"T{i}", "reason": "R"} for i in range(10)
    ]
    client = _fake_client_with_candidates(candidates)
    with patch.object(source_discovery, "_get_client", return_value=client):
        result = source_discovery.discover_by_author("Autor X", set(), set(), max_results=3)

    assert len(result) == 3


def test_discover_skips_candidates_missing_url_or_title():
    candidates = [
        {"url": "", "title": "Ohne URL", "reason": "R"},
        {"url": "https://a.org", "title": "", "reason": "R"},
        {"url": "https://a.org/ok", "title": "OK", "reason": "R"},
    ]
    client = _fake_client_with_candidates(candidates)
    with patch.object(source_discovery, "_get_client", return_value=client):
        result = source_discovery.discover_by_topic("Thema", set(), set())

    assert len(result) == 1
    assert result[0]["url"] == "https://a.org/ok"
