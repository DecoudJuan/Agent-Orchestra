"""Declarative permission policies carried by each tool.

Historically the dispatcher inspected ``tool.type`` and hard-coded which check
to run for READ/WRITE/EXECUTE tools. That coupled the harness core to the set of
known tool kinds, so a new plugin could not express its own permission needs
without editing the dispatcher.

Instead, every tool now declares a list of :class:`PermissionRule` objects
(``Tool.permissions``). The dispatcher only knows how to iterate those rules and
call :meth:`PermissionRule.check`; it no longer knows anything about specific
tools. Plugins ship their own rules — or reuse the presets below.
"""

from abc import ABC, abstractmethod
from fnmatch import fnmatch
from pathlib import Path


class PermissionDenied(Exception):
    """Raised by a permission rule when a call is not allowed."""


class PermissionContext:
    """Everything a permission rule may need to evaluate a call.

    Passed to every :meth:`PermissionRule.check`. Wrapping it keeps rules
    decoupled from the concrete ``AgentConfig`` shape.
    """

    def __init__(self, config):
        self.config = config
        self.workspace_path = config.workspace_path

    def relative_to_workspace(self, path: str) -> str:
        try:
            return Path(path).resolve().relative_to(self.workspace_path).as_posix()
        except ValueError:
            return Path(path).as_posix().lstrip("./")


class PermissionRule(ABC):
    """A single permission check. Raise :class:`PermissionDenied` to block."""

    @abstractmethod
    def check(self, kwargs: dict, ctx: PermissionContext) -> None: ...


class DenyPaths(PermissionRule):
    """Deny access to a path (from ``kwargs[param]``) matching a deny list.

    The deny patterns are read from the config at check time so live config
    edits are honoured. ``action`` selects which list (``read`` / ``write``) and
    only labels the error message.
    """

    def __init__(self, action: str, param: str = "path"):
        self.action = action
        self.param = param

    def check(self, kwargs: dict, ctx: PermissionContext) -> None:
        path = kwargs.get(self.param, "")
        if not path:
            return
        deny_patterns = getattr(ctx.config.permissions, self.action).deny
        rel = ctx.relative_to_workspace(path)
        name = Path(path).name
        for pattern in deny_patterns:
            base = pattern.rstrip("/*")
            if (
                fnmatch(rel, pattern)
                or fnmatch(name, pattern)
                or rel == base
                or rel.startswith(base + "/")
            ):
                raise PermissionDenied(
                    f"Policy denies {self.action} access to '{path}' (rule: '{pattern}')"
                )


class RequireInsideWorkspace(PermissionRule):
    """Deny writes to a path outside the configured workspace root."""

    def __init__(self, param: str = "path"):
        self.param = param

    def check(self, kwargs: dict, ctx: PermissionContext) -> None:
        path = kwargs.get(self.param, "")
        if not path:
            return
        try:
            Path(path).resolve().relative_to(ctx.workspace_path)
        except ValueError:
            raise PermissionDenied(
                f"Write outside the workspace is not allowed: '{path}' "
                f"(workspace: {ctx.workspace_path})"
            )


class CommandPolicy(PermissionRule):
    """Block denied command substrings; prompt for ones needing approval."""

    def __init__(self, param: str = "command"):
        self.param = param

    def check(self, kwargs: dict, ctx: PermissionContext) -> None:
        command = kwargs.get(self.param, "")
        for denied in ctx.config.commands.deny:
            if denied in command:
                raise PermissionDenied(f"Command denied by policy (contains '{denied}')")
        for needs_ok in ctx.config.commands.require_approval:
            if needs_ok in command:
                answer = input(
                    f"\n[APPROVAL REQUIRED] Run command: {command!r}? [y/N]: "
                ).strip().lower()
                if answer != "y":
                    raise PermissionDenied(f"User denied approval for command: {command!r}")
                break


# Presets matching the historical READ/WRITE/EXECUTE behaviour. Tools may reuse
# these or compose their own list of rules.
READ_POLICY = [DenyPaths("read")]
WRITE_POLICY = [RequireInsideWorkspace(), DenyPaths("write")]
EXECUTE_POLICY = [CommandPolicy()]
NO_POLICY: list[PermissionRule] = []
