# Idee 313ad93d: aus app/main.py ausgelagert (Verhalten unverändert).

import logging
import re
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Header, Request
from fastapi.responses import FileResponse, Response
from urllib.parse import quote
from app import i18n, llm, mcp_keys, usage, users
from app.models import DevVergleichIn, McpKeyCreateIn, McpKeyCreatedOut, McpKeyLimitsIn, McpKeyOut

from app import main
from app.retrieval import NO_ANSWER_PHRASES, _drop_no_answer_lead, _trim_history

router = APIRouter()


MCP_MAX_ACTIVE_KEYS_PER_USER = 10
_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


def _usage_month(month: str | None, x_lang: str) -> str:
    if month is None:
        return datetime.now(timezone.utc).strftime("%Y-%m")
    if not _MONTH_RE.match(month):
        raise HTTPException(400, i18n.get_message("mcp_limits_invalid", x_lang))
    return month


@router.get("/api/mcp/keys", response_model=list[McpKeyOut])
def list_own_mcp_keys(current_user: str = Depends(main.require_role(users.MCP_NUTZER))):
    return [mcp_keys.with_stats(k) for k in mcp_keys.list_keys(current_user)]


@router.post("/api/mcp/keys", response_model=McpKeyCreatedOut, status_code=201)
def create_mcp_key(
    payload: McpKeyCreateIn,
    current_user: str = Depends(main.require_role(users.MCP_NUTZER)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    active = [k for k in mcp_keys.list_keys(current_user) if not k["revoked_at"]]
    if len(active) >= MCP_MAX_ACTIVE_KEYS_PER_USER:
        raise HTTPException(400, i18n.get_message("mcp_limits_invalid", x_lang))
    key, secret = mcp_keys.create_key(current_user, payload.label)
    return {"key": mcp_keys.with_stats(key), "secret": secret}


@router.delete("/api/mcp/keys/{key_id}", response_model=McpKeyOut)
def revoke_mcp_key(key_id: str, request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    # Widerrufen dürfen die Inhaber:in selbst und User-Admins.
    email = main._get_current_user_email(request)
    key = mcp_keys.get_key(key_id)
    if key is None:
        raise HTTPException(404, i18n.get_message("mcp_key_not_found", x_lang))
    is_owner = email is not None and key["email"] == email and users.has_role(email, users.MCP_NUTZER)
    if not is_owner and not users.has_role(email, users.USER_ADMIN):
        raise HTTPException(403, i18n.get_message("role_required", x_lang, role=users.USER_ADMIN, user=email or "anon"))
    return mcp_keys.with_stats(mcp_keys.revoke_key(key_id))


@router.get("/api/mcp/admin/keys", response_model=list[McpKeyOut])
def list_all_mcp_keys(
    month: str | None = None,
    _user: str = Depends(main.require_role(users.USER_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    # Kosten je Schlüssel im gewählten Monat (wie die Übersichtstabelle).
    month = _usage_month(month, x_lang)
    return [mcp_keys.with_stats(k, month) for k in mcp_keys.list_keys()]


@router.put("/api/mcp/keys/{key_id}/limits", response_model=McpKeyOut)
def set_mcp_key_limits(
    key_id: str,
    payload: McpKeyLimitsIn,
    _user: str = Depends(main.require_role(users.USER_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    if payload.daily_call_limit < 0 or payload.monthly_eur_limit < 0:
        raise HTTPException(400, i18n.get_message("mcp_limits_invalid", x_lang))
    key = mcp_keys.set_limits(key_id, payload.daily_call_limit, payload.monthly_eur_limit)
    if key is None:
        raise HTTPException(404, i18n.get_message("mcp_key_not_found", x_lang))
    return mcp_keys.with_stats(key)


# Nutzerwunsch (2026-09-26): eigene Kostenübersicht-Seite (static/costs.html)
# statt Kostenblock auf der MCP-Seite - System-Admins sehen alle Kosten über
# alle Konten, alle anderen Angemeldeten nur ihre eigenen.
def _csv_response(content: str, filename: str) -> Response:
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _require_login(request: Request, x_lang: str) -> str:
    email = main._get_current_user_email(request)
    if not email or not users.get_user(email):
        raise HTTPException(401, i18n.get_message("login_required", x_lang))
    return email


@router.get("/api/costs")
def costs_summary(
    month: str | None = None,
    _user: str = Depends(main.require_role(users.SYSTEM_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    return usage.monthly_summary(_usage_month(month, x_lang))


@router.get("/api/costs.csv")
def costs_csv(
    month: str | None = None,
    _user: str = Depends(main.require_role(users.SYSTEM_ADMIN)),
    x_lang: str = Header(default=i18n.DEFAULT_LANG),
):
    month = _usage_month(month, x_lang)
    return _csv_response(usage.export_csv(month), f"betacodex-kosten-{month}.csv")


HISTORY_MONTHS = 12


@router.get("/api/costs/history")
def costs_history(_user: str = Depends(main.require_role(users.SYSTEM_ADMIN))):
    return usage.monthly_history(usage.last_months(HISTORY_MONTHS))


@router.get("/api/costs/mine/history")
def my_costs_history(request: Request, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    email = _require_login(request, x_lang)
    return usage.monthly_history(usage.last_months(HISTORY_MONTHS), email=email)


@router.get("/api/costs/mine")
def my_costs_summary(request: Request, month: str | None = None, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    email = _require_login(request, x_lang)
    return usage.monthly_summary(_usage_month(month, x_lang), email=email)


@router.get("/api/costs/mine.csv")
def my_costs_csv(request: Request, month: str | None = None, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    email = _require_login(request, x_lang)
    month = _usage_month(month, x_lang)
    return _csv_response(usage.export_csv(month, email=email), f"betacodex-meine-kosten-{month}.csv")


# Idee af02ecb1: Dev-Vergleichsseite (Antwort ohne/mit Beraterstimme, optional
# Sonnet). Bewusst NICHT unter static/: der Static-Mount (html=True) würde sie
# sonst auch in Produktion ausliefern. Eigene Routen, alle 404 ohne Dev.
DEV_VERGLEICH_DIR = main.BASE_DIR / "app" / "dev_vergleich"
DEV_VERGLEICH_FILES = {
    "/dev/vergleich": ("vergleich.html", "text/html; charset=utf-8"),
    "/dev/vergleich.js": ("vergleich.js", "text/javascript; charset=utf-8"),
    "/dev/vergleich.css": ("vergleich.css", "text/css; charset=utf-8"),
}
# Variante -> (Modell, max_tokens, mit Stimme?). Sonnet: 4096 wegen Thinking.
DEV_VERGLEICH_VARIANTS = {
    "basis": (llm.MODEL_NAME, 1536, False),
    "stimme": (llm.MODEL_NAME, 1536, True),
    "sonnet": ("claude-sonnet-5", 4096, True),
}


def _dev_vergleich_file(name: str, media_type: str) -> FileResponse:
    if not main.IS_DEV_ENVIRONMENT:
        raise HTTPException(404, "Not Found")
    return FileResponse(DEV_VERGLEICH_DIR / name, media_type=media_type, headers={"Cache-Control": "no-cache"})


for _path, (_name, _media) in DEV_VERGLEICH_FILES.items():
    router.add_api_route(
        _path, lambda n=_name, m=_media: _dev_vergleich_file(n, m), methods=["GET"], include_in_schema=False
    )


def _require_dev():
    # Als Abhängigkeit, damit auch ein ungültiger Body ohne Dev 404 gibt, nicht 422.
    if not main.IS_DEV_ENVIRONMENT:
        raise HTTPException(404, "Not Found")


def _dev_vergleich_column(variant, question, chunks, bios, lang, history):
    model, max_tokens, with_voice = DEV_VERGLEICH_VARIANTS[variant]
    info = {}
    try:
        # Datei pro Anfrage frisch lesen, damit Änderungen sofort wirken.
        system = llm.build_chat_system(lang, llm.load_stimme()) if with_voice else llm._BASE_PROMPTS[lang]
        raw = "".join(
            llm.stream_answer_question(
                question, chunks, lang=lang, author_bios=bios or None, history=history,
                usage={"channel": "vergleich"}, system_prompt=system, model=model,
                max_tokens=max_tokens, info=info,
            )
        )
    except Exception as exc:
        logging.getLogger("app.main").exception("Vergleich (%s) fehlgeschlagen", variant)
        error = (
            f"Skill-Datei fehlt: {llm.STIMME_FILE.name}" if isinstance(exc, FileNotFoundError) and with_voice
            else type(exc).__name__
        )
        return {"answer": "", "words": 0, "quote_count": 0, "quotes_expected": True, "stop_reason": None, "error": error}
    # Nachbearbeitung wie in _ask_event_stream (Kreativ-Link, Absage-Einstieg).
    link = f"/creative.html?instruction={quote(question)}"
    answer, quotes = llm.parse_answer_and_quotes(raw)
    answer, _ = _drop_no_answer_lead(answer, final=True)
    answer = answer.replace(llm.CREATIVE_LINK_PLACEHOLDER, link)
    quotes_expected = not (
        llm.CREATIVE_LINK_PLACEHOLDER in raw
        or any(raw.lstrip().startswith(p) and not raw.lstrip()[len(p):].strip() for p in NO_ANSWER_PHRASES.values())
    )
    return {
        "answer": answer, "words": len(answer.split()), "quote_count": sum(len(v) for v in quotes.values()),
        "quotes_expected": quotes_expected, "stop_reason": info.get("stop_reason"), "error": None,
    }


@router.post("/api/dev/vergleich", include_in_schema=False, dependencies=[Depends(_require_dev)])
def dev_vergleich(body: DevVergleichIn, x_lang: str = Header(default=i18n.DEFAULT_LANG)):
    import concurrent.futures

    lang = x_lang if x_lang in ("de", "en") else i18n.DEFAULT_LANG
    histories = {k: _trim_history([t.model_dump() for t in v]) for k, v in body.histories.items()}
    chunks, _refs, bios, _emb = main._ask_context(
        body.question, histories.get("basis", []), lang, rewrite_channel="vergleich"
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(body.variants)) as pool:
        futures = {
            v: pool.submit(_dev_vergleich_column, v, body.question, chunks, bios, lang, histories.get(v, []))
            for v in body.variants
        }
        columns = {v: f.result() for v, f in futures.items()}
    return {"sources": [c["title"] for c in chunks], "columns": columns}
