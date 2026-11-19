from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 60000  # Idee 313ad93d: große Dateien bleiben überschaubar

FILES = sorted(ROOT.glob("app/*.py")) + sorted(ROOT.glob("static/*.js"))


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_file_stays_below_size_limit(path):
    assert path.stat().st_size <= MAX_BYTES
