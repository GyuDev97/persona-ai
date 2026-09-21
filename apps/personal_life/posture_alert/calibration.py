from __future__ import annotations

import logging
import time

from .camera import PostureCamera
from .config import get_settings
from .pose_detector import PoseDetector
from .posture_analyzer import save_baseline


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger(__name__)
    settings = get_settings()
    logger.info("3초 뒤 정상 자세 캘리브레이션을 시작합니다. 화면을 보며 편하게 앉아주세요.")
    time.sleep(3)
    camera = PostureCamera(settings)
    detector = PoseDetector(settings)
    samples = []
    frame_number = 0
    deadline = time.monotonic() + settings.calibration_seconds
    camera.open()
    try:
        while time.monotonic() < deadline:
            frame = camera.read()
            if frame is None:
                time.sleep(settings.reconnect_seconds)
                camera.open()
                continue
            frame_number += 1
            if frame_number % settings.frame_skip:
                continue
            metrics = detector.detect(frame)
            if metrics is not None:
                samples.append(metrics)
        baseline = save_baseline(settings.baseline_path, samples)
        logger.info("정상 자세 기준 저장 완료 (%s개 샘플): %s", baseline.sample_count, settings.baseline_path)
    finally:
        detector.close()
        camera.close()


if __name__ == "__main__":
    main()
