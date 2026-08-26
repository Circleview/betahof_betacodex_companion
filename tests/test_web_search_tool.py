from unittest.mock import MagicMock

from app import web_search_tool


def test_build_tool_returns_expected_shape():
    assert web_search_tool.build_tool(3) == {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 3,
    }


def test_real_search_result_urls_collects_urls_from_search_result_blocks():
    search_block = MagicMock(type="web_search_tool_result")
    search_block.content = [MagicMock(url="https://a.org/x"), MagicMock(url="https://b.org/y")]
    message = MagicMock(content=[search_block])

    assert web_search_tool.real_search_result_urls(message) == {"https://a.org/x", "https://b.org/y"}


def test_real_search_result_urls_ignores_non_search_result_blocks():
    text_block = MagicMock(type="text", text="Ich habe nichts gefunden.")
    tool_use_block = MagicMock(type="tool_use")
    message = MagicMock(content=[text_block, tool_use_block])

    assert web_search_tool.real_search_result_urls(message) == set()


def test_real_search_result_urls_ignores_error_result_content():
    """WebSearchToolResultBlockContent ist entweder eine echte Trefferliste
    ODER ein WebSearchToolResultError-Objekt (z.B. bei Rate-Limits) - im
    Fehlerfall gibt es keine verifizierbaren URLs."""
    error_block = MagicMock(type="web_search_tool_result")
    error_block.content = MagicMock()  # kein list -> simuliert WebSearchToolResultError
    message = MagicMock(content=[error_block])

    assert web_search_tool.real_search_result_urls(message) == set()


def test_real_search_result_urls_returns_empty_set_without_any_blocks():
    message = MagicMock(content=[])
    assert web_search_tool.real_search_result_urls(message) == set()
