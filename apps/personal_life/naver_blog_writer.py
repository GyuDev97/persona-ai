import argparse
import os
import pathlib
import sys

from app.config import load_env_file
from app.services.blog_draft_service import get_blog_draft, get_latest_blog_draft, update_blog_draft_status
from app.storage.database import initialize_database


DEFAULT_BLOG_URL = "https://blog.naver.com"
PROFILE_DIR = pathlib.Path(__file__).resolve().parent / ".tmp_naver_blog_profile"
COMTYPES_GEN_DIR = pathlib.Path(__file__).resolve().parent / ".tmp_comtypes_gen"
DEFAULT_MODE = os.getenv("GYUVIS_NAVER_BLOG_MODE", "edge-existing")
DEFAULT_INPUT_MODE = os.getenv("GYUVIS_NAVER_INPUT_MODE", "direct")


def main() -> None:
    load_env_file()
    initialize_database()
    args = parse_args()
    draft = get_blog_draft(args.draft_id) if args.draft_id else get_latest_blog_draft("naver_blog")
    if draft is None:
        raise SystemExit("No naver_blog draft found. Create an agent 2 draft first.")

    fill_naver_blog_editor(draft, headless=args.headless, mode=args.mode, input_mode=args.input_mode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fill a Naver Blog editor with the latest GYUVIS draft.")
    parser.add_argument("--draft-id", type=int, default=None)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--mode", choices=("edge-existing", "playwright"), default=DEFAULT_MODE)
    parser.add_argument("--input-mode", choices=("direct", "paste"), default=DEFAULT_INPUT_MODE)
    return parser.parse_args()


def fill_naver_blog_editor(
    draft: dict,
    headless: bool = False,
    mode: str = DEFAULT_MODE,
    input_mode: str = DEFAULT_INPUT_MODE,
) -> None:
    title = str(draft["title"])
    body = str(draft["body"])

    if mode == "edge-existing":
        fill_existing_edge_window(title, body, input_mode=input_mode)
        update_blog_draft_status(int(draft["id"]), "filled")
        print("Naver Blog draft filled in the existing Edge window. Publish was not clicked.")
        return

    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SystemExit(
            "Playwright is required. Install with: pip install playwright && python -m playwright install chromium"
        ) from error

    blog_url = os.getenv("GYUVIS_NAVER_BLOG_URL", DEFAULT_BLOG_URL)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1550, "height": 950},
            locale="ko-KR",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(blog_url, wait_until="domcontentloaded")

        editor = open_write_editor(page, context)
        fill_editor(editor, title, body)
        update_blog_draft_status(int(draft["id"]), "filled")

        print("Naver Blog draft filled. Publish was not clicked.")
        print("Please review the editor manually before publishing.")
        try:
            page.wait_for_timeout(60 * 60 * 1000)
        except PlaywrightTimeoutError:
            pass
        finally:
            context.close()


def fill_existing_edge_window(title: str, body: str, input_mode: str = DEFAULT_INPUT_MODE) -> None:
    try:
        COMTYPES_GEN_DIR.mkdir(parents=True, exist_ok=True)
        import comtypes.client

        comtypes.client.gen_dir = str(COMTYPES_GEN_DIR)
        from pywinauto import Application, Desktop, keyboard
    except ImportError as error:
        raise SystemExit(
            "pywinauto is required for existing Edge control. Install with: pip install pywinauto"
        ) from error

    desktop = Desktop(backend="uia")
    edge = find_edge_blog_window(Application, desktop)
    focus_window(edge)
    click_write_button(edge)

    editor = wait_for_editor_window(Application, desktop)
    focus_window(editor)
    fill_editor_with_ui_automation(editor, title, body, keyboard, input_mode=input_mode)


def find_edge_blog_window(application_class, desktop):
    try:
        application = application_class(backend="uia").connect(path="msedge.exe", timeout=5)
        windows = list(application.windows())
    except Exception:
        windows = []

    if not windows:
        windows = [window for window in desktop.windows() if window.class_name() == "Chrome_WidgetWin_1"]

    visible_windows = [window for window in windows if window.is_visible() and window.window_text()]
    preferred = [
        window
        for window in visible_windows
        if any(keyword.lower() in window.window_text().lower() for keyword in ("naver", "blog", "네이버", "블로그"))
    ]
    if preferred:
        return preferred[0]
    if visible_windows:
        return visible_windows[0]
    handle = find_edge_window_handle_with_win32()
    if handle:
        try:
            return application_class(backend="uia").connect(handle=handle).window(handle=handle)
        except Exception:
            return application_class(backend="win32").connect(handle=handle).window(handle=handle)
    raise RuntimeError("Open Edge with the Naver Blog main page first, then run this command again.")


