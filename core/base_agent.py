"""BaseAgent: one class for every agent (orchestrator + subagents).

Roles differ only by configuration: name, system prompt and allowed tools.
The tool-use loop itself is the class TP harness (harness.run), integrated
here: BaseAgent builds the input, wires the dispatcher and monitor into the
loop, and parses the final text into an AgentResult.
"""

import json
from typing import Literal

from pydantic import BaseModel, Field

import harness
from .dispatcher import LoopDetected, PermissionDenied, ToolDispatcher

MAX_ITERATIONS = 20


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


RESULT_INSTRUCTION = (
    "\n\nWhen you finish, reply with ONLY a JSON object (no markdown fences, no extra text) "
    "with these keys:\n"
    '- "status": "done" | "blocked" | "needs_more_info"\n'
    '- "summary": short description of what you did / found\n'
    '- "attempted": list of strings describing what you tried\n'
    '- "missing": string with what you need to continue, or null\n'
    '- "sources": list of strings, each prefixed by its origin: "repo:<path>", '
    '"memory:<key>", "rag:<source>#<chunk_id>", "web:<url>", "inference:<claim>"\n'
    '- "files_touched": list of absolute paths you created/modified/deleted\n'
    '- "proposed_memory_update": object with keys among "architecture" (markdown string), '
    '"conventions"/"dependencies"/"useful_commands" (objects to merge), "decision" (string), '
    '"bug" (string) — or null if nothing worth remembering.\n'
    "Never invent results: if you lack evidence, permissions or a clear request, return "
    'status "blocked" with "attempted" and "missing" filled in.'
)


class BaseAgent:
    def __init__(
        self,
        name: str,
        system_prompt: str,
        allowed_tools: list[str],
        dispatcher: ToolDispatcher,
        llm_client,
        model: str,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.allowed_tools = allowed_tools
        self.dispatcher = dispatcher
        self.llm_client = llm_client
        self.model = model

    def _build_tool_schemas(self) -> list[dict]:
        return [
            tool.schema()
            for tool_name, tool in self.dispatcher.tools.items()
            if tool_name in self.allowed_tools
        ]

    def _dispatch(self, tool_name: str, kwargs: dict) -> str:
        """Bridge between the harness loop and the ToolDispatcher: policy or
        loop violations come back to the LLM as tool results, not crashes."""
        try:
            return self.dispatcher.call(tool_name, kwargs, self.name)
        except (PermissionDenied, LoopDetected) as e:
            result = f"[BLOCKED] {type(e).__name__}: {e}"
            print(f"  [{self.name}] {result}")
            return result
        except Exception as e:
            return f"[ERROR] {type(e).__name__}: {e}"

    def run(self, task_input: dict) -> AgentResult:
        step_id = int(task_input.get("step_id", 0))
        messages: list[dict] = [
            {"role": "user", "content": json.dumps(task_input, ensure_ascii=False, default=str)}
        ]

        final_text = harness.run(
            client=self.llm_client,
            messages=messages,
            model=self.model,
            system=self.system_prompt + RESULT_INSTRUCTION,
            tools=self._build_tool_schemas(),
            dispatch=self._dispatch,
            on_llm_call=lambda msgs, response, usage: self.dispatcher.monitor.log_llm_call(
                self.name, self.model, msgs, response, usage
            ),
            label=self.name,
            max_iterations=MAX_ITERATIONS,
        )

        if final_text is None:
            return AgentResult(
                agent=self.name,
                step_id=step_id,
                status="blocked",
                summary=f"Stopped after {MAX_ITERATIONS} iterations without finishing.",
                attempted=[f"{MAX_ITERATIONS} tool-use iterations"],
                missing="A smaller or clearer instruction, or a different strategy.",
            )
        return self._parse_result(final_text, step_id)

    def _parse_result(self, content: str, step_id: int) -> AgentResult:
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        try:
            data = json.loads(text)
            allowed_keys = set(AgentResult.model_fields) - {"agent", "step_id"}
            data = {k: v for k, v in data.items() if k in allowed_keys}
            return AgentResult(agent=self.name, step_id=step_id, **data)
        except Exception:
            return AgentResult(
                agent=self.name,
                step_id=step_id,
                status="done",
                summary=content.strip() or "(empty response)",
            )
