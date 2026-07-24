import json
import re

import anthropic

MODEL_NAME = "claude-haiku-4-5-20251001"

SYSTEM_PROMPTS = {
    "de": """Du erstellst eine sachliche Zusammenfassung von ungefähr 120 Wörtern für den folgenden Text.

Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau diesem Format, ohne Markdown-Codeblock und ohne weiteren Text:
{"summary": "...", "key_terms": ["...", "..."]}

- "summary": Zusammenfassung in deutscher Sprache, ca. 120 Wörter.
- "key_terms": 3 bis 6 prägnante, im Text vorkommende Begriffe oder Namen (kurze Substantive/Eigennamen, keine ganzen Sätze), die als Schlagworte für Querverweise zu anderen Quellen dienen.
""",
    "en": """You write a factual summary of approximately 120 words for the following text.

Reply EXCLUSIVELY with a JSON object in exactly this format, with no markdown code block and no other text:
{"summary": "...", "key_terms": ["...", "..."]}

- "summary": summary in English, about 120 words.
- "key_terms": 3 to 6 salient terms or names occurring in the text (short nouns/proper names, not full sentences), used as tags to cross-reference other sources.
""",
}

DEFAULT_LANG = "de"
MAX_INPUT_CHARS = 12000

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _parse_response(raw: str) -> dict:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    data = json.loads(cleaned)
    summary = (data.get("summary") or "").strip()
    key_terms = [t.strip() for t in data.get("key_terms") or [] if t and t.strip()]
    return {"summary": summary, "key_terms": key_terms}


def generate_summary(text: str, lang: str = DEFAULT_LANG) -> dict:
    lang = lang if lang in SYSTEM_PROMPTS else DEFAULT_LANG
    text = text.strip()
    if not text:
        return {"summary": "", "key_terms": []}

    client = _get_client()
    try:
        message = client.messages.create(
            model=MODEL_NAME,
            max_tokens=600,
            system=SYSTEM_PROMPTS[lang],
            messages=[{"role": "user", "content": text[:MAX_INPUT_CHARS]}],
        )
        return _parse_response(message.content[0].text)
    except Exception:
        return {"summary": "", "key_terms": []}
