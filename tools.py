import os
import subprocess
import requests
from pathlib import Path


def read_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"Error: archivo no encontrado: {path}"
    except Exception as e:
        return f"Error leyendo archivo: {e}"


def write_file(path: str, content: str) -> str:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(content, encoding="utf-8")
        return f"OK: archivo escrito en {path}"
    except Exception as e:
        return f"Error escribiendo archivo: {e}"


def run_command(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
            errors="replace",
        )
        parts = []
        if result.stdout:
            parts.append(f"stdout:\n{result.stdout.rstrip()}")
        if result.stderr:
            parts.append(f"stderr:\n{result.stderr.rstrip()}")
        parts.append(f"exit code: {result.returncode}")
        return "\n".join(parts) if parts else "(sin output)"
    except subprocess.TimeoutExpired:
        return "Error: el comando superó el timeout de 30 segundos"
    except Exception as e:
        return f"Error ejecutando comando: {e}"


def list_files(directory: str = ".") -> str:
    try:
        p = Path(directory)
        entries = sorted(p.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        if not entries:
            return "(directorio vacío)"
        lines = []
        for entry in entries:
            tag = "DIR " if entry.is_dir() else "FILE"
            lines.append(f"[{tag}] {entry.name}")
        return "\n".join(lines)
    except FileNotFoundError:
        return f"Error: directorio no encontrado: {directory}"
    except Exception as e:
        return f"Error listando archivos: {e}"


def web_search(query: str) -> str:
    api_key = os.getenv("TAVILY_API_KEY", "")
    if not api_key:
        return (
            "[web_search] TAVILY_API_KEY no configurada en .env — resultado simulado.\n"
            f"Query recibida: {query}\n"
            "Para activar: agregar TAVILY_API_KEY=<tu_key> en .env"
        )
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={"api_key": api_key, "query": query, "max_results": 5},
            timeout=15,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return "Sin resultados para la búsqueda."
        lines = []
        for r in results:
            lines.append(f"Title: {r.get('title', 'Sin título')}")
            lines.append(f"URL:   {r.get('url', '')}")
            lines.append(r.get("content", "")[:400])
            lines.append("")
        return "\n".join(lines).rstrip()
    except Exception as e:
        return f"Error en web_search: {e}"
