# Roadmap

## Hecho

- [x] Harness del TP en clase conservado e integrado: `harness.py` sigue siendo el inner loop de tool-use; todos los agentes lo usan vía `BaseAgent.run()` (guardrails/supervisión evolucionaron a `core/config.py` + `core/dispatcher.py`, el outer loop de `agent.py` a `main.py`).
- [x] Arquitectura multi-agente: orchestrator + 5 subagentes (explorer, researcher, implementer, tester, reviewer) como instancias de `BaseAgent`, factories en `agents.py`.
- [x] `SubagentTool` (type DELEGATE): el orchestrator solo ve subagentes como tools; jerarquía de un nivel, ejecución secuencial.
- [x] Estado compartido: `TaskState` (dueño: orchestrator, único punto de escritura `apply()`), persistido en `.agent/sessions/{task_id}.json`.
- [x] Memoria persistente por proyecto: `ProjectMemory` en `{workspace}/.agent/memory/` (lectura filtrada por agente, escritura solo vía `proposed_memory_update`).
- [x] Config + políticas: `agent.config.yaml` validado con pydantic; `ToolDispatcher` con chequeo genérico por `ToolType` (read/write deny, comandos prohibidos, aprobación de comandos).
- [x] Detección de loops: `ActionTracker` + excepción `LoopDetected` desde el dispatcher.
- [x] Observabilidad: `AgentMonitor` — JSONL local siempre (`traces/`), Langfuse si hay keys en `.env`.
- [x] Tools (8) en `tools.py`, incluida infraestructura RAG (`rag_search` con ChromaDB) y `rag/build_index.py` (chunking por heading + embeddings OpenAI).

## Pendiente

- [ ] **Corpus RAG**: agregar documentos markdown (React hooks/estado, TypeScript Handbook, guía de Vite) en `rag/corpus/` y correr `python rag/build_index.py`. Hasta entonces `rag_search` responde que el índice está vacío y el researcher cae a web search.
- [ ] **Caso de uso / target-repo**: definir el proyecto React+TS+Vite sobre el que trabaja el agente (crear `target-repo/` o apuntar `workspace` en `agent.config.yaml` a un repo existente).
- [ ] **Entregables del TP**: README actualizado, evidencia de 2+ tareas ejecutadas (RAG con fuentes, memoria, cambio de estrategia/loop), capturas de Langfuse, reflexión.
- [ ] (Opcional) Sistema de plugins para tools.
