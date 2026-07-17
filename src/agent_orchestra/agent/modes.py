class Modes:
    def __init__(self, plan: bool = False, supervision: bool = False):
        self.plan_mode: bool = plan
        self.supervision_mode: bool = supervision

    def toggle_plan(self) -> bool:
        self.plan_mode = not self.plan_mode
        return self.plan_mode

    def toggle_supervision(self) -> bool:
        self.supervision_mode = not self.supervision_mode
        return self.supervision_mode

    def status(self) -> str:
        plan = "ON" if self.plan_mode else "OFF"
        sup = "ON" if self.supervision_mode else "OFF"
        return f"Plan mode: {plan} | Supervision mode: {sup}"
