"""Shared cross-platform process helpers for the GYUVIS launchers."""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Any


APP_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = APP_ROOT / ".runtime"
PID_FILE = RUNTIME_DIR / "server.pid"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def listening_processes(port: int) -> list[dict[str, Any]]:
    """Use psutil when installed; status remains useful without it."""
    try:
        import psutil
    except ImportError:
        return []
    result: list[dict[str, Any]] = []
    for connection in psutil.net_connections(kind="inet"):
        if not connection.laddr or connection.laddr.port != port or connection.status != psutil.CONN_LISTEN:
            continue
        payload: dict[str, Any] = {"pid": connection.pid}
        if connection.pid:
            try:
                process = psutil.Process(connection.pid)
                payload["name"] = process.name()
                payload["cmdline"] = process.cmdline()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        result.append(payload)
    return result


def write_pid(pid: int) -> None:
    RUNTIME_DIR.mkdir(exist_ok=True)
    PID_FILE.write_text(json.dumps({"pid": pid}), encoding="utf-8")


def read_pid() -> int | None:
    try:
        payload = json.loads(PID_FILE.read_text(encoding="utf-8"))
        return int(payload["pid"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def remove_pid() -> None:
    PID_FILE.unlink(missing_ok=True)
