from abc import ABC, abstractmethod

from src.agent_orchestra.tools.tool_type import ToolType

class Tool(ABC):
    name: str
    description: str
    type: ToolType
    parameters_schema: dict

    @abstractmethod
    def execute(self, **kwargs) -> str: ...

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }
