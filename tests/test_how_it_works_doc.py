import re

from scripts import how_it_works as hiw


def test_doc_matches_code():
    # Schlägt fehl, wenn Prompts/Modelle/Suchparameter geändert wurden, ohne
    # die Doku zu prüfen: Text in beiden Sprachen nachziehen, dann
    # `python scripts/how_it_works.py --write`.
    for lang, path in hiw.DOCS.items():
        assert hiw.current_block(path.read_text()) == hiw.block(lang), (
            f"{path.name} ist veraltet - Text prüfen, dann: python scripts/how_it_works.py --write"
        )


def test_referenced_files_exist():
    for path in hiw.DOCS.values():
        for ref in re.findall(r"`((?:app|tools|scripts|static|tests|docs)/[\w./-]+)", path.read_text()):
            assert (hiw.ROOT / ref).exists(), f"{path.name} verweist auf fehlende Datei {ref}"
