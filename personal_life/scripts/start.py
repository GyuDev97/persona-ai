#!/usr/bin/env python3
"""Run GyuNexus Core with the interpreter that launched this script."""

from __future__ import annotations

import argparse
import subprocess
import sys

from common import APP_ROOT, port_in_use, write_pid


def main() -> int:
    parser = argparse.ArgumentParser(description="Start the cross-platform GyuNexus Core server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Enable Uvicorn reload for development.")
    parser.add_argument("--background", action="store_true", help="Run detached and save a local PID file.")
    args = parser.parse_args()

    if port_in_use("127.0.0.1", args.port):
        print(f"GyuNexus appears to be running on http://127.0.0.1:{args.port}")
        return 0

    command = [sys.executable, "-m", "uvicorn", "main:app", "--host", args.host, "--port", str(args.port)]
    if args.reload:
        command.append("--reload")
    if args.background:
        process = subprocess.Popen(command, cwd=APP_ROOT, close_fds=True)
        write_pid(process.pid)
        print(f"GyuNexus started in the background (PID {process.pid}) on port {args.port}.")
        return 0

    print(f"Starting GyuNexus with {sys.executable} on port {args.port}.")
    return subprocess.run(command, cwd=APP_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
