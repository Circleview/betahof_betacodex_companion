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


def test_generate_bilingual_summary_includes_known_terms_in_prompt():
    # Nutzerwunsch (2026-09-22): bereits etablierte Schlagworte der Sammlung
    # sollen in die Generierung einfließen, damit das Modell einen
    # passenden vorhandenen Begriff bevorzugt statt eine neue Formulierung
    # fürs selbe Thema zu erfinden.
    client = _fake_tool_client(
        {"summary_de": "d", "summary_en": "e", "key_terms_de": ["x"], "key_terms_en": ["y"]}
    )
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.generate_bilingual_summary(
            "Quelltext.", known_terms_de=["Selbstorganisation"], known_terms_en=["Self-organization"]
        )

    system_prompt = client.messages.create.call_args.kwargs["system"]
    assert "Selbstorganisation" in system_prompt
    assert "Self-organization" in system_prompt


def test_generate_bilingual_summary_omits_known_terms_instruction_when_none_given():
    client = _fake_tool_client(
        {"summary_de": "d", "summary_en": "e", "key_terms_de": ["x"], "key_terms_en": ["y"]}
    )
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.generate_bilingual_summary("Quelltext.")

    system_prompt = client.messages.create.call_args.kwargs["system"]
    assert "vorhandene Schlagworte" not in system_prompt


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


def _fake_tool_block(tool_input):
    block = MagicMock()
    block.type = "tool_use"
    block.input = tool_input
    return block


def test_generate_bilingual_summary_retries_once_when_one_language_is_empty():
    # Regressionstest: beim Import einer per KI-OCR erkannten PDF lieferte
    # ein einzelner Aufruf eine valide Tool-Antwort mit gefüllter englischer,
    # aber leerer deutscher Zusammenfassung - obwohl beide Felder im
    # Tool-Schema als Pflichtfelder deklariert sind. Ein erneuter Aufruf mit
    # demselben Text lieferte sofort eine vollständige Antwort.
    incomplete = MagicMock()
    incomplete.content = [
        _fake_tool_block(
            {
                "summary_de": "",
                "summary_en": "English summary.",
                "key_terms_de": [],
                "key_terms_en": ["Term"],
            }
        )
    ]
    complete = MagicMock()
    complete.content = [
        _fake_tool_block(
            {
                "summary_de": "Deutsche Zusammenfassung.",
                "summary_en": "English summary.",
                "key_terms_de": ["Begriff"],
                "key_terms_en": ["Term"],
            }
        )
    ]
    client = MagicMock()
    client.messages.create.side_effect = [incomplete, complete]
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_bilingual_summary("Ein langer Quelltext.")

    assert client.messages.create.call_count == 2
    assert result == {
        "de": {"summary": "Deutsche Zusammenfassung.", "key_terms": ["Begriff"]},
        "en": {"summary": "English summary.", "key_terms": ["Term"]},
    }


def test_generate_bilingual_summary_does_not_retry_when_already_complete():
    client = _fake_tool_client(
        {
            "summary_de": "Deutsche Zusammenfassung.",
            "summary_en": "English summary.",
            "key_terms_de": ["Begriff"],
            "key_terms_en": ["Term"],
        }
    )
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.generate_bilingual_summary("Ein langer Quelltext.")

    assert client.messages.create.call_count == 1


def test_generate_bilingual_summary_keeps_retry_result_even_if_still_incomplete():
    still_incomplete = MagicMock()
    still_incomplete.content = [
        _fake_tool_block(
            {"summary_de": "", "summary_en": "English summary.", "key_terms_de": [], "key_terms_en": ["Term"]}
        )
    ]
    client = MagicMock()
    client.messages.create.side_effect = [still_incomplete, still_incomplete]
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.generate_bilingual_summary("Ein langer Quelltext.")

    assert client.messages.create.call_count == 2
    assert result["en"]["summary"] == "English summary."
    assert result["de"]["summary"] == ""


def test_extract_key_terms_returns_tool_result():
    client = _fake_tool_client({"key_terms": ["BetaCodex", "Dezentralisierung"]})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.extract_key_terms("Eine von Hand geschriebene Zusammenfassung.")

    assert result == ["BetaCodex", "Dezentralisierung"]


