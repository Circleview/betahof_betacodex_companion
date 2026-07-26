from unittest.mock import MagicMock, patch

from app import llm


def _fake_client(response_text):
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text=response_text)]
    return client


def test_answer_question_uses_german_prompt_by_default():
    client = _fake_client("Antwort")
    with patch.object(llm, "_get_client", return_value=client):
        result = llm.answer_question("Frage?", [{"title": "T", "author": "A", "date": "D", "text": "Text"}])

    assert result == "Antwort"
    assert client.messages.create.call_args.kwargs["system"] == llm.SYSTEM_PROMPTS["de"]


def test_answer_question_uses_english_prompt_when_requested():
    client = _fake_client("Answer")
    with patch.object(llm, "_get_client", return_value=client):
        result = llm.answer_question(
            "Question?", [{"title": "T", "author": "A", "date": "D", "text": "Text"}], lang="en"
        )

    assert result == "Answer"
    assert client.messages.create.call_args.kwargs["system"] == llm.SYSTEM_PROMPTS["en"]


def test_answer_question_falls_back_to_german_for_unknown_lang():
    client = _fake_client("Antwort")
    with patch.object(llm, "_get_client", return_value=client):
        llm.answer_question("Frage?", [], lang="fr")

    assert client.messages.create.call_args.kwargs["system"] == llm.SYSTEM_PROMPTS["de"]


def test_parse_answer_and_quotes_splits_answer_from_quote_block():
    raw = (
        'Ein Flip ist ein Zustandswechsel [1].\n\n'
        '---QUOTES---\n'
        '[1]: "Any irritation can flip the system into the New state."\n'
    )
    answer, quotes = llm.parse_answer_and_quotes(raw)

    assert answer == "Ein Flip ist ein Zustandswechsel [1]."
    assert quotes == {1: "Any irritation can flip the system into the New state."}


def test_parse_answer_and_quotes_handles_multiple_quotes():
    raw = (
        'Antwort mit zwei Belegen [1][2].\n\n'
        '---QUOTES---\n'
        '[1]: "Erstes Zitat."\n'
        '[2]: "Zweites Zitat."\n'
    )
    _, quotes = llm.parse_answer_and_quotes(raw)

    assert quotes == {1: "Erstes Zitat.", 2: "Zweites Zitat."}


def test_parse_answer_and_quotes_returns_empty_dict_without_marker():
    answer, quotes = llm.parse_answer_and_quotes("Testantwort [1].")

    assert answer == "Testantwort [1]."
    assert quotes == {}


def test_parse_answer_and_quotes_returns_empty_dict_for_empty_block():
    raw = "Antwort ohne Belege.\n\n---QUOTES---\n"
    answer, quotes = llm.parse_answer_and_quotes(raw)

    assert answer == "Antwort ohne Belege."
    assert quotes == {}
