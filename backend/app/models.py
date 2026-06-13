from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=10_000)


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    program_name: str | None = None
    model_name: str | None = None


class Citation(BaseModel):
    index: int
    section_id: str
    section_title: str
    absatz: str | None = None
    page_number: int
    doc_name: str
    doc_filename: str = ""
    program_name: str = ""
    source_url: str = ""
    content: str
    doc_type: str = ""
    reranker_score: float = 0.0
    chunk_index: int | None = None
    amendment_context: str = ""


class IngestResponse(BaseModel):
    documents_processed: int
    chunks_created: int
    chunks_indexed: int


class FeedbackRequest(BaseModel):
    message_id: str = Field(default="", max_length=100)
    rating: Literal["up", "down"]
    comment: str = Field(default="", max_length=2000)
    query: str = Field(default="", max_length=2000)
    response: str = Field(default="", max_length=10_000)
