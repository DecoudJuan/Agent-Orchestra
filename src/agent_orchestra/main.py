import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from src.agent_orchestra.agent import Agent, SubagentTool
from src.agent_orchestra.observability import flush_traces, get_openai_client
from src.agent_orchestra.memory.action_tracker import ActionTracker
from src.agent_orchestra.agent.config import load_config
from src.agent_orchestra.agent.modes import Modes
from src.agent_orchestra.tools import ToolDispatcher
from src.agent_orchestra.memory import ProjectMemory
from src.agent_orchestra.memory import TaskState
from src.agent_orchestra.tools import (
    DeleteFileTool,
    EditFileTool,
    ListFilesTool,
    RagSearchTool,
    ReadFileTool,
    RunCommandTool,
    WebSearchTool,
    WriteFileTool,
)

RAG_INDEX_DIR = str(Path(__file__).parent / "rag" / "index")

COMMON_RULES = (
    "\n\n<general_rules>\n"
    "1. Always use ABSOLUTE paths in every file tool call. The workspace root is provided in your input.\n"
    "2. Prefix every source you report with its origin (e.g., repo:<path>, memory:<key>, rag:<source>#<chunk_id>, web:<url>, inference:<claim>).\n"
    "3. You cannot call other subagents. Work only with your own tools.\n"
    "4. If a tool call returns [BLOCKED], do not retry it exactly as-is: change your approach or return status 'blocked'.\n"
    "5. Return status 'blocked' (never invent or hallucinate) when the request is ambiguous, documentation is missing, a permission was denied, an error cannot be diagnosed, or a change is too risky.\n"
    "</general_rules>"
)


def _build_subagent(name: str, prompt: str, tools: list[str], dispatcher, config, llm_client, modes=None) -> Agent:
    return Agent(
        name=name,
        system_prompt=prompt + COMMON_RULES,
        allowed_tools=tools,
        dispatcher=dispatcher,
        llm_client=llm_client,
        model=config.llm.model,
        modes=modes,
    )


def build_explorer(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "<role>\n"
        "You are the Explorer subagent of an expert coding-agent system specialized in React + TypeScript + Vite projects.\n"
        "Your responsibility is to thoroughly understand the repository: its structure, architecture, dependencies, conventions, and relevant files.\n"
        "</role>\n\n"
        "<instructions>\n"
        "1. Use list_files and read_file to carefully inspect the workspace.\n"
        "2. Analyze the project structure to gather necessary context.\n"
        "3. Report your findings concisely and accurately.\n"
        "4. Propose memory updates (for architecture, conventions, or dependencies) whenever you discover durable, valuable knowledge about the project.\n"
        "</instructions>"
    )
    return _build_subagent("explorer", prompt, ["list_files", "read_file"], dispatcher, config, llm_client, modes)


def build_researcher(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "<role>\n"
        "You are the Researcher subagent of an expert coding-agent system specialized in React + TypeScript + Vite.\n"
        "Your responsibility is to find precise technical information to assist the team.\n"
        "</role>\n\n"
        "<instructions>\n"
        "1. ALWAYS call rag_search first to query the internal knowledge base.\n"
        "2. Only if the RAG evidence is insufficient or empty, fall back to web_search.\n"
        "3. When using web search, prioritize official documentation (e.g., react.dev, typescriptlang.org, vitejs.dev).\n"
        "4. Clearly categorize your findings in your report: specify exactly what came from RAG, what came from the web, and what is your own inference.\n"
        "</instructions>"
    )
    return _build_subagent("researcher", prompt, ["rag_search", "web_search"], dispatcher, config, llm_client, modes)


