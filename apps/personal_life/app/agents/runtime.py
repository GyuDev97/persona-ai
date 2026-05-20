from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.services.agent_status_service import agent_id_for_task_type, mark_agent_error, mark_agent_running, mark_agent_success
from app.services.agent_task_service import complete_agent_task, fail_agent_task
from app.services.event_bus_service import publish_event


AgentTaskHandler = Callable[[str, str], tuple[str, dict[str, Any]]]


@dataclass(frozen=True)
class AgentRuntimeResult:
    task_id: int
    task_type: str
    agent_id: int
    status: str
    summary: str = ""
    payload: dict[str, Any] | None = None
    error: str = ""


class AgentRuntime:
    def __init__(self, task_handler: AgentTaskHandler) -> None:
        self.task_handler = task_handler

    def run_claimed_task(self, task: Any) -> AgentRuntimeResult:
        task_id = int(task.id)
        task_type = str(task.task_type)
        query = str(task.search_query or task.command_text or "")
        agent_id = agent_id_for_task_type(task_type)

        start_message = f"Task #{task_id} started: {task_type}"
        mark_agent_running(agent_id, start_message)
        publish_event(
            "agent.task.started",
            agent_id=agent_id,
            task_id=task_id,
            message=start_message,
            payload={"task_type": task_type},
        )

        try:
            summary, payload = self.task_handler(task_type, query)
            complete_agent_task(task_id, summary, payload)
        except Exception as error:
            error_message = str(error)
            fail_agent_task(task_id, error_message)
            fail_message = f"Task #{task_id} failed: {error_message}"
            mark_agent_error(agent_id, fail_message)
            publish_event(
                "agent.task.failed",
                agent_id=agent_id,
                task_id=task_id,
                level="error",
                message=fail_message,
                payload={"task_type": task_type, "error": error_message},
            )
            return AgentRuntimeResult(
                task_id=task_id,
                task_type=task_type,
                agent_id=agent_id,
                status="failed",
                error=error_message,
            )

        success_message = f"Task #{task_id} completed: {task_type}"
        mark_agent_success(agent_id, success_message)
        publish_event(
            "agent.task.completed",
            agent_id=agent_id,
            task_id=task_id,
            message=success_message,
            payload={"task_type": task_type, "summary": summary},
        )
        return AgentRuntimeResult(
            task_id=task_id,
            task_type=task_type,
            agent_id=agent_id,
            status="completed",
            summary=summary,
            payload=payload,
        )
