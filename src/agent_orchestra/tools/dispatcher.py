import time

from src.agent_orchestra.agent.config import AgentConfig
from src.agent_orchestra.observability.tracing import mark_error, observe, update_current_span
from src.agent_orchestra.memory.action_tracker import ActionTracker
from src.agent_orchestra.tools.permissions import PermissionContext, PermissionDenied
from src.agent_orchestra.tools.tool import Tool
from src.agent_orchestra.tools.tool_type import ToolType


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
        # The dispatcher no longer knows anything about specific tool kinds:
        # each tool carries its own permission policy, evaluated against this
        # shared context.
        self.permission_context = PermissionContext(config)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def register_all(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

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
            tool.check_permissions(kwargs, self.permission_context)
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