def build_implementer(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "<role>\n"
        "You are the Implementer subagent of an expert coding-agent system specialized in React + TypeScript + Vite.\n"
        "Your responsibility is to carefully make code changes based on the findings provided in your input (previous steps and project memory).\n"
        "</role>\n\n"
        "<instructions>\n"
        "1. Analyze the context and findings provided to you. You cannot read files directly, so rely strictly on this given context and perform precise edits.\n"
        "2. For small modifications, prefer edit_file (unique find-and-replace).\n"
        "3. For creating new files, use write_file.\n"
        "4. Ensure every file you modify or create is meticulously tracked and listed in files_touched.\n"
        "</instructions>"
    )
    return _build_subagent(
        "implementer", prompt, ["write_file", "delete_file", "edit_file"], dispatcher, config, llm_client, modes
    )


def build_tester(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "<role>\n"
        "You are the Tester subagent of an expert coding-agent system specialized in React + TypeScript + Vite.\n"
        "Your responsibility is to validate results by rigorously running checks.\n"
        "</role>\n\n"
        "<instructions>\n"
        "1. Run necessary checks such as tests, build processes, type-checking (tsc --noEmit), linters, or other relevant commands.\n"
        "2. Always pass the workspace root as the cwd (current working directory).\n"
        "3. Report exact failures, including the relevant output excerpts.\n"
        "4. Propose useful_commands memory updates whenever you discover or refine commands that work effectively for this project.\n"
        "</instructions>"
    )
    return _build_subagent("tester", prompt, ["run_command"], dispatcher, config, llm_client, modes)


def build_reviewer(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "<role>\n"
        "You are the Reviewer subagent of an expert coding-agent system specialized in React + TypeScript + Vite.\n"
        "Your responsibility is to audit the changes made (files listed in previous steps) and validate that they flawlessly answer the user's original request.\n"
        "</role>\n\n"
        "<instructions>\n"
        "1. Read the touched files.\n"
        "2. Meticulously check for correctness, coding style, and whether the scope of the request was met.\n"
        "3. If the changes are completely satisfactory, return 'done' with an approval summary.\n"
        "4. If the changes do not match the request or introduce issues, return 'blocked' with a clear explanation of the discrepancies.\n"
        "</instructions>"
    )
    return _build_subagent("reviewer", prompt, ["list_files", "read_file"], dispatcher, config, llm_client, modes)


def build_orchestrator(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "<role>\n"
        "You are the Orchestrator of an expert coding-agent system specialized in React + TypeScript + Vite.\n"
        "You receive the user's task and coordinate specialized subagents to complete it. They are your ONLY tools.\n"
        "</role>\n\n"
        "<available_subagents>\n"
        "- invoke_explorer: Understands the repository (structure, files, conventions).\n"
        "- invoke_researcher: Searches the RAG corpus and, as fallback, the web.\n"
        "- invoke_implementer: Writes, edits, or deletes code files.\n"
        "- invoke_tester: Runs commands to validate (tests, build, tsc, lint).\n"
        "- invoke_reviewer: Reviews the changes against the original request.\n"
        "</available_subagents>\n\n"
        "<instructions>\n"
        "1. Invoke ONE subagent at a time. Use its result to thoughtfully decide the next step.\n"
        "2. Give each subagent a clear, self-contained instruction with the concrete context it needs (e.g., tell the implementer exactly which files and changes are needed, since it cannot read files).\n"
        "3. Follow a typical flow when appropriate: explore -> (research if needed) -> implement -> test -> review. Adapt this flow to the task; trivial questions may require fewer steps.\n"
        "4. If a subagent returns 'blocked' or 'needs_more_info', do NOT retry the same instruction blindly. Change your strategy, try another subagent, or finish with status 'blocked'/'needs_more_info' and explain to the user what was attempted and what is missing.\n"
        "5. In your final summary, strictly cite the sources reported by the subagents using their respective prefixes.\n"
        "</instructions>"
    )
    return _build_subagent(
        "orchestrator",
        prompt,
        [f"invoke_{n}" for n in ["explorer", "researcher", "implementer", "tester", "reviewer"]],
        dispatcher,
        config,
        llm_client,
        modes,
    )


