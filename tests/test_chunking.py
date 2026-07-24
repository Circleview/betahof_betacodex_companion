from app.chunking import _encoding, chunk_text


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
