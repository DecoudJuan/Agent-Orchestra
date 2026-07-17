"""Tool interface shared by every tool in the system."""

from abc import ABC, abstractmethod
from enum import Enum


class ToolType(str, Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SEARCH = "search"
    DELEGATE = "delegate"


class Tool(ABC):
    name: str
    description: str
    type: ToolType
    parameters_schema: dict

    @abstractmethod
    def execute(self, **kwargs) -> str:
        ...

    def schema(self) -> dict:
        """OpenAI function-calling schema for this tool."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
