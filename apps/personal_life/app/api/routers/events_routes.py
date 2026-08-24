from fastapi import APIRouter, Header, HTTPException, status

from ...domain.schemas import HomeArrivalEventCreate
from ...services.home_arrival_service import handle_home_arrival, is_valid_api_token
from ...domain.schemas import PostureWarningEventCreate
from ...services.posture_warning_service import handle_posture_warning, is_valid_posture_api_token


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
