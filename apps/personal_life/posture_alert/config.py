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


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class PostureSettings:
    camera_index: int
    camera_width: int
    camera_height: int
    frame_skip: int
    reconnect_seconds: float
    pose_detection_confidence: float
    pose_tracking_confidence: float
    calibration_seconds: float
    bad_duration_seconds: float
    cooldown_seconds: int
    api_failure_backoff_seconds: int
    forward_head_delta: float
    head_down_angle_delta_degrees: float
    warning_ratio: float
    smoothing_alpha: float
    api_url: str
    api_token: str
    api_timeout_seconds: float
    screen_alert_enabled: bool
    screen_alert_pulses: int
    screen_alert_opacity: float
    screen_alert_interval_ms: int
    session_source: str
    session_start_detection_seconds: float
    session_end_absence_seconds: float
    state_debounce_seconds: float
    analytics_timeout_seconds: float
    baseline_path: Path


def get_settings() -> PostureSettings:
    load_env_file()
    return PostureSettings(
        camera_index=_int("POSTURE_CAMERA_INDEX", 0),
        camera_width=_int("POSTURE_CAMERA_WIDTH", 640, minimum=320),
        camera_height=_int("POSTURE_CAMERA_HEIGHT", 480, minimum=240),
        frame_skip=max(1, _int("POSTURE_FRAME_SKIP", 3, minimum=1)),
        reconnect_seconds=_float("POSTURE_CAMERA_RECONNECT_SECONDS", 5.0, minimum=1.0),
        pose_detection_confidence=_float("POSTURE_POSE_DETECTION_CONFIDENCE", 0.6, minimum=0),
        pose_tracking_confidence=_float("POSTURE_POSE_TRACKING_CONFIDENCE", 0.6, minimum=0),
        calibration_seconds=_float("POSTURE_CALIBRATION_SECONDS", 5.0, minimum=2.0),
        bad_duration_seconds=_float("POSTURE_BAD_DURATION_SECONDS", 12.0, minimum=1.0),
        cooldown_seconds=_int("POSTURE_COOLDOWN_SECONDS", 1500, minimum=0),
        api_failure_backoff_seconds=_int("POSTURE_API_FAILURE_BACKOFF_SECONDS", 60, minimum=1),
        forward_head_delta=_float("POSTURE_FORWARD_HEAD_DELTA", 0.18, minimum=0.01),
        head_down_angle_delta_degrees=_float("POSTURE_HEAD_DOWN_ANGLE_DELTA_DEGREES", 16.0, minimum=1.0),
        warning_ratio=_float("POSTURE_WARNING_RATIO", 0.65, minimum=0.1),
        smoothing_alpha=_float("POSTURE_SMOOTHING_ALPHA", 0.28, minimum=0.01),
        api_url=os.getenv("POSTURE_API_URL", "http://127.0.0.1:8000/api/events/posture-warning").strip().rstrip("/"),
        api_token=os.getenv("POSTURE_API_TOKEN", "").strip(),
        api_timeout_seconds=_float("POSTURE_API_TIMEOUT_SECONDS", 5.0, minimum=1.0),
        screen_alert_enabled=_bool("POSTURE_SCREEN_ALERT_ENABLED", True),
        screen_alert_pulses=_int("POSTURE_SCREEN_ALERT_PULSES", 3, minimum=1),
        screen_alert_opacity=min(0.9, _float("POSTURE_SCREEN_ALERT_OPACITY", 0.55, minimum=0.1)),
        screen_alert_interval_ms=_int("POSTURE_SCREEN_ALERT_INTERVAL_MS", 170, minimum=50),
        session_source=os.getenv("POSTURE_SESSION_SOURCE", "posture_alert").strip() or "posture_alert",
        session_start_detection_seconds=_float("POSTURE_SESSION_START_DETECTION_SECONDS", 10.0, minimum=1.0),
        session_end_absence_seconds=_float("POSTURE_SESSION_END_ABSENCE_SECONDS", 300.0, minimum=10.0),
        state_debounce_seconds=_float("POSTURE_STATE_DEBOUNCE_SECONDS", 1.5, minimum=0.0),
        analytics_timeout_seconds=_float("POSTURE_ANALYTICS_TIMEOUT_SECONDS", 3.0, minimum=1.0),
        baseline_path=BASE_DIR / "data" / "posture_baseline.json",
    )
