import anthropic

MODEL_NAME = "claude-haiku-4-5-20251001"

SYSTEM_PROMPTS = {
    "de": """Du erstellst eine sachliche Zusammenfassung von ungefähr 120 Wörtern für den folgenden Text und rufst dafür das bereitgestellte Werkzeug auf.

- "summary": Zusammenfassung in deutscher Sprache, ca. 120 Wörter.
- "key_terms": 3 bis 6 prägnante, im Text vorkommende Begriffe oder Namen (kurze Substantive/Eigennamen, keine ganzen Sätze), die als Schlagworte für Querverweise zu anderen Quellen dienen.
""",
    "en": """You write a factual summary of approximately 120 words for the following text and call the provided tool with the result.

- "summary": summary in English, about 120 words.
- "key_terms": 3 to 6 salient terms or names occurring in the text (short nouns/proper names, not full sentences), used as tags to cross-reference other sources.
""",
}

BILINGUAL_SYSTEM_PROMPT = """Du erstellst eine sachliche Zusammenfassung von ungefähr 120 Wörtern für den folgenden Text – und zwar sowohl auf Deutsch als auch auf Englisch. Rufe dafür das bereitgestellte Werkzeug auf.

- "summary_de"/"summary_en": inhaltlich gleichwertige Zusammenfassungen, jeweils ca. 120 Wörter, in der jeweils genannten Sprache.
- "key_terms_de"/"key_terms_en": jeweils 3 bis 6 prägnante Begriffe/Namen aus dem Text (kurze Substantive/Eigennamen, keine ganzen Sätze) in der jeweiligen Sprache – für "key_terms_en" die übliche englische Entsprechung verwenden, falls gebräuchlich, sonst den Originalbegriff. Dienen als Schlagworte für Querverweise zu anderen Quellen.
"""

BIO_SYSTEM_PROMPTS = {
    "de": """Du schreibst eine kurze, sachliche Vita (ca. 60-80 Wörter) für eine Autorin/einen Autor, basierend auf den Titeln und Zusammenfassungen ihrer/seiner Quellen.

Antworte AUSSCHLIESSLICH mit dem Vita-Text selbst - ohne Anführungszeichen, ohne Markdown, ohne Überschrift, ohne weiteren Text.""",
    "en": """You write a short, factual bio (approximately 60-80 words) for an author, based on the titles and summaries of their sources.

Reply EXCLUSIVELY with the bio text itself - no quotation marks, no markdown, no heading, no other text.""",
}

DEFAULT_LANG = "de"
MAX_INPUT_CHARS = 12000

_client = None

_SUMMARY_TOOL = {
    "name": "provide_summary",
    "description": "Liefert die Zusammenfassung und Schlagworte für den Text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "key_terms": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "key_terms"],
    },
}

_BILINGUAL_SUMMARY_TOOL = {
    "name": "provide_bilingual_summary",
    "description": "Liefert die zweisprachige Zusammenfassung und Schlagworte für den Text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "summary_de": {"type": "string"},
            "summary_en": {"type": "string"},
            "key_terms_de": {"type": "array", "items": {"type": "string"}},
            "key_terms_en": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary_de", "summary_en", "key_terms_de", "key_terms_en"],
    },
}


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _call_tool(system_prompt: str, tool: dict, content: str) -> dict | None:
    """Nutzt Anthropics Tool-Use statt freitextigem JSON in der Antwort - die
    API validiert/strukturiert das Ergebnis serverseitig. Vorher wurde das
    Modell gebeten, selbst valides JSON als Text auszugeben; enthielt die
    Zusammenfassung dabei Anführungszeichen (z.B. ein zitierter Buch- oder
    Podcast-Titel), hat das Modell diese im JSON-String gelegentlich nicht
    korrekt escaped - das Parsen schlug dann fehl und die Zusammenfassung
    blieb lautlos leer, ohne dass das irgendwo sichtbar wurde."""
    client = _get_client()
    message = client.messages.create(
        model=MODEL_NAME,
        max_tokens=1000,
        system=system_prompt,
        tools=[tool],
        tool_choice={"type": "tool", "name": tool["name"]},
        messages=[{"role": "user", "content": content}],
    )
    for block in message.content:
        if block.type == "tool_use":
            return block.input
    return None


def generate_summary(text: str, lang: str = DEFAULT_LANG) -> dict:
    lang = lang if lang in SYSTEM_PROMPTS else DEFAULT_LANG
    text = text.strip()
    if not text:
        return {"summary": "", "key_terms": []}

    try:
        data = _call_tool(SYSTEM_PROMPTS[lang], _SUMMARY_TOOL, text[:MAX_INPUT_CHARS])
        if not data:
            return {"summary": "", "key_terms": []}
        summary = (data.get("summary") or "").strip()
        key_terms = [t.strip() for t in data.get("key_terms") or [] if t and t.strip()]
        return {"summary": summary, "key_terms": key_terms}
    except Exception:
        return {"summary": "", "key_terms": []}


def generate_bilingual_summary(text: str) -> dict:
    text = text.strip()
    empty = {"de": {"summary": "", "key_terms": []}, "en": {"summary": "", "key_terms": []}}
    if not text:
        return empty

    try:
        data = _call_tool(BILINGUAL_SYSTEM_PROMPT, _BILINGUAL_SUMMARY_TOOL, text[:MAX_INPUT_CHARS])
        if not data:
            return empty
        return {
            "de": {
                "summary": (data.get("summary_de") or "").strip(),
                "key_terms": [t.strip() for t in data.get("key_terms_de") or [] if t and t.strip()],
            },
            "en": {
                "summary": (data.get("summary_en") or "").strip(),
                "key_terms": [t.strip() for t in data.get("key_terms_en") or [] if t and t.strip()],
            },
        }
    except Exception:
        return empty


def generate_author_bio(name: str, texts: list[str], lang: str = DEFAULT_LANG) -> str:
    lang = lang if lang in BIO_SYSTEM_PROMPTS else DEFAULT_LANG
    content = "\n\n".join(t.strip() for t in texts if t and t.strip())
    if not content:
        return ""

    client = _get_client()
    try:
        message = client.messages.create(
            model=MODEL_NAME,
            max_tokens=300,
            system=BIO_SYSTEM_PROMPTS[lang],
            messages=[{"role": "user", "content": f"Name: {name}\n\n{content[:MAX_INPUT_CHARS]}"}],
        )
        return message.content[0].text.strip()
    except Exception:
        return ""
