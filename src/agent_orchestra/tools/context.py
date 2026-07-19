from dataclasses import dataclass
from typing import Any


@dataclass
class ToolContext:
    config: Any
    llm_client: Any = None
    embedding_model: str | None = None
    rag_index_dir: str | None = None
