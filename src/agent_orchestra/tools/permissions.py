from abc import ABC, abstractmethod
from fnmatch import fnmatch
from pathlib import Path


class PermissionDenied(Exception): ...


class PermissionContext:

    def __init__(self, config):
        self.config = config
        self.workspace_path = config.workspace_path

    def relative_to_workspace(self, path: str) -> str:
        try:
            return Path(path).resolve().relative_to(self.workspace_path).as_posix()
        except ValueError:
            return Path(path).as_posix().lstrip("./")


class PermissionRule(ABC):

    @abstractmethod
    def check(self, kwargs: dict, ctx: PermissionContext) -> None: ...


class DenyPaths(PermissionRule):

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


READ_POLICY = [DenyPaths("read")]
WRITE_POLICY = [RequireInsideWorkspace(), DenyPaths("write")]
EXECUTE_POLICY = [CommandPolicy()]
NO_POLICY: list[PermissionRule] = []
