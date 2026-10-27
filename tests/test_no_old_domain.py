"""Wächter: die abgeschaltete Domain darf nirgends mehr im Repo stehen."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD = ("chat." + "betacodex.org").encode()


def test_no_old_domain_left():
    files = [ROOT / "README.md"]
    for d in ("app", "scripts", "static", "docs", "tests", ".github"):
        files += [p for p in (ROOT / d).rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    hits = [str(p.relative_to(ROOT)) for p in files if OLD in p.read_bytes() and p.name != Path(__file__).name]
    assert not hits, hits