def test_extract_key_terms_includes_known_terms_in_prompt():
    client = _fake_tool_client({"key_terms": ["Selbstorganisation"]})
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.extract_key_terms("Text.", known_terms=["Selbstorganisation", "Agilität"])

    system_prompt = client.messages.create.call_args.kwargs["system"]
    assert "Selbstorganisation" in system_prompt
    assert "Agilität" in system_prompt


def test_extract_key_terms_returns_empty_when_no_tool_use_block():
    block = MagicMock()
    block.type = "text"
    client = MagicMock()
    client.messages.create.return_value.content = [block]
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.extract_key_terms("Text.")

    assert result == []


def test_extract_key_terms_returns_empty_on_api_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.extract_key_terms("Text.")

    assert result == []


def test_extract_key_terms_returns_empty_for_blank_text():
    result = summarization.extract_key_terms("   ")
    assert result == []


def test_extract_key_terms_uses_english_prompt_when_requested():
    client = _fake_tool_client({"key_terms": ["Term"]})
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.extract_key_terms("Summary text.", lang="en")

    assert client.messages.create.call_args.kwargs["system"] == summarization.KEY_TERMS_SYSTEM_PROMPTS["en"]


def test_extract_key_terms_filters_blank_terms():
    client = _fake_tool_client({"key_terms": ["Gut", "", "  "]})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.extract_key_terms("Text.")

    assert result == ["Gut"]


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


def test_translate_summary_returns_tool_result():
    client = _fake_tool_client({"translation": "Translated summary."})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.translate_summary("Eine deutsche Zusammenfassung.", target_lang="en")

    assert result == "Translated summary."


def test_translate_summary_returns_empty_when_no_tool_use_block():
    block = MagicMock()
    block.type = "text"
    client = MagicMock()
    client.messages.create.return_value.content = [block]
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.translate_summary("Text.", target_lang="en")

    assert result == ""


def test_translate_summary_returns_empty_on_api_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.translate_summary("Text.", target_lang="en")

    assert result == ""


def test_translate_summary_returns_empty_for_blank_text():
    result = summarization.translate_summary("   ", target_lang="en")
    assert result == ""


def test_translate_summary_uses_target_language_prompt():
    client = _fake_tool_client({"translation": "Übersetzung."})
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.translate_summary("Summary text.", target_lang="de")

    assert client.messages.create.call_args.kwargs["system"] == summarization.TRANSLATE_SYSTEM_PROMPTS["de"]


def test_translate_summary_defaults_to_german_for_unknown_target_lang():
    client = _fake_tool_client({"translation": "Übersetzung."})
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.translate_summary("Text.", target_lang="fr")

    assert client.messages.create.call_args.kwargs["system"] == summarization.TRANSLATE_SYSTEM_PROMPTS["de"]


def _fake_merge_groups_client(groups):
    block = MagicMock()
    block.type = "tool_use"
    block.input = {"groups": groups}
    client = MagicMock()
    client.messages.create.return_value.content = [block]
    return client


def test_find_similar_term_groups_returns_groups():
    client = _fake_merge_groups_client(
        [{"canonical": "Selbstorganisation", "variants": ["Selbstorganisierung"]}]
    )
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.find_similar_term_groups(
            ["Selbstorganisation", "Selbstorganisierung", "Agilität"], "de"
        )

    assert result == [{"canonical": "Selbstorganisation", "variants": ["Selbstorganisierung"]}]


def test_find_similar_term_groups_drops_hallucinated_canonical():
    # Der Prompt weist das Modell an, "canonical" unverändert aus der
    # Eingabe zu übernehmen - hält es sich nicht daran (neu formulierter
    # Begriff, der gar nicht in der Liste stand), wird die Gruppe verworfen,
    # statt einen Begriff einzuführen, der in keiner Quelle je vorkam.
    client = _fake_merge_groups_client(
        [{"canonical": "Erfundener Begriff", "variants": ["Agilität"]}]
    )
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.find_similar_term_groups(["Agilität", "Selbstorganisation"], "de")

    assert result == []


def test_find_similar_term_groups_drops_hallucinated_variants_and_empty_groups():
    client = _fake_merge_groups_client(
        [{"canonical": "Agilität", "variants": ["Nicht in der Liste"]}]
    )
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.find_similar_term_groups(["Agilität", "Selbstorganisation"], "de")

    assert result == []


def test_find_similar_term_groups_returns_empty_for_fewer_than_two_terms():
    client = MagicMock()
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.find_similar_term_groups(["Nur einer"], "de")

    assert result == []
    client.messages.create.assert_not_called()


