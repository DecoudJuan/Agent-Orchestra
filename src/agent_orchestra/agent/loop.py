import json

from src.agent_orchestra.observability.tracing import mark_error, observe, update_current_span


def _assistant_msg(message) -> dict:
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


@observe(name="agent-loop-iteration", as_type="chain", capture_input=False)
def _call_model(client, *, label: str, iteration: int, model: str, messages: list, tools: list[dict]):
    update_current_span(metadata={"agent": label, "iteration": iteration, "model": model})
    return client.chat.completions.create(
        name=f"{label}:iteration-{iteration}",
        model=model,
        messages=messages,
        tools=tools or None,
        max_tokens=4096,
    )


@observe(name="agent-loop", as_type="agent", capture_input=False)
def run(
    client,
    messages: list,
    model: str,
    system: str,
    tools: list[dict],
    dispatch,
    label: str = "agent",
    max_iterations: int = 20,
    max_tool_result_chars: int = 8000,
    supervision_confirm=None,
) -> str | None:
    update_current_span(metadata={"agent": label, "model": model})
    full_messages = [{"role": "system", "content": system}] + messages

    iteration = 0
    while iteration < max_iterations:
        iteration += 1
        print(f"  [{label} iter {iteration}] calling LLM...", end=" ", flush=True)

        try:
            response = _call_model(
                client,
                label=label,
                iteration=iteration,
                model=model,
                messages=full_messages,
                tools=tools,
            )
        except Exception as e:
            mark_error(f"{type(e).__name__}: {e}")
            raise

        choice = response.choices[0]
        finish_reason = choice.finish_reason
        message = choice.message
        print(f"finish={finish_reason}")

        msg_dict = _assistant_msg(message)
        messages.append(msg_dict)
        full_messages.append(msg_dict)

        if finish_reason == "stop":
            return message.content or ""

        if finish_reason != "tool_calls":
            mark_error(f"unexpected finish_reason: {finish_reason}")
            return f"(unexpected finish_reason: {finish_reason})"

        for tc in (message.tool_calls or []):
            try:
                params = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                params = {}

            if supervision_confirm is not None and not supervision_confirm(tc.function.name, params):
                result = "[DENIED by user] Tool call was rejected during supervision. Adjust your approach."
            else:
                result = dispatch(tc.function.name, params)

            tool_msg = {
                "role": "tool",
                "tool_call_id": tc.id,
                "content": (result or "(empty result)")[:max_tool_result_chars],
            }
            messages.append(tool_msg)
            full_messages.append(tool_msg)

    mark_error(f"stopped after {max_iterations} iterations")
    return None
