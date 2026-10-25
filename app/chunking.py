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


def _chunk_plain(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Token-Fenster mit Satzgrenzen-Einrasten (der Algorithmus ohne Struktur)."""
    if chunk_size <= overlap:
        raise ValueError("chunk_size muss größer als overlap sein")
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


_HEADING_RE = re.compile(r"#{1,3} \S")
_PREFIX_MAX_TOKENS = 50


def _section_starts(text: str) -> list[int]:
    """Zeichenpositionen der Überschriftszeilen (# bis ###), Codeblöcke ausgenommen."""
    starts, pos, in_code = [], 0, False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            in_code = not in_code
        elif not in_code and _HEADING_RE.match(line):
            starts.append(pos)
        pos += len(line)
    return starts


def _split_long_section(section: str, chunk_size: int, overlap: int) -> list[str]:
    """Abschnitt > chunk_size: Folge-Chunks bekommen die (gekappte) Überschrift."""
    first_line = section.split("\n", 1)[0]
    if not _HEADING_RE.match(first_line):  # Text vor der ersten Überschrift
        return _chunk_plain(section, chunk_size, overlap)
    heading = _encoding.decode(_encoding.encode(first_line)[:_PREFIX_MAX_TOKENS]).replace("\ufffd", "")
    prefix = heading + "\n"
    # 2 Tokens Reserve, weil Zusammensetzen Token-Grenzen verschieben kann
    budget = max(overlap + 1, chunk_size - len(_encoding.encode(prefix)) - 2)
    chunks = _chunk_plain(section, budget, overlap)
    return chunks[:1] + [prefix + c for c in chunks[1:]]


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Zerlegt Text kapitelweise (Markdown-Überschriften # bis ###); ohne
    Überschriften exakt das Token-Fenster-Verfahren."""
    if chunk_size <= overlap:
        raise ValueError("chunk_size muss größer als overlap sein")
    starts = _section_starts(text)
    if not starts:
        return _chunk_plain(text, chunk_size, overlap)
    bounds = ([0] if starts[0] > 0 else []) + starts + [len(text)]
    sections = [(a, b) for a, b in zip(bounds, bounds[1:]) if text[a:b].strip()]

    chunks: list[str] = []
    cur: tuple[int, int] | None = None  # laufende Gruppe ganzer Abschnitte
    for a, b in sections:
        if cur and len(_encoding.encode(text[cur[0]:b].strip())) <= chunk_size:
            cur = (cur[0], b)
            continue
        if cur:
            chunks.append(text[cur[0]:cur[1]].strip())
            cur = None
        if len(_encoding.encode(text[a:b].strip())) <= chunk_size:
            cur = (a, b)
        else:
            chunks.extend(_split_long_section(text[a:b].strip(), chunk_size, overlap))
    if cur:
        chunks.append(text[cur[0]:cur[1]].strip())
    return chunks


MAX_IMAGES_PER_CHUNK = 3


def norm_anchor(text: str) -> str:
    """Vergleichsform für Bild-Anker: nur Buchstaben/Ziffern, klein - robust
    gegen Markdown-Zeichen, Zeilenumbrüche und Leerraum."""
    return re.sub(r"\W+", "", text.lower())


def assign_images(chunks: list[str], images: list[dict]) -> list[list[dict]]:
    """Ordnet jedem Chunk seine Bilder zu: ein Bild kommt in den ersten Chunk,
    der seinen Anker enthält (höchstens 3 je Chunk). Unbekannter Anker oder
    voller Chunk -> das Bild entfällt. Ergebnis ohne Anker: {kind, url|file, alt, page}."""
    normalized = [norm_anchor(c) for c in chunks]
    result: list[list[dict]] = [[] for _ in chunks]
    for image in images:
        anchor = norm_anchor(image.get("anchor") or "")
        if not anchor:
            continue
        for i, chunk in enumerate(normalized):
            if anchor in chunk and len(result[i]) < MAX_IMAGES_PER_CHUNK:
                ref = {"kind": image["kind"], "alt": image.get("alt") or "", "page": image.get("page")}
                ref["url" if image["kind"] == "url" else "file"] = image.get("url" if image["kind"] == "url" else "file")
                result[i].append(ref)
                break
    return result
