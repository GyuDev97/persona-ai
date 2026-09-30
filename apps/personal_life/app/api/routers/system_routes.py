from datetime import datetime

from fastapi import APIRouter

from ...config import get_settings
from ...domain.schemas import AssistantStatusResponse
from ...services.system_status_service import build_system_status
from ...services.environment_check_service import build_environment_check


router = APIRouter()


@router.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


@router.get("/system/status")
def get_system_status() -> dict:
    return build_system_status()


@router.get("/system/environment")
def get_system_environment() -> dict:
    """Report optional OS integrations without making them startup requirements."""
    return build_environment_check()


@router.get("/assistant/status", response_model=AssistantStatusResponse)
def get_assistant_status() -> AssistantStatusResponse:
    settings = get_settings()
    return AssistantStatusResponse(
        ai_enabled=settings.has_openai,
        mode="openai" if settings.has_openai else "fallback",
        model=settings.openai_model if settings.has_openai else None,
    )
