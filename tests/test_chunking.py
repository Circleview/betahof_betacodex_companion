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


# --- Kapitelweises Chunking (Idee 8d1b69dd) ---------------------------------

def _old_chunk_text(text, chunk_size=900, overlap=130):
    """Eingefrorene Kopie des Algorithmus vor der Kapitel-Erweiterung."""
    from app.chunking import _snap_to_sentence_boundary
    tokens = _encoding.encode(text)
    if not tokens:
        return []
    chunks, start = [], 0
    while start < len(tokens):
        target_end = start + chunk_size
        if target_end >= len(tokens):
            end = len(tokens)
        else:
            end = _snap_to_sentence_boundary(tokens, start, target_end) or target_end
        chunks.append(_encoding.decode(tokens[start:end]))
        if end >= len(tokens):
            break
        start = end - overlap
    return chunks


def _words(prefix, n):
    return " ".join(f"{prefix}{i}" for i in range(n))


def _ntok(s):
    return len(_encoding.encode(s))


def test_without_headings_identical_to_old_algorithm():
    for n in (10, 900, 1500, 3000):
        text = _words("wort", n)
        assert chunk_text(text) == _old_chunk_text(text)
    sentences = " ".join(f"Dies ist Satz Nummer {i}." for i in range(600))
    assert chunk_text(sentences, 300, 50) == _old_chunk_text(sentences, 300, 50)
    # '#' ohne gültige Überschrift ändert nichts
    odd = "#Tag und #### vier und # \n" + _words("x", 2000)
    assert chunk_text(odd) == _old_chunk_text(odd)


def test_sections_are_not_mixed_across_chunks():
    secs = [f"# Kapitel {i}\n\n{_words(f'k{i}w', 150)}" for i in range(4)]
    chunks = chunk_text("\n\n".join(secs))
    for c in chunks:
        # kein Chunk enthält Teile mehrerer Kapitel
        assert sum(f"# Kapitel {i}" in c for i in range(4)) <= 1
        # und jeder beginnt an einer Überschrift
        assert c.startswith("# Kapitel")
    assert len(chunks) == 4


def test_small_sections_are_merged_up_to_limit():
    secs = [f"## Abschnitt {i}\n\n{_words(f'a{i}w', 30)}" for i in range(3)]
    text = "\n\n".join(secs)
    chunks = chunk_text(text)
    assert chunks == [text]  # wörtlicher Ausschnitt, alles in einem Chunk


def test_merged_chunks_respect_limit():
    secs = [f"# K{i}\n\n{_words(f'k{i}w', 60)}" for i in range(10)]
    chunks = chunk_text("\n\n".join(secs))
    assert all(_ntok(c) <= 900 for c in chunks)
    assert len(chunks) > 3


def test_long_section_split_with_heading_prefix():
    text = "# Langes Kapitel\n\n" + _words("lang", 3000)
    chunks = chunk_text(text)
    assert len(chunks) > 2
    assert chunks[0].startswith("# Langes Kapitel")
    for c in chunks:
        assert c.startswith("# Langes Kapitel")
        assert _ntok(c) <= 900


def test_overlap_never_crosses_heading():
    text = "# Eins\n\n" + _words("eins", 2000) + "\n\n# Zwei\n\n" + _words("zwei", 2000)
    chunks = chunk_text(text)
    for c in chunks:
        assert not ("eins" in c and "zwei" in c)


def test_huge_heading_terminates_and_prefix_is_capped():
    text = "# " + _words("titel", 2000) + "\n\n" + _words("body", 3000)
    chunks = chunk_text(text)
    assert len(chunks) > 2
    for c in chunks[1:]:
        assert _ntok(c) <= 900
        assert c.startswith("# titel0")


def test_chunk_size_not_above_overlap_raises():
    import pytest
    for text in ("# A\n\ntext", "ohne Überschrift"):
        with pytest.raises(ValueError):
            chunk_text(text, chunk_size=100, overlap=100)
        with pytest.raises(ValueError):
            chunk_text(text, chunk_size=50, overlap=100)


