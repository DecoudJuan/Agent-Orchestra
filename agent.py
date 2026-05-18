import os
import sys
from dotenv import load_dotenv
import openai

from harness import run
from guardrails import Guardrails

load_dotenv()

MODEL = "gpt-4o"
GUARDRAILS_FILE = "guardrails.json"

SYSTEM_PROMPT = (
    "Eres un agente de codigo autonomo. Tenes acceso a herramientas para leer y escribir "
    "archivos, ejecutar comandos de terminal, listar directorios y buscar en la web. "
    "Usa las herramientas que necesites para completar cada tarea del usuario. "
    "Cuando termines, explica brevemente que hiciste y el resultado obtenido."
)

HELP_TEXT = """
Comandos disponibles:
  /plan       toggle plan mode  (muestra plan antes de ejecutar, pide aprobacion)
  /supervise  toggle supervision (confirma antes de write_file y run_command)
  /status     muestra el estado actual de los modos y mensajes en historial
  /clear      limpia el historial de conversacion
  /help       muestra esta ayuda
  /exit       salir
"""


def banner(plan_mode: bool, supervision_mode: bool) -> None:
    print()
    print("+--------------------------------------------------+")
    print("|        Agent-Orchestra  --  coding agent         |")
    print("|               powered by OpenAI                  |")
    print("+--------------------------------------------------+")
    print(f"|  plan mode:    {'ON' if plan_mode else 'OFF':<34}|")
    print(f"|  supervision:  {'ON' if supervision_mode else 'OFF':<34}|")
    print("+--------------------------------------------------+")
    print("|  /plan  /supervise  /status  /clear  /help  /exit|")
    print("+--------------------------------------------------+")
    print()


def main() -> None:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: OPENAI_API_KEY no encontrada.")
        print("Configura la variable en .env o en el entorno.")
        sys.exit(1)

    client = openai.OpenAI(api_key=api_key)
    guardrails = Guardrails(GUARDRAILS_FILE)

    plan_mode = False
    supervision_mode = False
    messages: list = []

    banner(plan_mode, supervision_mode)

    # --- outer loop ---
    while True:
        try:
            user_input = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nChau!")
            break

        if not user_input:
            continue

        cmd = user_input.lower()

        if cmd == "/exit":
            print("Chau!")
            break
        elif cmd == "/plan":
            plan_mode = not plan_mode
            print(f"  plan mode: {'ON' if plan_mode else 'OFF'}")
            continue
        elif cmd == "/supervise":
            supervision_mode = not supervision_mode
            print(f"  supervision: {'ON' if supervision_mode else 'OFF'}")
            continue
        elif cmd == "/status":
            print(
                f"  plan={'ON' if plan_mode else 'OFF'} | "
                f"supervision={'ON' if supervision_mode else 'OFF'} | "
                f"mensajes en historial: {len(messages)}"
            )
            continue
        elif cmd == "/clear":
            messages.clear()
            print("  historial limpiado")
            continue
        elif cmd == "/help":
            print(HELP_TEXT)
            continue

        messages.append({"role": "user", "content": user_input})

        try:
            # --- inner loop ---
            response = run(
                client=client,
                messages=messages,
                model=MODEL,
                system=SYSTEM_PROMPT,
                plan_mode=plan_mode,
                supervision_mode=supervision_mode,
                guardrails=guardrails,
            )
            print(f"\nAgent> {response}\n")

        except openai.APIError as e:
            print(f"\n[API error] {e}\n")
            messages.pop()
        except Exception as e:
            print(f"\n[error] {type(e).__name__}: {e}\n")
            messages.pop()


if __name__ == "__main__":
    main()
