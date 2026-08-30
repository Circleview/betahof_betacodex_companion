from unittest.mock import MagicMock, patch

from app import llm


def _fake_client(response_text):
    client = MagicMock()
    stream_manager = client.messages.stream.return_value
    stream_manager.__enter__.return_value.text_stream = iter([response_text])
    return client


def test_answer_question_uses_german_prompt_by_default():
    client = _fake_client("Antwort")
    with patch.object(llm, "_get_client", return_value=client):
        result = llm.answer_question("Frage?", [{"title": "T", "author": "A", "date": "D", "text": "Text"}])

    assert result == "Antwort"
    assert client.messages.stream.call_args.kwargs["system"] == llm.SYSTEM_PROMPTS["de"]


def test_answer_question_uses_english_prompt_when_requested():
    client = _fake_client("Answer")
    with patch.object(llm, "_get_client", return_value=client):
        result = llm.answer_question(
            "Question?", [{"title": "T", "author": "A", "date": "D", "text": "Text"}], lang="en"
        )

    assert result == "Answer"
    assert client.messages.stream.call_args.kwargs["system"] == llm.SYSTEM_PROMPTS["en"]


def test_answer_question_falls_back_to_german_for_unknown_lang():
    client = _fake_client("Antwort")
    with patch.object(llm, "_get_client", return_value=client):
        llm.answer_question("Frage?", [], lang="fr")

    assert client.messages.stream.call_args.kwargs["system"] == llm.SYSTEM_PROMPTS["de"]


def test_answer_question_appends_author_bios_as_unnumbered_section():
    client = _fake_client("Antwort")
    with patch.object(llm, "_get_client", return_value=client):
        llm.answer_question(
            "Wer ist Peter Pröll?",
            [{"title": "T", "author": "A", "date": "D", "text": "Text"}],
            author_bios=[{"name": "Peter Pröll", "bio": "Berater und Autor."}],
        )

    user_content = client.messages.stream.call_args.kwargs["messages"][0]["content"]
    assert "Autor:innen-Informationen" in user_content
    assert "Peter Pröll: Berater und Autor." in user_content
    # Die normale Chunk-Nummerierung [1] bleibt unberührt von der Vita.
    assert "[1] (Quelle: T, A, D)" in user_content


def test_answer_question_repeats_language_instruction_next_to_the_question():
    """Bug (per Screenshot gemeldet): eine englische Frage bei deutschen
    Quell-Chunks kippte mitten im ersten Satz von Englisch auf Deutsch -
    reproduziert auch mit explizit korrektem lang='en'. Die im System-Prompt
    vergrabene Sprachregel reicht nicht, sie wird deshalb zusätzlich direkt
    neben der Frage wiederholt (Nähe zur Generierung wirkt zuverlässiger)."""
    client = _fake_client("Answer")
    with patch.object(llm, "_get_client", return_value=client):
        llm.answer_question(
            "What is leadership about?",
            [{"title": "T", "author": "A", "date": "D", "text": "Deutscher Text"}],
            lang="en",
        )

    user_content = client.messages.stream.call_args.kwargs["messages"][0]["content"]
    assert user_content.rstrip().endswith(llm._LANGUAGE_REMINDERS["en"])


def test_answer_question_without_author_bios_omits_section():
    client = _fake_client("Antwort")
    with patch.object(llm, "_get_client", return_value=client):
        llm.answer_question("Frage?", [{"title": "T", "author": "A", "date": "D", "text": "Text"}])

    user_content = client.messages.stream.call_args.kwargs["messages"][0]["content"]
    assert "Autor:innen-Informationen" not in user_content


