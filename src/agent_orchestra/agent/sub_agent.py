from src.agent_orchestra.agent.agent import Agent
from src.agent_orchestra.memory.project_memory import ProjectMemory
from src.agent_orchestra.memory.task_state import TaskState
from src.agent_orchestra.tools.tool import Tool
from src.agent_orchestra.tools.tool_type import ToolType

SUBAGENT_NAMES = ["explorer", "researcher", "implementer", "tester", "reviewer"]


class SubagentTool(Tool):

    type = ToolType.DELEGATE

    def __init__(
        self,
        subagent: Agent,
        task_state: TaskState,
        memory: ProjectMemory,
        workspace: str,
    ):
        self.subagent = subagent
        self.task_state = task_state
        self.memory = memory
        self.workspace = workspace
        self.name = f"invoke_{subagent.name}"
        self.description = f"Delegate one concrete instruction to the {subagent.name} subagent."
        self.parameters_schema = {
            "type": "object",
            "properties": {
                "instruction": {
                    "type": "string",
                    "description": "Clear, self-contained instruction for the subagent",
                }
            },
            "required": ["instruction"],
        }

    def execute(self, instruction: str) -> str:
        step = self.task_state.new_step(self.subagent.name, instruction)
        print(f"\n[orchestrator] step {step.id} -> {self.subagent.name}: {instruction[:100]}")
        task_input = {
            "step_id": step.id,
            "instruction": instruction,
            "original_request": self.task_state.original_request,
            "workspace": self.workspace,
            "previous_steps": self.task_state.get_summaries_for(SUBAGENT_NAMES),
            "project_memory": self.memory.load_relevant(self.subagent.name, instruction),
        }
        result = self.subagent.run(task_input)
        self.task_state.apply(result)
        if result.proposed_memory_update:
            self.memory.apply_update(result.proposed_memory_update, result.agent, self.task_state.task_id)
        print(f"[orchestrator] step {step.id} <- {self.subagent.name}: {result.status} — {result.summary[:100]}")
        return result.model_dump_json()
