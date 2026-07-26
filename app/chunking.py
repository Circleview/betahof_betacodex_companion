import re

import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")

CHUNK_SIZE = 900
CHUNK_OVERLAP = 130

# Wie weit (relativ zur Chunk-Größe) darf ein Chunk-Ende von der Ziel-
# Tokenanzahl abweichen, um noch auf die nächste Satzgrenze "einzurasten"?
# Wird keine Satzgrenze in diesem Toleranzfenster gefunden (z.B. bei
# interpunktionsfreiem Text), fällt chunk_text() auf den harten Schnitt
# bei der Ziel-Tokenanzahl zurück.
_BOUNDARY_TOLERANCE = 0.15

_SENTENCE_END_RE = re.compile(r"[.!?](?=\s|$)")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Zerlegt Text anhand von Satzzeichen (./!/?) gefolgt von Leerraum -
    ein regex-basierter Heuristik-Ansatz, der bewusst KEINE Absatz- oder
    Markdown-Struktur voraussetzt, weil die bei PDF-Extraktion und
    Transkripten (YouTube, künftig Audio) nicht robust vorhanden ist."""
    text = text.strip()
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _snap_to_sentence_boundary(tokens: list[int], start: int, target_end: int) -> int | None:
    """Sucht nahe `target_end` eine Satzgrenze und gibt die Token-Position
    direkt danach zurück. None, wenn keine Satzgrenze innerhalb der
    Toleranz gefunden wird."""
    tolerance = max(1, int((target_end - start) * _BOUNDARY_TOLERANCE))
    window_end = min(len(tokens), target_end + tolerance)
    window_text = _encoding.decode(tokens[start:window_end])

    matches = list(_SENTENCE_END_RE.finditer(window_text))
    if not matches:
        return None

    target_len = target_end - start
    best_end = None
    best_distance = None
    for match in matches:
        candidate_len = len(_encoding.encode(window_text[: match.end()]))
        distance = abs(candidate_len - target_len)
        if distance <= tolerance and (best_distance is None or distance < best_distance):
            best_distance = distance
            best_end = start + candidate_len
    return best_end


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    tokens = _encoding.encode(text)
    if not tokens:
        return []

    chunks = []
    start = 0
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
