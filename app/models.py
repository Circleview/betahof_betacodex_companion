from typing import Optional

from pydantic import BaseModel


class SourceIn(BaseModel):
    title: str
    authors: list[str] = []
    date: Optional[str] = None
    url: Optional[str] = None
    listen_url: Optional[str] = None
    text: str
    pdf_upload_id: Optional[str] = None
    audio_upload_id: Optional[str] = None
    restricted: bool = False
    summary: Optional[str] = None
    key_terms: Optional[list[str]] = None
    relevance_score: Optional[int] = None


class SourceOut(BaseModel):
    id: str
    title: str
    authors: list[str] = []
    date: Optional[str] = None
    url: Optional[str] = None
    listen_url: Optional[str] = None
    imported_at: str
    chunk_count: int
    text: str
    restricted: bool = False
    summary: str = ""
    key_terms: list[str] = []
    has_pdf: bool = False
    has_audio: bool = False
    relevance_score: Optional[int] = None
    processing_status: Optional[str] = None
    processing_step: Optional[str] = None
    processing_error: Optional[str] = None
    # Backlog (2026-08-02): Ergebnis der wöchentlichen Hintergrund-
    # Link-Prüfung (app/main.py: _run_url_health_check_once), direkt im
    # sources.json-Eintrag persistiert statt live pro Seitenaufruf
    # berechnet. None = noch nie geprüft (z.B. ganz neue Quelle vor dem
    # ersten Lauf) - bewusst NICHT wie "kaputt" behandeln.
    url_reachable: Optional[bool] = None
    url_reason_code: Optional[str] = None
    url_status_code: Optional[int] = None
    url_checked_at: Optional[str] = None


class BrokenLinksCountOut(BaseModel):
    count: int


class ImportJobOut(BaseModel):
    id: str
    title: str
    processing_status: str
    processing_step: Optional[str] = None
    processing_error: Optional[str] = None


class HistoryTurnIn(BaseModel):
    question: str
    answer: str


class QuestionIn(BaseModel):
    question: str
    top_k: int = 5
    turnstile_token: str = ""
    # Backlog #97: vom Frontend gesetzt (conversationHistory.length === 0
    # zum Zeitpunkt des Absendens) - der Server kennt sonst keine
    # Konversation, jede Anfrage steht für sich (siehe app/main.py ask()).
    is_first_message: bool = False
    # Backlog (2026-08-03): vorherige Turns der laufenden Konversation, damit
    # das Modell nicht bei jeder Folgefrage bei null anfängt (siehe
    # app/main.py ask() - wird dort defensiv auf die letzten paar Turns
    # gekappt, unabhängig davon, wie viele das Frontend mitschickt).
    history: list[HistoryTurnIn] = []


class QuestionLogEntryOut(BaseModel):
    text: str
    timestamp: str


class FeedbackIn(BaseModel):
    message: str
    email: str = ""
    turnstile_token: str = ""


class ChunkRef(BaseModel):
    chunk_id: str
    source_id: str
    title: str
    authors: list[str] = []
    date: Optional[str] = None
    url: Optional[str] = None
    listen_url: Optional[str] = None
    position: int
    text: str
    summary: Optional[str] = None
    highlighted_texts: list[str] = []
    # Backlog: LLM/Internet-Fallback bei dünner Quellenlage - kennzeichnet
    # Chunks aus der separaten Web-Fallback-Collection (statt aus den
    # kuratierten Quellen) für die dezente Kennzeichnung im Frontend
    # (question.js: buildSourceInfo).
    is_web_fallback: bool = False
    # Nutzerwunsch: Quellen-Pfleger:innen/System-Admins sollen eine
    # erkennbar unpassende Web-Fallback-Quelle direkt aus der
    # Konversationsansicht heraus ausschließen können (siehe question.js:
    # appendExcludeWebPageButton) - dafür wird hier die zugehörige
    # web_allowlist-Eintrags-ID mitgegeben (nur bei Web-Fallback-Chunks
    # gesetzt, sonst None).
    allowlist_entry_id: Optional[str] = None


