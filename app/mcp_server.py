"""MCP-Zugang zu BetaCodex Chat (Nutzerwunsch 2026-09-24, erweitert
2026-09-26): Endpunkt /mcp in der bestehenden App (Streamable HTTP,
zustandslos, JSON-Antworten). Werkzeuge: Frage beantworten (wie der
Konversationsmodus, nur kuratierte Quellen, mit Belegen) sowie Text erzeugen
und Text überarbeiten (Kreativ-Modus, Websuche abschaltbar, Default an).

Anmeldung: "Authorization: Bearer <Schlüssel>" oder "x-api-key: <Schlüssel>"
(app/mcp_keys.py, siehe _extract_key). Der
Schlüssel wird VOR dem MCP-SDK in _BearerKeyAuth geprüft, das Ergebnis liegt
serverseitig im ASGI-Scope - die Werkzeuge lesen nur diesen geprüften Wert,
nie den Header selbst.

Jeder Aufruf läuft durch dieselbe Kreativ-Logik wie die Oberfläche
(app/main.py: _creative_context/_creative_event_stream), landet mit Schlüssel
und Konto im Verbrauchsprotokoll (app/usage.py) und - anonym, Badge "MCP" -
im Fragen-Log."""
import json
import re

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from app import i18n, llm, mcp_keys, question_log, users

MCP_PATH = "/mcp"
_SCOPE_KEY = "bcx_mcp_key"

# DNS-Rebinding-Schutz des SDK: nur diese Host-Header werden angenommen.
ALLOWED_HOSTS = [
    "chat.betacodex.org",
    "companion.betahof.com",
    "127.0.0.1:*",
    "localhost:*",
    "testserver",
]

server = MCPServer(
    name="BetaCodex Chat",
    instructions=(
        "Beantwortet Fragen zum Beta-Kodex (Beta-Organisation, dezentrale Führung) ausschließlich aus "
        "kuratierten Quellen mit Belegen (ask_question) und schreibt bzw. überarbeitet Texte auf dieser "
        "Grundlage, optional ergänzt um eine Websuche (create_text, revise_text). "
        "Answers questions about the BetaCodex strictly from curated sources with citations (ask_question) "
        "and writes or revises texts on that basis, optionally with web search (create_text, revise_text)."
    ),
)

PUBLIC_BASE_URL = "https://chat.betacodex.org"
MAX_QUESTION_CHARS = 2000


def _format_result(document: str, sources: dict, lang: str) -> str:
    lines = [document.strip()]
    betacodex = sources.get("betacodex") or []
    web = sources.get("web") or []
    if betacodex or web:
        lines.append("\n---\n" + ("Quellen:" if lang == "de" else "Sources:"))
        for s in betacodex:
            authors = ", ".join(s.get("authors") or [])
            year = (s.get("date") or "")[:4]
            meta = ", ".join(x for x in (authors, year) if x)
            lines.append(f"- BetaCodex: {s['title']}" + (f" ({meta})" if meta else "") + (f" {s['url']}" if s.get("url") else ""))
        for s in web:
            lines.append(f"- Web: {s.get('title') or s['url']} {s['url']}")
    return "\n".join(lines)


