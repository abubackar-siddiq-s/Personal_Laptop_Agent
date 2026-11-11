from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field

MemoryCategory = Literal[
    "user_preference",
    "personal_fact",
    "active_project",
    "project_decision",
    "conversation_summary",
    "frequently_used_workflow",
    "user_approved_instruction",
]

MemorySource = Literal[
    "user_explicit",
    "conversation_summary",
    "agent_inference",
    "workflow_learned",
]

class MemoryCreate(BaseModel):
    category: MemoryCategory
    content: str = Field(..., min_length=3, max_length=2000)
    key: Optional[str] = Field(None, max_length=100)
    source: MemorySource = "user_explicit"
    conversation_id: Optional[int] = None
    confidence: float = Field(1.0, ge=0.0, le=1.0)

class MemoryUpdate(BaseModel):
    content: Optional[str] = Field(None, min_length=3, max_length=2000)
    category: Optional[MemoryCategory] = None
    key: Optional[str] = Field(None, max_length=100)
    status: Optional[Literal["active", "archived"]] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

class MemoryOut(BaseModel):
    id: int
    category: str
    key: Optional[str] = None
    content: str
    source: str
    conversation_id: Optional[int] = None
    confidence: float
    status: str
    created_at: str
    updated_at: str
    last_accessed_at: str
    access_count: int

