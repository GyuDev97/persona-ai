import argparse
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from dataclasses import dataclass


COMTYPES_GEN_DIR = pathlib.Path(__file__).resolve().parent / ".tmp_comtypes_gen"
NCS_PLAYLIST_URL = "https://www.youtube.com/watch?v=K4DyBUG242c&list=PLRBp0Fe2Gpgn8Y9qI-p0aTxVtw8onBSFj"


@dataclass
class MonitorInfo:
    index: int
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def main() -> None:
    args = parse_args()
    result = execute_monitor_command(args.text)
    print(json.dumps(result, ensure_ascii=False))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GYUVIS desktop actions on specific monitors.")
    parser.add_argument("--text", required=True)
    return parser.parse_args()


def execute_monitor_command(text: str) -> dict:
    actions = parse_monitor_actions(text)
    if not actions:
        return {"ok": False, "message": "모니터 번호가 포함된 실행 명령을 찾지 못했습니다."}

    results = []
    for monitor_index, action_text in actions:
        if is_excel_action(action_text):
            results.append(run_excel_action(monitor_index, action_text))
        elif is_youtube_action(action_text):
            results.append(run_youtube_action(monitor_index, action_text))
        elif is_web_action(action_text):
            results.append(run_web_action(monitor_index, action_text))
        else:
            results.append(
                {
                    "ok": False,
                    "monitor": monitor_index,
                    "message": f"{monitor_index}번 모니터 명령을 해석하지 못했습니다.",
                }
            )

    ok = all(item.get("ok") for item in results)
    message = " ".join(str(item.get("message", "")).strip() for item in results if item.get("message"))
    return {"ok": ok, "message": message or "데스크톱 명령을 처리했습니다.", "results": results}


def parse_monitor_actions(text: str) -> list[tuple[int, str]]:
    matches = list(re.finditer(r"(\d+)\s*번\s*모니터(?:에는|에서|으로|로|에)?", text))
    if not matches:
        return []

    actions = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        monitor_index = int(match.group(1))
        action_text = text[start:end].strip(" ,.\n\t")
        if action_text:
            actions.append((monitor_index, action_text))
    return actions


def is_youtube_action(text: str) -> bool:
    normalized = normalize(text)
    return "유튜브" in normalized or "youtube" in normalized


def is_excel_action(text: str) -> bool:
    normalized = normalize(text)
    return "엑셀" in normalized or "excel" in normalized


def is_web_action(text: str) -> bool:
    normalized = normalize(text)
    return any(keyword in normalized for keyword in ("네이버", "구글", "gpt", "지피티", "뉴스", "날씨"))


def run_youtube_action(monitor_index: int, text: str) -> dict:
    query = extract_youtube_query(text)
    if "ncs" in text.lower() or "ncs" in query.lower():
        url = NCS_PLAYLIST_URL
    else:
        url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
    open_browser_url(url)
    move_matching_window_to_monitor(monitor_index, ("youtube", "유튜브"))
    return {
        "ok": True,
        "monitor": monitor_index,
        "message": f"{monitor_index}번 모니터에 유튜브에서 {query}를 검색했습니다.",
    }


def run_web_action(monitor_index: int, text: str) -> dict:
    normalized = normalize(text)
    if "네이버" in normalized:
        url = "https://www.naver.com"
        label = "네이버"
        keywords = ("naver", "네이버")
    elif "구글" in normalized:
        url = "https://www.google.com"
        label = "구글"
        keywords = ("google", "구글")
    elif "gpt" in normalized or "지피티" in normalized:
        url = "https://chatgpt.com"
        label = "GPT"
        keywords = ("chatgpt", "gpt")
    elif "뉴스" in normalized:
        url = "https://news.google.com/topstories?hl=ko&gl=KR&ceid=KR:ko"
        label = "뉴스"
        keywords = ("news", "뉴스")
    else:
        url = "https://www.google.com/search?q=%ED%98%84%EC%9E%AC+%EB%82%A0%EC%94%A8"
        label = "날씨"
        keywords = ("weather", "날씨", "google")

    open_browser_url(url)
    move_matching_window_to_monitor(monitor_index, keywords)
    return {"ok": True, "monitor": monitor_index, "message": f"{monitor_index}번 모니터에 {label}를 열었습니다."}


