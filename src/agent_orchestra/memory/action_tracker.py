import hashlib
import json

class ActionTracker:
    def __init__(self):
        self.history: list[dict] = []

    @staticmethod
    def _signature(agent: str, tool_name: str, kwargs: dict, result_sig: str) -> str:
        payload = json.dumps(
            {"agent": agent, "tool": tool_name, "kwargs": kwargs, "result": result_sig},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record(self, agent: str, tool_name: str, kwargs: dict, result_sig: str) -> None:
        self.history.append(
            {"agent": agent, "sig": self._signature(agent, tool_name, kwargs, result_sig)}
        )

    def is_repeating(
        self,
        agent: str,
        tool_name: str,
        kwargs: dict,
        result_sig: str,
        window: int = 4,
        threshold: int = 2,
    ) -> bool:
        sig = self._signature(agent, tool_name, kwargs, result_sig)
        recent = [h for h in self.history if h["agent"] == agent][-window:]
        return sum(1 for h in recent if h["sig"] == sig) >= threshold
