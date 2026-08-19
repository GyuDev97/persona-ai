import os
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..config import APP_ROOT


DEFAULT_HUD_URL = "http://127.0.0.1:8000/gyuvis/standby-v3?boot=veil&veil=1&autoGesture=1&autoPresence=1&voiceWelcome=0"


def get_jarvis_hud_path() -> Path:
    configured = os.getenv("GYUVIS_JARVIS_HUD_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()

    return APP_ROOT.parent / "javis-app" / "standby-v3.html"


def get_jarvis_hud_url(*, immediate: bool = False) -> str:
    configured = os.getenv("GYUVIS_JARVIS_HUD_URL", DEFAULT_HUD_URL).strip() or DEFAULT_HUD_URL
    return _with_hud_boot_params(configured, immediate=immediate)


def _with_hud_boot_params(url: str, *, immediate: bool = False) -> str:
    """Set the normal veil flow, or bypass it for a home-arrival event."""
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if immediate:
        query["boot"] = "ready"
        query["veil"] = "0"
        query["autoGesture"] = "0"
        query["autoPresence"] = "0"
    else:
        query["boot"] = "veil"
        query["veil"] = "1"
        query["autoGesture"] = "1"
        query["autoPresence"] = "1"
    query["voiceWelcome"] = "0"
    query["cacheBust"] = str(int(time.time() * 1000))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment))


def launch_jarvis_hud(*, immediate: bool = False) -> str:
    target = get_jarvis_hud_path()
    if not target.exists():
        raise FileNotFoundError(f"GYUVIS HUD not found: {target}")

    url = get_jarvis_hud_url(immediate=immediate)
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
    if auto_allow_camera and browser.name.lower() != "msedge.exe":
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
