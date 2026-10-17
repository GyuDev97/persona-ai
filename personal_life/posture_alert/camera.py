from __future__ import annotations

import logging

import cv2

from .config import PostureSettings
from app.services.platform_service import opencv_camera_backend


logger = logging.getLogger(__name__)


class PostureCamera:
    """Small OpenCV camera wrapper with native backend selection."""

    def __init__(self, settings: PostureSettings) -> None:
        self._settings = settings
        self._capture: cv2.VideoCapture | None = None

    def open(self) -> bool:
        self.close()
        backend = opencv_camera_backend(cv2)
        capture = cv2.VideoCapture(self._settings.camera_index, backend)
        if not capture.isOpened() and backend != cv2.CAP_ANY:
            capture.release()
            capture = cv2.VideoCapture(self._settings.camera_index)
        if not capture.isOpened():
            logger.error("자세 감지 카메라 %s번을 열 수 없습니다.", self._settings.camera_index)
            capture.release()
            return False
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings.camera_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings.camera_height)
        self._capture = capture
        logger.info("자세 감지 카메라 %s번 연결됨 (%sx%s 요청).", self._settings.camera_index, self._settings.camera_width, self._settings.camera_height)
        return True

    def read(self):
        if self._capture is None or not self._capture.isOpened():
            return None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            logger.warning("카메라 프레임을 읽지 못했습니다. 재연결합니다.")
            self.close()
            return None
        return frame

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
