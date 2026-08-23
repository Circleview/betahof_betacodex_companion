"""Proaktive Quellen-Suche im offenen Web (Nutzerwunsch: Quellenlage
systematisch verbreitern statt nur auf manuell eingereichte Quellen zu
warten). Nutzt Claudes serverseitiges Web-Search-Tool
(web_search_20250305, kein zusätzlicher Such-API-Vendor nötig) kombiniert
mit einem eigenen "submit_candidates"-Tool in DEMSELBEN Call: das Modell
sucht zuerst (läuft serverseitig innerhalb des Calls, keine eigene
Round-Trip-Logik nötig) und ruft danach das eigene Tool mit den
gefundenen Kandidaten auf. tool_choice bleibt bewusst "auto" - würde
submit_candidates erzwungen, würde das Modell gar nicht erst suchen.

Fehler-Konvention wie llm.rewrite_followup_query (app/llm.py): der ganze
Call steckt in try/except Exception, gibt bei jedem Fehler eine leere
Liste zurück - ein Discovery-Lauf darf nie den wöchentlichen Hintergrund-
Worker (app/main.py) zum Absturz bringen."""
import anthropic

MODEL_NAME = "claude-haiku-4-5-20251001"
MAX_SEARCH_USES = 5

_client = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


_SUBMIT_CANDIDATES_TOOL = {
    "name": "submit_candidates",
    "description": "Liefert die gefundenen Quellen-Kandidaten.",
    "input_schema": {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "title": {"type": "string"},
                        "reason": {
                            "type": "string",
                            "description": "Ein bis zwei Sätze, warum diese Seite thematisch bzw. autor:innen-mäßig zur bestehenden Quellensammlung passt.",
                        },
                    },
                    "required": ["url", "title", "reason"],
                },
            },
        },
        "required": ["candidates"],
    },
}

_EXCLUSION_HINT = (
    "Schlage NICHTS von diesen bereits bekannten URLs vor: {known_urls}. "
    "Schlage außerdem nichts von diesen Domains vor, sie wurden bereits "
    "mehrfach abgelehnt: {excluded_domains}."
)

_AUTHOR_SYSTEM_PROMPT = """Du hilfst dabei, die Quellensammlung eines Wissensassistenten zum Thema \
BetaCodex/dezentrale Organisationsentwicklung zu erweitern. Suche im Web nach öffentlich zugänglichen, \
frei lesbaren Text-Artikeln oder Blogbeiträgen EINER bestimmten, bereits bekannten Autorin/eines bereits \
bekannten Autors, die noch NICHT in der Sammlung enthalten sind. Rufe danach das Werkzeug \
"submit_candidates" mit den gefundenen Ergebnissen auf (leere Liste, falls nichts Passendes gefunden \
wurde). Nur deutsch- oder englischsprachige Inhalte, keine Bezahlschranken, keine reinen \
Video-/Audio-Inhalte."""

_TOPIC_SYSTEM_PROMPT = """Du hilfst dabei, die Quellensammlung eines Wissensassistenten zum Thema \
BetaCodex/dezentrale Organisationsentwicklung inhaltlich zu verbreitern. Suche im Web nach öffentlich \
zugänglichen, frei lesbaren Text-Artikeln oder Blogbeiträgen ANDERER Autor:innen/Domains, die sich mit \
denselben oder eng verwandten Themen befassen wie die unten skizzierte bestehende Sammlung. Rufe danach \
das Werkzeug "submit_candidates" mit den gefundenen Ergebnissen auf (leere Liste, falls nichts Passendes \
gefunden wurde). Nur deutsch- oder englischsprachige Inhalte, keine Bezahlschranken, keine reinen \
Video-/Audio-Inhalte."""


def _run_discovery(system_prompt: str, user_content: str) -> list[dict]:
    try:
        client = _get_client()
        message = client.messages.create(
            model=MODEL_NAME,
            max_tokens=2048,
            system=system_prompt,
            tools=[
                {"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCH_USES},
                _SUBMIT_CANDIDATES_TOOL,
            ],
            messages=[{"role": "user", "content": user_content}],
        )
        for block in message.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "submit_candidates":
                return [
                    c
                    for c in block.input.get("candidates") or []
                    if c.get("url") and c.get("title")
                ]
        return []
    except Exception:
        return []


def discover_by_author(
    author_name: str, known_urls: set[str], excluded_domains: set[str], max_results: int = 5
) -> list[dict]:
    exclusion = _EXCLUSION_HINT.format(
        known_urls=", ".join(sorted(known_urls)) or "(keine)",
        excluded_domains=", ".join(sorted(excluded_domains)) or "(keine)",
    )
    user_content = f'Autorin/Autor: "{author_name}"\n\n{exclusion}'
    candidates = _run_discovery(_AUTHOR_SYSTEM_PROMPT, user_content)[:max_results]
    for c in candidates:
        c["discovered_via"] = "author"
        c["author_hint"] = author_name
    return candidates


def discover_by_topic(
    topic_seed_text: str, known_urls: set[str], excluded_domains: set[str], max_results: int = 5
) -> list[dict]:
    exclusion = _EXCLUSION_HINT.format(
        known_urls=", ".join(sorted(known_urls)) or "(keine)",
        excluded_domains=", ".join(sorted(excluded_domains)) or "(keine)",
    )
    user_content = f"Bestehende Themen/Titel der Sammlung (Auszug):\n{topic_seed_text}\n\n{exclusion}"
    candidates = _run_discovery(_TOPIC_SYSTEM_PROMPT, user_content)[:max_results]
    for c in candidates:
        c["discovered_via"] = "topic"
        c["author_hint"] = None
    return candidates
