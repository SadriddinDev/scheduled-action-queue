import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class TaskCreate(BaseModel):
    action: str = Field(..., min_length=1, max_length=255)
    payload: dict[str, Any] = Field(default_factory=dict)
    run_at: datetime
    idempotency_key: Optional[str] = Field(default=None, max_length=255)
    max_retries: int = Field(default=3, ge=0, le=10)


class TaskLogResponse(BaseModel):
    id: uuid.UUID
    task_id: uuid.UUID
    attempt: int
    status: str
    error: Optional[str]
    started_at: datetime
    finished_at: Optional[datetime]

    model_config = {"from_attributes": True}


class TaskResponse(BaseModel):
    id: uuid.UUID
    action: str
    payload: dict[str, Any]
    run_at: datetime
    status: str
    idempotency_key: Optional[str]
    max_retries: int
    retry_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskDetailResponse(TaskResponse):
    logs: list[TaskLogResponse] = []
