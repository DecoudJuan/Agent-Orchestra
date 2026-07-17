import os
import subprocess
from pathlib import Path

import requests

from src.agent_orchestra.agent import Agent
from src.agent_orchestra.memory.project_memory import ProjectMemory
from src.agent_orchestra.memory.task_state import TaskState
from src.agent_orchestra.observability.tracing import retriever_observation
from src.agent_orchestra.tools.tool import Tool
from src.agent_orchestra.tools.tool_type import ToolType

SUBAGENT_NAMES = ["explorer", "researcher", "implementer", "tester", "reviewer"]

PATH_PARAM = {"path": {"type": "string", "description": "Absolute path"}}

class ListFilesTool(Tool):
    name = "list_files"
    description = "List files and directories under an absolute path, optionally filtered by a glob pattern."
    type = ToolType.READ
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path of the directory"},
            "pattern": {"type": "string", "description": "Glob pattern, default '*'"},
        },
        "required": ["path"],
    }

    def execute(self, path: str, pattern: str = "*") -> str:
        directory = Path(path)
        if not directory.is_dir():
            return f"Error: not a directory: {path}"
        entries = sorted(directory.glob(pattern), key=lambda e: (not e.is_dir(), e.name.lower()))
        if not entries:
            return "(no matches)"
        return "\n".join(f"[{'DIR ' if e.is_dir() else 'FILE'}] {e.name}" for e in entries)

class ReadFileTool(Tool):
    name = "read_file"
    description = "Read the content of a file given its absolute path."
    type = ToolType.READ
    parameters_schema = {"type": "object", "properties": PATH_PARAM, "required": ["path"]}

    def execute(self, path: str) -> str:
        try:
            return Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except Exception as e:
            return f"Error reading file: {e}"

class WriteFileTool(Tool):
    name = "write_file"
    description = "Write content to a file (absolute path), replacing it if it exists."
    type = ToolType.WRITE
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path"},
            "content": {"type": "string", "description": "Full content to write"},
        },
        "required": ["path", "content"],
    }

    def execute(self, path: str, content: str) -> str:
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(content, encoding="utf-8")
            return f"OK: wrote {len(content)} chars to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

class DeleteFileTool(Tool):
    name = "delete_file"
    description = "Delete a file given its absolute path."
    type = ToolType.WRITE
    parameters_schema = {"type": "object", "properties": PATH_PARAM, "required": ["path"]}

    def execute(self, path: str) -> str:
        try:
            Path(path).unlink()
            return f"OK: deleted {path}"
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        except Exception as e:
            return f"Error deleting file: {e}"

class EditFileTool(Tool):
    name = "edit_file"
    description = (
        "Find-and-replace edit: replaces old_str with new_str in a file. "
        "old_str must appear exactly once."
    )
    type = ToolType.WRITE
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path"},
            "old_str": {"type": "string", "description": "Exact text to replace (must be unique in the file)"},
            "new_str": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_str", "new_str"],
    }

    def execute(self, path: str, old_str: str, new_str: str) -> str:
        try:
            content = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"Error: file not found: {path}"
        count = content.count(old_str)
        if count == 0:
            return "Error: old_str not found in file"
        if count > 1:
            return f"Error: old_str appears {count} times; it must be unique"
        Path(path).write_text(content.replace(old_str, new_str), encoding="utf-8")
        return f"OK: edited {path}"

class RunCommandTool(Tool):
    name = "run_command"
    description = "Run a shell command (e.g. npm test, tsc --noEmit, eslint) in a working directory."
    type = ToolType.EXECUTE
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to run"},
            "cwd": {"type": "string", "description": "Absolute path of the working directory"},
        },
        "required": ["command", "cwd"],
    }

    def execute(self, command: str, cwd: str) -> str:
        try:
            result = subprocess.run(
                command, shell=True, cwd=cwd, capture_output=True, text=True,
                timeout=120, encoding="utf-8", errors="replace",
            )
            parts = []
            if result.stdout:
                parts.append(f"stdout:\n{result.stdout.rstrip()}")
            if result.stderr:
                parts.append(f"stderr:\n{result.stderr.rstrip()}")
            parts.append(f"exit code: {result.returncode}")
            return "\n".join(parts)
        except subprocess.TimeoutExpired:
            return "Error: command timed out after 120 seconds"
        except Exception as e:
            return f"Error running command: {e}"

class RagSearchTool(Tool):
    name = "rag_search"
    description = (
        "Semantic search over the indexed documentation corpus (React, TypeScript, Vite). "
        "Returns chunks with their source, heading and chunk_id."
    )
    type = ToolType.SEARCH
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "top_k": {"type": "integer", "description": "Number of results, default 5"},
        },
        "required": ["query"],
    }

    def __init__(self, index_dir: str, llm_client, embedding_model: str):
        self.index_dir = index_dir
        self.llm_client = llm_client
        self.embedding_model = embedding_model

    def execute(self, query: str, top_k: int = 5) -> str:
        try:
            import chromadb
        except ImportError:
            return "Error: chromadb is not installed (pip install chromadb)."
        client = chromadb.PersistentClient(path=self.index_dir)
        try:
            collection = client.get_collection("docs")
        except Exception:
            return (
                "RAG index is empty: no corpus has been indexed yet. "
                "Run 'python rag/build_index.py' after adding documents to rag/corpus/. "
                "Fall back to web_search if you need external information."
            )
        embedding = (
            self.llm_client.embeddings.create(model=self.embedding_model, input=query)
            .data[0]
            .embedding
        )
        with retriever_observation("rag-search", input={"query": query, "top_k": top_k}) as observation:
            results = collection.query(query_embeddings=[embedding], n_results=top_k)
            if observation is not None:
                observation.update(
                    output=results.get("documents", [[]])[0],
                    metadata={
                        "sources": [
                            meta.get("source")
                            for meta in results.get("metadatas", [[]])[0]
                        ],
                        "chunk_ids": [
                            meta.get("chunk_id")
                            for meta in results.get("metadatas", [[]])[0]
                        ],
                    },
                )
        if not results["documents"] or not results["documents"][0]:
            return "No results found in the RAG index."
        lines = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            lines.append(
                f"--- source: {meta.get('source')} | heading: {meta.get('heading')} "
                f"| chunk_id: {meta.get('chunk_id')} ---\n{doc}\n"
            )
        return "\n".join(lines)

class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web (Tavily API). Use only when the RAG has no sufficient evidence."
    type = ToolType.SEARCH
    parameters_schema = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "Search query"}},
        "required": ["query"],
    }

    def execute(self, query: str) -> str:
        api_key = os.getenv("TAVILY_API_KEY", "")
        if not api_key:
            return (
                "Error: TAVILY_API_KEY is not configured in .env — web search unavailable. "
                f"Query received: {query}"
            )
        try:
            resp = requests.post(
                "https://api.tavily.com/search",
                json={"api_key": api_key, "query": query, "max_results": 5},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])
            if not results:
                return "No results found."
            lines = []
            for r in results:
                lines.append(f"Title: {r.get('title', '(no title)')}")
                lines.append(f"URL:   {r.get('url', '')}")
                lines.append(r.get("content", "")[:400])
                lines.append("")
            return "\n".join(lines).rstrip()
        except Exception as e:
            return f"Error in web_search: {e}"


class SubagentTool(Tool):
    """Wraps a subagent as a tool for the orchestrator."""

    type = ToolType.DELEGATE

    def __init__(
        self,
        subagent: Agent,
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
        print(f"[orchestrator] step {step.id} <- {self.subagent.name}: {result.status} â€” {result.summary[:100]}")
        return result.model_dump_json()
