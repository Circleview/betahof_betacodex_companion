from typing import Optional

from pydantic import BaseModel


class SourceIn(BaseModel):
    title: str
    author: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None
    text: str


class SourceOut(BaseModel):
    id: str
    title: str
    author: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None
    imported_at: str
    chunk_count: int


class QuestionIn(BaseModel):
    question: str
    top_k: int = 5


class ChunkRef(BaseModel):
    chunk_id: str
    source_id: str
    title: str
    author: Optional[str] = None
    date: Optional[str] = None
    url: Optional[str] = None
    position: int
    text: str


class AnswerOut(BaseModel):
    answer: str
    sources: list[ChunkRef]
