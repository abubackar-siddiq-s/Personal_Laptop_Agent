from __future__ import annotations
import json
import logging
import re
import time
import uuid
from typing import Optional, List, Dict, Any
from app.core.db import conn
from app.core.security import audit
from app.tools.registry import registry
from app.providers.router import chat_turn
from app.planner.models import StepDefinition, TaskOut, TaskStepOut, RiskLevel, TaskStatus

logger = logging.getLogger("laptop_ai.planner")

CONSEQUENTIAL_TOOLS = {
    "native.app.launch",
    "native.terminal.diagnostic",
    "native.system.kill_process",
    "browser.click",
    "browser.download_file",
}

class TaskPlanner:
    def __init__(self):
        pass

    async def create_plan(
        self,
        user_request: str,
        objective: Optional[str] = None,
        conversation_id: Optional[int] = None,
        provider: str = "groq",
        model: str = "",
    ) -> dict:
        req_clean = user_request.strip()
        if not req_clean:
            raise ValueError("User request cannot be empty.")

        task_id = f"task_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        obj_clean = objective.strip() if objective else req_clean

        # Generate ordered steps
        steps_def = await self._decompose_request(req_clean, obj_clean, provider=provider, model=model)
        if not steps_def:
            # Fallback to single-step execution
            steps_def = [
                StepDefinition(
                    step_index=1,
                    title="Execute request",
                    description=req_clean,
                    tool_name="native.system.overview",
                    arguments={},
                    dependencies=[],
                    risk="low",
                    requires_approval=False,
                )
            ]

        # Validate plan
        is_valid, val_err = self.validate_plan(steps_def)
        if not is_valid:
            logger.warning("Decomposed plan had invalid dependencies (%s); linearizing steps", val_err)
            for i, s in enumerate(steps_def):
                s.dependencies = [i] if i > 0 else []

        # Determine overall task risk and approval requirement
        has_consequential = any(s.risk in ("high", "consequential") or s.requires_approval for s in steps_def)
        task_risk: RiskLevel = "consequential" if has_consequential else ("medium" if len(steps_def) > 2 else "low")
        approval_req = has_consequential or len(steps_def) >= 4
        initial_status: TaskStatus = "awaiting_approval" if approval_req else "planned"

        title = req_clean[:60] + "..." if len(req_clean) > 60 else req_clean

        with conn() as c:
            c.execute(
                """
                INSERT INTO tasks (
                    id, title, user_request, objective, description,
                    risk_level, status, approval_required, expected_output,
                    completion_criteria, total_steps, completed_steps, conversation_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    task_id,
                    title,
                    req_clean,
                    obj_clean,
                    f"Plan with {len(steps_def)} step(s) to fulfill: {req_clean}",
                    task_risk,
                    initial_status,
                    1 if approval_req else 0,
                    f"Completion of all {len(steps_def)} steps.",
                    "All dependent steps executed successfully without error.",
                    len(steps_def),
                    conversation_id,
                ),
            )

            for s in steps_def:
                step_id = f"step_{task_id}_{s.step_index}"
                step_status = "awaiting_approval" if s.requires_approval else "pending"
                c.execute(
                    """
                    INSERT INTO task_steps (
                        id, task_id, step_index, title, description,
                        tool_name, arguments, dependencies, risk,
                        requires_approval, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        step_id,
                        task_id,
                        s.step_index,
                        s.title,
                        s.description,
                        s.tool_name,
                        json.dumps(s.arguments),
                        json.dumps(s.dependencies),
                        s.risk,
                        1 if s.requires_approval else 0,
                        step_status,
                    ),
                )

        audit("planner.task_created", f"Created task {task_id} with {len(steps_def)} steps (status: {initial_status})")
        return self.get_task(task_id)

    async def _decompose_request(
        self,
        user_request: str,
        objective: str,
        provider: str = "groq",
        model: str = "",
    ) -> List[StepDefinition]:
        """Decompose request into ordered steps with tool assignments and dependencies."""
        q_lower = user_request.lower()

        # 1. Deterministic heuristic decomposition for common patterns
        # Pattern A: System health, audit & telemetry check
        if any(
            k in q_lower
            for k in (
                "system audit",
                "audit system",
                "system health",
                "health check",
                "system overview",
                "hardware",
                "cpu ram",
                "telemetry",
                "cpu",
                "processes",
            )
        ):
            steps = [
                StepDefinition(
                    step_index=1,
                    title="Collect System Telemetry",
                    description="Inspect CPU, memory, battery, and disk resources.",
                    tool_name="native.system.overview",
                    arguments={},
                    dependencies=[],
                    risk="low",
                    requires_approval=False,
                ),
                StepDefinition(
                    step_index=2,
                    title="List Top Processes",
                    description="Inspect running processes for high resource consumption.",
                    tool_name="native.system.processes",
                    arguments={"limit": 10},
                    dependencies=[1],
                    risk="low",
                    requires_approval=False,
                ),
            ]
            if "screenshot" in q_lower:
                steps.append(
                    StepDefinition(
                        step_index=3,
                        title="Capture Desktop Screen",
                        description="Capture current desktop screenshot.",
                        tool_name="native.system.screenshot",
                        arguments={},
                        dependencies=[],
                        risk="low",
                        requires_approval=False,
                    )
                )
            return steps

        # Pattern B: Web navigation, extraction & screenshot
        if any(k in q_lower for k in ("http://", "https://", "browse", "website", "webpage")):
            urls = re.findall(r"https?://[^\s\"']+", user_request)
            target_url = urls[0] if urls else "https://example.com"
            steps = [
                StepDefinition(
                    step_index=1,
                    title=f"Open URL",
                    description=f"Navigate browser to {target_url}",
                    tool_name="browser.open",
                    arguments={"url": target_url},
                    dependencies=[],
                    risk="low",
                    requires_approval=False,
                ),
                StepDefinition(
                    step_index=2,
                    title="Extract Page Text",
                    description="Read the main visible text from the page.",
                    tool_name="browser.get_text",
                    arguments={},
                    dependencies=[1],
                    risk="low",
                    requires_approval=False,
                ),
            ]
            if "screenshot" in q_lower:
                steps.append(
                    StepDefinition(
                        step_index=3,
                        title="Capture Page Screenshot",
                        description="Save a visual snapshot of the page.",
                        tool_name="browser.screenshot",
                        arguments={},
                        dependencies=[1],
                        risk="low",
                        requires_approval=False,
                    )
                )
            return steps

        # Pattern C: File search and read
        if any(k in q_lower for k in ("search file", "find file", "search downloads", "read file", "search documents")):
            return [
                StepDefinition(
                    step_index=1,
                    title="Search Directory",
                    description="Search user folders for matching files.",
                    tool_name="native.files.search",
                    arguments={"query": ""},
                    dependencies=[],
                    risk="low",
                    requires_approval=False,
                ),
            ]

        # Pattern D: Application launch
        if any(k in q_lower for k in ("launch", "open notepad", "open calc", "start application")):
            app_name = "notepad" if "calc" not in q_lower else "calc"
            return [
                StepDefinition(
                    step_index=1,
                    title=f"Launch Application ({app_name})",
                    description=f"Launch Windows application {app_name}.",
                    tool_name="native.app.launch",
                    arguments={"app_name": app_name},
                    dependencies=[],
                    risk="consequential",
                    requires_approval=True,
                )
            ]

        # Pattern E: Terminal diagnostic command
        if any(k in q_lower for k in ("whoami", "ipconfig", "terminal diagnostic", "run diagnostic")):
            cmd = "whoami" if "ipconfig" not in q_lower else "ipconfig"
            return [
                StepDefinition(
                    step_index=1,
                    title=f"Terminal Diagnostic ({cmd})",
                    description=f"Run diagnostic command {cmd}.",
                    tool_name="native.terminal.diagnostic",
                    arguments={"command_id": cmd},
                    dependencies=[],
                    risk="consequential",
                    requires_approval=True,
                )
            ]

        # 2. LLM-Assisted Decomposition for custom multi-step requests
        try:
            available_tools = [
                {"name": t.name, "description": t.description[:90]}
                for t in registry.list()[:20]
            ]
            prompt = (
                f"You are a task planner. Decompose this user request into 1 to 4 ordered executable steps.\n"
                f"Request: \"{user_request}\"\n\n"
                f"Available tools: {json.dumps(available_tools)}\n\n"
                "Output ONLY a valid JSON array of objects with keys: "
                "\"step_index\" (int), \"title\" (str), \"description\" (str), \"tool_name\" (str), "
                "\"arguments\" (dict), \"dependencies\" (list of int step indices).\n"
                "Do NOT include markdown formatting or extra text."
            )
            try:
                res = await chat_turn(
                    provider=provider,
                    model=model or ("gemini-2.5-flash" if provider == "gemini" else "openai/gpt-oss-20b"),
                    messages=[{"role": "user", "content": prompt}],
                )
            except Exception as e_prov:
                if provider != "gemini":
                    res = await chat_turn(
                        provider="gemini",
                        model="gemini-2.5-flash",
                        messages=[{"role": "user", "content": prompt}],
                    )
                else:
                    raise e_prov
            raw = res.content.strip()
            # Extract JSON array
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if m:
                parsed = json.loads(m.group(0))
                steps = []
                for p in parsed:
                    idx = int(p.get("step_index", len(steps) + 1))
                    t_name = p.get("tool_name", "")
                    if t_name not in registry.items:
                        # Fallback to closest matching tool or overview
                        t_name = "native.system.overview"
                    is_consequential = t_name in CONSEQUENTIAL_TOOLS
                    steps.append(
                        StepDefinition(
                            step_index=idx,
                            title=p.get("title", f"Step {idx}"),
                            description=p.get("description", ""),
                            tool_name=t_name,
                            arguments=p.get("arguments", {}) if isinstance(p.get("arguments"), dict) else {},
                            dependencies=p.get("dependencies", [idx - 1] if idx > 1 else []),
                            risk="consequential" if is_consequential else "low",
                            requires_approval=is_consequential,
                        )
                    )
                if steps:
                    return steps
        except Exception as e:
            logger.debug("LLM plan decomposition failed: %s", e)

        # 3. Default fallback single-step plan
        return [
            StepDefinition(
                step_index=1,
                title="Execute Request",
                description=user_request,
                tool_name="native.system.overview",
                arguments={},
                dependencies=[],
                risk="low",
                requires_approval=False,
            )
        ]

    def get_task(self, task_id: str) -> Optional[dict]:
        with conn() as c:
            t = c.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if not t:
                return None
            t_dict = dict(t)
            s_rows = c.execute(
                "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_index ASC",
                (task_id,),
            ).fetchall()
            steps = []
            for sr in s_rows:
                sd = dict(sr)
                try:
                    sd["arguments"] = json.loads(sd["arguments"]) if sd["arguments"] else {}
                except Exception:
                    pass
                try:
                    sd["dependencies"] = json.loads(sd["dependencies"]) if sd["dependencies"] else []
                except Exception:
                    pass
                try:
                    sd["result"] = json.loads(sd["result"]) if sd["result"] else sd["result"]
                except Exception:
                    pass
                steps.append(sd)
            t_dict["steps"] = steps
            return t_dict

    def list_tasks(self, status: Optional[str] = None, limit: int = 50) -> List[dict]:
        with conn() as c:
            sql = "SELECT * FROM tasks"
            params: list = []
            if status:
                sql += " WHERE status = ?"
                params.append(status)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = c.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def validate_plan(self, steps: List[StepDefinition]) -> tuple[bool, Optional[str]]:
        """
        Validate plan dependencies, detect missing information or circular dependencies.
        Returns (is_valid, error_message).
        """
        if not steps:
            return False, "Plan must contain at least one step."

        step_indices = {s.step_index for s in steps}

        # 1. Verify all dependencies refer to existing steps and not self
        for s in steps:
            for dep in s.dependencies:
                if dep not in step_indices:
                    return False, f"Step {s.step_index} depends on non-existent step index {dep}."
                if dep == s.step_index:
                    return False, f"Circular dependency: Step {s.step_index} cannot depend on itself."

        # 2. Cycle detection using DFS graph coloring (0=unvisited, 1=visiting, 2=visited)
        adj: Dict[int, List[int]] = {s.step_index: list(s.dependencies) for s in steps}
        color: Dict[int, int] = {s.step_index: 0 for s in steps}

        def has_cycle(u: int) -> bool:
            color[u] = 1
            for v in adj.get(u, []):
                if color.get(v, 0) == 1:
                    return True
                if color.get(v, 0) == 0:
                    if has_cycle(v):
                        return True
            color[u] = 2
            return False

        for s in steps:
            if color[s.step_index] == 0:
                if has_cycle(s.step_index):
                    return False, f"Circular dependency detected in plan involving step {s.step_index}."

        # 3. Missing tool validation
        for s in steps:
            if not s.tool_name or not s.tool_name.strip():
                return False, f"Step {s.step_index} is missing required tool_name."

        return True, None

    def edit_plan(
        self,
        task_id: str,
        title: Optional[str] = None,
        objective: Optional[str] = None,
        description: Optional[str] = None,
        steps: Optional[List[dict]] = None,
    ) -> dict:
        """Edit an existing task plan before execution."""
        task = self.get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found.")

        if task["status"] in ("running", "completed"):
            raise ValueError(f"Cannot edit task {task_id} in status '{task['status']}'.")

        with conn() as c:
            updates = ["updated_at = CURRENT_TIMESTAMP"]
            params = []
            if title is not None and title.strip():
                updates.append("title = ?")
                params.append(title.strip())
            if objective is not None and objective.strip():
                updates.append("objective = ?")
                params.append(objective.strip())
            if description is not None:
                updates.append("description = ?")
                params.append(description.strip())

            if steps is not None:
                step_defs = []
                for i, sd in enumerate(steps, 1):
                    idx = int(sd.get("step_index", i))
                    t_name = sd.get("tool_name", "native.system.overview")
                    spec = registry.items.get(t_name)
                    is_consequential = t_name in CONSEQUENTIAL_TOOLS or (spec is not None and spec.risk != "read")
                    step_defs.append(
                        StepDefinition(
                            step_index=idx,
                            title=sd.get("title", f"Step {idx}"),
                            description=sd.get("description", ""),
                            tool_name=t_name,
                            arguments=sd.get("arguments", {}) if isinstance(sd.get("arguments"), dict) else {},
                            dependencies=sd.get("dependencies", []),
                            risk="consequential" if is_consequential else "low",
                            requires_approval=is_consequential,
                        )
                    )

                valid, err = self.validate_plan(step_defs)
                if not valid:
                    raise ValueError(f"Invalid plan steps: {err}")

                c.execute("DELETE FROM task_steps WHERE task_id = ?", (task_id,))
                has_consequential = any(s.risk in ("high", "consequential") or s.requires_approval for s in step_defs)
                updates.append("total_steps = ?")
                params.append(len(step_defs))
                updates.append("risk_level = ?")
                params.append("consequential" if has_consequential else ("medium" if len(step_defs) > 2 else "low"))
                updates.append("approval_required = ?")
                params.append(1 if has_consequential else 0)

                for s in step_defs:
                    step_id = f"step_{task_id}_{s.step_index}"
                    step_status = "awaiting_approval" if s.requires_approval else "pending"
                    c.execute(
                        """
                        INSERT INTO task_steps (
                            id, task_id, step_index, title, description,
                            tool_name, arguments, dependencies, risk,
                            requires_approval, status
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            step_id,
                            task_id,
                            s.step_index,
                            s.title,
                            s.description,
                            s.tool_name,
                            json.dumps(s.arguments),
                            json.dumps(s.dependencies),
                            s.risk,
                            1 if s.requires_approval else 0,
                            step_status,
                        ),
                    )

            params.append(task_id)
            c.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
            audit("planner.task_edited", f"Edited plan for task {task_id}")
            return self.get_task(task_id)

    def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[dict]:
        with conn() as c:
            updates = ["status = ?", "updated_at = CURRENT_TIMESTAMP"]
            params = [status]
            if result is not None:
                updates.append("result = ?")
                params.append(result)
            if error is not None:
                updates.append("error = ?")
                params.append(error)
            if status == "running":
                updates.append("started_at = COALESCE(started_at, CURRENT_TIMESTAMP)")
            elif status in ("completed", "failed", "cancelled"):
                updates.append("completed_at = CURRENT_TIMESTAMP")

            params.append(task_id)
            c.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", params)
            audit("planner.task_status", f"Task {task_id} transitioned to '{status}'")
            return self.get_task(task_id)

task_planner = TaskPlanner()
