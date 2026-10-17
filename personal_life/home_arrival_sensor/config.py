from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def load_env_file(path: Path | None = None) -> None:
    env_path = path or BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _int(name: str, default: int, *, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _float(name: str, default: float, *, minimum: float = 0) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except ValueError:
        return default


@dataclass(frozen=True)
class SensorSettings:
    camera_index: int
    camera_width: int
    camera_height: int
    frame_skip: int
    reconnect_seconds: float
    face_provider: str
    detection_size: int
    face_match_threshold: float
    required_match_frames: int
    cooldown_seconds: int
    api_failure_backoff_seconds: int
    api_url: str
    api_token: str
    api_timeout_seconds: float
    owner_embedding_path: Path


def get_settings() -> SensorSettings:
    load_env_file()
    return SensorSettings(
        camera_index=_int("CAMERA_INDEX", 0),
        camera_width=_int("CAMERA_WIDTH", 640, minimum=320),
        camera_height=_int("CAMERA_HEIGHT", 480, minimum=240),
        frame_skip=max(1, _int("FRAME_SKIP", 3, minimum=1)),
        reconnect_seconds=_float("CAMERA_RECONNECT_SECONDS", 5.0, minimum=1.0),
        face_provider=os.getenv("FACE_PROVIDER", "cpu").strip().lower(),
        detection_size=_int("FACE_DETECTION_SIZE", 640, minimum=320),
        face_match_threshold=_float("FACE_MATCH_THRESHOLD", 0.45, minimum=0),
        required_match_frames=max(1, _int("REQUIRED_MATCH_FRAMES", 4, minimum=1)),
        cooldown_seconds=_int("COOLDOWN_SECONDS", 600, minimum=0),
        api_failure_backoff_seconds=_int("API_FAILURE_BACKOFF_SECONDS", 60, minimum=1),
        api_url=os.getenv("API_URL", "").strip().rstrip("/"),
        api_token=os.getenv("API_TOKEN", "").strip(),
        api_timeout_seconds=_float("API_TIMEOUT_SECONDS", 5.0, minimum=1.0),
        owner_embedding_path=BASE_DIR / "data" / "owner_embedding.npy",
    )
