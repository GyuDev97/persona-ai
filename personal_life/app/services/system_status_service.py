from typing import Any

from ..storage.database import fetch_one
from .agent_status_service import list_agent_statuses
from .agent_standby_service import get_agent_standby_status


def build_system_status() -> dict[str, Any]:
    db_status = "connected" if _is_db_connected() else "disconnected"
    agent_state = _safe_agent_state()
    tracked_statuses = _safe_tracked_statuses()
    return {
        "server": "running",
        "db": db_status,
        # TODO: Persist process heartbeat from pc_agent_runner.py and pc_wake_listener.py.
        "agent_runner": "running",
        "wake_listener": "running",
        "agents": [
            _agent_payload(agent, tracked_statuses)
            for agent in agent_state.get("agents", [])
        ],
    }


def _is_db_connected() -> bool:
    try:
        fetch_one("SELECT 1 AS ok")
        return True
    except Exception:
        return False


def _safe_agent_state() -> dict[str, Any]:
    try:
        return get_agent_standby_status()
    except Exception:
        return {
            "agents": [
                {"id": 1, "status": "idle"},
                {"id": 2, "status": "idle"},
                {"id": 3, "status": "idle"},
                {"id": 4, "status": "idle"},
            ]
        }


def _safe_tracked_statuses() -> dict[int, dict[str, Any]]:
    try:
        return list_agent_statuses()
    except Exception:
        return {}


def _agent_payload(agent: dict[str, Any], tracked_statuses: dict[int, dict[str, Any]]) -> dict[str, Any]:
    agent_id = int(agent.get("id") or 0)
    tracked = tracked_statuses.get(agent_id, {})
    status = tracked.get("status") or _normalize_agent_status(str(agent.get("tone") or agent.get("status") or "idle"))
    payload = {
        "id": agent_id,
        "status": _normalize_agent_status(str(status)),
        "last_run_at": tracked.get("last_run_at"),
        "last_success_at": tracked.get("last_success_at"),
    }
    if tracked.get("last_error"):
        payload["error"] = tracked.get("last_error")
    return payload


def _normalize_agent_status(value: str) -> str:
    lowered = value.lower()
    if lowered in {"active", "running", "활성", "진행중"}:
        return "running"
    if lowered in {"error", "failed", "확인 필요"}:
        return "error"
    return "idle"
