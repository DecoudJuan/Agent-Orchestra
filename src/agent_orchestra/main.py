import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from src.agent_orchestra.agent import Agent, SubagentTool
from src.agent_orchestra.observability import flush_traces, get_openai_client, trace_attributes, update_current_trace
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
    "\n\nGeneral rules:\n"
    "- Always use ABSOLUTE paths in every file tool call. The workspace root is given in your input.\n"
    "- Prefix every source you report: repo:<path>, memory:<key>, rag:<source>#<chunk_id>, "
    "web:<url>, inference:<claim>.\n"
    "- You cannot call other subagents. Work only with your own tools.\n"
    "- If a tool call returns [BLOCKED], do not retry it as-is: change approach or return status 'blocked'.\n"
    "- Return status 'blocked' (never invent) when the request is ambiguous, documentation is missing, "
    "a permission was denied, an error cannot be diagnosed, or a change is too risky."
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
        "You are the Explorer subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite projects. Your responsibility is to understand the repository: "
        "structure, architecture, dependencies, conventions and relevant files. "
        "Use list_files and read_file to inspect the workspace. Report findings concisely and "
        "propose memory updates (architecture, conventions, dependencies) when you learn something durable."
    )
    return _build_subagent("explorer", prompt, ["list_files", "read_file"], dispatcher, config, llm_client, modes)


def build_researcher(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "You are the Researcher subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite. Your responsibility is to find technical information. "
        "ALWAYS call rag_search first. Only if the RAG evidence is insufficient or empty, "
        "fall back to web_search, prioritizing official documentation "
        "(react.dev, typescriptlang.org, vitejs.dev). "
        "Clearly separate what came from RAG, from the web, and what is your own inference."
    )
    return _build_subagent("researcher", prompt, ["rag_search", "web_search"], dispatcher, config, llm_client, modes)


def build_implementer(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "You are the Implementer subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite. Your responsibility is to make code changes based on the "
        "findings provided in your input (previous steps and project memory). "
        "You cannot read files: rely on the context given and on precise edits. "
        "Prefer edit_file (unique find-and-replace) for small changes and write_file for new files. "
        "List every file you touch in files_touched."
    )
    return _build_subagent(
        "implementer", prompt, ["write_file", "delete_file", "edit_file"], dispatcher, config, llm_client, modes
    )


def build_tester(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "You are the Tester subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite. Your responsibility is to validate results by running checks: "
        "tests, build, type-checking (tsc --noEmit), lint, or other commands. "
        "Always pass the workspace root as cwd. Report exact failures with the relevant output excerpt. "
        "Propose useful_commands memory updates when you discover commands that work for this project."
    )
    return _build_subagent("tester", prompt, ["run_command"], dispatcher, config, llm_client, modes)


def build_reviewer(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "You are the Reviewer subagent of a coding-agent system specialized in "
        "React + TypeScript + Vite. Your responsibility is to review the changes made "
        "(files listed in previous steps) and validate that they answer the user's original request. "
        "Read the touched files, check correctness, style and scope. "
        "Return 'done' with an approval summary, or 'blocked' explaining what does not match the request."
    )
    return _build_subagent("reviewer", prompt, ["list_files", "read_file"], dispatcher, config, llm_client, modes)


def build_orchestrator(dispatcher, config, llm_client, modes=None) -> Agent:
    prompt = (
        "You are the Orchestrator of a coding-agent system specialized in React + TypeScript + Vite. "
        "You receive the user's task and coordinate specialized subagents - they are your ONLY tools:\n"
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

    with trace_attributes(session_id=task_id, metadata={"workspace": workspace}):
        update_current_trace(
            name="agent-task",
            input={"task": task, "workspace": workspace},
        )
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
        update_current_trace(
            output={
                "status": result.status,
                "summary": result.summary,
                "files_touched": result.files_touched,
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
