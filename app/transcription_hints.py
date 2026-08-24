import json
from pathlib import Path

# Nutzerwunsch (2026-08-24): feste Vokabular-Hinweise für die Audio-
# Transkription (siehe _process_audio_transcription in app/main.py) leben
# bewusst in einer eigenen, separat gepflegten Datei statt als Konstante in
# main.py - so lassen sich neue, wiederkehrend falsch erkannte Begriffe
# ergänzen, ohne main.py anzufassen. Schreibweise unterscheidet sich je nach
# Sprache (z.B. "Beta-Kodex" im Deutschen, "BetaCodex" im Englischen), daher
# pro Sprache eine eigene Liste statt einer gemeinsamen.
HINTS_FILE = Path(__file__).resolve().parent / "transcription_hints.json"


def get_hints(lang: str) -> list[str]:
    try:
        data = json.loads(HINTS_FILE.read_text())
    except Exception:
        return []
    return data.get(lang, [])
