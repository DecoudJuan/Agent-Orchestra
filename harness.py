import json
import openai
from tools import read_file, write_file, run_command, list_files, web_search
from guardrails import Guardrails, GuardrailError

# OpenAI tool definitions (format distinto a Anthropic)
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lee el contenido de un archivo dado su path.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path del archivo a leer"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Escribe contenido en un archivo, reemplazando su contenido actual.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path del archivo"},
                    "content": {"type": "string", "description": "Contenido a escribir"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Ejecuta un comando de terminal y devuelve stdout y stderr.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Comando a ejecutar"}
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "Lista los archivos y directorios en un directorio.",
            "parameters": {
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Directorio a listar. Default: '.'",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Busca información en la web y devuelve resultados.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Consulta de búsqueda"}
                },
                "required": ["query"],
            },
        },
    },
]

DESTRUCTIVE_TOOLS = {"write_file", "run_command"}

PLAN_SYSTEM = (
    "El usuario activó el modo plan. Tu tarea es ÚNICAMENTE describir "
    "un plan de acción en formato de lista numerada para resolver la solicitud. "
    "No ejecutes ninguna herramienta todavía. Solo describe los pasos que seguirías."
)


def _dispatch(name: str, params: dict) -> str:
    if name == "read_file":
        return read_file(params["path"])
    elif name == "write_file":
        return write_file(params["path"], params["content"])
    elif name == "run_command":
        return run_command(params["command"])
    elif name == "list_files":
        return list_files(params.get("directory", "."))
    elif name == "web_search":
        return web_search(params["query"])
    else:
        return f"Tool desconocida: {name}"


def _assistant_msg(message) -> dict:
    """Convierte un mensaje de respuesta de OpenAI a dict para el historial."""
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


def _generate_plan(client: openai.OpenAI, messages: list, model: str) -> str:
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": PLAN_SYSTEM}] + messages,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


def run(
    client: openai.OpenAI,
    messages: list,
    model: str,
    system: str,
    plan_mode: bool,
    supervision_mode: bool,
    guardrails: Guardrails,
) -> str:
    """
    Inner loop: envía mensajes al LLM, ejecuta tools, repite hasta stop.
    Muta `messages` in-place. Retorna el texto de la respuesta final.
    """
    if plan_mode:
        plan_text = _generate_plan(client, messages, model)
        print(f"\n{'='*52}")
        print("[PLAN MODE] Plan propuesto:")
        print("-" * 52)
        print(plan_text)
        print("=" * 52)
        raw = input("Aprobar? [Enter/s=si | n=cancelar | texto=modificar]: ").strip()

        if raw.lower() == "n":
            messages.append({
                "role": "assistant",
                "content": f"Propuse el siguiente plan:\n{plan_text}\nEl usuario rechazó la ejecución.",
            })
            return "Plan rechazado. No se ejecutaron acciones."

        messages.append({"role": "assistant", "content": f"Mi plan:\n{plan_text}"})
        if raw.lower() in ("", "s"):
            messages.append({"role": "user", "content": "Aprobado, ejecuta el plan."})
        else:
            messages.append({"role": "user", "content": f"Aprobado con ajuste: {raw}"})

    full_messages = [{"role": "system", "content": system}] + messages

    iteration = 0
    while True:
        iteration += 1
        print(f"  [iter {iteration}] consultando LLM...", end=" ", flush=True)

        response = client.chat.completions.create(
            model=model,
            messages=full_messages,
            tools=TOOLS,
            max_tokens=4096,
        )

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
            return f"(finish_reason inesperado: {finish_reason})"

        for tc in (message.tool_calls or []):
            name = tc.function.name
            tid = tc.id
            try:
                params = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                params = {}

            # --- guardrails ---
            try:
                guardrails.check(name, params)
            except GuardrailError as e:
                msg = f"[BLOQUEADO] {e}"
                print(f"\n  [guardrail] {msg}")
                tool_msg = {"role": "tool", "tool_call_id": tid, "content": msg}
                messages.append(tool_msg)
                full_messages.append(tool_msg)
                continue

            # --- supervision ---
            if supervision_mode and name in DESTRUCTIVE_TOOLS:
                preview = str(params)[:120]
                ans = input(f"\n  [SUPERVISION] '{name}' | args: {preview}\n  Ejecutar? [s/n]: ").strip()
                if ans.lower() != "s":
                    msg = "Accion cancelada por el usuario."
                    print("  [supervision] cancelado")
                    tool_msg = {"role": "tool", "tool_call_id": tid, "content": msg}
                    messages.append(tool_msg)
                    full_messages.append(tool_msg)
                    continue

            # --- execute ---
            arg_preview = ", ".join(f"{k}={str(v)[:50]!r}" for k, v in params.items())
            print(f"  [tool] {name}({arg_preview})")
            result = _dispatch(name, params)
            short = result[:100].replace("\n", " ")
            ellipsis = "..." if len(result) > 100 else ""
            print(f"         -> {short}{ellipsis}")

            tool_msg = {"role": "tool", "tool_call_id": tid, "content": result}
            messages.append(tool_msg)
            full_messages.append(tool_msg)
