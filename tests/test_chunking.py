from app.chunking import _encoding, chunk_text, split_sentences


def test_empty_text_returns_no_chunks():
    assert chunk_text("") == []


def test_short_text_returns_single_chunk():
    text = "Ein kurzer Satz über den BetaCodex."
    chunks = chunk_text(text)
    assert chunks == [text]


def test_long_text_is_split_into_multiple_chunks():
    text = " ".join(f"wort{i}" for i in range(3000))
    chunks = chunk_text(text, chunk_size=900, overlap=130)
    assert len(chunks) > 1


def test_non_final_chunks_match_requested_token_size():
    text = " ".join(f"wort{i}" for i in range(3000))
    chunks = chunk_text(text, chunk_size=900, overlap=130)
    for chunk in chunks[:-1]:
        assert len(_encoding.encode(chunk)) == 900


def test_consecutive_chunks_overlap():
    text = " ".join(f"wort{i}" for i in range(3000))
    chunks = chunk_text(text, chunk_size=900, overlap=130)
    first_word_of_second_chunk = chunks[1].split()[0]
    assert first_word_of_second_chunk in chunks[0]


def test_chunk_boundaries_snap_to_sentence_ends_when_punctuation_present():
    # Viele kurze Sätze, damit garantiert eine Satzgrenze innerhalb der
    # Toleranz um jede Ziel-Chunk-Grenze liegt.
    text = " ".join(f"Dies ist Satz Nummer {i}." for i in range(600))
    chunks = chunk_text(text, chunk_size=900, overlap=130)
    assert len(chunks) > 1
    for chunk in chunks[:-1]:
        assert chunk.rstrip().endswith(".")


def test_split_sentences_splits_on_punctuation():
    text = "Erster Satz. Zweiter Satz! Dritter Satz?"
    assert split_sentences(text) == ["Erster Satz.", "Zweiter Satz!", "Dritter Satz?"]


def test_split_sentences_returns_single_sentence_unchanged():
    assert split_sentences("Nur ein Satz ohne Satzzeichen") == ["Nur ein Satz ohne Satzzeichen"]


def test_split_sentences_returns_empty_list_for_empty_text():
    assert split_sentences("") == []
    assert split_sentences("   ") == []
