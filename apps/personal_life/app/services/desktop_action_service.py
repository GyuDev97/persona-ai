import os
import subprocess
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from ..config import APP_ROOT


@dataclass
class DesktopActionResult:
    action_key: str
    target_name: str
    summary: str


_OPEN_VERBS = ["열어", "켜", "실행", "띄워", "보여", "launch", "open"]
_BROWSER_URL = "http://127.0.0.1:8000/"
_CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path.home() / r"AppData\Local\Google\Chrome\Application\chrome.exe",
]


def maybe_run_desktop_action(text: str) -> DesktopActionResult | None:
    normalized = " ".join(text.strip().split())
    lowered = normalized.lower()

    if not _looks_like_desktop_action(normalized, lowered):
        return None

    if any(keyword in normalized for keyword in ["메모장", "노트패드"]) or "notepad" in lowered:
        _launch_process(["notepad.exe"])
        return DesktopActionResult("notepad", "메모장", "네, 메모장 열어드렸어요.")

    if "계산기" in normalized or "calc" in lowered:
        _launch_process(["calc.exe"])
        return DesktopActionResult("calculator", "계산기", "네, 계산기 실행해둘게요.")

    if any(keyword in normalized for keyword in ["탐색기", "파일 탐색기", "폴더"]):
        _open_path(APP_ROOT)
        return DesktopActionResult("explorer", "personal_life 폴더", "네, 작업 폴더를 탐색기로 열어드렸어요.")

    if any(keyword in normalized for keyword in ["브라우저", "크롬", "chrome"]):
        _open_browser()
        return DesktopActionResult("browser", "브라우저", "네, 브라우저를 열어드렸어요.")

    if any(keyword in normalized for keyword in ["지출표", "가계부", "26년5월", "이번 달 엑셀"]):
        target = APP_ROOT / "data" / "26년5월.xlsx"
        _open_path(target)
        return DesktopActionResult("expense_sheet", target.name, "네, 이번 달 지출표 파일 열어드렸어요.")

    if any(keyword in normalized for keyword in ["현금 목표", "3억 목표", "목표 시뮬레이션", "시뮬레이션 파일"]):
        target = APP_ROOT / "data" / "3억_현금목표_시뮬레이션.xlsx"
        _open_path(target)
        return DesktopActionResult("cash_goal_sheet", target.name, "네, 현금 목표 시뮬레이션 파일 열어드렸어요.")

    return None


def _looks_like_desktop_action(text: str, lowered: str) -> bool:
    has_verb = any(verb in text or verb in lowered for verb in _OPEN_VERBS)
    has_target = any(
        keyword in text or keyword in lowered
        for keyword in [
            "메모장",
            "노트패드",
            "notepad",
            "계산기",
            "calc",
            "탐색기",
            "폴더",
            "브라우저",
            "크롬",
            "chrome",
            "지출표",
            "가계부",
            "26년5월",
            "현금 목표",
            "3억 목표",
            "목표 시뮬레이션",
        ]
    )
    return has_verb and has_target


def _launch_process(command: list[str]) -> None:
    subprocess.Popen(command, close_fds=True)


def _open_browser() -> None:
    for path in _CHROME_CANDIDATES:
        if path.exists():
            subprocess.Popen([str(path), _BROWSER_URL], close_fds=True)
            return
    webbrowser.open(_BROWSER_URL)


def _open_path(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"열 대상이 존재하지 않습니다: {path}")
    os.startfile(str(path))