def run_task(task: str, config, llm_client, dispatcher, memory, modes: Modes | None = None) -> None:
    task_id = f"task-{int(time.time())}"
    task_state = TaskState(task_id=task_id, original_request=task)
    workspace = str(config.workspace_path)

    subagents = [
        build_explorer(dispatcher, config, llm_client, modes),
        build_researcher(dispatcher, config, llm_client, modes),
        build_implementer(dispatcher, config, llm_client, modes),
        build_tester(dispatcher, config, llm_client, modes),
        build_reviewer(dispatcher, config, llm_client, modes),
    ]
    for subagent in subagents:
        dispatcher.register(SubagentTool(subagent, task_state, memory, workspace))

    orchestrator = build_orchestrator(dispatcher, config, llm_client, modes)
    result = orchestrator.run(
        {
            "step_id": 0,
            "instruction": task,
            "workspace": workspace,
            "project_memory": memory.load_relevant("orchestrator", task),
        }
    )

    task_state.save(str(memory.dir / "sessions" / f"{task_id}.json"))

    print("\n" + "=" * 60)
    print(f"Status:  {result.status}")
    print(f"Summary: {result.summary}")
    if result.missing:
        print(f"Missing: {result.missing}")
    if task_state.files_modified:
        print(f"Files modified: {task_state.files_modified}")
    all_sources = sorted({src for step in task_state.steps for src in step.sources})
    if all_sources:
        print("Sources:")
        for src in all_sources:
            print(f"  - {src}")
    print(f"Session saved: .agent/sessions/{task_id}.json")
    print("=" * 60)


HELP_TEXT = """
Session commands:
  /plan        Toggle plan mode (agent shows a plan and waits for approval before acting)
  /supervise   Toggle supervision mode (agent asks confirmation before write/execute actions)
  /status      Show current modes and workspace info
  /help        Show this help message
  /exit        Quit
"""


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not found. Set it in .env or the environment.")
        sys.exit(1)

    config = load_config()
    if not config.workspace_path.exists():
        print(f"WARNING: workspace does not exist yet: {config.workspace_path}")
        print("Set 'workspace' in agent.config.yaml to the project the agent should work on.")

    llm_client = get_openai_client()
    tracker = ActionTracker()
    dispatcher = ToolDispatcher(tools={}, config=config, tracker=tracker)

    for tool in (
        ListFilesTool(),
        ReadFileTool(),
        WriteFileTool(),
        DeleteFileTool(),
        EditFileTool(),
        RunCommandTool(),
        RagSearchTool(RAG_INDEX_DIR, llm_client, config.llm.embedding_model),
        WebSearchTool(),
    ):
        dispatcher.register(tool)

    memory = ProjectMemory(config.workspace_path / ".agent")
    modes = Modes()

    print("Agent-Orchestra — multi-agent coding system")
    print(f"Workspace : {config.workspace_path}")
    print(f"Model     : {config.llm.model}")
    print(f"Modes     : {modes.status()}")
    print("Type a task or a /command. Type /help for commands.\n")

    try:
        while True:
            try:
                task = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            if not task:
                continue

            if task.lower() in ("/exit", "exit", "quit"):
                print("Bye!")
                break
            elif task.lower() == "/plan":
                state = modes.toggle_plan()
                print(f"Plan mode {'ON' if state else 'OFF'}.")
                continue
            elif task.lower() == "/supervise":
                state = modes.toggle_supervision()
                print(f"Supervision mode {'ON' if state else 'OFF'}.")
                continue
            elif task.lower() == "/status":
                print(modes.status())
                print(f"Workspace : {config.workspace_path}")
                print(f"Model     : {config.llm.model}")
                continue
            elif task.lower() == "/help":
                print(HELP_TEXT)
                continue

            try:
                run_task(task, config, llm_client, dispatcher, memory, modes)
            except Exception as e:
                print(f"\n[error] {type(e).__name__}: {e}\n")
    finally:
        flush_traces()


if __name__ == "__main__":
    main()
