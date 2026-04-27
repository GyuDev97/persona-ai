import os
from pathlib import Path

from ..config import APP_ROOT


def get_jarvis_hud_path() -> Path:
    configured = os.getenv("GYUVIS_JARVIS_HUD_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()

    return APP_ROOT.parent / "javis-app" / "index.html"


def launch_jarvis_hud() -> Path:
    target = get_jarvis_hud_path()
    if not target.exists():
        raise FileNotFoundError(f"Jarvis HUD not found: {target}")

    os.startfile(str(target))
    return target
