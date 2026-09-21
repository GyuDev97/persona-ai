from __future__ import annotations

import logging
import time

from .camera import PostureCamera
from .config import BASE_DIR, get_settings
from .gyuvis_client import GyuvisPostureClient
from .pose_detector import PoseDetector
from .posture_analyzer import PostureAnalyzer, load_baseline
from .screen_alert import ScreenAlert
from .session_tracker import PostureSessionTracker, SessionAction


def configure_logging() -> None:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_dir / "posture_alert.log", encoding="utf-8")],
    )


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    settings = get_settings()
    if not settings.baseline_path.exists():
        raise SystemExit(f"정상 자세 기준 파일이 없습니다: {settings.baseline_path}. 먼저 run_calibration.bat을 실행하세요.")
    analyzer = PostureAnalyzer(load_baseline(settings.baseline_path), settings)
    camera = PostureCamera(settings)
    detector = PoseDetector(settings)
    client = GyuvisPostureClient(settings)
    screen_alert = ScreenAlert(settings)
    session_tracker = PostureSessionTracker(settings)
    camera.open()
    frame_number = 0
    next_warning_allowed_at = 0.0
    previous_state: str | None = None

    logger.info("자세 모니터 시작: 나쁜 자세 지속=%.1f초, 재경고 대기=%s초", settings.bad_duration_seconds, settings.cooldown_seconds)
    try:
        while True:
            frame = camera.read()
            if frame is None:
                monotonic_now = time.monotonic()
                wall_now = _now()
                assessment = analyzer.assess(None, monotonic_now)
                _log_state_change(logger, previous_state, assessment.state, assessment.score)
                previous_state = assessment.state
                _send_session_actions(client, session_tracker.observe(assessment, monotonic_now, wall_now), logger, settings.session_source)
                time.sleep(settings.reconnect_seconds)
                camera.open()
                continue
            frame_number += 1
            if frame_number % settings.frame_skip:
                continue
            monotonic_now = time.monotonic()
            wall_now = _now()
            assessment = analyzer.assess(detector.detect(frame), monotonic_now)
            _log_state_change(logger, previous_state, assessment.state, assessment.score)
            previous_state = assessment.state
            _send_session_actions(client, session_tracker.observe(assessment, monotonic_now, wall_now), logger, settings.session_source)
            if assessment.state != "BAD" or assessment.bad_duration_seconds < settings.bad_duration_seconds:
                continue
            if time.monotonic() < next_warning_allowed_at:
                time.sleep(0.5)
                continue

            screen_alert.flash()
            response = client.send_warning(
                assessment.posture_type or "head_down",
                assessment.bad_duration_seconds,
                assessment.score,
                session_id=session_tracker.session_id,
            )
            if response.sent and (response.accepted or response.duplicate):
                next_warning_allowed_at = time.monotonic() + settings.cooldown_seconds
                logger.warning("자세 경고 전송: 유형=%s 지속=%.1f초 점수=%.2f 재경고 대기=%s초", assessment.posture_type, assessment.bad_duration_seconds, assessment.score, settings.cooldown_seconds)
            else:
                next_warning_allowed_at = time.monotonic() + settings.api_failure_backoff_seconds
                logger.warning("자세 경고 전송 실패. %s초 동안 재전송하지 않습니다.", settings.api_failure_backoff_seconds)
    except KeyboardInterrupt:
        logger.info("자세 모니터를 종료했습니다.")
    finally:
        _send_session_actions(client, session_tracker.stop(_now()), logger, settings.session_source)
        detector.close()
        camera.close()


def _log_state_change(logger: logging.Logger, previous: str | None, current: str, score: float) -> None:
    if previous != current:
        if current == "NOT_DETECTED":
            logger.warning("자세 랜드마크를 찾지 못해 타이머를 초기화했습니다.")
        elif current == "BAD":
            logger.warning("나쁜 자세 감지 시작 (점수=%.2f)", score)
        else:
            state_name = {"NORMAL": "정상 자세", "WARNING": "주의 자세"}.get(current, current)
            logger.info("자세 상태: %s (점수=%.2f)", state_name, score)


def _send_session_actions(client: GyuvisPostureClient, actions: list[SessionAction], logger: logging.Logger, source: str) -> None:
    for action in actions:
        if action.kind == "start":
            sent = client.start_session(action.session_id, source, action.state or "NORMAL", action.timestamp)
            logger.info("자세 세션 시작 %s: %s", "전송" if sent else "전송 실패", action.session_id)
        elif action.kind == "state_change":
            sent = client.send_state_change(
                action.session_id,
                action.previous_state or "NORMAL",
                action.state or "NORMAL",
                action.score,
                action.timestamp,
                "debounced_state_change",
            )
            logger.info("자세 상태 변경 %s: %s -> %s", "전송" if sent else "전송 실패", action.previous_state, action.state)
        elif action.kind == "end":
            sent = client.end_session(action.session_id, action.timestamp, action.reason or "monitor_stopped")
            logger.info("자세 세션 종료 %s: %s", "전송" if sent else "전송 실패", action.reason)


def _now():
    from datetime import datetime

    return datetime.now().astimezone()


if __name__ == "__main__":
    main()
