# Agent-Orchestra

Agent-Orchestra is a multi-agent coding assistant designed for React + TypeScript + Vite projects. It uses an orchestrator agent to coordinate specialized sub-agents through an OpenAI-compatible LLM

## Architecture

```
src/agent_orchestra/
├── main.py            Entry point — REPL, build agents, wire everything together
├── agent.py           Agent class — plan mode gate, supervision gate, inner-loop invocation
├── loop.py            Core agentic loop — LLM calls, tool dispatch, message history
├── modes.py           Runtime flags — plan_mode and supervision_mode
├── config.py          Configuration loading (agent.config.yaml)
├── tools/
│   ├── tools.py       All tool implementations
│   ├── dispatcher.py  Tool dispatch, permission checks, loop detection
│   ├── tool.py        Tool base class
│   └── tool_type.py   ToolType enum (READ, WRITE, EXECUTE, SEARCH, DELEGATE)
├── memory/            Project memory (persistent JSON) + task state
├── rag/               RAG index builder and search tool
└── observability/     Tracing / Langfuse integration
```

---

## Agents

| Agent | Tools | Responsibility |
|---|---|---|
| **Orchestrator** | `invoke_*` tools | Receives the task, decides which sub-agents to call and in what order |
| **Explorer** | `list_files`, `read_file` | Reads the repository to understand structure and conventions |
| **Researcher** | `rag_search`, `web_search` | Looks up technical information (RAG first, web as fallback) |
| **Implementer** | `write_file`, `edit_file`, `delete_file` | Makes code changes |
| **Tester** | `run_command` | Runs tests, build, type-check, lint |
| **Reviewer** | `list_files`, `read_file` | Validates that changes match the original request |

Typical flow: **explore → (research) → implement → test → review**. The Orchestrator adapts this to each task.

---

## Tools

| Tool | Type | Description |
|---|---|---|
| `list_files` | READ | Lists files and directories inside a path |
| `read_file` | READ | Reads the content of a file |
| `write_file` | WRITE | Creates or replaces a file |
| `edit_file` | WRITE | Find-and-replace within a file |
| `delete_file` | WRITE | Deletes a file |
| `run_command` | EXECUTE | Runs a shell command and returns stdout/stderr |
| `rag_search` | SEARCH | Searches the local RAG index |
| `web_search` | SEARCH | Searches the web via Tavily API |

---

## Modes

Both modes are **off by default** and can be toggled at any time with a session command.

### Plan mode (`/plan`)

When **ON**, the Orchestrator generates a numbered step-by-step plan before calling any tool and presents it to the user:

```
[orchestrator] Proposed plan:

1. Use explorer to list all files in src/
2. Use researcher to find the correct React hook pattern
3. Use implementer to create src/hooks/useFetch.ts
4. Use tester to run `npm run build`
5. Use reviewer to validate the change

Approve plan? [y]es / [n]o (abort) / [m]odify:
```

- **`y`** — approve and execute
- **`n`** — abort the task
- **`m`** — type your modifications; they are appended to the plan and the agent follows the adjusted version

### Supervision mode (`/supervise`)

When **ON**, the agent asks for confirmation before every action that modifies the system:

```
  [SUPERVISION] write_file(path='/home/user/project/src/App.tsx', content='...')
  Allow this action? [y]es / [n]o:
```

**Actions that require confirmation:** `write_file`, `edit_file`, `delete_file`, `run_command`

**Actions that are always allowed:** `read_file`, `list_files`, `rag_search`, `web_search`

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

Required:
- `OPENAI_API_KEY` — OpenAI API key (used for the LLM and embeddings)

Optional:
- `TAVILY_API_KEY` — enables real web search (otherwise `web_search` returns a stub)
- `LANGFUSE_*` — enables tracing via Langfuse (see `.env.example`)

### 3. Configure the agent

```bash
cp docs/agent.config.yaml.example agent.config.yaml
# Edit agent.config.yaml
```

Key settings:

```yaml
workspace: ./my-project          # path to the project the agent will work on

llm:
  model: gpt-4.1                 # LLM model
  embedding_model: text-embedding-3-small

permissions:
  write:
    deny:
      - ".env"                   # files the agent cannot write
  read:
    deny: []

commands:
  deny:
    - "rm -rf"                   # forbidden shell substrings
  require_approval: []           # commands that always need human approval
```

### 4. (Optional) Build the RAG index

If you want the Researcher to search your codebase semantically:

```bash
python -m src.agent_orchestra.rag.build --workspace ./my-project
```

---

## Running

```bash
python -m src.agent_orchestra.main
```

### Session commands

```
/plan        Toggle plan mode
/supervise   Toggle supervision mode
/status      Show current modes, workspace, and model
/help        Show available commands
/exit        Quit
```

### Example tasks

```
Task> List all components in src/components and describe what each one does.
Task> Add a useFetch custom hook and use it in the App component.
Task> The build is failing with a TypeScript error. Find and fix it.
Task> Search the web for how to configure Vite for SSR and add an example config.
```

---

## Project memory

After each task the agent can propose updates to the project memory (architecture notes, conventions, discovered commands, decisions, bugs). These are stored under `<workspace>/.agent/` and automatically injected into future tasks as context.

---

## Observability

Set the `LANGFUSE_*` variables in `.env` to enable tracing. Every agent run, loop iteration, and tool call is recorded as a span so you can inspect the full execution trace in the Langfuse dashboard.

---

## Requirements

- Python 3.11+
- See `requirements.txt` for all dependencies
