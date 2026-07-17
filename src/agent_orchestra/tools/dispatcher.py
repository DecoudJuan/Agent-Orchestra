import time
from fnmatch import fnmatch
from pathlib import Path

from src.agent_orchestra.agent.config import AgentConfig
from src.agent_orchestra.observability.tracing import mark_error, observe, update_current_span
from src.agent_orchestra.memory.action_tracker import ActionTracker
from src.agent_orchestra.tools.tool import Tool
from src.agent_orchestra.tools.tool_type import ToolType


class PermissionDenied(Exception):
    pass


class LoopDetected(Exception):
    pass


class ToolDispatcher:
    def __init__(
        self,
        tools: dict[str, Tool],
        config: AgentConfig,
        tracker: ActionTracker,
    ):
        self.tools = tools
        self.config = config
        self.tracker = tracker

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    @observe(name="tool-call", as_type="tool", capture_input=True, capture_output=True)
    def call(self, tool_name: str, kwargs: dict, requesting_agent: str) -> str:
        start = time.time()
        update_current_span(name=tool_name, metadata={"agent": requesting_agent, "tool": tool_name})
        tool = self.tools.get(tool_name)
        if tool is None:
            message = f"Unknown tool: '{tool_name}'"
            mark_error(message)
            raise PermissionDenied(message)

        try:
            self._check_permissions(tool, kwargs)
        except PermissionDenied as e:
            mark_error(str(e))
            raise

        if tool.type != ToolType.DELEGATE:
            arg_preview = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in kwargs.items())
            print(f"  [{requesting_agent}] {tool_name}({arg_preview})")

        try:
            result = tool.execute(**kwargs)
        except Exception as e:
            mark_error(f"{type(e).__name__}: {e}")
            raise

        result_sig = (result or "")[:200]

        if tool.type != ToolType.DELEGATE:
            if self.tracker.is_repeating(requesting_agent, tool_name, kwargs, result_sig):
                self.tracker.record(requesting_agent, tool_name, kwargs, result_sig)
                reason = (
                    f"Loop detected: '{tool_name}' called repeatedly with the same "
                    "arguments and same result. Change strategy or report blocked."
                )
                mark_error(reason)
                raise LoopDetected(reason)
            self.tracker.record(requesting_agent, tool_name, kwargs, result_sig)

        update_current_span(
            metadata={
                "agent": requesting_agent,
                "tool": tool_name,
                "tool_type": tool.type.value,
                "latency_s": round(time.time() - start, 3),
            }
        )
        return result

    def _check_permissions(self, tool: Tool, kwargs: dict) -> None:
        if tool.type == ToolType.READ:
            self._check_path(kwargs.get("path", ""), self.config.permissions.read.deny, "read")
        elif tool.type == ToolType.WRITE:
            path = kwargs.get("path", "")
            self._check_inside_workspace(path)
            self._check_path(path, self.config.permissions.write.deny, "write")
        elif tool.type == ToolType.EXECUTE:
            self._check_command(kwargs.get("command", ""))

    def _relative_to_workspace(self, path: str) -> str:
        try:
            return Path(path).resolve().relative_to(self.config.workspace_path).as_posix()
        except ValueError:
            return Path(path).as_posix().lstrip("./")

    def _check_path(self, path: str, deny_patterns: list[str], action: str) -> None:
        rel = self._relative_to_workspace(path)
        name = Path(path).name
        for pattern in deny_patterns:
            base = pattern.rstrip("/*")
            if (
                fnmatch(rel, pattern)
                or fnmatch(name, pattern)
                or rel == base
                or rel.startswith(base + "/")
            ):
                raise PermissionDenied(f"Policy denies {action} access to '{path}' (rule: '{pattern}')")

    def _check_inside_workspace(self, path: str) -> None:
        try:
            Path(path).resolve().relative_to(self.config.workspace_path)
        except ValueError:
            raise PermissionDenied(
                f"Write outside the workspace is not allowed: '{path}' "
                f"(workspace: {self.config.workspace_path})"
            )

    def _check_command(self, command: str) -> None:
        for denied in self.config.commands.deny:
            if denied in command:
                raise PermissionDenied(f"Command denied by policy (contains '{denied}')")
        for needs_ok in self.config.commands.require_approval:
            if needs_ok in command:
                answer = input(f"\n[APPROVAL REQUIRED] Run command: {command!r}? [y/N]: ").strip().lower()
                if answer != "y":
                    raise PermissionDenied(f"User denied approval for command: {command!r}")
                break
