from unittest.mock import MagicMock, patch

from app import summarization


def _fake_client(response_text):
    """Für generate_author_bio - antwortet mit reinem Text, kein Tool-Use."""
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text=response_text)]
    return client


def _fake_tool_client(tool_input):
    """Für generate_summary/generate_bilingual_summary - simuliert eine
    Tool-Use-Antwort (structured output), das eigentliche Format, in dem
    die Anthropic-API das Ergebnis serverseitig validiert/liefert, statt
    freitextigem JSON, das das Modell selbst korrekt escapen müsste."""
    block = MagicMock()
    block.type = "tool_use"
    block.input = tool_input
    client = MagicMock()
    client.messages.create.return_value.content = [block]
    return client


def test_generate_summary_returns_tool_result():
    client = _fake_tool_client({"summary": "Eine Zusammenfassung.", "key_terms": ["BetaCodex", "Dezentralisierung"]})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_summary("Ein langer Quelltext.")

    assert result == {
        "summary": "Eine Zusammenfassung.",
        "key_terms": ["BetaCodex", "Dezentralisierung"],
    }


def test_generate_summary_handles_quotes_in_summary_text():
    # Regressionstest: früher wurde die Antwort als freitextiges JSON
    # geparst - enthielt die Zusammenfassung selbst Anführungszeichen (z.B.
    # ein zitierter Titel), konnte das vom Modell erzeugte JSON ungültig
    # sein und die Zusammenfassung blieb lautlos leer. Mit Tool-Use kommt
    # das Ergebnis bereits als strukturiertes Objekt an, das Problem kann
    # strukturell nicht mehr auftreten.
    summary_with_quotes = 'Der Podcast „Talking About Organizations" behandelt "Dynamic Administration".'
    client = _fake_tool_client({"summary": summary_with_quotes, "key_terms": ["Dynamic Administration"]})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_summary("Quelltext mit Zitaten.")

    assert result["summary"] == summary_with_quotes


def test_generate_summary_returns_empty_when_no_tool_use_block():
    block = MagicMock()
    block.type = "text"
    client = MagicMock()
    client.messages.create.return_value.content = [block]
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
    client = _fake_tool_client({"summary": "Summary.", "key_terms": ["Term"]})
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.generate_summary("Source text.", lang="en")

    assert client.messages.create.call_args.kwargs["system"] == summarization.SYSTEM_PROMPTS["en"]


def test_generate_summary_uses_tool_choice_to_force_structured_output():
    client = _fake_tool_client({"summary": "Text.", "key_terms": ["Begriff"]})
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.generate_summary("Quelltext.")

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {"type": "tool", "name": "provide_summary"}
    assert kwargs["tools"][0]["name"] == "provide_summary"


def test_generate_summary_filters_blank_key_terms():
    client = _fake_tool_client({"summary": "Text.", "key_terms": ["Gut", "", "  "]})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_summary("Quelltext.")

    assert result["key_terms"] == ["Gut"]


def test_generate_bilingual_summary_returns_tool_result():
    client = _fake_tool_client(
        {
            "summary_de": "Deutsche Zusammenfassung.",
            "summary_en": "English summary.",
            "key_terms_de": ["Begriff"],
            "key_terms_en": ["Term"],
        }
    )
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_bilingual_summary("Ein langer Quelltext.")

    assert result == {
        "de": {"summary": "Deutsche Zusammenfassung.", "key_terms": ["Begriff"]},
        "en": {"summary": "English summary.", "key_terms": ["Term"]},
    }


def test_generate_bilingual_summary_handles_quotes_in_summary_text():
    summary_with_quotes = 'Bezieht sich auf "Dynamic Administration" von Mary Parker Follett.'
    client = _fake_tool_client(
        {
            "summary_de": summary_with_quotes,
            "summary_en": summary_with_quotes,
            "key_terms_de": ["Dynamic Administration"],
            "key_terms_en": ["Dynamic Administration"],
        }
    )
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_bilingual_summary("Quelltext mit Zitaten.")

    assert result["de"]["summary"] == summary_with_quotes
    assert result["en"]["summary"] == summary_with_quotes


def test_generate_bilingual_summary_returns_empty_when_no_tool_use_block():
    block = MagicMock()
    block.type = "text"
    client = MagicMock()
    client.messages.create.return_value.content = [block]
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_bilingual_summary("Quelltext.")

    assert result == {"de": {"summary": "", "key_terms": []}, "en": {"summary": "", "key_terms": []}}


def test_generate_bilingual_summary_returns_empty_on_api_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_bilingual_summary("Quelltext.")

    assert result == {"de": {"summary": "", "key_terms": []}, "en": {"summary": "", "key_terms": []}}


def test_generate_bilingual_summary_returns_empty_for_blank_text():
    result = summarization.generate_bilingual_summary("   ")
    assert result == {"de": {"summary": "", "key_terms": []}, "en": {"summary": "", "key_terms": []}}


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
