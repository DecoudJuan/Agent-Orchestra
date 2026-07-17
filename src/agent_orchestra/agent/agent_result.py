import json
from typing import Literal
from pydantic import BaseModel, Field


class AgentResult(BaseModel):
    agent: str
    step_id: int
    status: Literal["done", "blocked", "needs_more_info"]
    summary: str
    attempted: list[str] = Field(default_factory=list)
    missing: str | None = None
    sources: list[str] = Field(default_factory=list)
    files_touched: list[str] = Field(default_factory=list)
    proposed_memory_update: dict | None = None