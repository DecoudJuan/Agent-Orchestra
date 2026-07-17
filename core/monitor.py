"""Observability: every tool call and LLM call goes through AgentMonitor.

Always writes a local JSONL trace. If Langfuse credentials are present in the
environment (LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY), events are also sent
to Langfuse.
"""

import json
import os
import time
from pathlib import Path

# USD per 1M tokens (input, output) — rough estimates for cost reporting.
PRICES = {
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-small": (0.02, 0.0),
}


class AgentMonitor:
    def __init__(self, trace_dir: str = "traces"):
        self.enabled = True
        Path(trace_dir).mkdir(parents=True, exist_ok=True)
        self.trace_path = Path(trace_dir) / f"trace-{int(time.time())}.jsonl"
        self.langfuse = None
        if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
            # Accept either env var name for the host (SDK versions differ).
            host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL")
            if host:
                os.environ.setdefault("LANGFUSE_HOST", host)
                os.environ.setdefault("LANGFUSE_BASE_URL", host)
            try:
                from langfuse import Langfuse

                self.langfuse = Langfuse()
                print("[monitor] Langfuse enabled")
            except Exception as e:
                print(f"[monitor] Langfuse init failed ({e}) — using local JSONL only")
        else:
            print("[monitor] Langfuse keys not set — using local JSONL only")

    def _write(self, record: dict) -> None:
        record["ts"] = time.time()
        with self.trace_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def _to_langfuse(self, name: str, record: dict) -> None:
        if not self.langfuse:
            return
        try:
            self.langfuse.create_event(name=name, input=record.get("input"), output=record.get("output"), metadata=record)
        except Exception as e:
            print(f"[monitor] Langfuse event failed: {e}")

    def log_tool_call(
        self,
        agent: str,
        tool_name: str,
        kwargs: dict,
        result: str,
        blocked: bool,
        latency: float,
        reason: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        record = {
            "type": "tool_call",
            "agent": agent,
            "tool": tool_name,
            "input": kwargs,
            "output": (result or "")[:500],
            "blocked": blocked,
            "reason": reason,
            "latency_s": round(latency, 3),
        }
        self._write(record)
        self._to_langfuse(f"tool:{tool_name}", record)

    def log_llm_call(self, agent: str, model: str, messages: list, response, usage) -> None:
        if not self.enabled:
            return
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        in_price, out_price = PRICES.get(model, (0.0, 0.0))
        cost = (prompt_tokens * in_price + completion_tokens * out_price) / 1_000_000
        record = {
            "type": "llm_call",
            "agent": agent,
            "model": model,
            "input": {"n_messages": len(messages), "last_role": messages[-1]["role"] if messages else None},
            "output": (getattr(response, "content", None) or "")[:500],
            "tool_calls": [tc.function.name for tc in (getattr(response, "tool_calls", None) or [])],
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost_usd": round(cost, 6),
        }
        self._write(record)
        self._to_langfuse(f"llm:{agent}", record)

    def shutdown(self) -> None:
        if self.langfuse:
            try:
                self.langfuse.flush()
            except Exception:
                pass