def _run_creative(key: dict, instruction: str, document: str, lang: str, web_search: bool) -> str:
    from app import main  # zur Laufzeit - main bindet dieses Modul selbst ein

    lang = lang if lang in ("de", "en") else i18n.DEFAULT_LANG
    instruction = instruction.strip()
    if not instruction:
        raise ToolError(i18n.get_message("creative_instruction_empty", lang))
    if len(instruction) > main.CREATIVE_MAX_INSTRUCTION_CHARS:
        raise ToolError(i18n.get_message("creative_instruction_too_long", lang))
    if len(document) > main.CREATIVE_MAX_DOCUMENT_CHARS:
        raise ToolError(i18n.get_message("creative_document_too_long", lang))
    _check_limits(key, lang)

    llm_chunks, betacodex_sources = main._creative_context(instruction, document, lang)
    creative_stream = llm.stream_creative_response(instruction, document, llm_chunks, lang=lang, web_search=web_search)
    usage_meta = {"channel": "mcp", "web_search": web_search, "key_id": key["id"], "email": key["email"]}
    result_document, sources = "", {}
    for line in main._creative_event_stream(lang, betacodex_sources, creative_stream, usage_meta):
        event = json.loads(line)
        if event["type"] == "document":
            result_document = event["document"]
        elif event["type"] == "done":
            sources = event["sources"]
        elif event["type"] == "error":
            raise ToolError(event["message"])

    if not main.IS_DEV_ENVIRONMENT and not users.has_role(key["email"], users.SYSTEM_ADMIN):
        question_log.log_mcp(instruction, result_document)
    return _format_result(result_document, sources, lang)


def _check_limits(key: dict, lang: str) -> None:
    exceeded = mcp_keys.limit_exceeded(key)
    if exceeded:
        raise ToolError(
            i18n.get_message(
                f"mcp_limit_{exceeded}",
                lang,
                calls=key["daily_call_limit"],
                eur=f"{key['monthly_eur_limit']:.2f}",
            )
        )


def _format_answer(answer: str, chunk_refs: list[dict], lang: str) -> str:
    """Antwort mit ihren [n]-Belegen, darunter die zitierten Quellen in
    derselben Nummerierung. Relative Links (z. B. in der Keine-Antwort-
    Erklärung) werden absolut, damit sie außerhalb der Website funktionieren."""
    answer = answer.strip().replace("](/", f"]({PUBLIC_BASE_URL}/")
    cited = sorted({int(n) for n in re.findall(r"\[(\d+)\]", answer)})
    lines = [answer]
    refs = [(n, chunk_refs[n - 1]) for n in cited if 0 < n <= len(chunk_refs)]
    if refs:
        lines.append("\n---\n" + ("Quellen:" if lang == "de" else "Sources:"))
        for n, ref in refs:
            authors = ", ".join(ref.get("authors") or [])
            year = (ref.get("date") or "")[:4]
            meta = ", ".join(x for x in (authors, year) if x)
            url = None if ref.get("url_reachable") is False else ref.get("listen_url") or ref.get("url")
            kind = "Web" if ref.get("is_web_fallback") else "BetaCodex"
            lines.append(f"[{n}] {kind}: {ref['title']}" + (f" ({meta})" if meta else "") + (f" {url}" if url else ""))
    return "\n".join(lines)


def _run_ask(key: dict, question: str, lang: str) -> str:
    """Nutzerwunsch (2026-09-26): Frage-Antwort wie im Konversationsmodus -
    dieselbe Suche (main._ask_context) und derselbe Antwort-Stream wie der
    Chat, Kosten auf den Schlüssel (Kanal "mcp_ask", zählt gegen dessen
    Limits wie ein Kreativ-Aufruf)."""
    from app import main  # zur Laufzeit - main bindet dieses Modul selbst ein

    lang = lang if lang in ("de", "en") else i18n.DEFAULT_LANG
    question = question.strip()
    if not question:
        raise ToolError(i18n.get_message("mcp_question_empty", lang))
    if len(question) > MAX_QUESTION_CHARS:
        raise ToolError(i18n.get_message("mcp_question_too_long", lang))
    _check_limits(key, lang)

    try:
        llm_chunks, chunk_refs, author_bios, query_embedding = main._ask_context(
            question, [], lang, usage_email=key["email"]
        )
    except main.HTTPException as e:
        raise ToolError(e.detail) from e
    usage_meta = {"channel": "mcp_ask", "email": key["email"], "key_id": key["id"]}
    answer, sources = "", []
    for line in main._ask_event_stream(
        question,
        llm_chunks,
        lang,
        author_bios or None,
        chunk_refs,
        [ref.text for ref in chunk_refs],
        query_embedding,
        [],
        False,
        None,
        usage_meta,
    ):
        event = json.loads(line)
        if event["type"] == "answer":
            answer = event["answer"]
        elif event["type"] == "done":
            sources = event["sources"]
        elif event["type"] == "error":
            raise ToolError(event["message"])

    if not main.IS_DEV_ENVIRONMENT and not users.has_role(key["email"], users.SYSTEM_ADMIN):
        question_log.log_mcp(question, answer)
    return _format_answer(answer, sources, lang)


