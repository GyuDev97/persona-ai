from __future__ import annotations

import logging

import cv2

from .config import SensorSettings


logger = logging.getLogger(__name__)


class EntranceCamera:
    def __init__(self, settings: SensorSettings) -> None:
        self._settings = settings
        self._capture: cv2.VideoCapture | None = None

    def open(self) -> bool:
        self.close()
        backend = cv2.CAP_DSHOW if hasattr(cv2, "CAP_DSHOW") else cv2.CAP_ANY
        capture = cv2.VideoCapture(self._settings.camera_index, backend)
        if not capture.isOpened() and backend != cv2.CAP_ANY:
            capture.release()
            capture = cv2.VideoCapture(self._settings.camera_index)
        if not capture.isOpened():
            logger.error("Camera %s could not be opened.", self._settings.camera_index)
            capture.release()
            return False
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self._settings.camera_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self._settings.camera_height)
        self._capture = capture
        logger.info("Camera %s connected (%sx%s requested).", self._settings.camera_index, self._settings.camera_width, self._settings.camera_height)
        return True

    def read(self):
        if self._capture is None or not self._capture.isOpened():
            return None
        ok, frame = self._capture.read()
        if not ok or frame is None:
            logger.warning("Camera frame read failed; reconnecting.")
            self.close()
            return None
        return frame

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
