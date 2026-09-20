"""Gemeinsames Laden/Speichern der JSON-Datendateien in data/ - vorher hatte
jedes Modul (authors, users, audit, question_log, ...) eine eigene, fast
identische Kopie."""

import json
import os
import threading
from pathlib import Path


def load(path: Path, default, *, tolerant: bool = False):
    """Fehlende Datei -> default. Kaputte Datei: mit tolerant=True ebenfalls
    default, sonst der JSON-Fehler (für Bestandsdaten wie authors.json bewusst
    laut - ein stilles Leer-Ergebnis würde beim nächsten save() die Datei
    überschreiben und die Daten vernichten)."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        if tolerant:
            return default
        raise


def save(path: Path, data) -> None:
    """Atomar schreiben (Temp-Datei + Rename statt direktem write_text):
    write_text() truncatet die Datei zuerst - liest ein anderer Thread
    währenddessen (z.B. _finish_synchronous_import parallel zum
    Request-Thread), bekäme er eine leere/unvollständige Datei. os.replace()
    ist auf POSIX atomar: Leser sehen immer die alte oder die neue Version.

    Der Temp-Dateiname MUSS je Aufruf eindeutig sein (reales Datenverlust-
    Vorkommnis 2026-07-28): teilten sich zwei gleichzeitige Schreibvorgänge
    denselben Temp-Pfad, konnte B den Temp-Inhalt von A überschreiben, BEVOR A
    umbenennt - A's replace() hätte dann B's (evtl. älteren) Datensatz
    "gewonnen". Das atomare Rename schützt nur vor kaputten Lesevorgängen,
    nicht mehrere Schreiber voreinander."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".json.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.replace(path)