def test_answer_question_includes_history_as_prior_messages():
    """Backlog (2026-08-03): ohne Verlauf beantwortete das Modell jede
    Folgefrage isoliert - frühere Turns werden jetzt als eigene user/
    assistant-Nachrichten VOR der aktuellen Kontext-Frage eingereiht."""
    client = _fake_client("Antwort")
    with patch.object(llm, "_get_client", return_value=client):
        llm.answer_question(
            "Und was ist mit Vertrauen?",
            [{"title": "T", "author": "A", "date": "D", "text": "Text"}],
            history=[
                {"question": "Was ist der BetaCodex?", "answer": "Ein Prinzipien-Set [1]."},
                {"question": "Wer hat ihn entwickelt?", "answer": "Niels Pfläging [1]."},
            ],
        )

    messages = client.messages.stream.call_args.kwargs["messages"]
    assert messages[0] == {"role": "user", "content": "Was ist der BetaCodex?"}
    assert messages[1] == {"role": "assistant", "content": "Ein Prinzipien-Set [1]."}
    assert messages[2] == {"role": "user", "content": "Wer hat ihn entwickelt?"}
    assert messages[3] == {"role": "assistant", "content": "Niels Pfläging [1]."}
    assert messages[4]["role"] == "user"
    assert "Frage: Und was ist mit Vertrauen?" in messages[4]["content"]
    assert len(messages) == 5


