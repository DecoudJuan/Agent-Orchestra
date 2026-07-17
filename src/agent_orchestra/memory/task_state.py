import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.agent_orchestra.agent import AgentResult


class Step(BaseModel):
    id: int
    agent: str
    instruction: str
    status: Literal["pending", "in_progress", "done", "blocked"] = "pending"
    summary: str | None = None
    sources: list[str] = Field(default_factory=list)


class TaskState(BaseModel):
    task_id: str
    original_request: str
    steps: list[Step] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    observations: list[str] = Field(default_factory=list)

    def new_step(self, agent: str, instruction: str) -> Step:
        step = Step(id=len(self.steps) + 1, agent=agent, instruction=instruction, status="in_progress")
        self.steps.append(step)
        return step

    def apply(self, result: AgentResult) -> None:
        step = next((s for s in self.steps if s.id == result.step_id), None)
        if step is None:
            return
        step.status = "done" if result.status == "done" else "blocked"
        step.summary = result.summary
        step.sources = result.sources
        for path in result.files_touched:
            if path not in self.files_modified:
                self.files_modified.append(path)
        if result.status in ("blocked", "needs_more_info"):
            self.observations.append(
                f"[step {result.step_id}] {result.agent} returned {result.status}. "
                f"Attempted: {result.attempted}. Missing: {result.missing}"
            )

    def get_summaries_for(self, agent_names: list[str]) -> list[dict]:
        return [
            {
                "step_id": s.id,
                "agent": s.agent,
                "instruction": s.instruction,
                "status": s.status,
                "summary": s.summary,
                "sources": s.sources,
            }
            for s in self.steps
            if s.agent in agent_names and s.summary
        ]

    def save(self, path: str) -> None:
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(self.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8")
