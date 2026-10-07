"""Hält docs/WIE-ES-FUNKTIONIERT.md und docs/HOW-IT-WORKS.md aktuell.

Beide Dokumente enthalten einen generierten Block (Stellschrauben-Tabelle +
Fingerabdruck) zwischen BEGIN/END-Markern. Der Fingerabdruck deckt Prompts,
Stilrichtlinie, Modelle und Suchparameter ab. Ändert sich davon etwas,
schlägt tests/test_how_it_works_doc.py fehl (und damit das Deploy-Gate), bis
jemand den Fließtext geprüft und den Block neu geschrieben hat:

    python scripts/how_it_works.py --write
"""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import chunking, embeddings, llm, main, models, summarization  # noqa: E402

DOCS = {"de": ROOT / "docs" / "WIE-ES-FUNKTIONIERT.md", "en": ROOT / "docs" / "HOW-IT-WORKS.md"}
BEGIN, END = "<!-- BEGIN generiert: scripts/how_it_works.py -->", "<!-- END generiert -->"

# (Wert, Fundstelle, Beschreibung DE, Beschreibung EN)
PARAMS = [
    (llm.MODEL_NAME, "app/llm.py: MODEL_NAME", "Modell für Antworten, Folgefragen-Umformulierung, Überarbeitungen", "Model for answers, follow-up rewriting, revisions"),
    (llm.CREATIVE_FIRST_DRAFT_MODEL, "app/llm.py: CREATIVE_FIRST_DRAFT_MODEL", "Modell für den ersten Kreativ-Entwurf", "Model for the first creative draft"),
    (summarization.MODEL_NAME, "app/summarization.py: MODEL_NAME", "Modell für Zusammenfassungen und Schlagworte beim Import", "Model for summaries and key terms on import"),
    (embeddings.MODEL_NAME, "app/embeddings.py: MODEL_NAME", "Embedding-Modell (lokal)", "Embedding model (local)"),
    (chunking.CHUNK_SIZE, "app/chunking.py: CHUNK_SIZE", "Zeichen pro Textabschnitt (Chunk)", "Characters per text chunk"),
    (chunking.CHUNK_OVERLAP, "app/chunking.py: CHUNK_OVERLAP", "Überlappung zwischen Chunks (Zeichen)", "Overlap between chunks (characters)"),
    (models.QuestionIn.model_fields["top_k"].default, "app/models.py: QuestionIn.top_k", "Textausschnitte pro Antwort (Konversation)", "Excerpts per answer (conversation)"),
    (main.RELEVANCE_OVERFETCH_MULTIPLIER, "app/main.py: RELEVANCE_OVERFETCH_MULTIPLIER", "So viele Kandidaten mehr werden vor dem Neusortieren geholt", "Candidate over-fetch factor before reranking"),
    (main.RELEVANCE_MAX_ADJUSTMENT, "app/main.py: RELEVANCE_MAX_ADJUSTMENT", "Max. Einfluss des Relevanzscores (1–10) auf die Distanz", "Max. influence of the relevance score (1–10) on distance"),
    (main.AUTHOR_MENTION_DISTANCE_FACTOR, "app/main.py: AUTHOR_MENTION_DISTANCE_FACTOR", "Distanz-Faktor für Quellen einer genannten Autor:in", "Distance factor for sources of a mentioned author"),
    (main.AUTHOR_MENTION_KEYWORD_MATCH_FACTOR, "app/main.py: AUTHOR_MENTION_KEYWORD_MATCH_FACTOR", "… wenn zusätzlich ein Schlagwort der Quelle in der Frage steht", "… if a key term of the source also appears in the question"),
    (main.LEXICAL_MAX_TERMS, "app/main.py: LEXICAL_MAX_TERMS", "Begriffe pro Frage mit garantiertem Ausschnitt (Hybrid-Suche)", "Terms per question with a guaranteed excerpt (hybrid search)"),
    (main.ASK_HISTORY_MAX_TURNS, "app/main.py: ASK_HISTORY_MAX_TURNS", "Frühere Gesprächsrunden im Prompt", "Previous conversation turns in the prompt"),
    (main.ASK_HISTORY_MAX_CHARS, "app/main.py: ASK_HISTORY_MAX_CHARS", "Zeichenbudget für den Gesprächsverlauf im Prompt", "Character budget for the conversation history in the prompt"),
    (main.ASK_REWRITE_HISTORY_TURNS, "app/main.py: ASK_REWRITE_HISTORY_TURNS", "Gesprächsrunden für die Umformulierung der Suchanfrage", "Conversation turns used to rewrite the search query"),
    (main.CREATIVE_TOP_K, "app/main.py: CREATIVE_TOP_K", "Textausschnitte als Beta-Kontext im Kreativ-Modus", "Excerpts as Beta context in creative mode"),
    (llm.CREATIVE_MAX_SEARCH_USES, "app/llm.py: CREATIVE_MAX_SEARCH_USES", "Max. Websuchen pro Kreativ-Anfrage", "Max. web searches per creative request"),
    (f"{main.CREATIVE_RATE_LIMIT_MAX_REQUESTS}/{main.CREATIVE_RATE_LIMIT_WINDOW_SECONDS // 60} min", "app/main.py: CREATIVE_RATE_LIMIT_*", "Kreativ-Anfragen pro IP", "Creative requests per IP"),
]

# Inhalte, deren Änderung den Fließtext betreffen kann.
FINGERPRINTED = [
    llm.SYSTEM_PROMPTS, llm.REWRITE_SYSTEM_PROMPTS, llm._PARTIAL_ANSWER_REMINDERS,
    llm._LANGUAGE_REMINDERS, llm.CREATIVE_SYSTEM_PROMPTS, llm.CREATIVE_SECTION_SYSTEM_PROMPTS,
    llm._HUMANIZER_BRIDGES, llm._HUMANIZER_GUIDE, main.NO_ANSWER_PHRASES,
    [p[0] for p in PARAMS],
]


def fingerprint() -> str:
    return hashlib.sha256(repr(FINGERPRINTED).encode()).hexdigest()[:12]


def block(lang: str) -> str:
    head = ("| Stellschraube | Wert | Fundstelle |" if lang == "de" else "| Setting | Value | Location |")
    rows = [f"| {de if lang == 'de' else en} | `{value}` | `{where}` |" for value, where, de, en in PARAMS]
    note = (
        "Diese Tabelle wird aus dem Code erzeugt. Ändern sich Prompts oder Parameter, "
        "schlägt `tests/test_how_it_works_doc.py` fehl, bis der Text oben geprüft und "
        "`python scripts/how_it_works.py --write` gelaufen ist."
        if lang == "de" else
        "This table is generated from the code. If prompts or settings change, "
        "`tests/test_how_it_works_doc.py` fails until the text above has been reviewed "
        "and `python scripts/how_it_works.py --write` has been run."
    )
    return "\n".join([BEGIN, head, "|---|---|---|", *rows, "", note, "", f"<!-- fingerprint: {fingerprint()} -->", END])


def current_block(text: str) -> str:
    return text[text.index(BEGIN): text.index(END) + len(END)]


def write() -> None:
    for lang, path in DOCS.items():
        text = path.read_text()
        path.write_text(text.replace(current_block(text), block(lang)))
        print(f"{path.name}: Block aktualisiert ({fingerprint()})")


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        sys.exit(__doc__)
    write()