def find_edge_window_handle_with_win32() -> int | None:
    try:
        import win32gui
    except Exception:
        return None

    candidates: list[tuple[int, str]] = []

    def collect(hwnd, _extra):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd)
            class_name = win32gui.GetClassName(hwnd)
        except Exception:
            return
        if class_name == "Chrome_WidgetWin_1" and title:
            candidates.append((hwnd, title))

    try:
        win32gui.EnumWindows(collect, None)
    except Exception:
        return None
    if not candidates:
        return None

    preferred_keywords = ("naver", "blog", "네이버", "블로그")
    for hwnd, title in candidates:
        lowered = title.lower()
        if any(keyword in lowered for keyword in preferred_keywords):
            return hwnd
    return candidates[0][0]


def wait_for_editor_window(application_class, desktop, timeout_seconds: float = 12):
    deadline = time_monotonic() + timeout_seconds
    fallback = None
    while time_monotonic() < deadline:
        try:
            application = application_class(backend="uia").connect(path="msedge.exe", timeout=2)
            windows = [window for window in application.windows() if window.is_visible() and window.window_text()]
        except Exception:
            windows = [window for window in desktop.windows() if window.class_name() == "Chrome_WidgetWin_1"]

        for window in windows:
            title = window.window_text().lower()
            if any(keyword in title for keyword in ("글쓰기", "write", "editor", "blog", "블로그")):
                return window
            if "naver" in title or "네이버" in title:
                fallback = window
        handle = find_edge_window_handle_with_win32()
        if handle:
            try:
                fallback = application_class(backend="uia").connect(handle=handle).window(handle=handle)
            except Exception:
                try:
                    fallback = application_class(backend="win32").connect(handle=handle).window(handle=handle)
                except Exception:
                    pass
        sleep_seconds(0.5)
    if fallback is not None:
        return fallback
    raise RuntimeError("Naver Blog editor did not appear after clicking the write button.")


def focus_window(window) -> None:
    try:
        window.restore()
    except Exception:
        pass
    try:
        window.set_focus()
    except Exception:
        force_foreground_window(window)
    sleep_seconds(0.4)


def force_foreground_window(window) -> None:
    try:
        import win32com.client
        import win32con
        import win32gui

        hwnd = int(window.handle)
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        shell = win32com.client.Dispatch("WScript.Shell")
        shell.SendKeys("%")
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        pass


def click_write_button(window) -> None:
    focus_window(window)
    candidates = find_named_controls(window, "글쓰기")
    for candidate in candidates:
        try:
            focus_window(window)
            candidate.click_input()
            sleep_seconds(2.5)
            return
        except Exception:
            try:
                focus_window(window)
                candidate.invoke()
                sleep_seconds(2.5)
                return
            except Exception:
                continue
    raise RuntimeError("Could not find the Naver Blog '글쓰기' button in the open Edge window.")


def fill_editor_with_ui_automation(window, title: str, body: str, keyboard, input_mode: str = DEFAULT_INPUT_MODE) -> None:
    title_control = find_title_control(window)
    if title_control is None:
        raise RuntimeError("Could not find the title placeholder in the Naver Blog editor.")

    focus_window(window)
    title_control.click_input()
    input_text(title_control, title, keyboard, input_mode=input_mode)
    sleep_seconds(0.3)

    body_control = find_body_control(window, title_control)
    if body_control is not None:
        focus_window(window)
        body_control.click_input()
        input_text(body_control, body, keyboard, input_mode=input_mode)
    else:
        keyboard.send_keys("{TAB}")
        sleep_seconds(0.2)
        paste_text(body, keyboard)


def find_title_control(window):
    for control in find_named_controls(window, "제목"):
        if is_text_input_candidate(control):
            return control
    edit_controls = safe_descendants(window, control_type="Edit")
    return edit_controls[0] if edit_controls else None


def find_body_control(window, title_control):
    body_keywords = ("글감과", "일상을", "기록", "본문", "내용")
    for keyword in body_keywords:
        for control in find_named_controls(window, keyword):
            if control.element_info != title_control.element_info:
                return control

    candidates = []
    for control_type in ("Edit", "Document"):
        candidates.extend(safe_descendants(window, control_type=control_type))

    for control in candidates:
        if control.element_info != title_control.element_info:
            return control
    return None


