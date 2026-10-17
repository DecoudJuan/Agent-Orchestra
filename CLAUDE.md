# Agent-Orchestra

Multi-agent coding assistant written from scratch (no LangChain, CrewAI or AutoGen). An orchestrator delegates each
step to a specialised sub-agent (explorer, researcher, implementer, tester, reviewer) working on a real project on disk.

## Stack
- Python 3.11+, OpenAI-compatible API (default `gpt-4.1`), `text-embedding-3-small`, ChromaDB, PyYAML, pydantic.
- Optional: Tavily (`web_search`) and Langfuse tracing.

## Commands
```bash
pip install -r requirements.txt
cp .env.example .env                                  # OPENAI_API_KEY is required
cp docs/agent.config.yaml.example agent.config.yaml   # set `workspace` to the target project
python -m src.agent_orchestra.rag.build_index         # optional: index the bundled docs corpus
python -m src.agent_orchestra.main                    # start the `Task>` prompt
```
The repo has no test suite or build step.

## Structure
- `src/agent_orchestra/agent/` — the loop (`loop.py`), `Agent`/sub-agent classes, config loading, `/plan` and `/supervise` modes.
- `src/agent_orchestra/tools/` — `Tool` base class, registry, `dispatcher.py` (permissions, loop detection, iteration cap), `permissions.py`, `plugins/`.
- `src/agent_orchestra/memory/` — task state (persisted, used by `/resume`), project memory, action tracker.
- `src/agent_orchestra/rag/` — `build_index.py` and the markdown `corpus/` (React, TypeScript, Vite).
- `src/agent_orchestra/observability/` — tracing (local JSONL, Langfuse if keys are set).
- `docs/` — architecture (Spanish), demo runs, example config, slides.

## Conventions
- Imports are absolute from the repo root (`from src.agent_orchestra...`), so run with `python -m` from the root.
- A sub-agent never calls another sub-agent: only the orchestrator delegates. Keep it one level deep.
- Each agent gets only the tools its role needs; every tool call goes through the dispatcher.
- New tools: a class inheriting `Tool` in `tools/plugins/` (or a dir listed in `plugin_dirs`).
- If an agent does not know something, it reports being blocked instead of inventing it.
- Never commit `.env` or `agent.config.yaml` (both are git-ignored).

## Git
Commits and PRs sin atribución a Claude: nada de `Co-Authored-By: Claude` ni "Generated with Claude Code".
Commits convencionales (`docs:`, `feat:`, `fix:`). The repo has a co-author (Julian Ritondale): do not rewrite shared history.
