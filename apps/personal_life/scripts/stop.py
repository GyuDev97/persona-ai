#!/usr/bin/env python3
"""Stop the GyuNexus process started by the portable launcher."""

from __future__ import annotations

import argparse

from common import listening_processes, read_pid, remove_pid


def main() -> int:
    parser = argparse.ArgumentParser(description="Stop a GyuNexus server started by scripts/start.py.")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--force-port", action="store_true", help="Also stop a listener on the requested port.")
    args = parser.parse_args()
    try:
        import psutil
    except ImportError:
        print("psutil is required for stop.py. Install requirements.txt first.")
        return 2

    target_pids = {pid for pid in [read_pid()] if pid}
    if args.force_port:
        target_pids.update(item["pid"] for item in listening_processes(args.port) if item.get("pid"))
    if not target_pids:
        print("No launcher-managed GyuNexus process found. Use --force-port only when intended.")
        return 1
    for pid in target_pids:
        try:
            psutil.Process(pid).terminate()
            print(f"Requested graceful stop for PID {pid}.")
        except psutil.NoSuchProcess:
            pass
        except psutil.AccessDenied:
            print(f"Permission denied stopping PID {pid}.")
            return 2
    remove_pid()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
