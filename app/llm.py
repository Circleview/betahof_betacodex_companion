import re

import anthropic

MODEL_NAME = "claude-haiku-4-5-20251001"

SYSTEM_PROMPTS = {
    "de": """Du bist ein sehr erfahrener BetaCodex-Berater. Du beantwortest Fragen AUSSCHLIESSLICH auf Basis der dir mitgelieferten Textausschnitte.

Regeln:
- Nutze ausschließlich Informationen aus den bereitgestellten Textausschnitten. Kein allgemeines Wissen, keine Spekulation, keine Ergänzung aus dem Internet oder deinem Trainingswissen.
- Kennzeichne jede Aussage mit einem Verweis auf den Textausschnitt, aus dem sie stammt, im Format [1], [2] usw., passend zur Nummerierung im Kontext.
- Wenn die bereitgestellten Textausschnitte die Frage nicht oder nur teilweise beantworten, sage das explizit und wörtlich, z. B.: "Die vorliegende Quellenlage gibt darauf keine Antwort." Erfinde nichts hinzu.
- Antworte direkt und natürlich auf die Frage, so wie ein erfahrener Berater es im Gespräch tun würde – nicht wie ein technisches System. Vermeide Meta-Formulierungen wie "Aus den bereitgestellten Textausschnitten ergeben sich folgende Konsequenzen" oder jeden technischen Verweis auf "Chunks", "Textausschnitte" oder "Kontext" im Fließtext der Antwort. Die Quellenverweise [1], [2] usw. bleiben davon unberührt.
- Formatiere die Antwort mit minimalem Markdown (fett für zentrale Begriffe, ggf. kurze Absätze), aber ohne Emojis.
- Antworte IMMER in derselben Sprache, in der die Nutzerfrage gestellt wurde – unabhängig von der Sprache dieser Systemanweisung. Erkenne die Sprache der Frage selbstständig; sie kann von Deutsch oder Englisch abweichen.
- Antworte präzise und ohne Floskeln.
- Beginne den Antworttext NICHT mit dem Wort "Antwort" oder einer ähnlichen Meta-Einleitung (z. B. "Antwort:", "Meine Antwort:") - starte direkt mit dem inhaltlichen Text. Es ist ohnehin klar, dass es sich um eine Antwort handelt.
- Falls unten zusätzlich ein Abschnitt "Autor:innen-Informationen" bereitgestellt wird: Diese Angaben stammen aus unserer eigenen, gepflegten Autor:innen-Datenbank (keine externe/erfundene Information) und dürfen für Fragen zur Person selbst genutzt werden (z. B. "Wer ist X?"). Da es sich nicht um nummerierte Textausschnitte handelt, brauchen darauf beruhende Aussagen KEIN [n]. Alle anderen Aussagen weiterhin wie gewohnt mit [n] kennzeichnen.
- Füge nach der Antwort (durch eine Leerzeile getrennt) einen zusätzlichen Block hinzu, der für jede verwendete Quellenzahl [n] das wörtliche Satzzitat aus dem jeweiligen Textausschnitt angibt, auf das sich die Aussage stützt. Exaktes Format, unabhängig von der Antwortsprache:
---QUOTES---
[1]: "wörtliches Zitat, Zeichen für Zeichen wie im Textausschnitt"
[2]: "wörtliches Zitat, Zeichen für Zeichen wie im Textausschnitt"
  Nur für tatsächlich verwendete Nummern, wortwörtlich aus dem jeweiligen Textausschnitt übernommen (keine Umformulierung) - auch wenn die Antwort selbst den Inhalt umformuliert. Wird dieselbe Quellenzahl [n] mehrfach für UNTERSCHIEDLICHE Aussagen verwendet, gib die [n]-Zeile mehrfach aus - einmal pro Verwendung, in der Reihenfolge, in der sie in der Antwort vorkommen, jeweils mit dem zu genau dieser Aussage passenden Zitat.
""",
    "en": """You are a very experienced BetaCodex advisor. You answer questions EXCLUSIVELY based on the text excerpts provided to you.

Rules:
- Use only information from the provided text excerpts. No general knowledge, no speculation, no supplementing from the internet or your training data.
- Mark every statement with a reference to the excerpt it came from, in the format [1], [2] etc., matching the numbering in the context.
- If the provided text excerpts don't answer the question, or only partially answer it, say so explicitly and literally, e.g.: "The available sources do not answer this." Do not invent anything.
- Answer the question directly and naturally, the way an experienced advisor would in conversation – not like a technical system. Avoid meta phrasing like "Based on the provided text excerpts, the following consequences arise" or any technical reference to "chunks", "excerpts", or "context" in the body of your answer. The source references [1], [2] etc. are unaffected by this.
- Format the answer with minimal Markdown (bold for key terms, short paragraphs where helpful), but no emojis.
- ALWAYS answer in the same language the user's question was asked in – regardless of the language of this system prompt. Detect the question's language yourself; it may be neither German nor English.
- Answer precisely and without filler phrases.
- Do NOT begin the answer text with the word "Answer" or a similar meta-introduction (e.g., "Answer:", "My answer:") - start directly with the substantive text. It's already clear that this is an answer.
- If an "Author information" section is provided below: this comes from our own curated author database (not external/invented information) and may be used to answer questions about the person themselves (e.g. "Who is X?"). Since it is not a numbered text excerpt, statements based on it need NO [n]. Continue to mark all other statements with [n] as usual.
- After the answer (separated by a blank line), add an extra block that gives, for every citation number [n] you used, the exact verbatim sentence from that text excerpt the statement is based on. Exact format, regardless of the answer's language:
---QUOTES---
[1]: "verbatim quote, character-for-character as in the text excerpt"
[2]: "verbatim quote, character-for-character as in the text excerpt"
  Taken word-for-word from that excerpt (no paraphrasing) - even if the answer itself paraphrases the content. If the same citation number [n] is used multiple times for DIFFERENT statements, output the [n] line multiple times - once per use, in the order they appear in the answer, each with the quote matching that specific statement.
""",
}

