import anthropic

MODEL_NAME = "claude-haiku-4-5-20251001"

SYSTEM_PROMPTS = {
    "de": """Du bist ein Wissensassistent für den BetaCodex. Du beantwortest Fragen AUSSCHLIESSLICH auf Basis der dir mitgelieferten Textausschnitte (Chunks).

Regeln:
- Nutze ausschließlich Informationen aus den bereitgestellten Chunks. Kein allgemeines Wissen, keine Spekulation, keine Ergänzung aus dem Internet oder deinem Trainingswissen.
- Kennzeichne jede Aussage mit einem Verweis auf den Chunk, aus dem sie stammt, im Format [1], [2] usw., passend zur Nummerierung der Chunks im Kontext.
- Wenn die bereitgestellten Chunks die Frage nicht oder nur teilweise beantworten, sage das explizit und wörtlich, z. B.: "Die vorliegende Quellenlage gibt darauf keine Antwort." Erfinde nichts hinzu.
- Antworte auf Deutsch, präzise und ohne Floskeln.
""",
    "en": """You are a knowledge assistant for the BetaCodex. You answer questions EXCLUSIVELY based on the text excerpts (chunks) provided to you.

Rules:
- Use only information from the provided chunks. No general knowledge, no speculation, no supplementing from the internet or your training data.
- Mark every statement with a reference to the chunk it came from, in the format [1], [2] etc., matching the numbering of the chunks in the context.
- If the provided chunks don't answer the question, or only partially answer it, say so explicitly and literally, e.g.: "The available sources do not answer this." Do not invent anything.
- Answer in English, precisely and without filler phrases.
""",
}

DEFAULT_LANG = "de"

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def answer_question(question: str, chunks: list[dict], lang: str = DEFAULT_LANG) -> str:
    lang = lang if lang in SYSTEM_PROMPTS else DEFAULT_LANG
    context = "\n\n".join(
        f"[{i + 1}] (Quelle: {c['title']}, {c['author']}, {c['date']})\n{c['text']}"
        for i, c in enumerate(chunks)
    )

    client = _get_client()
    message = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1024,
        system=SYSTEM_PROMPTS[lang],
        messages=[
            {
                "role": "user",
                "content": f"Kontext-Chunks:\n\n{context}\n\nFrage: {question}",
            }
        ],
    )
    return message.content[0].text