def run_excel_action(monitor_index: int, text: str) -> dict:
    try:
        import win32com.client
    except ImportError as error:
        raise RuntimeError("pywin32가 필요합니다. pip install pywin32로 설치해주세요.") from error

    value = extract_quoted_or_default_text(text, default="안녕하세요")
    font_size = extract_font_size(text, default=30)

    excel = win32com.client.Dispatch("Excel.Application")
    excel.Visible = True
    workbook = excel.Workbooks.Add()
    sheet = workbook.Worksheets(1)
    cell = sheet.Range("A1")
    cell.Value = value
    cell.Font.Size = font_size
    cell.EntireColumn.AutoFit()

    time.sleep(1.0)
    move_hwnd_to_monitor(int(excel.Hwnd), monitor_index)
    return {
        "ok": True,
        "monitor": monitor_index,
        "message": f"{monitor_index}번 모니터에 엑셀을 열고 A1에 {value}, {font_size}포인트로 입력했습니다.",
    }


def extract_youtube_query(text: str) -> str:
    cleaned = re.sub(r"유튜브|youtube|에서|검색해서|검색해|재생해|재생|틀어줘|틀어|음악을|음악", " ", text, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.~")
    if not cleaned:
        return "NCS music playlist"
    if "ncs" in cleaned.lower():
        return "NCS music playlist"
    return cleaned


def extract_quoted_or_default_text(text: str, default: str) -> str:
    quote_match = re.search(r"['\"]([^'\"]+)['\"]", text)
    if quote_match:
        return quote_match.group(1).strip()
    after_action_match = re.search(r"(?:실행해서|열어서|켜서|열고|실행하고)\s*([가-힣A-Za-z0-9 ]+?)\s*(?:글자|텍스트|문구)", text)
    if after_action_match:
        value = after_action_match.group(1).strip()
        if value:
            return value
    korean_text_match = re.search(r"([가-힣A-Za-z0-9 ]+?)\s*(?:글자|텍스트|문구)", text)
    if korean_text_match:
        value = korean_text_match.group(1).strip()
        value = re.sub(r"^(엑셀|excel|프로그램|실행해서|실행하고|열어서|열고|켜서|에|는)\s*", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"^(엑셀\s*프로그램|excel\s*program)\s*", "", value, flags=re.IGNORECASE).strip()
        if value:
            return value
    return default


def extract_font_size(text: str, default: int) -> int:
    match = re.search(r"(\d+)\s*(?:pt|포인트|폰트|크기)", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return default


def open_browser_url(url: str) -> None:
    try:
        subprocess.Popen(["cmd", "/c", "start", "", "msedge", url])
    except Exception:
        webbrowser.open(url)
    time.sleep(2.0)


def move_matching_window_to_monitor(monitor_index: int, keywords: tuple[str, ...]) -> bool:
    try:
        prepare_comtypes_cache()
        from pywinauto import Desktop
    except ImportError:
        return False

    deadline = time.monotonic() + 8
    selected = None
    while time.monotonic() < deadline:
        windows = [window for window in Desktop(backend="uia").windows() if window.is_visible() and window.window_text()]
        for window in windows:
            title = window.window_text().lower()
            if any(keyword.lower() in title for keyword in keywords):
                selected = window
                break
        if selected is not None:
            break
        time.sleep(0.4)

    if selected is None:
        return False

    try:
        selected.restore()
    except Exception:
        pass
    selected.set_focus()
    monitor = get_monitor(monitor_index)
    selected.move_window(monitor.left, monitor.top, monitor.width, monitor.height, repaint=True)
    return True


def move_hwnd_to_monitor(hwnd: int, monitor_index: int) -> None:
    import win32gui

    monitor = get_monitor(monitor_index)
    win32gui.ShowWindow(hwnd, 9)
    win32gui.MoveWindow(hwnd, monitor.left, monitor.top, monitor.width, monitor.height, True)


def get_monitor(index: int) -> MonitorInfo:
    monitors = list_monitors()
    if index < 1 or index > len(monitors):
        raise RuntimeError(f"{index}번 모니터를 찾지 못했습니다. 현재 감지된 모니터는 {len(monitors)}개입니다.")
    return monitors[index - 1]


def list_monitors() -> list[MonitorInfo]:
    import win32api

    monitors = []
    for index, item in enumerate(win32api.EnumDisplayMonitors(), start=1):
        _handle, _device, rect = item
        left, top, right, bottom = rect
        monitors.append(MonitorInfo(index, left, top, right, bottom))
    monitors.sort(key=lambda monitor: (monitor.left, monitor.top))
    return [MonitorInfo(index + 1, monitor.left, monitor.top, monitor.right, monitor.bottom) for index, monitor in enumerate(monitors)]


def normalize(text: str) -> str:
    return re.sub(r"[\s?!.,~]+", "", text.lower())


def prepare_comtypes_cache() -> None:
    COMTYPES_GEN_DIR.mkdir(parents=True, exist_ok=True)
    try:
        import comtypes.client

        comtypes.client.gen_dir = str(COMTYPES_GEN_DIR)
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"ok": False, "message": str(error)}, ensure_ascii=False))
        sys.exit(1)
