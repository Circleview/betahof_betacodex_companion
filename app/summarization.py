import anthropic

MODEL_NAME = "claude-haiku-4-5-20251001"

# Nutzerwunsch (2026-09-22): einmalige, von Quellen-Pfleger:innen angestoßene
# Analyse vorhandener Schlagworte auf inhaltliche Nähe (z.B. "hierarchiefreie
# Organisationen" vs. "hierarchielose Organisation") - anders als die
# häufigen, günstigen Zusammenfassungs-Aufrufe (Haiku) braucht dieser
# seltene, aber folgenreiche Abwägungs-Schritt (ein falsch erkanntes
# "Synonym" würde zwei unterschiedliche Konzepte vermischen) das bessere
# Modell, wie schon beim ersten Kreativ-Entwurf (siehe app/llm.py,
# CREATIVE_FIRST_DRAFT_MODEL).
MERGE_SUGGESTIONS_MODEL = "claude-sonnet-5"

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
- Schreibweise: im Deutschen immer "Beta-Kodex", im Englischen immer "BetaCodex" (Eigennamen wie "BetaCodex Network" bleiben unverändert).
- "key_terms_de"/"key_terms_en": jeweils 3 bis 6 prägnante Begriffe/Namen aus dem Text (kurze Substantive/Eigennamen, keine ganzen Sätze) in der jeweiligen Sprache – für "key_terms_en" die übliche englische Entsprechung verwenden, falls gebräuchlich, sonst den Originalbegriff. Dienen als Schlagworte für Querverweise zu anderen Quellen.
"""

KEY_TERMS_SYSTEM_PROMPTS = {
    "de": """Du extrahierst prägnante Schlagworte aus dem folgenden, bereits fertigen Zusammenfassungstext und rufst dafür das bereitgestellte Werkzeug auf.

- "key_terms": 3 bis 6 prägnante, im Text vorkommende Begriffe oder Namen (kurze Substantive/Eigennamen, keine ganzen Sätze), die als Schlagworte für Querverweise zu anderen Quellen dienen.
""",
    "en": """You extract salient tags from the following, already finished summary text and call the provided tool with the result.

- "key_terms": 3 to 6 salient terms or names occurring in the text (short nouns/proper names, not full sentences), used as tags to cross-reference other sources.
""",
}

BIO_SYSTEM_PROMPTS = {
    "de": """Du schreibst eine kurze, sachliche Vita (ca. 60-80 Wörter) für eine Autorin/einen Autor, basierend auf den Titeln und Zusammenfassungen ihrer/seiner Quellen.

Ergänze das gerne um dein eigenes Allgemeinwissen über diese Person (z. B. Wirken, weitere Werke, Rolle/Organisation) - beschränke dich nicht nur auf den gegebenen Text. Erfinde dabei aber keine nicht überprüfbaren Details; wenn du die Person nicht kennst, bleib beim gegebenen Text.

Antworte AUSSCHLIESSLICH mit dem Vita-Text selbst - ohne Anführungszeichen, ohne Markdown, ohne Überschrift, ohne weiteren Text.""",
    "en": """You write a short, factual bio (approximately 60-80 words) for an author, based on the titles and summaries of their sources.

Feel free to also draw on your own general knowledge about this person (e.g. their body of work, other publications, role/organization) - don't limit yourself to only the given text. Don't invent unverifiable details, though; if you don't know the person, stick to the given text.

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

_KEY_TERMS_TOOL = {
    "name": "provide_key_terms",
    "description": "Liefert die Schlagworte für den Text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "key_terms": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["key_terms"],
    },
}

_MERGE_SUGGESTIONS_TOOL = {
    "name": "provide_merge_suggestions",
    "description": "Liefert Gruppen von Schlagworten, die dasselbe Konzept bezeichnen.",
    "input_schema": {
        "type": "object",
        "properties": {
            "groups": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "canonical": {
                            "type": "string",
                            "description": "Einer der gegebenen Begriffe, unverändert übernommen - kein neu formulierter Begriff.",
                        },
                        "variants": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Andere gegebene Begriffe, die durch 'canonical' ersetzt werden sollen.",
                        },
                    },
                    "required": ["canonical", "variants"],
                },
            },
        },
        "required": ["groups"],
    },
}