def test_find_similar_term_groups_returns_empty_on_api_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.find_similar_term_groups(["A", "B"], "de")

    assert result == []


def test_find_similar_term_groups_uses_sonnet_model():
    client = _fake_merge_groups_client([])
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.find_similar_term_groups(["A", "B"], "de")

    assert client.messages.create.call_args.kwargs["model"] == summarization.MERGE_SUGGESTIONS_MODEL


def test_bilingual_summary_ignores_key_terms_returned_as_string():
    """Regression: ein String statt Liste wurde Buchstabe für Buchstabe zu Schlagworten."""
    from unittest.mock import patch
    from app import summarization

    data = {"summary_de": "D", "summary_en": "E", "key_terms_de": ["Theorie X"], "key_terms_en": "OpenSpace Beta, Beta Codex"}
    with patch.object(summarization, "_call_tool", return_value=data):
        result = summarization._call_bilingual_summary_tool("Text")
    assert result["en"]["key_terms"] == []
    assert result["de"]["key_terms"] == ["Theorie X"]


# --- detect_source_language (Idee 134c868a) ---


def test_detect_source_language_german_text_returns_de_and_english_title():
    client = _fake_tool_client({"text_lang": "de", "title_en": "Organisations Without Hierarchy"})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.detect_source_language("Organisationen ohne Hierarchie", "Dies ist ein deutscher Text.")

    assert result == {"text_lang": "de", "title_en": "Organisations Without Hierarchy"}


def test_detect_source_language_english_text_has_no_title_even_if_model_returns_one():
    client = _fake_tool_client({"text_lang": "en", "title_en": "Should be dropped"})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.detect_source_language("Dynamic Administration", "This is an English text.")

    assert result == {"text_lang": "en", "title_en": None}


def test_detect_source_language_french_text_returns_fr_and_english_title():
    client = _fake_tool_client({"text_lang": "fr", "title_en": "Reinventing Organizations"})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.detect_source_language("Reinventer les organisations", "Ceci est un texte français.")

    assert result == {"text_lang": "fr", "title_en": "Reinventing Organizations"}


def test_detect_source_language_blank_text_makes_no_api_call():
    client = _fake_tool_client({"text_lang": "de", "title_en": "X"})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.detect_source_language("Titel", "   ")

    assert result == {"text_lang": None, "title_en": None}
    client.messages.create.assert_not_called()


def test_detect_source_language_returns_none_on_api_error():
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("API down")
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.detect_source_language("Titel", "Text.")

    assert result == {"text_lang": None, "title_en": None}


def test_detect_source_language_returns_none_when_no_tool_use_block():
    client = MagicMock()
    client.messages.create.return_value.content = []
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.detect_source_language("Titel", "Text.")

    assert result == {"text_lang": None, "title_en": None}


def test_detect_source_language_rejects_invalid_language_code():
    # K4: der Code landet in einer URL (translate.google.com ... sl=) - nur 2-3 Kleinbuchstaben.
    for bad in ("de&u=https://evil.example", "german", "d", "de\n", ""):
        client = _fake_tool_client({"text_lang": bad, "title_en": "X"})
        with patch.object(summarization, "_get_client", return_value=client):
            result = summarization.detect_source_language("Titel", "Text.")
        assert result == {"text_lang": None, "title_en": None}, bad


def test_detect_source_language_truncates_title_to_300_chars_and_removes_line_breaks():
    client = _fake_tool_client({"text_lang": "de", "title_en": "A\nB " + "x" * 400})
    with patch.object(summarization, "_get_client", return_value=client):
        result = summarization.detect_source_language("Titel", "Text.")

    assert len(result["title_en"]) == 300
    assert "\n" not in result["title_en"]
    assert result["title_en"].startswith("A B x")


def test_detect_source_language_sends_title_and_only_first_3000_chars_and_treats_text_as_data():
    client = _fake_tool_client({"text_lang": "de", "title_en": "T"})
    with patch.object(summarization, "_get_client", return_value=client):
        summarization.detect_source_language("Mein Titel", "a" * 3000 + "ENDMARKER")

    kwargs = client.messages.create.call_args.kwargs
    content = kwargs["messages"][0]["content"]
    assert "Mein Titel" in content
    assert "ENDMARKER" not in content
    assert "instruction" in kwargs["system"].lower()  # Quelltext ist Daten, keine Anweisung
