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
    restricted: bool = False
    summary: Optional[str] = None
    key_terms: Optional[list[str]] = None


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


class QuestionIn(BaseModel):
    question: str
    top_k: int = 5
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


class AnswerOut(BaseModel):
    answer: str
    sources: list[ChunkRef]


class RequestLinkIn(BaseModel):
    email: str


class InviteIn(BaseModel):
    email: str
    role: str


class WhoAmIOut(BaseModel):
    email: Optional[str] = None
    roles: list[str] = []


class AdminUserOut(BaseModel):
    email: str
    roles: list[str]
    status: str
    invited_at: Optional[str] = None
    last_login_at: Optional[str] = None


class MessageOut(BaseModel):
    detail: str


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


class ExtractedUpload(ExtractedSource):
    upload_id: Optional[str] = None


class UrlCheckOut(BaseModel):
    has_url: bool
    reachable: Optional[bool] = None
    status_code: Optional[int] = None


class SummaryOut(BaseModel):
    summary: str
    key_terms: list[str]


class VersionOut(BaseModel):
    version: str