MERGE_SUGGESTIONS_SYSTEM_PROMPTS = {
    "de": """Du bekommst eine Liste von Schlagworten aus einer kuratierten Quellensammlung, einen pro Zeile. Finde Gruppen von mindestens zwei Begriffen, die dasselbe inhaltliche Konzept bezeichnen, sich aber in Schreibweise oder Formulierung unterscheiden (z.B. Singular/Plural, unterschiedliche Wortbildung wie "hierarchiefrei" vs. "hierarchielos", Bindestrich-/Leerzeichen-Varianten, Abkürzung vs. ausgeschriebene Form).

Rufe das bereitgestellte Werkzeug auf. Für jede Gruppe:
- "canonical": EINER der gegebenen Begriffe unverändert (die klarste/gebräuchlichste Schreibweise) - erfinde keine neue Formulierung.
- "variants": die ÜBRIGEN Begriffe derselben Gruppe (nicht den canonical-Begriff selbst).

Nimm eine Gruppe nur auf, wenn du wirklich sicher bist, dass es dasselbe Konzept ist - im Zweifel lieber weglassen, als zwei unterschiedliche Themen fälschlich zusammenzulegen. Begriffe, für die es keine passende Gruppe gibt, einfach nicht erwähnen.""",
    "en": """You receive a list of tags from a curated source collection, one per line. Find groups of two or more terms that refer to the same underlying concept but differ in spelling or phrasing (e.g. singular/plural, different word formation, hyphen/space variants, abbreviation vs. spelled-out form).

Call the provided tool. For each group:
- "canonical": ONE of the given terms, unchanged (the clearest/most common spelling) - do not invent new wording.
- "variants": the OTHER terms in the same group (not the canonical term itself).

Only include a group when you are genuinely confident it's the same concept - when in doubt, leave it out rather than wrongly merging two distinct topics. Terms with no matching group simply don't need to be mentioned.""",
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


# Nutzerwunsch (2026-09-22): vorhandene Schlagworte der Sammlung sollen bei
# der automatischen Generierung neuer Schlagworte einfließen, damit sich
# Schreibweisen für dasselbe Thema nicht immer weiter auseinanderentwickeln
# und inhaltliche Zusammenhänge (die z.B. das Netzwerk-Diagramm zeigt) nicht
# durch bloße Formulierungsunterschiede übersehen werden. Reine Textliste im
# Prompt statt z.B. eines eigenen Tool-Parameters - das Modell soll die
# Begriffe wie zusätzliches Wissen abwägen, nicht stur draus auswählen
# müssen (ein wirklich neues Thema soll weiterhin einen neuen Begriff
# bekommen dürfen).
def _known_terms_instruction(known_terms_by_lang: dict[str, list[str]]) -> str:
    parts = [f"{lang}: {', '.join(terms)}" for lang, terms in known_terms_by_lang.items() if terms]
    if not parts:
        return ""
    return (
        "\n\nBereits vorhandene Schlagworte, die schon an anderer Stelle in der Sammlung "
        "verwendet werden (bevorzugt einen passenden davon wiederverwenden, statt eine neue "
        "Formulierung für dasselbe Konzept zu erfinden - nur einen neuen Begriff prägen, wenn "
        "wirklich keiner davon passt):\n" + "\n".join(parts)
    )


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


def _call_bilingual_summary_tool(
    text: str, known_terms_de: list[str] | None = None, known_terms_en: list[str] | None = None
) -> dict | None:
    system_prompt = BILINGUAL_SYSTEM_PROMPT + _known_terms_instruction(
        {"Deutsch": known_terms_de or [], "Englisch": known_terms_en or []}
    )
    try:
        data = _call_tool(system_prompt, _BILINGUAL_SUMMARY_TOOL, text[:MAX_INPUT_CHARS])
        if not data:
            return None
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
        return None


def generate_bilingual_summary(
    text: str, known_terms_de: list[str] | None = None, known_terms_en: list[str] | None = None
) -> dict:
    text = text.strip()
    empty = {"de": {"summary": "", "key_terms": []}, "en": {"summary": "", "key_terms": []}}
    if not text:
        return empty

    result = _call_bilingual_summary_tool(text, known_terms_de, known_terms_en)
    # Vereinzelt liefert das Modell in einem Aufruf zwar eine valide
    # Tool-Antwort, lässt darin aber eine der beiden (laut Schema
    # verpflichtenden) Sprachen leer, während die andere korrekt gefüllt ist
    # - beobachtet beim Import einer per KI-OCR erkannten PDF, wo summary_en
    # gefüllt war, summary_de aber leer blieb, obwohl ein erneuter Aufruf mit
    # demselben Text sofort eine vollständige deutsche Zusammenfassung
    # lieferte. Ein einziger Retry behebt das in der Praxis zuverlässig.
    if result and (not result["de"]["summary"] or not result["en"]["summary"]):
        retry = _call_bilingual_summary_tool(text, known_terms_de, known_terms_en)
        if retry:
            result = retry
    return result or empty


_TRANSLATE_TOOL = {
    "name": "provide_translation",
    "description": "Liefert die Übersetzung des Textes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "translation": {"type": "string"},
        },
        "required": ["translation"],
    },
}

