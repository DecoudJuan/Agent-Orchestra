"""Configuration loading and validation (agent.config.yaml)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class LlmConfig(BaseModel):
    model: str = "gpt-4.1"
    embedding_model: str = "text-embedding-3-small"


class PathPolicy(BaseModel):
    deny: list[str] = Field(default_factory=list)


class Permissions(BaseModel):
    read: PathPolicy = Field(default_factory=PathPolicy)
    write: PathPolicy = Field(default_factory=PathPolicy)


class Commands(BaseModel):
    deny: list[str] = Field(default_factory=list)
    require_approval: list[str] = Field(default_factory=list)


class AgentConfig(BaseModel):
    workspace: str = "./target-repo"
    llm: LlmConfig = Field(default_factory=LlmConfig)
    permissions: Permissions = Field(default_factory=Permissions)
    commands: Commands = Field(default_factory=Commands)

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace).resolve()


def load_config(path: str = "agent.config.yaml") -> AgentConfig:
    """Load and validate the config once at process start."""
    config_file = Path(path)
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    data = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
    return AgentConfig(**data)
