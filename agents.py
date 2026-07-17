"""All agents in a single file, as factory functions over BaseAgent.

There are no per-role subclasses: the orchestrator and every subagent are
instances of the same BaseAgent class, differing only in name, system prompt
and allowed tools. The orchestrator's only tools are the subagents themselves,
wrapped as SubagentTool (single-level hierarchy, sequential execution).
"""

from core.base_agent import BaseAgent
from core.config import AgentConfig
from core.dispatcher import ToolDispatcher
from core.project_memory import ProjectMemory
from core.task_state import TaskState
from core.tool import Tool, ToolType

SUBAGENT_NAMES = ["explorer", "researcher", "implementer", "tester", "reviewer"]

COMMON_RULES = (
    "\n\nGeneral rules:\n"
    "- Always use ABSOLUTE paths in every file tool call. The workspace root is given in your input.\n"
    "- Prefix every source you report: repo:<path>, memory:<key>, rag:<source>#<chunk_id>, "
    "web:<url>, inference:<claim>.\n"
    "- You cannot call other subagents. Work only with your own tools.\n"
    "- If a tool call returns [BLOCKED], do not retry it as-is: change approach or return status 'blocked'.\n"
    "- Return status 'blocked' (never invent) when the request is ambiguous, documentation is missing, "
    "a permission was denied, an error cannot be diagnosed, or a change is too risky."
)


class SubagentTool(Tool):
    """Wraps a subagent as a tool for the orchestrator. Builds the subagent's
    input (instruction + TaskState slice + ProjectMemory slice), runs it, and
    applies the AgentResult back to state and memory on the orchestrator's behalf."""

    type = ToolType.DELEGATE

    def __init__(
        self,
        subagent: BaseAgent,
        task_state: TaskState,
        memory: ProjectMemory,
        workspace: str,
    ):
        self.subagent = subagent
        self.task_state = task_state
        self.memory = memory
        self.workspace = workspace
        self.name = f"invoke_{subagent.name}"
        self.description = f"Delegate one concrete instruction to the {subagent.name} subagent."
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "Clear, self-contained instruction for the subagent",
                }
            },
            "required": ["instruction"],
        }

    def execute(self, instruction: str) -> str:
        step = self.task_state.new_step(self.subagent.name, instruction)
        print(f"\n[orchestrator] step {step.id} -> {self.subagent.name}: {instruction[:100]}")
        task_input = {
            "step_id": step.id,
            "instruction": instruction,
            "original_request": self.task_state.original_request,
            "workspace": self.workspace,
            "previous_steps": self.task_state.get_summaries_for(SUBAGENT_NAMES),
            "project_memory": self.memory.load_relevant(self.subagent.name, instruction),
        }
        result = self.subagent.run(task_input)
        self.task_state.apply(result)
        if result.proposed_memory_update:
            self.memory.apply_update(result.proposed_memory_update, result.agent, self.task_state.task_id)
        print(f"[orchestrator] step {step.id} <- {self.subagent.name}: {result.status} — {result.summary[:100]}")
        return result.model_dump_json()


# --- factory functions ------------------------------------------------------


def _build(name: str, prompt: str, tools: list[str], dispatcher, config, llm_client) -> BaseAgent:
    return BaseAgent(
        name=name,
        system_prompt=prompt + COMMON_RULES,
        allowed_tools=tools,
        dispatcher=dispatcher,
        llm_client=llm_client,
        model=config.llm.model,
    )


def build_explorer(dispatcher: ToolDispatcher, config: AgentConfig, llm_client) -> BaseAgent:
    prompt = (
        "You are the Explorer subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite projects. Your responsibility is to understand the repository: "
        "structure, architecture, dependencies, conventions and relevant files. "
        "Use list_files and read_file to inspect the workspace. Report findings concisely and "
        "propose memory updates (architecture, conventions, dependencies) when you learn something durable."
    )
    return _build("explorer", prompt, ["list_files", "read_file"], dispatcher, config, llm_client)


