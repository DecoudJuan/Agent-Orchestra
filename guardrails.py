import json
from pathlib import Path


class GuardrailError(Exception):
    pass


class Guardrails:
    def __init__(self, config_path: str = "guardrails.json"):
        self.blocked_paths: list = []
        self.forbidden_commands: list = []
        self.allowed_dirs: list = []

        path = Path(config_path)
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8"))
            self.blocked_paths = cfg.get("blocked_paths", [])
            self.forbidden_commands = cfg.get("forbidden_commands", [])
            self.allowed_dirs = cfg.get("allowed_dirs", [])
            print(
                f"[guardrails] config cargada: {len(self.blocked_paths)} paths bloqueados, "
                f"{len(self.forbidden_commands)} comandos prohibidos"
            )
        else:
            print(f"[guardrails] {config_path} no encontrado — sin restricciones activas")

    def check(self, tool_name: str, params: dict) -> None:
        if tool_name in ("read_file", "write_file"):
            self._check_path(params.get("path", ""))
        elif tool_name == "run_command":
            self._check_command(params.get("command", ""))
        elif tool_name == "list_files":
            self._check_allowed_dir(params.get("directory", "."))

    def _check_path(self, path: str) -> None:
        normalized = Path(path).as_posix()
        for blocked in self.blocked_paths:
            if blocked in normalized or normalized.endswith(blocked):
                raise GuardrailError(f"acceso denegado al path '{path}'")
        if self.allowed_dirs:
            try:
                abs_path = Path(path).resolve()
                allowed = any(
                    str(abs_path).startswith(str(Path(d).resolve()))
                    for d in self.allowed_dirs
                )
                if not allowed:
                    raise GuardrailError(f"'{path}' fuera de los directorios permitidos")
            except GuardrailError:
                raise
            except Exception:
                pass  # si no se puede resolver el path, dejamos pasar

    def _check_command(self, command: str) -> None:
        cmd_lower = command.lower()
        for forbidden in self.forbidden_commands:
            if forbidden.lower() in cmd_lower:
                raise GuardrailError(f"comando prohibido: contiene '{forbidden}'")

    def _check_allowed_dir(self, directory: str) -> None:
        if self.allowed_dirs:
            try:
                abs_dir = Path(directory).resolve()
                allowed = any(
                    str(abs_dir).startswith(str(Path(d).resolve()))
                    for d in self.allowed_dirs
                )
                if not allowed:
                    raise GuardrailError(f"directorio '{directory}' fuera de los permitidos")
            except GuardrailError:
                raise
            except Exception:
                pass
