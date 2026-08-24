from __future__ import annotations

import math

import cv2

from .config import PostureSettings
from .models import PoseMetrics


class PoseDetector:
    """Extracts side-camera friendly head/neck metrics without storing frames."""

    def __init__(self, settings: PostureSettings) -> None:
        try:
            import mediapipe as mp
        except ImportError as error:
            raise RuntimeError("필수 라이브러리가 없습니다. posture_monitor/requirements.txt를 설치하세요.") from error
        self._mp_pose = mp.solutions.pose
        self._pose = self._mp_pose.Pose(
            static_image_mode=False,
            model_complexity=0,
            enable_segmentation=False,
            min_detection_confidence=settings.pose_detection_confidence,
            min_tracking_confidence=settings.pose_tracking_confidence,
        )

    def detect(self, frame) -> PoseMetrics | None:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._pose.process(rgb_frame)
        if not result.pose_landmarks:
            return None
        landmarks = result.pose_landmarks.landmark
        nose = landmarks[self._mp_pose.PoseLandmark.NOSE]
        candidates = []
        for ear_id, shoulder_id in (
            (self._mp_pose.PoseLandmark.LEFT_EAR, self._mp_pose.PoseLandmark.LEFT_SHOULDER),
            (self._mp_pose.PoseLandmark.RIGHT_EAR, self._mp_pose.PoseLandmark.RIGHT_SHOULDER),
        ):
            ear = landmarks[ear_id]
            shoulder = landmarks[shoulder_id]
            visibility = min(float(nose.visibility), float(ear.visibility), float(shoulder.visibility))
            candidates.append((visibility, ear, shoulder))
        visibility, ear, shoulder = max(candidates, key=lambda item: item[0])
        if visibility < 0.55:
            return None

        face_scale = math.hypot(float(nose.x - ear.x), float(nose.y - ear.y))
        if face_scale < 0.01:
            return None
        forward_offset = abs(float(ear.x - shoulder.x)) / face_scale
        nose_ear_angle_degrees = math.degrees(math.atan2(float(nose.y - ear.y), float(nose.x - ear.x)))
        return PoseMetrics(forward_offset=forward_offset, nose_ear_angle_degrees=nose_ear_angle_degrees)

    def close(self) -> None:
        self._pose.close()