def find_named_controls(window, text: str) -> list:
    matches = []
    for control in safe_descendants(window):
        try:
            name = control.window_text()
        except Exception:
            continue
        if text in name:
            matches.append(control)
    return matches


def safe_descendants(window, control_type: str | None = None) -> list:
    try:
        if control_type is None:
            return list(window.descendants())
        return list(window.descendants(control_type=control_type))
    except Exception:
        return []


def is_text_input_candidate(control) -> bool:
    try:
        control_type = control.element_info.control_type
    except Exception:
        return False
    return control_type in {"Edit", "Document", "Pane", "Custom", "Text"}


def paste_text(text: str, keyboard) -> None:
    set_clipboard_text(text)
    keyboard.send_keys("^v")
    sleep_seconds(0.2)


def input_text(control, text: str, keyboard, input_mode: str = DEFAULT_INPUT_MODE) -> None:
    if input_mode == "direct":
        if set_control_value(control, text):
            return
    paste_text(text, keyboard)


def set_control_value(control, text: str) -> bool:
    for method_name in ("set_edit_text", "set_text"):
        method = getattr(control, method_name, None)
        if method is None:
            continue
        try:
            method(text)
            sleep_seconds(0.2)
            return True
        except Exception:
            continue

    try:
        value_pattern = control.iface_value
        value_pattern.SetValue(text)
        sleep_seconds(0.2)
        return True
    except Exception:
        return False


def set_clipboard_text(text: str) -> None:
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]

    global_memory = kernel32.GlobalAlloc(0x0002, (len(text) + 1) * 2)
    if not global_memory:
        raise RuntimeError("Could not allocate clipboard memory.")
    locked_memory = kernel32.GlobalLock(global_memory)
    if not locked_memory:
        raise RuntimeError("Could not lock clipboard memory.")
    ctypes.memmove(locked_memory, text.encode("utf-16le") + b"\x00\x00", (len(text) + 1) * 2)
    kernel32.GlobalUnlock(global_memory)

    if not user32.OpenClipboard(None):
        raise RuntimeError("Could not open Windows clipboard.")
    try:
        user32.EmptyClipboard()
        user32.SetClipboardData(13, global_memory)
    finally:
        user32.CloseClipboard()


def time_monotonic() -> float:
    import time

    return time.monotonic()


def sleep_seconds(seconds: float) -> None:
    import time

    time.sleep(seconds)


def open_write_editor(page, context):
    before_pages = set(context.pages)
    write_button = page.get_by_text("글쓰기", exact=False).last
    write_button.wait_for(timeout=30_000)
    write_button.click()
    page.wait_for_timeout(1500)

    new_pages = [candidate for candidate in context.pages if candidate not in before_pages]
    editor = new_pages[-1] if new_pages else page
    editor.wait_for_load_state("domcontentloaded")
    editor.wait_for_timeout(2500)
    return editor


def fill_editor(page, title: str, body: str) -> None:
    page = find_editor_frame(page)
    fill_title(page, title)
    fill_body(page, body)


def find_editor_frame(page):
    title_candidates = ("text=제목", "[placeholder*='제목']", "textarea", "[contenteditable='true']")
    for frame in [page, *page.frames]:
        for selector in title_candidates:
            try:
                if frame.locator(selector).first.count() > 0:
                    return frame
            except Exception:
                continue
    return page


def fill_title(page, title: str) -> None:
    selectors = [
        "[placeholder*='제목']",
        "textarea[placeholder*='제목']",
        "input[placeholder*='제목']",
        "textarea",
        "input[type='text']",
        "[contenteditable='true']",
    ]
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            locator.wait_for(timeout=3500)
            locator.click()
            locator.fill(title)
            return
        except Exception:
            continue
    raise RuntimeError("Could not find Naver Blog title field.")


def fill_body(page, body: str) -> None:
    content_editables = page.locator("[contenteditable='true']")
    try:
        count = content_editables.count()
    except Exception:
        count = 0

    if count >= 2:
        target = content_editables.nth(1)
    elif count == 1:
        target = content_editables.first
    else:
        target = page.locator("textarea").last

    target.wait_for(timeout=5000)
    target.click()
    target.fill(body)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
