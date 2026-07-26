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


def test_generate_author_bio_returns_plain_text_response():
    client = _fake_client("Eine kurze Vita.")
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_author_bio("Jane Doe", ["Titel: Zusammenfassung."])

    assert result == "Eine kurze Vita."


def test_generate_author_bio_returns_empty_for_no_texts():
    with patch.object(summarization, "_get_client") as get_client_mock:
        result = summarization.generate_author_bio("Jane Doe", [])

    assert result == ""
    get_client_mock.assert_not_called()


def test_generate_author_bio_returns_empty_on_api_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_author_bio("Jane Doe", ["Titel: Text."])

    assert result == ""


def test_generate_author_bio_uses_english_prompt_when_requested():
    client = _fake_client("Bio.")
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.generate_author_bio("Jane Doe", ["Title: Text."], lang="en")

    assert client.messages.create.call_args.kwargs["system"] == summarization.BIO_SYSTEM_PROMPTS["en"]
