import importlib
import importlib.util
import inspect
import pkgutil
import sys
from pathlib import Path

from src.agent_orchestra.tools.context import ToolContext
from src.agent_orchestra.tools.tool import Tool

BUILTIN_PACKAGES = (
    "src.agent_orchestra.tools.tools",
    "src.agent_orchestra.tools.plugins",
)


class PluginRegistry:
    def __init__(self, ctx: ToolContext, config=None):
        self.ctx = ctx
        self.tools_config = getattr(config, "tools", None)

    def discover(self, packages: tuple[str, ...] = BUILTIN_PACKAGES) -> list[Tool]:
        classes: dict[str, type[Tool]] = {}

        for package in packages:
            for cls in self._classes_in_package(package):
                classes[cls.__qualname__] = cls

        for extra_dir in self._extra_plugin_dirs():
            for cls in self._classes_in_directory(extra_dir):
                classes[cls.__qualname__] = cls

        instances: list[Tool] = []
        seen_names: set[str] = set()
        for cls in classes.values():
            instance = self._instantiate(cls)
            if instance is None:
                continue
            if not self._is_enabled(instance):
                continue
            if instance.name in seen_names:
                print(f"  [registry] duplicate tool name '{instance.name}' skipped")
                continue
            seen_names.add(instance.name)
            instances.append(instance)
        return instances


    def _classes_in_package(self, package_name: str) -> list[type[Tool]]:
        try:
            package = importlib.import_module(package_name)
        except ModuleNotFoundError:
            return []
        found: list[type[Tool]] = []
        modules = [package]
        if hasattr(package, "__path__"):
            for info in pkgutil.iter_modules(package.__path__, package_name + "."):
                try:
                    modules.append(importlib.import_module(info.name))
                except Exception as e:
                    print(f"  [registry] failed to import {info.name}: {e}")
        for module in modules:
            found.extend(self._tool_classes(module))
        return found

    def _classes_in_directory(self, directory: Path) -> list[type[Tool]]:
        found: list[type[Tool]] = []
        for path in sorted(directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            module = self._load_file(path)
            if module is not None:
                found.extend(self._tool_classes(module))
        return found

    def _load_file(self, path: Path):
        mod_name = f"_ao_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            return module
        except Exception as e:
            print(f"  [registry] failed to load plugin file {path}: {e}")
            return None

    @staticmethod
    def _tool_classes(module) -> list[type[Tool]]:
        result = []
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, Tool)
                and obj is not Tool
                and obj.__module__ == module.__name__
                and not inspect.isabstract(obj)
            ):
                result.append(obj)
        return result

    def _instantiate(self, cls: type[Tool]) -> Tool | None:
        try:
            return cls.build(self.ctx)
        except Exception as e:
            print(f"  [registry] failed to build {cls.__qualname__}: {e}")
            return None


    def _is_enabled(self, tool: Tool) -> bool:
        if not getattr(tool, "enabled", True):
            enabled = self._config_list("enabled")
            return enabled is not None and tool.name in enabled
        enabled = self._config_list("enabled")
        if enabled is not None:
            return tool.name in enabled
        return tool.name not in (self._config_list("disabled") or [])

    def _config_list(self, field: str):
        if self.tools_config is None:
            return None
        return getattr(self.tools_config, field, None)

    def _extra_plugin_dirs(self) -> list[Path]:
        dirs = self._config_list("plugin_dirs") or []
        resolved = []
        for d in dirs:
            path = Path(d)
            if path.is_dir():
                resolved.append(path)
            else:
                print(f"  [registry] plugin_dir not found: {d}")
        return resolved
