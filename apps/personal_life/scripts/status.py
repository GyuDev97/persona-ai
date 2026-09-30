#!/usr/bin/env python3
"""Show portable GyuNexus server status without shell-specific commands."""

from __future__ import annotations

import argparse
import json

from common import listening_processes, port_in_use, read_pid


def main() -> int:
    parser = argparse.ArgumentParser(description="Show GyuNexus server status.")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    payload = {
        "port": args.port,
        "listening": port_in_use("127.0.0.1", args.port),
        "processes": listening_processes(args.port),
        "launcher_pid": read_pid(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if payload["listening"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
