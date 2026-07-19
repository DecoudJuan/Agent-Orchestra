from abc import ABC, abstractmethod

from src.agent_orchestra.tools.context import ToolContext
from src.agent_orchestra.tools.permissions import PermissionContext, PermissionRule
from src.agent_orchestra.tools.tool_type import ToolType


class Tool(ABC):
    """Common interface every tool (builtin or plugin) must implement.

    A tool declares:
      - ``name`` / ``description`` — identity shown to the LLM,
      - ``parameters_schema`` — JSON schema of its arguments,
      - ``type`` — coarse category (used for tracing and loop detection),
      - ``permissions`` — the permission policy it enforces (see permissions.py),
      - ``execute`` — the execution function.

    Plugins are discovered and instantiated automatically by the registry via
    :meth:`build`; nothing in the harness core needs editing to add a tool.
    """

    name: str
    description: str
    type: ToolType
    parameters_schema: dict

    # Permission policy carried by the tool itself. Override in subclasses or
    # reuse the presets in permissions.py (READ_POLICY, WRITE_POLICY, ...).
    permissions: list[PermissionRule] = []

    # Discovery flag. A plugin can ship disabled-by-default; config can also
    # toggle tools by name (see ToolsConfig).
    enabled: bool = True

    @abstractmethod
    def execute(self, **kwargs) -> str: ...

    @classmethod
    def build(cls, ctx: ToolContext) -> "Tool":
        """Factory used by the registry. Default assumes a no-arg constructor;
        tools needing dependencies (LLM client, index path, ...) override this."""
        return cls()

    def check_permissions(self, kwargs: dict, ctx: PermissionContext) -> None:
        """Run every declared permission rule; a rule raises PermissionDenied."""
        for rule in self.permissions:
            rule.check(kwargs, ctx)

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
