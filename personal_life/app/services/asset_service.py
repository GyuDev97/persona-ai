from datetime import date

from ..domain.schemas import (
    AssetCategorySummary,
    AssetCreate,
    AssetResponse,
    AssetSummaryResponse,
    AssetTrendPoint,
    AssetUpdate,
)
from ..storage.database import execute, fetch_all, fetch_one
from .datetime_utils import ensure_datetime


def create_asset(payload: AssetCreate) -> AssetResponse:
    asset_id = execute(
        """
        INSERT INTO assets (asset_name, category, current_value, as_of_date, notes)
        VALUES (?, ?, ?, ?, ?)
        """,
        (payload.asset_name, payload.category, payload.current_value, payload.as_of_date, payload.notes),
    )
    row = fetch_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
    _record_snapshot(
        asset_id=asset_id,
        asset_name=payload.asset_name,
        category=payload.category,
        current_value=payload.current_value,
        snapshot_date=payload.as_of_date or date.today().isoformat(),
    )
    return _row_to_asset(row)


def list_assets(limit: int = 100) -> list[AssetResponse]:
    rows = fetch_all(
        """
        SELECT *
        FROM assets
        ORDER BY current_value DESC, updated_at DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [_row_to_asset(row) for row in rows]


def update_asset(asset_id: int, payload: AssetUpdate) -> AssetResponse | None:
    existing = fetch_one("SELECT id FROM assets WHERE id = ?", (asset_id,))
    if existing is None:
        return None

    execute(
        """
        UPDATE assets
        SET asset_name = ?, category = ?, current_value = ?, as_of_date = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (payload.asset_name, payload.category, payload.current_value, payload.as_of_date, payload.notes, asset_id),
    )
    _record_snapshot(
        asset_id=asset_id,
        asset_name=payload.asset_name,
        category=payload.category,
        current_value=payload.current_value,
        snapshot_date=payload.as_of_date or date.today().isoformat(),
    )
    row = fetch_one("SELECT * FROM assets WHERE id = ?", (asset_id,))
    return _row_to_asset(row)


def build_asset_summary() -> AssetSummaryResponse:
    assets = list_assets(limit=500)
    total_assets = sum(asset.current_value for asset in assets)

    category_totals: dict[str, int] = {}
    for asset in assets:
        category_totals[asset.category] = category_totals.get(asset.category, 0) + asset.current_value

    categories = [
        AssetCategorySummary(
            category=category,
            total_value=value,
            ratio=round((value / total_assets), 4) if total_assets else 0.0,
        )
        for category, value in sorted(category_totals.items(), key=lambda item: item[1], reverse=True)
    ]

    trend_rows = fetch_all(
        """
        SELECT snapshot_date, SUM(current_value) AS total_value
        FROM asset_snapshots
        GROUP BY snapshot_date
        ORDER BY snapshot_date DESC
        LIMIT 6
        """
    )
    trend_rows = list(reversed(trend_rows))
    trend = [
        AssetTrendPoint(
            snapshot_date=row["snapshot_date"],
            total_value=int(row["total_value"] or 0),
        )
        for row in trend_rows
    ]

    latest_change_amount = 0
    latest_change_rate = 0.0
    if len(trend) >= 2:
        previous = trend[-2].total_value
        current = trend[-1].total_value
        latest_change_amount = current - previous
        latest_change_rate = round((latest_change_amount / previous), 4) if previous else 0.0

    return AssetSummaryResponse(
        total_assets=total_assets,
        categories=categories,
        latest_change_amount=latest_change_amount,
        latest_change_rate=latest_change_rate,
        trend=trend,
    )


def _record_snapshot(
    asset_id: int,
    asset_name: str,
    category: str,
    current_value: int,
    snapshot_date: str,
) -> None:
    existing = fetch_one(
        """
        SELECT id
        FROM asset_snapshots
        WHERE asset_id = ? AND snapshot_date = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (asset_id, snapshot_date),
    )

    if existing is None:
        execute(
            """
            INSERT INTO asset_snapshots (asset_id, asset_name, category, current_value, snapshot_date)
            VALUES (?, ?, ?, ?, ?)
            """,
            (asset_id, asset_name, category, current_value, snapshot_date),
        )
        return

    execute(
        """
        UPDATE asset_snapshots
        SET asset_name = ?, category = ?, current_value = ?
        WHERE id = ?
        """,
        (asset_name, category, current_value, existing["id"]),
    )


def _row_to_asset(row: dict) -> AssetResponse:
    return AssetResponse(
        id=row["id"],
        asset_name=row["asset_name"],
        category=row["category"],
        current_value=int(row["current_value"]),
        as_of_date=row["as_of_date"],
        notes=row["notes"],
        created_at=ensure_datetime(row["created_at"]),
        updated_at=ensure_datetime(row["updated_at"]),
    )
