"""HTTP request / response schemas (Pydantic v2)."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class TripRequest(BaseModel):
    conversation_name: Optional[str] = Field(
        default=None, description="Acts as thread_id; auto-generated when omitted."
    )
    bot_user_input: Optional[str] = Field(default=None, description="Free-form user constraints.")
    destination: str
    departure: Optional[str] = None
    days_num: int = Field(ge=1, le=30)
    people_num: int = Field(ge=1, le=20)
    start_date: Optional[str] = None
    travel_theme: Optional[str] = None


class TripResponse(BaseModel):
    trip_id: str
    thread_id: str
    status: str
    version: int


class RefineRequest(BaseModel):
    instruction: str


class VersionItem(BaseModel):
    version: int
    created_at: str
    pdf_path: Optional[str] = None
    md_path: Optional[str] = None


class VersionsResponse(BaseModel):
    versions: List[VersionItem]


class FileItem(BaseModel):
    name: str
    path: str
    url: str
    size: Optional[int] = None
    mtime: Optional[float] = None


class FilesResponse(BaseModel):
    files: List[FileItem]


class MessageItem(BaseModel):
    """Slim, persistence-friendly view of a chat message.

    Sourced from the LangGraph checkpoint (when the process is still alive)
    plus session-dir artefacts (which survive restarts). It deliberately
    omits transient process traces such as tool/node logs and partial
    thoughts — those are kept in-memory only.
    """

    id: str
    role: str  # "user" | "ai"
    content: str
    version: Optional[int] = None
    files: List[FileItem] = Field(default_factory=list)
    timestamp: Optional[float] = None


class MessagesResponse(BaseModel):
    thread_id: str
    messages: List[MessageItem]
    expired: bool
