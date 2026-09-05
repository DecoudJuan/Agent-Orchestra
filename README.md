# Agent-Orchestra

**A multi-agent coding assistant built from scratch — no LangChain, no CrewAI, no AutoGen. Just the loop.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![OpenAI-compatible](https://img.shields.io/badge/LLM-OpenAI--compatible-10a37f.svg)](https://platform.openai.com/)

An orchestrator agent breaks a coding task into steps and delegates each one to
a specialised sub-agent — explorer, researcher, implementer, tester, reviewer —
running against a real project on disk.

It was written to find out what an agent framework is actually *doing* under the
abstraction. Every part a framework hides is here in the open and editable: the
tool-calling loop, the dispatcher that gates every call, the memory tiers, the
loop detector, the retry policy.

---

## The design

### Orchestrator–workers, exactly one level deep

A sub-agent **cannot call another sub-agent.** Every instruction comes from the
orchestrator.

That is a real constraint, and it is deliberate. Let agents call each other
freely and you get cycles, runaway fan-out, and a trace nobody can read after
the fact. Flattening it to one level makes the whole run a linear sequence of
orchestrator decisions — which is both auditable and debuggable, and costs
almost nothing in capability for tasks this size.

From the orchestrator's side, invoking a sub-agent looks exactly like invoking
any other tool: send an instruction, get a result back. That symmetry is what
keeps the loop small.

The orchestrator is also the only agent that talks to the user, and it **never
writes files or runs commands itself.** It decides *what*; sub-agents decide
*how*.

### The five workers

| Agent | Owns | Notably cannot |
|---|---|---|
| **Explorer** | Reading project layout, conventions, installed tooling | Delete files |
| **Researcher** | Technical lookup — local docs first, then the web, always cited | Write anything |
| **Implementer** | Creating, editing and deleting code; reads a file before touching it | Run commands |
| **Tester** | Running builds, tests, linters, servers; reports exact error output | Edit code |
| **Reviewer** | Checking the changed files against what the user originally asked for | Change the work it reviews |

Each agent is handed **only the tools its role needs**. The explorer has no
delete tool, so no prompt injection can talk it into using one. The permission
boundary is structural, not a request in a system prompt.

### Three tiers of memory

Context management is most of what makes a long agent run work or fall over:

- **Turn context** — the agent's own messages and tool results, discarded the
  moment its turn ends. Lets a sub-agent think without polluting global state.
- **Task state** — what the user asked, what each agent did, which files changed,
  what failed. Persisted to disk, which is what makes `/resume <task_id>` work
  after you kill the process.
- **Project memory** — long-term, survives across tasks: architecture notes,
  code conventions, dependencies, useful commands, past decisions and fixes.
  Each agent receives **only its own slice**, so the implementer is not reading
  the tester's command history.

### The dispatcher

Every tool call from every agent goes through one chokepoint, which does four
things:

1. **Permissions** — path allowlists keep writes inside the workspace; a deny
   list blocks destructive shell commands outright; a second list forces
   approval for things like `npm install` and `git commit`.
2. **Loop detection** — if an agent reads the same file three times running, it
   is stuck in a cycle rather than making progress. The dispatcher breaks it and
   tells the agent to try something else.
3. **Instrumentation** — which agent called which tool, and how long it took.
4. **Iteration cap** — 20 tool calls per turn, then the agent stops and asks the
   user rather than burning tokens in place.

### Retrieval

React, TypeScript and Vite reference docs are chunked **on their own headings**
— so a chunk is a coherent section rather than an arbitrary 512-token window —
embedded with `text-embedding-3-small` and stored in a local ChromaDB. The
researcher searches that first and only reaches for the web when it misses,
which keeps the common case cheap and offline.

### Not guessing

The standing rule across every agent: **if you do not know, say you are blocked.**
An agent that invents a filename, an API or a config key produces work that
looks finished and is not, which costs more to discover than an honest stop.

---

## Two modes worth knowing about

- **`/plan`** — the orchestrator writes out a numbered plan and waits for
  approval before calling a single tool. You can approve, abort, or type
  modifications that get appended to the plan.
- **`/supervise`** — confirmation prompt before *every* action that changes the
  system. Reads and searches stay unprompted, so it stays usable.

Both are documented in full below.

---

## Requirements

- Python 3.11+
- An OpenAI API key

---

## Installation

```bash
git clone https://github.com/DecoudJuan/Agent-Orchestra.git
cd Agent-Orchestra
pip install -r requirements.txt
```

---

## Configuration

### 1. Environment variables

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

| Variable | Required | Description |
|---|---|---|
| `OPENAI_API_KEY` | ✅ | OpenAI API key (LLM + embeddings) |
| `TAVILY_API_KEY` | ⬜ | Enables real web search. Without it, `web_search` returns an error message |
| `LANGFUSE_PUBLIC_KEY` | ⬜ | Enables Langfuse tracing |
| `LANGFUSE_SECRET_KEY` | ⬜ | Enables Langfuse tracing |
| `LANGFUSE_BASE_URL` | ⬜ | Langfuse host (default: `https://us.cloud.langfuse.com`) |

### 2. Agent configuration

```bash
cp docs/agent.config.yaml.example agent.config.yaml
```

Edit `agent.config.yaml`:

```yaml
workspace: ./my-project          # path to the project the agent will work on

llm:
  model: gpt-4.1                 # LLM model to use
  embedding_model: text-embedding-3-small

permissions:
  read:
    deny: [".env", "**/*.pem", "secrets/**", "node_modules/**"]
  write:
    deny: [".github/**", "package-lock.json", ".git/**"]

commands:
  deny: ["rm -rf", "git push", "git reset --hard"]
  require_approval: ["npm install", "npm uninstall", "git commit"]

tools:
  disabled: []       # tool names to skip (all enabled by default)
  plugin_dirs: []    # extra directories scanned for plugin modules
```

The `workspace` field must point to the project you want the agent to work on.

### 3. (Optional) Build the RAG index

To let the Researcher agent search your codebase semantically, build the index once before running:

```bash
python -m src.agent_orchestra.rag.build --workspace ./my-project
```

Rerun this command whenever the codebase changes significantly.

---

## Running

```bash
python -m src.agent_orchestra.main
```

You will get a `Task>` prompt. Type your task in natural language and press Enter.

### Session commands

| Command | Description |
|---|---|
| `/plan` | Toggle plan mode — agent proposes a step-by-step plan before acting |
| `/supervise` | Toggle supervision mode — agent asks for confirmation before every write or execute action |
| `/new` | Clear the current session and start a fresh one (also: `/clear`, `/reset`) |
| `/resume <task_id> [instruction]` | Resume a previous session by its ID; optionally append a new instruction |
| `/status` | Show current modes, workspace path, and model |
| `/help` | Show available commands |
| `/exit` | Quit |

### Example tasks

```
Task> List all components in src/components and describe what each one does.
Task> Add a useFetch custom hook and use it in the App component.
Task> The build is failing with a TypeScript error. Find and fix it.
Task> Search the web for how to configure Vite for SSR and add an example config.
```

---

## Plan mode

When `/plan` is ON, the orchestrator presents a numbered plan before calling any tool:

```
[orchestrator] Proposed plan:

1. Use explorer to list all files in src/
2. Use implementer to create src/hooks/useFetch.ts
3. Use tester to run `npm run build`
4. Use reviewer to validate the change

Approve plan? [y]es / [n]o (abort) / [m]odify:
```

- **`y`** — approve and execute
- **`n`** — abort the task
- **`m`** — type your modifications; they are appended to the plan

## Supervision mode

When `/supervise` is ON, the agent asks before every action that modifies the system:

```
[SUPERVISION] write_file(path='src/hooks/useFetch.ts', content='...')
Allow this action? [y]es / [n]o:
```

Actions always allowed (no prompt): `read_file`, `list_files`, `rag_search`, `web_search`

---

## Adding Custom Tools (Plugins)

Agent-Orchestra supports a plugin system that automatically discovers and registers new tools. You can add new capabilities without modifying the core system.

To add a new tool:
1. Create a new `.py` file inside the `src/agent_orchestra/tools/plugins/` directory (or any custom directory specified in your `agent.config.yaml` under `plugin_dirs`).
2. Define a class that inherits from `Tool`.
3. Implement the required properties (`name`, `description`, `type`, `parameters_schema`) and the `execute` method.

Example:

```python
from src.agent_orchestra.tools.tool import Tool
from src.agent_orchestra.tools.tool_type import ToolType

class MyCustomTool(Tool):
    name = "say_hello"
    description = "A simple tool that says hello to a given name."
    type = ToolType.READ
    parameters_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "The name to greet."}
        },
        "required": ["name"]
    }

    def execute(self, name: str) -> str:
        return f"Hello, {name}!"
```

The system will automatically discover your file on startup, register the tool, and make it available to the agents based on their configuration.
