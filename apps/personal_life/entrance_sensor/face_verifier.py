from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .config import SensorSettings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FaceMatch:
    matched: bool
    confidence: float
    faces_detected: int


class FaceVerifier:
    def __init__(self, settings: SensorSettings) -> None:
        try:
            from insightface.app import FaceAnalysis
        except ImportError as error:
            raise RuntimeError("Install entrance_sensor/requirements.txt before running the sensor.") from error

        if not settings.owner_embedding_path.exists():
            raise RuntimeError(f"Owner embedding not found: {settings.owner_embedding_path}. Run enroll.py first.")
        embedding = np.load(settings.owner_embedding_path)
        if embedding.ndim != 1 or embedding.size == 0:
            raise RuntimeError("Owner embedding is invalid. Run enroll.py again.")
        self._owner_embedding = _normalize(embedding.astype(np.float32))
        providers = ["CPUExecutionProvider"]
        if settings.face_provider == "gpu":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._app = FaceAnalysis(name="buffalo_l", providers=providers)
        self._app.prepare(ctx_id=0 if settings.face_provider == "gpu" else -1, det_size=(settings.detection_size, settings.detection_size))
        self._threshold = settings.face_match_threshold
        logger.info("Face verifier ready (provider=%s, threshold=%.2f).", settings.face_provider, self._threshold)

    def verify(self, frame: np.ndarray) -> FaceMatch:
        faces = self._app.get(frame)
        best_confidence = 0.0
        for face in faces:
            embedding = getattr(face, "normed_embedding", None)
            if embedding is None:
                embedding = _normalize(face.embedding)
            confidence = float(np.dot(self._owner_embedding, _normalize(np.asarray(embedding, dtype=np.float32))))
            best_confidence = max(best_confidence, confidence)
        return FaceMatch(
            matched=best_confidence >= self._threshold,
            confidence=best_confidence,
            faces_detected=len(faces),
        )


def create_embedding_from_images(image_paths: list[Path], settings: SensorSettings) -> np.ndarray:
    """Create one normalized owner embedding from local enrollment photos."""
    try:
        import cv2
        from insightface.app import FaceAnalysis
    except ImportError as error:
        raise RuntimeError("Install entrance_sensor/requirements.txt before enrollment.") from error

    providers = ["CPUExecutionProvider"]
    if settings.face_provider == "gpu":
        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    app = FaceAnalysis(name="buffalo_l", providers=providers)
    app.prepare(ctx_id=0 if settings.face_provider == "gpu" else -1, det_size=(settings.detection_size, settings.detection_size))
    embeddings: list[np.ndarray] = []
    for path in image_paths:
        image = cv2.imread(str(path))
        if image is None:
            logger.warning("Skipped unreadable enrollment image: %s", path.name)
            continue
        faces = app.get(image)
        if len(faces) != 1:
            logger.warning("Skipped %s: expected one face, found %s.", path.name, len(faces))
            continue
        embeddings.append(_normalize(np.asarray(faces[0].embedding, dtype=np.float32)))
    if not embeddings:
        raise RuntimeError("No enrollment image with exactly one detectable face was found.")
    return _normalize(np.mean(embeddings, axis=0))


def _normalize(vector: np.ndarray) -> np.ndarray:
    norm = float(np.linalg.norm(vector))
    if norm == 0:
        raise RuntimeError("Face embedding has zero length.")
    return vector / norm
