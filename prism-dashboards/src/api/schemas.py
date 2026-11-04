from pydantic import BaseModel, Field
from typing import Optional


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str = Field(max_length=5000)


class ChatSessionCreate(BaseModel):
    user_id: Optional[str] = "default"


class ChatSessionOut(BaseModel):
    session_id: str
    created_at: str
    message_count: int
