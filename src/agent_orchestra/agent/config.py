from pathlib import Path

import yaml
from pydantic import BaseModel, Field

DEFAULTS = {
    "model": "gpt-4.1",
    "embedding_model": "text-embedding-3-small",
    "workspace": "./project"
}

class LlmConfig(BaseModel):
    model: str = DEFAULTS["model"]
    embedding_model: str = DEFAULTS["embedding_model"]

class PathPolicy(BaseModel):
    deny: list[str] = Field(default_factory=list)

class Permissions(BaseModel):
    read: PathPolicy = Field(default_factory=PathPolicy)
    write: PathPolicy = Field(default_factory=PathPolicy)

class Commands(BaseModel):
    deny: list[str] = Field(default_factory=list)
    require_approval: list[str] = Field(default_factory=list)

class ToolsConfig(BaseModel):
    # None (default) = every discovered tool is enabled. A non-empty allowlist
    # restricts registration to exactly these tool names.
    enabled: list[str] | None = None
    # Tool names to skip (ignored when an `enabled` allowlist is given).
    disabled: list[str] = Field(default_factory=list)
    # Extra directories scanned for drop-in plugin modules.
    plugin_dirs: list[str] = Field(default_factory=list)

class AgentConfig(BaseModel):
    workspace: str = DEFAULTS["workspace"]
    llm: LlmConfig = Field(default_factory=LlmConfig)
    permissions: Permissions = Field(default_factory=Permissions)
    commands: Commands = Field(default_factory=Commands)
    tools: ToolsConfig = Field(default_factory=ToolsConfig)

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).resolve()

def load_config(path: str = "agent.config.yaml") -> AgentConfig:
    config_file = Path(path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    return AgentConfig(**data)
