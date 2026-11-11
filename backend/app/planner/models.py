from __future__ import annotations
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

TaskStatus = Literal[
    "draft",
    "planned",
    "awaiting_approval",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
]

StepStatus = Literal[
    "pending",
    "awaiting_approval",
    "running",
    "completed",
    "failed",
    "skipped",
    "cancelled",
]

RiskLevel = Literal["low", "medium", "high", "consequential"]

class StepDefinition(BaseModel):
    step_index: int
    title: str
    description: str = ""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[int] = Field(default_factory=list)
    risk: RiskLevel = "low"
    requires_approval: bool = False

class TaskPlanCreate(BaseModel):
    user_request: str
    objective: Optional[str] = None
    conversation_id: Optional[int] = None
    auto_execute: bool = False

class TaskPlanUpdate(BaseModel):
    title: Optional[str] = None
    objective: Optional[str] = None
    description: Optional[str] = None
    steps: Optional[List[Dict[str, Any]]] = None

class TaskStepOut(BaseModel):
    id: str
    task_id: str
    step_index: int
    title: str
    description: Optional[str] = ""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[int] = Field(default_factory=list)
    risk: str = "low"
    requires_approval: bool = False
    status: str = "pending"
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0
    checkpoint_data: Optional[str] = None

class TaskOut(BaseModel):
    id: str
    title: str
    user_request: str
    objective: str
    description: Optional[str] = ""
    risk_level: str = "low"
    status: str = "draft"
    approval_required: bool = False
    expected_output: Optional[str] = ""
    completion_criteria: Optional[str] = ""
    total_steps: int = 0
    completed_steps: int = 0
    result: Optional[str] = None
    error: Optional[str] = None
    conversation_id: Optional[int] = None
    created_at: str
    updated_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    steps: List[TaskStepOut] = Field(default_factory=list)

