"""Non-blocking, click-through Windows screen flash for posture warnings."""

from __future__ import annotations

import logging
import sys
import threading

from .config import PostureSettings


logger = logging.getLogger("posture_alert.screen_alert")


class ScreenAlert:
    """Shows one short red flash sequence without taking keyboard or mouse input."""

    def __init__(self, settings: PostureSettings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._active = False

    def flash(self) -> None:
        if not self._settings.screen_alert_enabled:
            return
        with self._lock:
            if self._active:
                logger.info("화면 경고가 이미 표시 중입니다.")
                return
            self._active = True
        threading.Thread(target=self._run, name="posture-screen-alert", daemon=True).start()

    def _run(self) -> None:
        root = None
        try:
            import tkinter as tk

            root = tk.Tk()
            monitor_bounds = self._monitor_bounds(root)
            overlays = [root] + [tk.Toplevel(root) for _ in monitor_bounds[1:]]
            for overlay, bounds in zip(overlays, monitor_bounds):
                self._configure_overlay(overlay, bounds)
            logger.warning("%s개 화면에 빨간 자세 경고 점멸 시작 (%s회)", len(overlays), self._settings.screen_alert_pulses)

            alphas = [value for _ in range(self._settings.screen_alert_pulses) for value in (self._settings.screen_alert_opacity, 0.0)]

            def next_flash(index: int = 0) -> None:
                if index >= len(alphas):
                    root.destroy()
                    return
                for overlay in overlays:
                    overlay.attributes("-alpha", alphas[index])
                root.after(self._settings.screen_alert_interval_ms, next_flash, index + 1)

            root.after(0, next_flash)
            root.mainloop()
        except Exception:
            logger.exception("화면 자세 경고를 표시하지 못했습니다.")
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass
        finally:
            with self._lock:
                self._active = False

    def _configure_overlay(self, overlay, bounds: tuple[int, int, int, int]) -> None:
        screen_x, screen_y, screen_width, screen_height = bounds
        overlay.overrideredirect(True)
        overlay.configure(bg="#ff0000")
        overlay.attributes("-topmost", True)
        overlay.attributes("-alpha", 0.0)
        overlay.geometry(f"{screen_width}x{screen_height}{screen_x:+d}{screen_y:+d}")
        overlay.update_idletasks()
        overlay.deiconify()
        overlay.lift()
        self._make_click_through(overlay)

    @staticmethod
    def _make_click_through(root) -> None:
        """Let input pass through the overlay on Windows rather than blocking work."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            get_window_long = ctypes.windll.user32.GetWindowLongW
            set_window_long = ctypes.windll.user32.SetWindowLongW
            style = get_window_long(root.winfo_id(), -20)  # GWL_EXSTYLE
            set_window_long(root.winfo_id(), -20, style | 0x00080000 | 0x00000020 | 0x08000000)
        except Exception:
            logger.warning("화면 경고 클릭스루 설정에 실패했습니다.")

    @staticmethod
    def _monitor_bounds(root) -> list[tuple[int, int, int, int]]:
        """Return one rectangle per display so mixed-DPI monitor layouts work reliably."""
        if sys.platform != "win32":
            return [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]
        try:
            import ctypes

            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()

            class Rect(ctypes.Structure):
                _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

            bounds: list[tuple[int, int, int, int]] = []
            callback_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(Rect), ctypes.c_ssize_t)

            def add_monitor(_monitor, _device_context, rect_pointer, _data) -> int:
                rect = rect_pointer.contents
                bounds.append((rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top))
                return 1

            callback = callback_type(add_monitor)
            user32.EnumDisplayMonitors(0, 0, callback, 0)
            if bounds:
                return bounds
        except Exception:
            logger.warning("모니터 목록을 읽지 못해 주 화면에만 경고를 표시합니다.")
        return [(0, 0, root.winfo_screenwidth(), root.winfo_screenheight())]