def _current_key(ctx: Context) -> dict:
    key = ctx.request_context.request.scope.get(_SCOPE_KEY)
    if key is None:  # nur erreichbar, wenn _BearerKeyAuth umgangen würde
        raise ToolError("Nicht angemeldet / not authenticated")
    return key


@server.tool(
    name="ask_question",
    description=(
        "Frage zum Beta-Kodex beantworten - wie der Konversationsmodus von BetaCodex Chat: ausschließlich "
        "aus kuratierten Quellen, mit Belegen [n] und Quellenliste, ohne Websuche und ohne Erfindungen. "
        "Answer a question about the BetaCodex like BetaCodex Chat's conversation mode: strictly from "
        "curated sources, with citations [n] and a source list. language: 'de' oder/or 'en'."
    ),
)
async def ask_question(question: str, ctx: Context, language: str = "de") -> str:
    key = _current_key(ctx)
    return await anyio.to_thread.run_sync(_run_ask, key, question, language)


@server.tool(
    name="create_text",
    description=(
        "Neuen Text im BetaCodex-Kreativ-Modus erzeugen (Markdown, mit Quellenliste). "
        "Create a new text (Markdown with source list). "
        "language: 'de' oder/or 'en'. web_search: Websuche ergänzend nutzen / use web search (default true)."
    ),
)
async def create_text(instruction: str, ctx: Context, language: str = "de", web_search: bool = True) -> str:
    key = _current_key(ctx)
    return await anyio.to_thread.run_sync(_run_creative, key, instruction, "", language, web_search)


@server.tool(
    name="revise_text",
    description=(
        "Bestehenden Text nach einer Anweisung komplett überarbeiten (z.B. kürzen, Zielgruppe ändern). "
        "Revise an existing text according to an instruction. "
        "language: 'de' oder/or 'en'. web_search: default true."
    ),
)
async def revise_text(
    document: str, instruction: str, ctx: Context, language: str = "de", web_search: bool = True
) -> str:
    key = _current_key(ctx)
    return await anyio.to_thread.run_sync(_run_creative, key, instruction, document, language, web_search)


_mcp_http_app = server.streamable_http_app(
    streamable_http_path=MCP_PATH,
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=["https://chat.betacodex.org", "https://companion.betahof.com"],
    ),
)
session_manager = server.session_manager


def _extract_key(scope) -> str | None:
    """Schlüssel aus "Authorization: Bearer <key>" (Claude Code u. a.),
    "x-api-key: <key>" oder "Authorization: <key>" ohne Schema - die
    Claude-Konnektoren (claude.ai) senden einen Request-Header exakt wie
    eingegeben und bieten x-api-key als Standard-Header an."""
    headers = dict(scope.get("headers") or [])
    authorization = headers.get(b"authorization", b"").decode("latin-1").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    if authorization:
        return authorization
    return headers.get(b"x-api-key", b"").decode("latin-1").strip() or None


class _BearerKeyAuth:
    """ASGI-Vorschaltung: ohne gültigen Schlüssel 401, sonst Schlüssel-
    Datensatz in den Scope und weiter ans MCP-SDK."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        key = await anyio.to_thread.run_sync(mcp_keys.authenticate, _extract_key(scope))
        if key is None:
            body = json.dumps({"error": "invalid_token", "error_description": "Missing, invalid or revoked MCP key."}).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b'Bearer realm="BetaCodex MCP"'),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        scope[_SCOPE_KEY] = key
        await self.app(scope, receive, send)


asgi_app = _BearerKeyAuth(_mcp_http_app)