def test_text_before_first_heading_is_own_section():
    pre = _words("vor", 350)
    text = pre + "\n\n# Kapitel\n\n" + _words("kap", 350)
    chunks = chunk_text(text)
    assert chunks[0] == pre
    assert chunks[1].startswith("# Kapitel")


def test_heading_after_heading_gives_no_empty_chunk():
    text = "# A\n# B\n## C\n\n" + _words("x", 50)
    chunks = chunk_text(text)
    assert all(c.strip() for c in chunks)
    assert chunks == [text]


def test_no_boundary_in_code_block_or_invalid_heading():
    text = (
        "# Echt\n\nText\n```\n# kein Kapitel im Code\n```\n"
        "#Tag\n#### vier\n# \nEnde"
    )
    assert chunk_text(text) == [text]
    big = "# Echt\n\n" + _words("a", 700) + "\n```\n# im Code\n" + _words("b", 700) + "\n```\n"
    for c in chunk_text(big):
        assert c.startswith("# Echt")  # kein Chunk beginnt mit der Code-Zeile


def test_heading_only_text_returns_chunk():
    assert chunk_text("# Nur Titel") == ["# Nur Titel"]
    assert chunk_text("   \n  ") == _old_chunk_text("   \n  ")


def test_truncated_heading_prefix_has_no_broken_characters():
    for heading in ("🎉" * 80, "✨" * 80, "🇩🇪" * 80):
        text = "# " + heading + "\n\n" + _words("body", 3000)
        chunks = chunk_text(text)
        assert len(chunks) > 2
        assert all("\ufffd" not in c for c in chunks)


# --- Bild-Zuordnung (Idee ff895248) -------------------------------------------


def _img(anchor, name="a"):
    return {"kind": "url", "url": f"https://img.example.org/{name}.jpg", "alt": "Alt", "anchor": anchor}


def test_assign_images_puts_image_into_chunk_with_its_anchor():
    from app.chunking import assign_images

    chunks = ["Erster Chunk über Budgets und Steuerung.", "Zweiter Chunk über die Selbstorganisation von Teams."]

    result = assign_images(chunks, [_img("Zweiter Chunk über die Selbstorganisation")])

    assert result[0] == []
    assert result[1] == [{"kind": "url", "url": "https://img.example.org/a.jpg", "alt": "Alt", "page": None}]


def test_assign_images_matches_despite_markdown_and_whitespace_differences():
    from app.chunking import assign_images

    chunks = ["Einleitung.", "Statt **Kontrolle** und\nBürokratie: Ansätze für Teams."]

    result = assign_images(chunks, [_img("Statt Kontrolle und Bürokratie: Ansätze für Teams.")])

    assert len(result[1]) == 1


def test_assign_images_discards_image_with_unknown_anchor():
    from app.chunking import assign_images

    assert assign_images(["Nur dieser Text."], [_img("Ein ganz anderer Satz, der nirgends steht.")]) == [[]]


def test_assign_images_takes_first_chunk_that_contains_anchor():
    from app.chunking import assign_images

    chunks = ["Gemeinsamer Satz im Überlapp.", "Gemeinsamer Satz im Überlapp. Und mehr."]

    result = assign_images(chunks, [_img("Gemeinsamer Satz im Überlapp.")])

    assert [len(r) for r in result] == [1, 0]


def test_assign_images_allows_at_most_three_per_chunk():
    from app.chunking import assign_images

    images = [_img("Gemeinsamer Anker Satz", name=f"i{i}") for i in range(5)]

    result = assign_images(["Gemeinsamer Anker Satz steht hier."], images)

    assert len(result[0]) == 3


def test_assign_images_keeps_file_images_with_page_and_drops_anchor():
    from app.chunking import assign_images

    image = {"kind": "file", "file": "a" * 32 + ".webp", "page": 7, "anchor": "Seitentext der siebten Seite"}

    result = assign_images(["Seitentext der siebten Seite und mehr."], [image])

    assert result == [[{"kind": "file", "file": "a" * 32 + ".webp", "alt": "", "page": 7}]]
