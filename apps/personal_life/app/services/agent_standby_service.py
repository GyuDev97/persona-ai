from datetime import datetime


DEFAULT_AGENTS = [
    {
        "id": 1,
        "title": "오후 6시 기준 AI 최신뉴스 요약",
        "status": "활성",
        "processing": "완료",
        "tone": "active",
    },
    {
        "id": 2,
        "title": "IT/모바일 관련 블로그 초안 추천",
        "status": "활성",
        "processing": "진행중",
        "tone": "active",
    },
    {
        "id": 3,
        "title": "고급유 노트 앱 업데이트 처리",
        "status": "대기",
        "processing": "대기중",
        "tone": "idle",
    },
    {
        "id": 4,
        "title": "유튜브 아이디어 탐색",
        "status": "서버 오류",
        "processing": "확인중",
        "tone": "error",
    },
]

_active_agent_id: int | None = None
_detail_agent_id: int | None = None
_detail_requested_at: str | None = None


def get_agent_standby_status() -> dict:
    return {
        "active_agent_id": _active_agent_id,
        "detail_agent_id": _detail_agent_id,
        "detail_requested_at": _detail_requested_at,
        "agents": DEFAULT_AGENTS,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def focus_agent(agent_id: int | None) -> dict:
    global _active_agent_id
    valid_ids = {agent["id"] for agent in DEFAULT_AGENTS}
    _active_agent_id = agent_id if agent_id in valid_ids else None
    return get_agent_standby_status()


def open_agent_detail(agent_id: int | None) -> dict:
    global _active_agent_id, _detail_agent_id, _detail_requested_at
    valid_ids = {agent["id"] for agent in DEFAULT_AGENTS}
    selected_agent_id = agent_id if agent_id in valid_ids else None
    _active_agent_id = selected_agent_id
    _detail_agent_id = selected_agent_id
    _detail_requested_at = datetime.now().isoformat(timespec="milliseconds")
    return get_agent_standby_status()
