from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class Citation(BaseModel):
    index: int
    section_id: str
    section_title: str
    absatz: str | None = None
    page_number: int
    doc_name: str
    source_url: str = ""
    content: str


class IngestResponse(BaseModel):
    documents_processed: int
    chunks_created: int
    chunks_indexed: int
