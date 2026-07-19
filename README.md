# Agent-Orchestra

A multi-agent coding assistant. An orchestrator agent coordinates specialized sub-agents (explorer, researcher, implementer, tester, reviewer) through an OpenAI-compatible LLM to complete coding tasks on a target project.

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
