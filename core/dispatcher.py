"""Single execution point for every tool call: permissions, loop detection,
observability."""

import time
from fnmatch import fnmatch
from pathlib import Path

from .action_tracker import ActionTracker
from .config import AgentConfig
from .monitor import AgentMonitor
from .tool import Tool, ToolType


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
        monitor: AgentMonitor,
    ):
        self.tools = tools
        self.config = config
        self.tracker = tracker
        self.monitor = monitor

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def call(self, tool_name: str, kwargs: dict, requesting_agent: str) -> str:
        start = time.time()
        tool = self.tools.get(tool_name)
        if tool is None:
            raise PermissionDenied(f"Unknown tool: '{tool_name}'")

        try:
            self._check_permissions(tool, kwargs)
        except PermissionDenied as e:
            self.monitor.log_tool_call(
                requesting_agent, tool_name, kwargs, "", blocked=True,
                latency=time.time() - start, reason=str(e),
            )
            raise

        if tool.type != ToolType.DELEGATE:
            arg_preview = ", ".join(f"{k}={str(v)[:60]!r}" for k, v in kwargs.items())
            print(f"  [{requesting_agent}] {tool_name}({arg_preview})")

        result = tool.execute(**kwargs)
        result_sig = (result or "")[:200]

        if tool.type != ToolType.DELEGATE:
            if self.tracker.is_repeating(requesting_agent, tool_name, kwargs, result_sig):
                self.tracker.record(requesting_agent, tool_name, kwargs, result_sig)
                reason = (
                    f"Loop detected: '{tool_name}' called repeatedly with the same "
                    "arguments and same result. Change strategy or report blocked."
                )
                self.monitor.log_tool_call(
                    requesting_agent, tool_name, kwargs, result, blocked=True,
                    latency=time.time() - start, reason=reason,
                )
                raise LoopDetected(reason)
            self.tracker.record(requesting_agent, tool_name, kwargs, result_sig)

        self.monitor.log_tool_call(
            requesting_agent, tool_name, kwargs, result, blocked=False,
            latency=time.time() - start,
        )
        return result

    # --- permissions -----------------------------------------------------

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
