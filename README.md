# Agent-Orchestra

A minimal coding agent built from scratch — raw agentic loop, no frameworks, just scaffolding between an LLM and its tools.

## What it is

A harness that connects OpenAI's API with a set of local tools. The agent receives a natural language instruction, decides which tools to use, executes them, feeds the results back to the model, and repeats until the task is complete. When it finishes, it waits for the next instruction — keeping full conversation history across turns.

There are two nested loops:
- **Inner loop**: sends messages to the LLM, executes tool calls, feeds results back, repeats until `stop`.
- **Outer loop**: waits for user input, appends it to the message history, and triggers the inner loop again.

## Project structure

```
agent.py          entry point and outer conversation loop
harness.py        inner loop — LLM calls, tool dispatch, message history management
tools.py          tool implementations
guardrails.py     pre-execution validation against guardrails.json
guardrails.json   restrictions: blocked paths, forbidden commands, allowed directories
requirements.txt
.env.example      template for API keys
```

## Tools

| Tool | Description |
|---|---|
| `read_file` | Reads the content of a file given its path |
| `write_file` | Writes content to a file, replacing its current content |
| `run_command` | Executes a shell command and returns stdout and stderr |
| `list_files` | Lists files and directories inside a given directory |
| `web_search` | Searches the web via Tavily API (stub if no API key configured) |

## Modes

**Plan mode** (`/plan`): before executing anything, the agent generates a numbered action plan and shows it to the user. The user can approve it, reject it, or request modifications. Execution only starts after approval.

**Supervision mode** (`/supervise`): before running any destructive action (`write_file`, `run_command`), the agent asks for explicit confirmation. Read-only tools (`read_file`, `list_files`, `web_search`) always run without prompting.

Both modes are off by default and can be toggled at any time during the session.

## Guardrails

At startup the agent loads `guardrails.json`, which defines:

- `blocked_paths`: files or directories the agent cannot read or write (e.g. `.env`)
- `forbidden_commands`: substrings that cannot appear in any shell command (e.g. `rm -rf`)
- `allowed_dirs`: if set, the agent can only operate within these directories

Every tool call is validated against these rules before execution. Blocked calls return an error message to the model instead of executing.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env and add your OPENAI_API_KEY
```

## Running

```bash
python agent.py
```

### Session commands

```
/plan        toggle plan mode
/supervise   toggle supervision mode
/status      show current modes and message history length
/clear       clear conversation history
/help        show available commands
/exit        quit
```

## Example tasks

- "List the files in this directory and summarize what this project does."
- "Write a Python function that sorts a list of dicts by a given key, save it to utils.py, and run it to verify it works."
- "Read the file bug.py, find what's broken, fix it, and run the tests."
- "Search the web for how to use the httpx library and write a small example."
