from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
RECOGNIZER_SCRIPT = APP_DIR / "wake_recognizer.ps1"
ELECTRON_CMD = APP_DIR / "node_modules" / ".bin" / "electron.cmd"
WAKE_PATTERNS = (
    "헤이일어나",
    "헤이자비스",
    "자비스일어나",
    "일어나자비스",
    "헤이재비스",
)
MIN_CONFIDENCE = 0.70


def normalize_korean(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", text).lower()


def launch_jarvis_app() -> None:
    if ELECTRON_CMD.exists():
        command = [str(ELECTRON_CMD), "."]
    else:
        command = ["npm.cmd", "start"]

    creationflags = 0
    for flag_name in ("CREATE_NEW_PROCESS_GROUP", "DETACHED_PROCESS", "CREATE_NO_WINDOW"):
        creationflags |= getattr(subprocess, flag_name, 0)

    subprocess.Popen(
        command,
        cwd=str(APP_DIR),
        creationflags=creationflags,
        shell=False,
    )


def is_wake_phrase(text: str, confidence: float) -> bool:
    if confidence < MIN_CONFIDENCE:
        return False

    normalized = normalize_korean(text)
    return any(pattern in normalized for pattern in WAKE_PATTERNS)


def run_listener() -> int:
    if not RECOGNIZER_SCRIPT.exists():
        print(f"wake recognizer not found: {RECOGNIZER_SCRIPT}")
        return 1

    powershell = [
        "powershell",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(RECOGNIZER_SCRIPT),
    ]

    print("Jarvis wake listener starting...")
    print("Wake phrases: 헤이 일어나 / 헤이 자비스 / 자비스 일어나")

    process = subprocess.Popen(
        powershell,
        cwd=str(APP_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue

            if line == "READY":
                print("Microphone is armed and listening.")
                continue

            if not line.startswith("HEARD::"):
                print(line)
                continue

            _, text, confidence_text = line.split("::", 2)
            try:
                confidence = float(confidence_text)
            except ValueError:
                confidence = 0.0

            print(f'heard="{text}" confidence={confidence:.3f}')

            if is_wake_phrase(text, confidence):
                print("Wake phrase detected. Launching JARVIS...")
                launch_jarvis_app()
                time.sleep(2.0)
    except KeyboardInterrupt:
        print("\nStopping wake listener.")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

    return process.returncode or 0


if __name__ == "__main__":
    sys.exit(run_listener())