def test_answer_question_without_history_has_only_the_current_message():
    client = _fake_client("Antwort")
    with patch.object(llm, "_get_client", return_value=client):
        llm.answer_question("Frage?", [{"title": "T", "author": "A", "date": "D", "text": "Text"}])

    messages = client.messages.stream.call_args.kwargs["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def _fake_create_client(response_text):
    client = MagicMock()
    block = MagicMock(type="text", text=response_text)
    client.messages.create.return_value = MagicMock(content=[block])
    return client


def test_rewrite_followup_query_returns_none_without_history():
    """Nichts umzuformulieren ohne Verlauf - darf dafür erst gar keinen
    LLM-Call auslösen (kein _get_client-Patch nötig, würde sonst crashen)."""
    assert llm.rewrite_followup_query("Frage?", []) is None


def test_rewrite_followup_query_returns_rewritten_text():
    client = _fake_create_client("BetaCodex und Vertrauen")
    history = [{"question": "Was ist der BetaCodex?", "answer": "Ein Prinzipien-Set [1]."}]
    with patch.object(llm, "_get_client", return_value=client):
        result = llm.rewrite_followup_query("Und wie sieht es mit Vertrauen aus?", history)

    assert result == "BetaCodex und Vertrauen"
    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["system"] == llm.REWRITE_SYSTEM_PROMPTS["de"]
    assert kwargs["messages"][0] == {"role": "user", "content": "Was ist der BetaCodex?"}
    assert kwargs["messages"][1] == {"role": "assistant", "content": "Ein Prinzipien-Set [1]."}
    assert "Und wie sieht es mit Vertrauen aus?" in kwargs["messages"][2]["content"]


def test_rewrite_followup_query_uses_english_prompt_when_requested():
    client = _fake_create_client("BetaCodex and trust")
    history = [{"question": "What is the BetaCodex?", "answer": "A set of principles [1]."}]
    with patch.object(llm, "_get_client", return_value=client):
        llm.rewrite_followup_query("And what about trust?", history, lang="en")

    assert client.messages.create.call_args.kwargs["system"] == llm.REWRITE_SYSTEM_PROMPTS["en"]


def test_rewrite_followup_query_returns_none_when_llm_call_fails():
    """Fix (2026-08-20): eine Anthropic-Störung beim Rewrite darf die
    Anfrage nicht blockieren - app/main.py fällt dann auf die einfache
    String-Verkettung zurück."""
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("boom")
    history = [{"question": "Was ist der BetaCodex?", "answer": "Ein Prinzipien-Set [1]."}]
    with patch.object(llm, "_get_client", return_value=client):
        result = llm.rewrite_followup_query("Und wie sieht es mit Vertrauen aus?", history)

    assert result is None


def test_parse_answer_and_quotes_splits_answer_from_quote_block():
    raw = (
        'Ein Flip ist ein Zustandswechsel [1].\n\n'
        '---QUOTES---\n'
        '[1]: "Any irritation can flip the system into the New state."\n'
    )
    answer, quotes = llm.parse_answer_and_quotes(raw)

    assert answer == "Ein Flip ist ein Zustandswechsel [1]."
    assert quotes == {1: ["Any irritation can flip the system into the New state."]}


def test_parse_answer_and_quotes_handles_multiple_quotes():
    raw = (
        'Antwort mit zwei Belegen [1][2].\n\n'
        '---QUOTES---\n'
        '[1]: "Erstes Zitat."\n'
        '[2]: "Zweites Zitat."\n'
    )
    _, quotes = llm.parse_answer_and_quotes(raw)

    assert quotes == {1: ["Erstes Zitat."], 2: ["Zweites Zitat."]}


def test_parse_answer_and_quotes_collects_repeated_citation_number_in_order():
    raw = (
        'Aussage A [1]. Aussage B [1].\n\n'
        '---QUOTES---\n'
        '[1]: "Beleg für Aussage A."\n'
        '[1]: "Beleg für Aussage B."\n'
    )
    _, quotes = llm.parse_answer_and_quotes(raw)

    assert quotes == {1: ["Beleg für Aussage A.", "Beleg für Aussage B."]}


def test_parse_answer_and_quotes_returns_empty_dict_without_marker():
    answer, quotes = llm.parse_answer_and_quotes("Testantwort [1].")

    assert answer == "Testantwort [1]."
    assert quotes == {}


def test_parse_answer_and_quotes_returns_empty_dict_for_empty_block():
    raw = "Text ohne Belege.\n\n---QUOTES---\n"
    answer, quotes = llm.parse_answer_and_quotes(raw)

    assert answer == "Text ohne Belege."
    assert quotes == {}


def test_parse_answer_and_quotes_strips_leading_answer_label_german():
    answer, _ = llm.parse_answer_and_quotes("Antwort: Der BetaCodex ist ein Organisationsmodell.")
    assert answer == "Der BetaCodex ist ein Organisationsmodell."


def test_parse_answer_and_quotes_strips_leading_answer_label_english():
    answer, _ = llm.parse_answer_and_quotes("Answer: BetaCodex is an organizational model.")
    assert answer == "BetaCodex is an organizational model."


def test_parse_answer_and_quotes_strips_bold_leading_answer_label():
    answer, _ = llm.parse_answer_and_quotes("**Antwort:** Der BetaCodex ist ein Organisationsmodell.")
    assert answer == "Der BetaCodex ist ein Organisationsmodell."


def test_parse_answer_and_quotes_strips_answer_label_without_punctuation():
    answer, _ = llm.parse_answer_and_quotes("Antwort Der BetaCodex ist ein Organisationsmodell.")
    assert answer == "Der BetaCodex ist ein Organisationsmodell."


def test_parse_answer_and_quotes_does_not_strip_antworten_plural():
    answer, _ = llm.parse_answer_and_quotes("Antworten auf komplexe Fragen erfordern Kontext.")
    assert answer == "Antworten auf komplexe Fragen erfordern Kontext."


def test_parse_answer_and_quotes_strips_answer_label_before_quote_block():
    raw = (
        'Antwort: Ein Flip ist ein Zustandswechsel [1].\n\n'
        '---QUOTES---\n'
        '[1]: "Any irritation can flip the system into the New state."\n'
    )
    answer, quotes = llm.parse_answer_and_quotes(raw)

    assert answer == "Ein Flip ist ein Zustandswechsel [1]."
    assert quotes == {1: ["Any irritation can flip the system into the New state."]}


# Backlog (2026-08-01): Nutzer möchte, dass ein Quellenverweis [n] IMMER am
# Ende des Satzes steht, auf den er sich bezieht - Sicherheitsnetz in
# parse_answer_and_quotes (_move_leading_citations_to_sentence_end), falls
# sich das Sprachmodell trotz verschärfter Prompt-Anweisung nicht daran hält.
def test_parse_answer_and_quotes_moves_leading_citation_to_sentence_end():
    answer, _ = llm.parse_answer_and_quotes("[1] Teams entscheiden selbst.")
    assert answer == "Teams entscheiden selbst [1]."


def test_parse_answer_and_quotes_leaves_already_correct_placement_untouched():
    answer, _ = llm.parse_answer_and_quotes("Teams entscheiden selbst [1].")
    assert answer == "Teams entscheiden selbst [1]."


def test_parse_answer_and_quotes_fixes_leading_citation_in_second_sentence():
    """Mehrere aufeinanderfolgende Sätze mit jeweils eigenem führendem
    Verweis müssen UNABHÄNGIG voneinander korrigiert werden."""
    answer, _ = llm.parse_answer_and_quotes(
        "[1] Erste Aussage hierzu. [2] Zweite Aussage dazu."
    )
    assert answer == "Erste Aussage hierzu [1]. Zweite Aussage dazu [2]."


def test_parse_answer_and_quotes_moves_leading_citation_group_of_two():
    answer, _ = llm.parse_answer_and_quotes("[1][2] Teams entscheiden selbst.")
    assert answer == "Teams entscheiden selbst [1] [2]."


def test_parse_answer_and_quotes_moves_leading_citation_at_paragraph_start():
    answer, _ = llm.parse_answer_and_quotes(
        "Erster Absatz endet hier.\n\n[2] Zweiter Absatz beginnt so."
    )
    assert answer == "Erster Absatz endet hier.\n\nZweiter Absatz beginnt so [2]."


def test_parse_answer_and_quotes_preserves_citation_order_for_same_number():
    """Verschieben darf die Reihenfolge MEHRFACHER Vorkommen DERSELBEN
    Quellenzahl nicht verändern, da app/main.py Zitate genau in dieser
    Reihenfolge aus quotes_by_citation entnimmt."""
    raw = (
        '[1] Erste Aussage. Zweite Aussage bezieht sich auch [1] darauf.\n\n'
        '---QUOTES---\n'
        '[1]: "Beleg für Erste Aussage."\n'
        '[1]: "Beleg für Zweite Aussage."\n'
    )
    answer, quotes = llm.parse_answer_and_quotes(raw)

    assert answer == "Erste Aussage [1]. Zweite Aussage bezieht sich auch [1] darauf."
    assert quotes == {1: ["Beleg für Erste Aussage.", "Beleg für Zweite Aussage."]}


# --- Kreativ-Modus (2026-08-26) ---


def _fake_creative_client(document_text, search_result_urls=None):
    client = MagicMock()
    stream_manager = client.messages.stream.return_value
    stream_manager.__enter__.return_value.text_stream = iter([document_text])
    search_block = MagicMock(type="web_search_tool_result")
    search_block.content = [MagicMock(url=u) for u in (search_result_urls or [])]
    stream_manager.__enter__.return_value.get_final_message.return_value = MagicMock(
        content=[search_block]
    )
    return client


def test_stream_creative_response_uses_sonnet_for_empty_document():
    client = _fake_creative_client("Erster Entwurf.")
    with patch.object(llm, "_get_client", return_value=client):
        stream = llm.stream_creative_response("Schreibe einen Blogpost.", "", [])
        list(stream)

    assert client.messages.stream.call_args.kwargs["model"] == llm.CREATIVE_FIRST_DRAFT_MODEL
    assert stream.model == llm.CREATIVE_FIRST_DRAFT_MODEL


def test_stream_creative_response_uses_haiku_for_non_empty_document():
    client = _fake_creative_client("Überarbeiteter Text.")
    with patch.object(llm, "_get_client", return_value=client):
        stream = llm.stream_creative_response("Kürze das.", "Bestehender Text.", [])
        list(stream)

    assert client.messages.stream.call_args.kwargs["model"] == llm.MODEL_NAME
    assert stream.model == llm.MODEL_NAME


def test_stream_creative_response_passes_web_search_tool_with_auto_choice():
    client = _fake_creative_client("Text.")
    with patch.object(llm, "_get_client", return_value=client):
        list(llm.stream_creative_response("Anweisung", "", []))

    kwargs = client.messages.stream.call_args.kwargs
    assert kwargs["tools"] == [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": llm.CREATIVE_MAX_SEARCH_USES}
    ]
    assert kwargs["tool_choice"] == {"type": "auto"}


def test_stream_creative_response_exposes_real_web_urls_after_exhausting_stream():
    client = _fake_creative_client("Text.", search_result_urls=["https://a.org/x"])
    with patch.object(llm, "_get_client", return_value=client):
        stream = llm.stream_creative_response("Anweisung", "", [])
        # Vor dem vollständigen Durchlaufen des Generators steht real_web_urls
        # noch nicht fest (siehe CreativeStream-Docstring) - erst danach.
        list(stream)

    assert stream.real_web_urls == {"https://a.org/x"}


def test_stream_creative_response_yields_document_text():
    client = _fake_creative_client("Der fertige Text.")
    with patch.object(llm, "_get_client", return_value=client):
        stream = llm.stream_creative_response("Anweisung", "", [])
        assert "".join(stream) == "Der fertige Text."


def test_stream_creative_response_uses_section_system_prompt_when_section_given():
    # Nutzerwunsch (2026-08-30): abschnittsweises Überarbeiten - ist section
    # gesetzt, muss der engere CREATIVE_SECTION_SYSTEM_PROMPTS-Pfad greifen
    # (nicht der Ganzdokument-Pfad CREATIVE_SYSTEM_PROMPTS), und sowohl das
    # Gesamtdokument als auch der Abschnitt selbst müssen im User-Content
    # landen.
    client = _fake_creative_client("Überarbeiteter Abschnitt.")
    with patch.object(llm, "_get_client", return_value=client):
        list(
            llm.stream_creative_response(
                "Kürze das.",
                "# Eins\n\nAlter Text.\n\n# Zwei\n\nWeiterer Text.",
                [],
                section="# Eins\n\nAlter Text.\n\n",
            )
        )

    kwargs = client.messages.stream.call_args.kwargs
    assert kwargs["system"] == llm.CREATIVE_SECTION_SYSTEM_PROMPTS["de"]
    user_content = kwargs["messages"][0]["content"]
    assert "# Eins\n\nAlter Text.\n\n# Zwei\n\nWeiterer Text." in user_content
    assert "# Eins\n\nAlter Text.\n\n" in user_content


def test_stream_creative_response_uses_whole_document_system_prompt_without_section():
    client = _fake_creative_client("Neuer Text.")
    with patch.object(llm, "_get_client", return_value=client):
        list(llm.stream_creative_response("Kürze das.", "Bestehender Text.", []))

    kwargs = client.messages.stream.call_args.kwargs
    assert kwargs["system"] == llm.CREATIVE_SYSTEM_PROMPTS["de"]


def test_stream_creative_response_uses_haiku_for_section_revision():
    # Ein Abschnitt stammt immer aus einem bereits nicht-leeren Dokument -
    # die bestehende Kosten-Heuristik (leeres Dokument -> Sonnet) darf hier
    # nicht versehentlich greifen.
    client = _fake_creative_client("Text.")
    with patch.object(llm, "_get_client", return_value=client):
        stream = llm.stream_creative_response(
            "Kürze das.", "# Eins\n\nText.", [], section="# Eins\n\nText."
        )
        list(stream)

    assert client.messages.stream.call_args.kwargs["model"] == llm.MODEL_NAME
    assert stream.model == llm.MODEL_NAME


def test_parse_document_and_sources_splits_document_from_source_block():
    raw = 'Der Text.\n\n---SOURCES---\n[Web]: Beispieltitel — https://example.org/a\n'
    document, sources = llm.parse_document_and_sources(raw)

    assert document == "Der Text."
    assert sources == [{"title": "Beispieltitel", "url": "https://example.org/a"}]


def test_parse_document_and_sources_parses_multiple_web_lines():
    raw = (
        "Text.\n\n---SOURCES---\n"
        "[Web]: Erste Quelle — https://a.org/1\n"
        "[Web]: Zweite Quelle — https://b.org/2\n"
    )
    _, sources = llm.parse_document_and_sources(raw)

    assert sources == [
        {"title": "Erste Quelle", "url": "https://a.org/1"},
        {"title": "Zweite Quelle", "url": "https://b.org/2"},
    ]


def test_parse_document_and_sources_returns_empty_list_without_marker():
    document, sources = llm.parse_document_and_sources("Nur Text, kein Quellenblock.")

    assert document == "Nur Text, kein Quellenblock."
    assert sources == []


def test_parse_document_and_sources_ignores_malformed_lines():
    raw = "Text.\n\n---SOURCES---\n[Web]: Ohne URL\nKeine Web-Zeile hier.\n"
    document, sources = llm.parse_document_and_sources(raw)

    assert document == "Text."
    assert sources == []
