from scripts.export_sources_md import format_author, render, sort_key


def _src(authors, title="T", **kw):
    return {"title": title, "authors": authors, "date": None, "url": None, "summary": "",
            "summary_ai_generated": True, "restricted": False, **kw}


def test_sort_by_last_name_with_particles_umlauts_and_orgs():
    sources = [
        _src(["Michael von Kutzschenbach"]),
        _src(["Götz W. Werner"]),
        _src(["Wikipedia"]),
        _src(["Jos de Blok"]),
        _src(["Edgar H. Schein"]),
        _src([]),
        _src(["Niels Pflaeging"], title="B"),
        _src(["Niels Pflaeging"], title="a"),
    ]
    order = [(s["authors"][:1] or [""])[0] + s["title"] for s in sorted(sources, key=sort_key)]
    assert order == [
        "Jos de BlokT", "Michael von KutzschenbachT", "Niels Pflaeginga", "Niels PflaegingB",
        "Edgar H. ScheinT", "Götz W. WernerT", "WikipediaT", "T",
    ]


def test_format_author():
    assert format_author("Jos de Blok") == "Blok, Jos de"
    assert format_author("Wikipedia") == "Wikipedia"


def test_render_marks_ai_vs_manual_and_never_includes_text():
    out = render([
        _src(["Lisa Gill"], title="KI", summary="Auto", text="GEHEIMER VOLLTEXT"),
        _src(["Ralf Hildebrandt"], title="Hand", summary="Zeile 1\nZeile 2",
             summary_ai_generated=False, restricted=True, url="https://x.org"),
    ], "de")
    assert "GEHEIMER VOLLTEXT" not in out
    assert "**Zusammenfassung (KI-generiert):**\n\n> Auto" in out
    assert "**Zusammenfassung (von Hand verfasst):**\n\n> Zeile 1\n> Zeile 2" in out
    assert "Link: <https://x.org> · geschützt" in out
    assert out.index("Gill, Lisa") < out.index("Hildebrandt, Ralf")
