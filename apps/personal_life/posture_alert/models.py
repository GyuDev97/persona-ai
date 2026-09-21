"""Dependency-free value objects shared by posture modules."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PoseMetrics:
    """Normalized posture measurements from one visible side of the body."""

    forward_offset: float
    nose_ear_angle_degrees: float