def build_researcher(dispatcher: ToolDispatcher, config: AgentConfig, llm_client) -> BaseAgent:
    prompt = (
        "You are the Researcher subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite. Your responsibility is to find technical information. "
        "ALWAYS call rag_search first. Only if the RAG evidence is insufficient or empty, "
        "fall back to web_search, prioritizing official documentation "
        "(react.dev, typescriptlang.org, vitejs.dev). "
        "Clearly separate what came from RAG, from the web, and what is your own inference."
    )
    return _build("researcher", prompt, ["rag_search", "web_search"], dispatcher, config, llm_client)


def build_implementer(dispatcher: ToolDispatcher, config: AgentConfig, llm_client) -> BaseAgent:
    prompt = (
        "You are the Implementer subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite. Your responsibility is to make code changes based on the "
        "findings provided in your input (previous steps and project memory). "
        "You cannot read files: rely on the context given and on precise edits. "
        "Prefer edit_file (unique find-and-replace) for small changes and write_file for new files. "
        "List every file you touch in files_touched."
    )
    return _build(
        "implementer", prompt, ["write_file", "delete_file", "edit_file"], dispatcher, config, llm_client
    )


def build_tester(dispatcher: ToolDispatcher, config: AgentConfig, llm_client) -> BaseAgent:
    prompt = (
        "You are the Tester subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite. Your responsibility is to validate results by running checks: "
        "tests, build, type-checking (tsc --noEmit), lint, or other commands. "
        "Always pass the workspace root as cwd. Report exact failures with the relevant output excerpt. "
        "Propose useful_commands memory updates when you discover commands that work for this project."
    )
    return _build("tester", prompt, ["run_command"], dispatcher, config, llm_client)


def build_reviewer(dispatcher: ToolDispatcher, config: AgentConfig, llm_client) -> BaseAgent:
    prompt = (
        "You are the Reviewer subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite. Your responsibility is to review the changes made "
        "(files listed in previous steps) and validate that they answer the user's original request. "
        "Read the touched files, check correctness, style and scope. "
        "Return 'done' with an approval summary, or 'blocked' explaining what does not match the request."
    )
    return _build("reviewer", prompt, ["list_files", "read_file"], dispatcher, config, llm_client)


def build_orchestrator(dispatcher: ToolDispatcher, config: AgentConfig, llm_client) -> BaseAgent:
    prompt = (
        "You are the Orchestrator of a coding-agent system specialized in React + TypeScript + Vite. "
        "You receive the user's task and coordinate specialized subagents — they are your ONLY tools:\n"
        "- invoke_explorer: understands the repository (structure, files, conventions)\n"
        "- invoke_researcher: searches the RAG corpus and, as fallback, the web\n"
        "- invoke_implementer: writes/edits/deletes code files\n"
        "- invoke_tester: runs commands to validate (tests, build, tsc, lint)\n"
        "- invoke_reviewer: reviews the changes against the original request\n\n"
        "Rules:\n"
        "- Invoke ONE subagent at a time and use its result to decide the next step.\n"
        "- Give each subagent a clear, self-contained instruction with the concrete context it needs "
        "(e.g. tell the implementer exactly which files and changes, since it cannot read files).\n"
        "- Typical flow: explore -> (research if needed) -> implement -> test -> review. Adapt it to the task; "
        "trivial questions may need fewer steps.\n"
        "- If a subagent returns 'blocked' or 'needs_more_info', do NOT retry the same instruction blindly: "
        "change strategy, try another subagent, or finish with status 'blocked'/'needs_more_info' "
        "explaining to the user what was attempted and what is missing.\n"
        "- In your final summary, cite the sources reported by the subagents with their prefixes."
    )
    return _build(
        "orchestrator",
        prompt,
        [f"invoke_{n}" for n in SUBAGENT_NAMES],
        dispatcher,
        config,
        llm_client,
    )
