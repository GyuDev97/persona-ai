from __future__ import annotations

import logging
import time

from .camera import EntranceCamera
from .config import BASE_DIR, get_settings
from .event_client import HomeArrivalEventClient
from .face_verifier import FaceVerifier


def configure_logging() -> None:
    log_dir = BASE_DIR / "logs"
    log_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_dir / "entrance_sensor.log", encoding="utf-8")],
    )


def main() -> None:
    configure_logging()
    logger = logging.getLogger(__name__)
    settings = get_settings()
    logger.info("Starting entrance sensor: camera=%s frame_skip=%s required_matches=%s cooldown=%ss", settings.camera_index, settings.frame_skip, settings.required_match_frames, settings.cooldown_seconds)
    camera = EntranceCamera(settings)
    verifier = FaceVerifier(settings)
    client = HomeArrivalEventClient(settings)
    camera.open()
    frame_number = 0
    matching_frames = 0
    next_event_allowed_at = 0.0

    try:
        while True:
            frame = camera.read()
            if frame is None:
                time.sleep(settings.reconnect_seconds)
                camera.open()
                continue
            frame_number += 1
            if frame_number % settings.frame_skip:
                continue
            result = verifier.verify(frame)
            if not result.matched:
                if matching_frames:
                    logger.info("Face mismatch/reset: confidence=%.3f faces=%s", result.confidence, result.faces_detected)
                matching_frames = 0
                continue

            matching_frames += 1
            logger.info("Owner match: confidence=%.3f frames=%s/%s", result.confidence, matching_frames, settings.required_match_frames)
            if matching_frames < settings.required_match_frames or time.monotonic() < next_event_allowed_at:
                continue

            response = client.send(result.confidence)
            matching_frames = 0
            if response.sent and (response.accepted or response.duplicate):
                next_event_allowed_at = time.monotonic() + settings.cooldown_seconds
                logger.info("Local cooldown started for %ss.", settings.cooldown_seconds)
            else:
                next_event_allowed_at = time.monotonic() + settings.api_failure_backoff_seconds
                logger.warning("Core is unavailable; backing off event sends for %ss.", settings.api_failure_backoff_seconds)
    except KeyboardInterrupt:
        logger.info("Entrance sensor stopped.")
    finally:
        camera.close()


if __name__ == "__main__":
    main()
