from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import PostureSettings
from .models import PoseMetrics


@dataclass(frozen=True)
class PostureBaseline:
    forward_offset: float
    nose_ear_angle_degrees: float
    sample_count: int


@dataclass(frozen=True)
class PostureAssessment:
    state: str
    posture_type: str | None
    score: float
    bad_duration_seconds: float


class PostureAnalyzer:
    def __init__(self, baseline: PostureBaseline, settings: PostureSettings) -> None:
        self._baseline = baseline
        self._settings = settings
        self._smoothed: PoseMetrics | None = None
        self._bad_started_at: float | None = None

    def assess(self, metrics: PoseMetrics | None, now: float) -> PostureAssessment:
        if metrics is None:
            self._bad_started_at = None
            return PostureAssessment("NOT_DETECTED", None, 0.0, 0.0)
        self._smoothed = _smooth(self._smoothed, metrics, self._settings.smoothing_alpha)
        forward_delta = self._smoothed.forward_offset - self._baseline.forward_offset
        angle_delta = abs(_angle_delta(self._smoothed.nose_ear_angle_degrees, self._baseline.nose_ear_angle_degrees))
        forward_ratio = max(0.0, forward_delta / self._settings.forward_head_delta)
        down_ratio = angle_delta / self._settings.head_down_angle_delta_degrees
        score = min(1.0, max(forward_ratio, down_ratio))
        posture_type = "head_down" if down_ratio >= forward_ratio else "forward_head"

        if score < self._settings.warning_ratio:
            return self.reset(score=score)
        if score < 1.0:
            self._bad_started_at = None
            return PostureAssessment("WARNING", posture_type, score, 0.0)
        if self._bad_started_at is None:
            self._bad_started_at = now
        return PostureAssessment("BAD", posture_type, score, now - self._bad_started_at)

    def reset(self, *, score: float = 0.0) -> PostureAssessment:
        self._bad_started_at = None
        return PostureAssessment("NORMAL", None, score, 0.0)


def load_baseline(path: Path) -> PostureBaseline:
    data = json.loads(path.read_text(encoding="utf-8"))
    return PostureBaseline(
        forward_offset=float(data["forward_offset"]),
        nose_ear_angle_degrees=float(data["nose_ear_angle_degrees"]),
        sample_count=int(data["sample_count"]),
    )


def save_baseline(path: Path, samples: list[PoseMetrics]) -> PostureBaseline:
    if not samples:
        raise RuntimeError("캘리브레이션 중 신뢰할 수 있는 자세 랜드마크를 찾지 못했습니다.")
    baseline = PostureBaseline(
        forward_offset=sum(sample.forward_offset for sample in samples) / len(samples),
        nose_ear_angle_degrees=_circular_mean([sample.nose_ear_angle_degrees for sample in samples]),
        sample_count=len(samples),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(baseline), ensure_ascii=False, indent=2), encoding="utf-8")
    return baseline


def _smooth(previous: PoseMetrics | None, current: PoseMetrics, alpha: float) -> PoseMetrics:
    if previous is None:
        return current
    return PoseMetrics(
        forward_offset=previous.forward_offset + alpha * (current.forward_offset - previous.forward_offset),
        nose_ear_angle_degrees=_interpolate_angle(previous.nose_ear_angle_degrees, current.nose_ear_angle_degrees, alpha),
    )


def _angle_delta(current: float, baseline: float) -> float:
    return (current - baseline + 180.0) % 360.0 - 180.0


def _interpolate_angle(previous: float, current: float, alpha: float) -> float:
    return previous + alpha * _angle_delta(current, previous)


def _circular_mean(angles: list[float]) -> float:
    sine = sum(math.sin(math.radians(angle)) for angle in angles)
    cosine = sum(math.cos(math.radians(angle)) for angle in angles)
    return math.degrees(math.atan2(sine, cosine))
