from app import source_suggestions


def _patch_files(tmp_path, monkeypatch):
    monkeypatch.setattr(source_suggestions, "SOURCE_SUGGESTIONS_FILE", tmp_path / "source_suggestions.json")
    monkeypatch.setattr(
        source_suggestions, "SOURCE_SUGGESTION_WEIGHTS_FILE", tmp_path / "source_suggestion_weights.json"
    )


def _candidate(url="https://beispiel.org/artikel", title="Artikel", reason="Passt thematisch.", author=None):
    return {
        "url": url,
        "title": title,
        "reason": reason,
        "discovered_via": "author" if author else "topic",
        "author_hint": author,
    }


def test_add_suggestion_defaults_to_pending(tmp_path, monkeypatch):
    _patch_files(tmp_path, monkeypatch)

    suggestion_id = source_suggestions.add_suggestion(_candidate(), "2026-01-01T00:00:00+00:00")

    suggestion = source_suggestions.get_suggestion(suggestion_id)
    assert suggestion["status"] == "pending"
    assert suggestion["url"] == "https://beispiel.org/artikel"
    assert suggestion["discovered_at"] == "2026-01-01T00:00:00+00:00"


def test_list_suggestions_filters_by_status(tmp_path, monkeypatch):
    _patch_files(tmp_path, monkeypatch)
    pending_id = source_suggestions.add_suggestion(_candidate(url="https://a.org"), "2026-01-01T00:00:00+00:00")
    rejected_id = source_suggestions.add_suggestion(_candidate(url="https://b.org"), "2026-01-01T00:00:00+00:00")
    source_suggestions.set_status(rejected_id, "rejected")

    pending = source_suggestions.list_suggestions(status="pending")
    all_suggestions = source_suggestions.list_suggestions(status=None)

    assert list(pending.keys()) == [pending_id]
    assert set(all_suggestions.keys()) == {pending_id, rejected_id}


def test_set_status_returns_none_for_unknown_id(tmp_path, monkeypatch):
    _patch_files(tmp_path, monkeypatch)
    assert source_suggestions.set_status("unknown", "accepted") is None


def test_known_urls_returns_every_stored_url_regardless_of_status(tmp_path, monkeypatch):
    _patch_files(tmp_path, monkeypatch)
    source_suggestions.add_suggestion(_candidate(url="https://a.org"), "2026-01-01T00:00:00+00:00")
    rejected_id = source_suggestions.add_suggestion(_candidate(url="https://b.org"), "2026-01-01T00:00:00+00:00")
    source_suggestions.set_status(rejected_id, "rejected")

    assert source_suggestions.known_urls() == {"https://a.org", "https://b.org"}


def test_adjust_weight_accumulates_per_author_and_domain(tmp_path, monkeypatch):
    _patch_files(tmp_path, monkeypatch)

    source_suggestions.adjust_weight(author_hint="Niels Pflaeging", url="https://beispiel.org/a", delta=1)
    source_suggestions.adjust_weight(author_hint="Niels Pflaeging", url="https://beispiel.org/b", delta=1)
    source_suggestions.adjust_weight(author_hint=None, url="https://beispiel.org/c", delta=-1)

    weights = source_suggestions._load_weights()
    assert weights["authors"]["Niels Pflaeging"] == 2
    assert weights["domains"]["beispiel.org"] == 1


def test_blocked_domains_only_below_threshold(tmp_path, monkeypatch):
    _patch_files(tmp_path, monkeypatch)
    for _ in range(3):
        source_suggestions.adjust_weight(author_hint=None, url="https://schlecht.org/x", delta=-1)
    source_suggestions.adjust_weight(author_hint=None, url="https://ok.org/x", delta=-1)

    blocked = source_suggestions.blocked_domains()

    assert "schlecht.org" in blocked
    assert "ok.org" not in blocked


def test_adjust_weight_can_be_reversed_by_undo(tmp_path, monkeypatch):
    """Undo eines Accept/Reject dreht die Gewichtung symmetrisch zurück
    (siehe app/main.py _revert_source_suggestion_changes)."""
    _patch_files(tmp_path, monkeypatch)

    source_suggestions.adjust_weight(author_hint="Autor X", url="https://beispiel.org/a", delta=1)
    source_suggestions.adjust_weight(author_hint="Autor X", url="https://beispiel.org/a", delta=-1)

    weights = source_suggestions._load_weights()
    assert weights["authors"]["Autor X"] == 0
    assert weights["domains"]["beispiel.org"] == 0


def test_pick_next_authors_picks_randomly_not_alphabetically(tmp_path, monkeypatch):
    """Nutzerfeedback (2026-08-23): ein Rundenlauf fragte immer zuerst
    dieselben, alphabetisch frühen Autor:innen ab - bei Autor:innen mit
    vielen Veröffentlichungen (z.B. Alfie Kohn) konnte eine einzelne Anfrage
    die gesamte Warteschlange füllen, ohne die Breite zu verbessern.
    pick_next_authors muss also echt zufällig auswählen (hier über
    random.sample geprüft) statt deterministisch von vorne durchzugehen."""
    _patch_files(tmp_path, monkeypatch)
    authors = ["A", "B", "C"]
    captured = {}

    def fake_sample(population, k):
        captured["population"] = list(population)
        captured["k"] = k
        return ["C", "A"]

    monkeypatch.setattr(source_suggestions.random, "sample", fake_sample)

    picked = source_suggestions.pick_next_authors(authors, 2)

    assert picked == ["C", "A"]
    assert captured == {"population": ["A", "B", "C"], "k": 2}


def test_pick_next_authors_returns_at_most_the_available_count(tmp_path, monkeypatch):
    _patch_files(tmp_path, monkeypatch)
    picked = source_suggestions.pick_next_authors(["A"], 5)
    assert picked == ["A"]


def test_pick_next_authors_skips_blocked_authors(tmp_path, monkeypatch):
    _patch_files(tmp_path, monkeypatch)
    for _ in range(3):
        source_suggestions.adjust_weight(author_hint="Gesperrt", url="https://x.org", delta=-1)

    picked = source_suggestions.pick_next_authors(["Gesperrt", "Frei"], 2)

    assert picked == ["Frei"]


def test_pick_next_authors_returns_empty_list_without_known_authors(tmp_path, monkeypatch):
    _patch_files(tmp_path, monkeypatch)
    assert source_suggestions.pick_next_authors([], 2) == []


def test_domain_of_strips_www_prefix():
    assert source_suggestions.domain_of("https://www.beispiel.org/artikel") == "beispiel.org"
    assert source_suggestions.domain_of("https://beispiel.org/artikel") == "beispiel.org"
