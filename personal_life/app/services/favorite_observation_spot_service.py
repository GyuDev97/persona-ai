"""Settings-backed favorite Night Sky locations.

Coordinates are intentionally never inferred from a place name.  The user
confirms the exact camera location in the JSON file before live comparison is
enabled for that spot.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..domain.schemas import FavoriteObservationSpotResponse


SPOTS_PATH = Path(__file__).resolve().parents[2] / "config" / "favorite_observation_spots.json"


def list_favorite_observation_spots(path: Path = SPOTS_PATH) -> list[FavoriteObservationSpotResponse]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_spots = payload.get("spots") if isinstance(payload, dict) else None
    if not isinstance(raw_spots, list):
        raise ValueError("favorite observation spots 설정이 올바르지 않습니다.")

    spots: list[FavoriteObservationSpotResponse] = []
    for item in raw_spots:
        if not isinstance(item, dict):
            continue
        latitude = item.get("latitude")
        longitude = item.get("longitude")
        coordinate_status = "ready" if latitude is not None and longitude is not None else "requires_confirmation"
        spots.append(
            FavoriteObservationSpotResponse(
                id=str(item["id"]),
                name=str(item["name"]),
                region=str(item["region"]),
                latitude=float(latitude) if latitude is not None else None,
                longitude=float(longitude) if longitude is not None else None,
                timezone=str(item.get("timezone") or "Asia/Seoul"),
                coordinate_status=coordinate_status,
                coordinate_note=str(item.get("coordinate_note") or "") or None,
            )
        )
    return spots


def find_favorite_observation_spot(text: str) -> FavoriteObservationSpotResponse | None:
    """Return only an explicitly named favorite; no place name is guessed."""
    compact = "".join(str(text or "").split()).lower()
    if not compact:
        return None
    for spot in list_favorite_observation_spots():
        if "".join(spot.name.split()).lower() in compact:
            return spot
    return None
