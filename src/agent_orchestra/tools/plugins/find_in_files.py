"""Example plugin: a `find_in_files` tool.

This module is *not* referenced anywhere in the harness core. Dropping it into
this package is enough for the registry to discover, build, and register it,
which is exactly what the plugin system is meant to demonstrate:

  - a common interface (name, description, parameters_schema, execute),
  - a permission policy carried by the tool (reuses READ_POLICY),
  - automatic discovery + registration.

To expose it to an agent, add ``"find_in_files"`` to that agent's allowed_tools.
"""

import re
from pathlib import Path

from src.agent_orchestra.tools.permissions import READ_POLICY
from src.agent_orchestra.tools.tool import Tool
from src.agent_orchestra.tools.tool_type import ToolType


class FindInFilesTool(Tool):
    name = "find_in_files"
    description = (
        "Search a regular expression across files under a directory and return "
        "matching lines with their file path and line number."
    )
    type = ToolType.READ
    permissions = READ_POLICY
    parameters_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Absolute path of the directory to search"},
            "pattern": {"type": "string", "description": "Regular expression to search for"},
            "glob": {"type": "string", "description": "File glob to restrict the search, default '**/*'"},
            "max_results": {"type": "integer", "description": "Maximum matching lines, default 50"},
        },
        "required": ["path", "pattern"],
    }

    def execute(self, path: str, pattern: str, glob: str = "**/*", max_results: int = 50) -> str:
        directory = Path(path)
        if not directory.is_dir():
            return f"Error: not a directory: {path}"
        try:
            regex = re.compile(pattern)
        except re.error as e:
            return f"Error: invalid regex: {e}"

        hits: list[str] = []
        for file in directory.glob(glob):
            if not file.is_file():
                continue
            try:
                lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
            except Exception:
                continue
            for lineno, line in enumerate(lines, start=1):
                if regex.search(line):
                    hits.append(f"{file}:{lineno}: {line.strip()[:200]}")
                    if len(hits) >= max_results:
                        return "\n".join(hits) + f"\n(stopped at {max_results} results)"
        return "\n".join(hits) if hits else "(no matches)"
