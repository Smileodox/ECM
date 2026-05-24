from pydantic import BaseModel


class ChatMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []
    program_name: str | None = None


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


class IngestResponse(BaseModel):
    documents_processed: int
    chunks_created: int
    chunks_indexed: int
