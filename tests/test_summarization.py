from unittest.mock import MagicMock, patch

from app import summarization


def _fake_client(response_text):
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text=response_text)]
    return client


def test_generate_summary_parses_json_response():
    raw = '{"summary": "Eine Zusammenfassung.", "key_terms": ["BetaCodex", "Dezentralisierung"]}'
    client = _fake_client(raw)
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_summary("Ein langer Quelltext.")

    assert result == {
        "summary": "Eine Zusammenfassung.",
        "key_terms": ["BetaCodex", "Dezentralisierung"],
    }


def test_generate_summary_strips_markdown_code_fence():
    raw = '```json\n{"summary": "Text.", "key_terms": ["Begriff"]}\n```'
    client = _fake_client(raw)
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_summary("Quelltext.")

    assert result == {"summary": "Text.", "key_terms": ["Begriff"]}


def test_generate_summary_returns_empty_on_malformed_json():
    client = _fake_client("das ist kein JSON")
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_summary("Quelltext.")

    assert result == {"summary": "", "key_terms": []}


def test_generate_summary_returns_empty_on_api_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_summary("Quelltext.")

    assert result == {"summary": "", "key_terms": []}


def test_generate_summary_returns_empty_for_blank_text():
    result = summarization.generate_summary("   ")
    assert result == {"summary": "", "key_terms": []}


def test_generate_summary_uses_english_prompt_when_requested():
    raw = '{"summary": "Summary.", "key_terms": ["Term"]}'
    client = _fake_client(raw)
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.generate_summary("Source text.", lang="en")

    assert client.messages.create.call_args.kwargs["system"] == summarization.SYSTEM_PROMPTS["en"]


def test_generate_summary_filters_blank_key_terms():
    raw = '{"summary": "Text.", "key_terms": ["Gut", "", "  "]}'
    client = _fake_client(raw)
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_summary("Quelltext.")

    assert result["key_terms"] == ["Gut"]
