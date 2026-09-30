"""Non-fatal runtime checks for the Core status endpoint and launcher."""

from __future__ import annotations

import platform
import sys
from typing import Any

from ..storage.database import fetch_one
from .platform_service import get_feature_capabilities


def build_environment_check() -> dict[str, Any]:
    capabilities = get_feature_capabilities().as_dict()
    database = _database_status()
    return {
        "os": capabilities.pop("os"),
        "architecture": capabilities.pop("architecture"),
        "python": platform.python_version(),
        "executable": sys.executable,
        "database": database,
        "capabilities": capabilities,
    }


def _database_status() -> dict[str, str]:
    try:
        fetch_one("SELECT 1 AS ok")
        return {"status": "ok"}
    except Exception as error:
        # Never expose a connection string, username, or password in a status
        # response. The error class is sufficient to distinguish configuration
        # from a healthy local SQLite database.
        return {"status": "unavailable", "reason": type(error).__name__}