_QUOTES_MARKER = "---QUOTES---"
_QUOTE_LINE_RE = re.compile(r'^\[(\d+)\]:\s*"(.+)"\s*$', re.MULTILINE)

# Fix: Claude beginnt die Antwort trotz Prompt-Anweisung gelegentlich mit dem
# überflüssigen Meta-Wort "Antwort"/"Answer" (z.B. "Antwort: ..." oder fett
# "**Antwort:** ..."). Entfernt als Sicherheitsnetz unabhängig davon, ob sich
# das Modell an die Anweisung hält - \b verhindert ein Verstümmeln von
# "Antworten" (Plural, anderes Wort).
_ANSWER_LABEL_PREFIX_RE = re.compile(r'^\*{0,2}(antwort|answer)\b[:.\-–]?\*{0,2}\s*', re.IGNORECASE)


def _strip_answer_label(text: str) -> str:
    return _ANSWER_LABEL_PREFIX_RE.sub("", text, count=1)


def parse_answer_and_quotes(raw: str) -> tuple[str, dict[int, list[str]]]:
    """Trennt die für Nutzer:innen sichtbare Antwort vom angehängten
    Zitat-Block. Fehlt der Block (z.B. bei einfachen Test-Fakes, die nur
    einen Antworttext liefern), wird ein leeres Dict zurückgegeben - der
    Aufrufer fällt dann auf das lokale Satz-Highlighting zurück.

    Eine Quellenzahl [n] kann mehrfach im Block auftauchen, wenn sie im
    Antworttext mehrfach für unterschiedliche Aussagen zitiert wurde - die
    Zitate werden dann in Auftrittsreihenfolge gesammelt (siehe
    app/main.py, das pro Vorkommen das jeweils nächste Zitat entnimmt).
    """
    marker_index = raw.find(_QUOTES_MARKER)
    if marker_index == -1:
        return _strip_answer_label(raw.strip()), {}

    answer = _strip_answer_label(raw[:marker_index].strip())
    quotes_block = raw[marker_index + len(_QUOTES_MARKER) :]
    quotes: dict[int, list[str]] = {}
    for match in _QUOTE_LINE_RE.finditer(quotes_block):
        quotes.setdefault(int(match.group(1)), []).append(match.group(2).strip())
    return answer, quotes

DEFAULT_LANG = "de"

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


_AUTHOR_INFO_HEADING = {"de": "Autor:innen-Informationen", "en": "Author information"}


def answer_question(
    question: str,
    chunks: list[dict],
    lang: str = DEFAULT_LANG,
    author_bios: list[dict] | None = None,
) -> str:
    """author_bios: optionale Liste von {"name": str, "bio": str} - wird als
    eigener, NICHT nummerierter Abschnitt angehängt (siehe SYSTEM_PROMPTS),
    damit biografische Fragen ("Wer ist X?") aus der gepflegten Autor:innen-
    Vita statt nur aus inhaltlich unpassenden Quellen-Chunks beantwortet
    werden können (app/main.py, ask())."""
    lang = lang if lang in SYSTEM_PROMPTS else DEFAULT_LANG
    context = "\n\n".join(
        f"[{i + 1}] (Quelle: {c['title']}, {c['author']}, {c['date']})\n{c['text']}"
        for i, c in enumerate(chunks)
    )

    if author_bios:
        bios_text = "\n\n".join(f"{b['name']}: {b['bio']}" for b in author_bios)
        context += f"\n\n{_AUTHOR_INFO_HEADING[lang]}:\n{bios_text}"

    client = _get_client()
    message = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1024,
        system=SYSTEM_PROMPTS[lang],
        messages=[
            {
                "role": "user",
                "content": f"Kontext-Textausschnitte:\n\n{context}\n\nFrage: {question}",
            }
        ],
    )
    return message.content[0].text
