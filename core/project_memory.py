"""Persistent per-project memory, stored inside the workspace at .agent/.

Read: every agent, but only the slice the orchestrator passes as input.
Write: only the orchestrator, via apply_update() from each subagent's
proposed_memory_update.
"""

import json
import time
from pathlib import Path

MEMORY_FILES = {
    "architecture": "architecture.md",
    "conventions": "conventions.json",
    "dependencies": "dependencies.json",
    "useful_commands": "useful_commands.json",
}

# Which memory slices each agent gets as input.
RELEVANT_KEYS = {
    "orchestrator": list(MEMORY_FILES),
    "explorer": ["architecture", "conventions", "dependencies"],
    "researcher": ["architecture", "dependencies"],
    "implementer": ["architecture", "conventions", "dependencies"],
    "tester": ["useful_commands", "dependencies"],
    "reviewer": ["architecture", "conventions"],
}


class ProjectMemory:
    def __init__(self, dir: Path):
        self.dir = Path(dir)
        (self.dir / "memory").mkdir(parents=True, exist_ok=True)
        (self.dir / "sessions").mkdir(parents=True, exist_ok=True)

    def load_relevant(self, subagent_name: str, topic_hint: str) -> dict:
        """Filtered read: only the slices relevant to the requesting agent."""
        out: dict = {}
        for key in RELEVANT_KEYS.get(subagent_name, list(MEMORY_FILES)):
            path = self.dir / "memory" / MEMORY_FILES[key]
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                continue
            out[key] = json.loads(text) if path.suffix == ".json" else text
        decisions = self._tail_jsonl("decisions_log.jsonl", 5)
        if decisions:
            out["recent_decisions"] = decisions
        return out

    def apply_update(self, update: dict, agent: str, task_id: str) -> None:
        """Single write point, called only by the orchestrator side."""
        for key, value in update.items():
            if key == "architecture":
                (self.dir / "memory" / MEMORY_FILES[key]).write_text(str(value), encoding="utf-8")
            elif key in ("conventions", "dependencies", "useful_commands"):
                if isinstance(value, dict):
                    self._merge_json(MEMORY_FILES[key], value)
                else:
                    print(f"[memory] Ignored '{key}' update: expected an object, got {type(value).__name__}")
            elif key == "decision":
                self._append_jsonl("decisions_log.jsonl", value, agent, task_id)
            elif key == "bug":
                self._append_jsonl("bugs_investigated.jsonl", value, agent, task_id)
            else:
                print(f"[memory] Ignored unknown memory key: '{key}'")

    # --- helpers ----------------------------------------------------------

    def _merge_json(self, filename: str, value: dict) -> None:
        path = self.dir / "memory" / filename
        current = {}
        if path.exists() and path.read_text(encoding="utf-8").strip():
            current = json.loads(path.read_text(encoding="utf-8"))
        current.update(value)
        path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")

    def _append_jsonl(self, filename: str, content, agent: str, task_id: str) -> None:
        record = {"ts": time.time(), "agent": agent, "task_id": task_id, "content": content}
        with (self.dir / "memory" / filename).open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _tail_jsonl(self, filename: str, n: int) -> list[dict]:
        path = self.dir / "memory" / filename
        if not path.exists():
            return []
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return [json.loads(line) for line in lines[-n:]]
