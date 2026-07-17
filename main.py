"""Entry point: wires config, tools, dispatcher, memory and agents, then runs
the orchestrator once per user task."""

import os
import sys
import time
from pathlib import Path

import openai
from dotenv import load_dotenv

from agents import (
    SubagentTool,
    build_explorer,
    build_implementer,
    build_orchestrator,
    build_researcher,
    build_reviewer,
    build_tester,
)
from core.action_tracker import ActionTracker
from core.config import load_config
from core.dispatcher import ToolDispatcher
from core.monitor import AgentMonitor
from core.project_memory import ProjectMemory
from core.task_state import TaskState
from tools import (
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


def run_task(task: str, config, llm_client, dispatcher, memory) -> None:
    task_id = f"task-{int(time.time())}"
    task_state = TaskState(task_id=task_id, original_request=task)
    workspace = str(config.workspace_path)

    subagents = [
        build_explorer(dispatcher, config, llm_client),
        build_researcher(dispatcher, config, llm_client),
        build_implementer(dispatcher, config, llm_client),
        build_tester(dispatcher, config, llm_client),
        build_reviewer(dispatcher, config, llm_client),
    ]
    for subagent in subagents:
        dispatcher.register(SubagentTool(subagent, task_state, memory, workspace))

    orchestrator = build_orchestrator(dispatcher, config, llm_client)
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


def main() -> None:
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not found. Set it in .env or the environment.")
        sys.exit(1)

    config = load_config()
    if not config.workspace_path.exists():
        print(f"WARNING: workspace does not exist yet: {config.workspace_path}")
        print("Set 'workspace' in agent.config.yaml to the project the agent should work on.")

    llm_client = openai.OpenAI()
    monitor = AgentMonitor()
    tracker = ActionTracker()
    dispatcher = ToolDispatcher(tools={}, config=config, tracker=tracker, monitor=monitor)

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

    print("Agent-Orchestra — multi-agent coding system (orchestrator + 5 subagents)")
    print(f"Workspace: {config.workspace_path} | Model: {config.llm.model}")
    print("Type a task, or 'exit' to quit.\n")

    try:
        while True:
            try:
                task = input("Task> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nBye!")
                break
            if not task:
                continue
            if task.lower() in ("exit", "quit", "/exit"):
                print("Bye!")
                break
            try:
                run_task(task, config, llm_client, dispatcher, memory)
            except openai.APIError as e:
                print(f"\n[API error] {e}\n")
            except Exception as e:
                print(f"\n[error] {type(e).__name__}: {e}\n")
    finally:
        monitor.shutdown()


if __name__ == "__main__":
    main()