TRANSLATE_SYSTEM_PROMPTS = {
    "de": """Du übersetzt den folgenden Zusammenfassungstext sinngemäß und stilistisch passend ins Deutsche und rufst dafür das bereitgestellte Werkzeug auf. Gib ausschließlich die Übersetzung selbst zurück, ohne Anmerkungen. Schreibe "Beta-Kodex" (nicht "BetaCodex"); Eigennamen wie "BetaCodex Network" bleiben.""",
    "en": """You translate the following summary text faithfully and in a matching style into English, and call the provided tool with the result. Return exclusively the translation itself, without any notes. Write "BetaCodex" (not "Beta-Kodex").""",
}


def translate_summary(text: str, target_lang: str = DEFAULT_LANG) -> str:
    """Übersetzt einen (ggf. von Hand überarbeiteten) Zusammenfassungstext in
    die jeweils andere Sprache - genutzt, wenn eine Quellen-Pfleger:in eine
    Zusammenfassung manuell bearbeitet (siehe update_source in app/main.py),
    damit beide Sprachversionen inhaltlich synchron bleiben, ohne die
    gesamte Zusammenfassung unabhängig neu generieren zu müssen (das würde
    inhaltlich von der gerade kuratierten Fassung abweichen)."""
    target_lang = target_lang if target_lang in TRANSLATE_SYSTEM_PROMPTS else DEFAULT_LANG
    text = text.strip()
    if not text:
        return ""

    try:
        data = _call_tool(TRANSLATE_SYSTEM_PROMPTS[target_lang], _TRANSLATE_TOOL, text[:MAX_INPUT_CHARS])
        if not data:
            return ""
        return (data.get("translation") or "").strip()
    except Exception:
        return ""


def extract_key_terms(text: str, lang: str = DEFAULT_LANG, known_terms: list[str] | None = None) -> list[str]:
    """Leitet NUR Schlagworte aus einem bereits vorhandenen (ggf. von Hand
    überarbeiteten) Zusammenfassungstext ab, ohne die Zusammenfassung selbst
    neu zu erzeugen - Backlog: die Begriffsliste soll auch dann mit einer
    manuell polierten Zusammenfassung synchron gehalten werden können, ohne
    deren Wortlaut zu überschreiben (siehe generate_summary/
    generate_bilingual_summary für die vollständige Neugenerierung inkl. der
    Zusammenfassung selbst)."""
    lang = lang if lang in KEY_TERMS_SYSTEM_PROMPTS else DEFAULT_LANG
    text = text.strip()
    if not text:
        return []

    system_prompt = KEY_TERMS_SYSTEM_PROMPTS[lang] + _known_terms_instruction({lang: known_terms or []})
    try:
        data = _call_tool(system_prompt, _KEY_TERMS_TOOL, text[:MAX_INPUT_CHARS])
        if not data:
            return []
        return [t.strip() for t in data.get("key_terms") or [] if t and t.strip()]
    except Exception:
        return []


def find_similar_term_groups(term_list: list[str], lang: str = DEFAULT_LANG) -> list[dict]:
    """Analysiert eine Liste bereits vorhandener Schlagworte auf inhaltliche
    Nähe (Nutzerwunsch 2026-09-22, z.B. "hierarchiefreie Organisationen" vs.
    "hierarchielose Organisation") und schlägt pro erkannter Gruppe einen
    kanonischen Begriff vor, auf den die übrigen Varianten zusammengeführt
    werden sollen. Reine Vorschlagsliste - wendet nichts an, das passiert
    erst über einen expliziten, von einer Quellen-Pfleger:in bestätigten
    zweiten Schritt (siehe /api/terms/merge in app/main.py)."""
    lang = lang if lang in MERGE_SUGGESTIONS_SYSTEM_PROMPTS else DEFAULT_LANG
    term_list = sorted({t.strip() for t in term_list if t and t.strip()})
    if len(term_list) < 2:
        return []

    client = _get_client()
    try:
        message = client.messages.create(
            model=MERGE_SUGGESTIONS_MODEL,
            max_tokens=4000,
            system=MERGE_SUGGESTIONS_SYSTEM_PROMPTS[lang],
            tools=[_MERGE_SUGGESTIONS_TOOL],
            tool_choice={"type": "tool", "name": _MERGE_SUGGESTIONS_TOOL["name"]},
            messages=[{"role": "user", "content": "\n".join(term_list)}],
        )
    except Exception:
        return []

    known_terms = set(term_list)
    groups = []
    for block in message.content:
        if block.type != "tool_use":
            continue
        for group in block.input.get("groups") or []:
            canonical = (group.get("canonical") or "").strip()
            # Nur Begriffe akzeptieren, die tatsächlich in der Eingabe standen
            # - schützt gegen ein vom Modell trotz Anweisung neu formuliertes
            # "canonical" sowie gegen halluzinierte Varianten.
            if canonical not in known_terms:
                continue
            variants = sorted(
                {v.strip() for v in group.get("variants") or [] if v and v.strip() in known_terms and v.strip() != canonical}
            )
            if variants:
                groups.append({"canonical": canonical, "variants": variants})
        break
    return groups


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
