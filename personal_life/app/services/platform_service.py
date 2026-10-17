"""Small OS adapter used by GYUVIS runtime features.

Business services should use these helpers instead of invoking ``cmd``,
PowerShell, or ``os.startfile`` directly.  Each operation is best-effort: a
desktop integration failure must not prevent the Core API from running.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import platform
import shutil
import subprocess
import sys
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path


logger = logging.getLogger("gyuos.platform")


@dataclass(frozen=True)
class FeatureCapabilities:
    os: str
    architecture: str
    camera: bool
    posture_monitor: bool
    entrance_sensor: bool
    hud_overlay: str
    tts: bool
    desktop_window_control: bool
    excel_com_automation: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def operating_system() -> str:
    return platform.system() or sys.platform


def is_windows() -> bool:
    return sys.platform == "win32"


def is_macos() -> bool:
    return sys.platform == "darwin"


def module_available(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def get_feature_capabilities() -> FeatureCapabilities:
    camera_ready = module_available("cv2")
    posture_ready = camera_ready and module_available("mediapipe")
    entrance_ready = camera_ready and module_available("insightface") and module_available("onnxruntime")
    window_control = is_windows() and module_available("win32gui")
    return FeatureCapabilities(
        os=operating_system(),
        architecture=platform.machine() or "unknown",
        camera=camera_ready,
        posture_monitor=posture_ready,
        entrance_sensor=entrance_ready,
        hud_overlay="full" if is_windows() else "limited",
        tts=module_available("edge_tts") or bool(shutil.which("say")) or module_available("pyttsx3"),
        desktop_window_control=window_control,
        excel_com_automation=is_windows() and module_available("win32com"),
    )


def opencv_camera_backend(cv2_module):
    """Choose the native OpenCV capture backend without hard-coding it in sensors."""
    if is_windows() and hasattr(cv2_module, "CAP_DSHOW"):
        return cv2_module.CAP_DSHOW
    if is_macos() and hasattr(cv2_module, "CAP_AVFOUNDATION"):
        return cv2_module.CAP_AVFOUNDATION
    return cv2_module.CAP_ANY


def open_url(url: str) -> bool:
    try:
        return bool(webbrowser.open(url))
    except Exception:
        logger.exception("Unable to open URL: %s", url)
        return False


def launch_program(command: list[str], *, quiet: bool = False) -> bool:
    """Launch an explicit executable/argument list without a shell."""
    try:
        kwargs = {"close_fds": True}
        if quiet:
            kwargs.update(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.Popen(command, **kwargs)
        return True
    except (FileNotFoundError, OSError):
        logger.exception("Unable to launch program: %s", command[0] if command else "<empty>")
        return False


def open_path(path: Path) -> bool:
    """Open a user-visible local path with the OS default handler."""
    if not path.exists():
        raise FileNotFoundError(f"Open target does not exist: {path}")
    try:
        if is_windows():
            # os.startfile is only available on Windows and intentionally stays
            # behind this adapter.
            os.startfile(str(path))
            return True
        elif is_macos():
            return launch_program(["open", str(path)])
        else:
            opener = shutil.which("xdg-open")
            if not opener:
                return False
            return launch_program([opener, str(path)])
    except Exception:
        logger.exception("Unable to open path: %s", path)
        return False


def launch_application(application: str) -> bool:
    """Launch a basic local app by logical name where the platform supports it."""
    commands: dict[str, list[str]] = {
        "notepad": ["notepad.exe"] if is_windows() else ["open", "-a", "TextEdit"],
        "calculator": ["calc.exe"] if is_windows() else ["open", "-a", "Calculator"],
    }
    command = commands.get(application)
    if not command:
        return False
    return launch_program(command)


def browser_candidates(configured: str = "") -> list[Path]:
    candidates: list[Path] = [Path(configured).expanduser()] if configured else []
    if is_windows():
        candidates.extend(
            [
                Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
                Path("C:/Program Files (x86)/Google/Chrome/Application/chrome.exe"),
                Path.home() / "AppData/Local/Google/Chrome/Application/chrome.exe",
                Path("C:/Program Files/Microsoft/Edge/Application/msedge.exe"),
                Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
            ]
        )
    elif is_macos():
        candidates.extend(
            [
                Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
                Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ]
        )
    return [candidate for candidate in candidates if candidate.exists()]


def launch_browser(url: str, configured: str = "") -> bool:
    for path in browser_candidates(configured):
        if launch_program([str(path), url]):
            return True
    return open_url(url)
