import json
from typing import Literal

from pydantic import BaseModel, Field

from src.agent_orchestra.agent import loop
from src.agent_orchestra.tools.dispatcher import LoopDetected, PermissionDenied, ToolDispatcher
from src.agent_orchestra.observability.tracing import observe
from src.agent_orchestra.tools.tool_type import ToolType
from src.agent_orchestra.agent.agent_result import AgentResult

MAX_ITERATIONS = 20

_SUPERVISED_TYPES = {ToolType.WRITE, ToolType.EXECUTE}

PLAN_PROMPT = (
    "\n\nBefore executing any tool, produce a numbered plan listing every step you "
    "intend to take (e.g. 1. read file X  2. write file Y  3. run tests). "
    "Output ONLY the plan — no tool calls — and wait. "
    "The user will approve, modify, or reject it."
)

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


class Agent:
    def __init__(
        self,
        name: str,
        system_prompt: str,
        allowed_tools: list[str],
        dispatcher: ToolDispatcher,
        llm_client,
        model: str,
        modes=None,
    ):
        self.name = name
        self.system_prompt = system_prompt
        self.allowed_tools = allowed_tools
        self.dispatcher = dispatcher
        self.llm_client = llm_client
        self.model = model
        self.modes = modes 

    def _build_tool_schemas(self) -> list[dict]:
        return [
            tool.schema()
            for tool_name, tool in self.dispatcher.tools.items()
            if tool_name in self.allowed_tools
        ]

    def _dispatch(self, tool_name: str, kwargs: dict) -> str:
        try:
            return self.dispatcher.call(tool_name, kwargs, self.name)
        except (PermissionDenied, LoopDetected) as e:
            result = f"[BLOCKED] {type(e).__name__}: {e}"
            print(f"  [{self.name}] {result}")
            return result
        except Exception as e:
            return f"[ERROR] {type(e).__name__}: {e}"

    def _build_plan_system(self) -> str:
        return self.system_prompt + PLAN_PROMPT

    def _request_plan(self, task_input: dict) -> str | None:
        messages: list[dict] = [
            {"role": "user", "content": json.dumps(task_input, ensure_ascii=False, default=str)}
        ]
        print(f"\n  [{self.name}] Plan mode is ON — generating plan...\n")

        plan_text = loop.run(
            client=self.llm_client,
            messages=messages,
            model=self.model,
            system=self._build_plan_system(),
            tools=[],
            dispatch=self._dispatch,
            label=f"{self.name}:plan",
            max_iterations=3,
        )

        if not plan_text:
            print(f"  [{self.name}] Could not generate a plan.")
            return None

        print("\n" + "─" * 60)
        print(f"[{self.name}] Proposed plan:\n")
        print(plan_text)
        print("─" * 60)

        while True:
            answer = input("\nApprove plan? [y]es / [n]o (abort) / [m]odify: ").strip().lower()
            if answer in ("y", "yes"):
                return plan_text
            elif answer in ("n", "no"):
                print(f"  [{self.name}] Plan rejected. Task aborted.")
                return None
            elif answer in ("m", "modify"):
                print("Enter your modifications (press Enter twice when done):")
                lines = []
                while True:
                    line = input()
                    if line == "" and lines and lines[-1] == "":
                        break
                    lines.append(line)
                modification = "\n".join(lines).strip()
                messages.append({"role": "assistant", "content": plan_text})
                messages.append({"role": "user", "content": f"Revise the plan based on my feedback:\n{modification}"})
                print(f"\n  [{self.name}] Revising plan...\n")
                revised = loop.run(
                    client=self.llm_client,
                    messages=messages,
                    model=self.model,
                    system=self._build_plan_system(),
                    tools=[],
                    dispatch=self._dispatch,
                    label=f"{self.name}:plan-revision",
                    max_iterations=3,
                )
                if not revised:
                    print(f"  [{self.name}] Could not revise the plan. Keeping original.")
                else:
                    plan_text = revised
                print("\n" + "─" * 60)
                print(f"[{self.name}] Revised plan:\n")
                print(plan_text)
                print("─" * 60)
            else:
                print("Please enter y, n, or m.")

    def _make_supervision_confirm(self):

        def confirm(tool_name: str, params: dict) -> bool:
            tool = self.dispatcher.tools.get(tool_name)
            if tool is None:
                return True 
            if tool.type not in _SUPERVISED_TYPES:
                return True

            preview = ", ".join(f"{k}={str(v)[:80]!r}" for k, v in params.items())
            print(f"\n  [SUPERVISION] {tool_name}({preview})")
            while True:
                answer = input("  Allow this action? [y]es / [n]o: ").strip().lower()
                if answer in ("y", "yes"):
                    return True
                elif answer in ("n", "no"):
                    print("  Action denied.")
                    return False
                else:
                    print("  Please enter y or n.")

        return confirm

    @observe(name="agent-run", as_type="agent", capture_input=True)
    def run(self, task_input: dict) -> AgentResult:
        step_id = int(task_input.get("step_id", 0))

        if self.modes and self.modes.plan_mode and self.name == "orchestrator":
            approved_plan = self._request_plan(task_input)
            if approved_plan is None:
                return AgentResult(
                    agent=self.name,
                    step_id=step_id,
                    status="blocked",
                    summary="Task aborted: plan was rejected by the user.",
                    attempted=["generated a plan and presented it to the user"],
                    missing="User approval of the proposed plan.",
                )
            task_input = dict(task_input)
            task_input["approved_plan"] = approved_plan

        messages: list[dict] = [
            {"role": "user", "content": json.dumps(task_input, ensure_ascii=False, default=str)}
        ]

        supervision_confirm = (
            self._make_supervision_confirm()
            if (self.modes and self.modes.supervision_mode)
            else None
        )

        final_text = loop.run(
            client=self.llm_client,
            messages=messages,
            model=self.model,
            system=self.system_prompt + RESULT_INSTRUCTION,
            tools=self._build_tool_schemas(),
            dispatch=self._dispatch,
            label=self.name,
            max_iterations=MAX_ITERATIONS,
            supervision_confirm=supervision_confirm,
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

