from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DatasetOut(BaseModel):
    id: str
    name: str
    status: str
    error: str | None = None
    file_size_bytes: int
    created_at: datetime
    validation_report: dict | None = None


class AnalyzeRequest(BaseModel):
    focus: str | None = Field(None, max_length=500, description="Optional area to emphasise.")


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class QueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=12)


class QueryResponse(BaseModel):
    answer: str
    evidence: list[dict]
    tools_used: list[str]
    mode: str
    flags: list[str] = []
    prompt_version: str
    run_id: str | None = None
