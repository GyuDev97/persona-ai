from fastapi import APIRouter, Header, HTTPException, status

from ...domain.schemas import HomeArrivalEventCreate, PostureSessionEndCreate, PostureSessionStartCreate, PostureStateChangeCreate, RidingEventCreate, RidingEventResponse
from ...services.home_arrival_service import handle_home_arrival, is_valid_api_token
from ...domain.schemas import PostureWarningEventCreate
from ...services.posture_warning_service import handle_posture_warning, is_valid_posture_api_token
from ...services.riding_event_service import handle_riding_event, is_valid_riding_api_token
from ...services.posture_session_service import end_posture_session, record_posture_state_change, start_posture_session


router = APIRouter(prefix="/api/events", tags=["events"])


@router.post("/home-arrival")
def post_home_arrival(
    payload: HomeArrivalEventCreate,
    x_api_token: str | None = Header(default=None),
) -> dict:
    if not is_valid_api_token(x_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    return handle_home_arrival(payload.model_dump())


@router.post("/posture-warning")
def post_posture_warning(
    payload: PostureWarningEventCreate,
    x_api_token: str | None = Header(default=None),
) -> dict:
    if not is_valid_posture_api_token(x_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    return handle_posture_warning(payload.model_dump())


@router.post("/posture-session/start")
def post_posture_session_start(
    payload: PostureSessionStartCreate,
    x_api_token: str | None = Header(default=None),
) -> dict:
    if not is_valid_posture_api_token(x_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    return start_posture_session(payload.model_dump())


@router.post("/posture-state")
def post_posture_state_change(
    payload: PostureStateChangeCreate,
    x_api_token: str | None = Header(default=None),
) -> dict:
    if not is_valid_posture_api_token(x_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    try:
        return record_posture_state_change(payload.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error


@router.post("/posture-session/end")
def post_posture_session_end(
    payload: PostureSessionEndCreate,
    x_api_token: str | None = Header(default=None),
) -> dict:
    if not is_valid_posture_api_token(x_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    return end_posture_session(payload.model_dump())


@router.post("/riding", response_model=RidingEventResponse)
def post_riding_event(
    payload: RidingEventCreate,
    x_api_token: str | None = Header(default=None),
) -> RidingEventResponse:
    if not is_valid_riding_api_token(x_api_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API token")
    return RidingEventResponse(**handle_riding_event(payload.model_dump()))
