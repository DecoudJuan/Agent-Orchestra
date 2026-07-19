"""Dependencies handed to a tool at discovery time.

A plugin's :meth:`Tool.build` receives a ``ToolContext`` so it can grab whatever
it needs (LLM client, embedding model, RAG index path, config) without the
harness core knowing which tools require what. Simple tools ignore it.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolContext:
    config: Any
    llm_client: Any = None
    embedding_model: str | None = None
    rag_index_dir: str | None = None
