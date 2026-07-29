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


def test_answer_question_without_author_bios_omits_section():
    client = _fake_client("Antwort")
    with patch.object(llm, "_get_client", return_value=client):
        llm.answer_question("Frage?", [{"title": "T", "author": "A", "date": "D", "text": "Text"}])

    user_content = client.messages.stream.call_args.kwargs["messages"][0]["content"]
    assert "Autor:innen-Informationen" not in user_content


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
