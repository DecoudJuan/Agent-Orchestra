"""Inner tool-use loop from the class TP, integrated into the multi-agent system.

Same structure as the original harness: send messages to the LLM, execute tool
calls, feed results back, repeat until stop. What changed to integrate it:
- The global TOOLS list is now a `tools` parameter (each agent has its own).
- `_dispatch`, guardrails and supervision moved into core/dispatcher.py
  (ToolDispatcher applies the agent.config.yaml policies); the loop receives a
  `dispatch` callback and treats its result as the tool output.
- Plan mode moved up: the orchestrator agent now does the planning.
Every BaseAgent.run() drives this same loop.
"""

import json


def _assistant_msg(message) -> dict:
    """Convert an OpenAI response message to a dict for the history."""
    d: dict = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": tc.type,
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
    return d


def run(
    client,
    messages: list,
    model: str,
    system: str,
    tools: list[dict],
    dispatch,
    on_llm_call=None,
    label: str = "agent",
    max_iterations: int = 20,
    max_tool_result_chars: int = 8000,
) -> str | None:
    """
    Inner loop: send messages to the LLM, execute tools, repeat until stop.
    Mutates `messages` in-place. Returns the final response text, or None if
    max_iterations was reached without a final answer.

    dispatch(tool_name: str, kwargs: dict) -> str  executes a tool call
    on_llm_call(messages, response_message, usage)  optional observability hook
    """
    full_messages = [{"role": "system", "content": system}] + messages

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        print(f"  [{label} iter {iteration}] calling LLM...", end=" ", flush=True)

        response = client.chat.completions.create(
            model=model,
            messages=full_messages,
            tools=tools or None,
            max_tokens=4096,
        )

        choice = response.choices[0]
        finish_reason = choice.finish_reason
        message = choice.message
        print(f"finish={finish_reason}")

        if on_llm_call:
            on_llm_call(full_messages, message, response.usage)

        msg_dict = _assistant_msg(message)
        messages.append(msg_dict)
        full_messages.append(msg_dict)

        if finish_reason == "stop":
            return message.content or ""

        if finish_reason != "tool_calls":
            return f"(unexpected finish_reason: {finish_reason})"

        for tc in (message.tool_calls or []):
            try:
                params = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                params = {}

            result = dispatch(tc.function.name, params)
            tool_msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": (result or "(empty result)")[:max_tool_result_chars],
            }
            messages.append(tool_msg)
            full_messages.append(tool_msg)

    return None
