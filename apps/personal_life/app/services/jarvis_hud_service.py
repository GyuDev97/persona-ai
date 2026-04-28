import os
import subprocess
from pathlib import Path

from ..config import APP_ROOT


DEFAULT_HUD_URL = "http://127.0.0.1:8000/gyuvis/standby-v2"


def get_jarvis_hud_path() -> Path:
    configured = os.getenv("GYUVIS_JARVIS_HUD_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()

    return APP_ROOT.parent / "javis-app" / "standby-v2.html"


def get_jarvis_hud_url() -> str:
    return os.getenv("GYUVIS_JARVIS_HUD_URL", DEFAULT_HUD_URL).strip() or DEFAULT_HUD_URL


def launch_jarvis_hud() -> str:
    target = get_jarvis_hud_path()
    if not target.exists():
        raise FileNotFoundError(f"GYUVIS HUD not found: {target}")

    url = get_jarvis_hud_url()
    if not _open_fullscreen(url):
        os.startfile(url)
    return url


def _open_fullscreen(url: str) -> bool:
    browser = _find_browser()
    if not browser:
        return False

    mode = os.getenv("GYUVIS_HUD_FULLSCREEN_MODE", "kiosk").strip().lower()
    fullscreen_arg = "--kiosk" if mode == "kiosk" else "--start-fullscreen"
    profile_dir = APP_ROOT / ".tmp_hud_browser_profile"
    auto_allow_camera = os.getenv("GYUVIS_HUD_AUTO_ALLOW_CAMERA", "1") == "1"
    browser_args = [
        str(browser),
        fullscreen_arg,
        "--new-window",
        "--app=" + url,
        "--user-data-dir=" + str(profile_dir),
    ]
    if auto_allow_camera:
        browser_args.append("--use-fake-ui-for-media-stream")

    try:
        subprocess.Popen(
            browser_args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _find_browser() -> Path | None:
    configured = os.getenv("GYUVIS_HUD_BROWSER_PATH", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path(os.environ.get("PROGRAMFILES", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Google" / "Chrome" / "Application" / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Microsoft" / "Edge" / "Application" / "msedge.exe",
    ]

    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return None