class RequestLinkIn(BaseModel):
    email: str


class EarlyAccessIn(BaseModel):
    password: str


class InviteIn(BaseModel):
    email: str
    role: str
    name: Optional[str] = None


class UpdateUserNameIn(BaseModel):
    name: str


class WhoAmIOut(BaseModel):
    email: Optional[str] = None
    roles: list[str] = []
    name: Optional[str] = None


class AdminUserOut(BaseModel):
    email: str
    name: Optional[str] = None
    roles: list[str]
    status: str
    invited_at: Optional[str] = None
    last_login_at: Optional[str] = None


class AuditLogEntryOut(BaseModel):
    id: str
    timestamp: str
    actor_email: str
    actor_name: Optional[str] = None
    action: str
    target_label: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    changes: Optional[dict] = None
    revertible: bool = False
    reverted_at: Optional[str] = None


class MessageOut(BaseModel):
    detail: str


class SpeechIn(BaseModel):
    text: str
    rate: float = 1.0


class SocialLink(BaseModel):
    platform: str
    url: str


class AuthorOut(BaseModel):
    name: str
    source_count: int
    source_ids: list[str]
    bio: str = ""
    bio_ai_generated: bool = False
    photo_url: str = ""
    website: str = ""
    social_links: list[SocialLink] = []


class AuthorProfileIn(BaseModel):
    bio: Optional[str] = None
    photo_url: Optional[str] = None
    website: Optional[str] = None
    social_links: Optional[list[SocialLink]] = None


class BioOut(BaseModel):
    bio: str


class AuthorBioPreviewIn(BaseModel):
    name: str
    text: str


class RenameAuthorIn(BaseModel):
    new_name: str


class TermOut(BaseModel):
    term: str
    source_count: int
    source_ids: list[str]


class UrlIn(BaseModel):
    url: str


class ExtractedSource(BaseModel):
    title: str
    authors: list[str] = []
    date: str
    text: str
    extracted: bool
    is_audio: bool = False
    is_pdf: bool = False


class ExtractedUpload(ExtractedSource):
    upload_id: Optional[str] = None


class UrlCheckOut(BaseModel):
    has_url: bool
    reachable: Optional[bool] = None
    status_code: Optional[int] = None
    reason_code: Optional[str] = None


class SummaryOut(BaseModel):
    summary: str
    key_terms: list[str]


class KeyTermsPreviewIn(BaseModel):
    text: str


class KeyTermsOut(BaseModel):
    key_terms: list[str]


class VersionOut(BaseModel):
    version: str
    embed_enabled: bool = False


class TurnstileConfigOut(BaseModel):
    site_key: str


class WebAllowlistEntryIn(BaseModel):
    url_prefix: str
    label: str
    reason: str
    max_pages: int = 50


class WebAllowlistEntryOut(BaseModel):
    id: str
    url_prefix: str
    label: str
    reason: str
    added_by: str
    added_at: str
    reviewed_at: Optional[str] = None
    max_pages: int
    page_count: int = 0
    needs_review: bool = False
    indexing_status: Optional[str] = None
    selection_mode: str = "negativ"


class WebIndexPageOut(BaseModel):
    id: str
    allowlist_entry_id: str
    url: str
    title: str
    date: Optional[str] = None
    indexed_at: str
    chunk_count: int
    excluded: bool = False


class WebCandidateOut(BaseModel):
    id: str
    allowlist_entry_id: str
    url: str
    title: str
    snippet: str
    relevance_score: float
    status: str


class SourceSuggestionOut(BaseModel):
    id: str
    url: str
    title: str
    reason: str
    discovered_via: str
    author_hint: Optional[str] = None
    status: str
    discovered_at: str
