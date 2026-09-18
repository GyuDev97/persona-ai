"""Local-only Windows Ambient AI Overlay for GYUVIS.

The process is invisible while idle.  It receives small JSON events over
localhost and renders listening, analyzing, result, and detail states without
opening a browser window or affecting the FastAPI request if it is not running.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import queue
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import tkinter as tk


TRANSPARENT = "#010203"
CARD_BACKGROUND = "#17212C"
CARD_EDGE = "#536373"
SURFACE = "#202C38"
SURFACE_MUTED = "#1B2631"
TEXT_PRIMARY = "#F4F6F8"
TEXT_SECONDARY = "#AAB7C4"
TEXT_MUTED = "#738394"
BLUE = "#38A9FF"
CYAN = "#52D1FF"
GOOD = "#52D690"
WARNING = "#D6A764"
BAD = "#C97979"
DIM = "#455361"
FONT_FAMILY = "Malgun Gothic"
MARGIN = 34
RESULT_TIMEOUT_MS = 12_000
LISTENING_TIMEOUT_MS = 7_500
ANALYZING_TIMEOUT_MS = 8_000


def _grade_color(grade: str) -> str:
    return {"good": GOOD, "fair": WARNING, "poor": BAD}.get(grade, DIM)


def _weather_score(payload: dict[str, Any]) -> Any:
    breakdown = payload.get("score_breakdown") or {}
    return breakdown.get("weather_score", payload.get("score"))


def _overall_score(payload: dict[str, Any]) -> Any:
    breakdown = payload.get("score_breakdown") or {}
    overall = breakdown.get("overall_score")
    return overall if overall is not None else _weather_score(payload)


def _condition_status(payload: dict[str, Any]) -> tuple[str, str]:
    score = _overall_score(payload)
    if score is None:
        return "확인 중", DIM
    if score >= 85:
        return "매우 좋음", GOOD
    if score >= 70:
        return "좋음", BLUE
    if score >= 50:
        return "보통", WARNING
    return "비추천", BAD


def _format_time(value: Any) -> str:
    raw = str(value or "")
    if "T" in raw:
        raw = raw.split("T", 1)[1]
    if len(raw) >= 5 and raw[2] == ":":
        return raw[:5]
    return raw or "—"


def _weather_icon(weather: dict[str, Any]) -> str:
    """Map the actual Open-Meteo WMO code to a compact row icon."""
    code = weather.get("current_weather_code")
    try:
        code = int(code) if code is not None else None
    except (TypeError, ValueError):
        code = None
    if code in {0, 1}:
        return "☀"
    if code == 2:
        return "◐"
    if code in {3, 45, 48}:
        return "☁"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}:
        return "☂"
    if code in {71, 73, 75, 77, 85, 86}:
        return "❄"

    precipitation = weather.get("precipitation_probability_percent")
    cloud = weather.get("cloud_cover_percent")
    if precipitation is not None and float(precipitation) >= 40:
        return "☂"
    if cloud is not None and float(cloud) <= 20:
        return "☀"
    return "☁"


def _wrap_overlay_text(text: Any, max_chars: int) -> list[str]:
    """Wrap Korean-friendly UI copy without letting a long token overflow."""
    words = str(text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            lines.append(current)
            current = word
        else:
            current = candidate
        while len(current) > max_chars:
            lines.append(current[:max_chars])
            current = current[max_chars:]
    if current:
        lines.append(current)
    return lines


def _make_taskbar_window(window: tk.Tk) -> None:
    """Keep the borderless overlay visible as an app button on Windows."""
    if sys.platform != "win32":
        return
    window.update_idletasks()
    try:
        user32 = ctypes.windll.user32
        extended_style = user32.GetWindowLongW(window.winfo_id(), -20)  # GWL_EXSTYLE
        # WS_EX_TOOLWINDOW deliberately hides taskbar buttons.  Replace it
        # with WS_EX_APPWINDOW without restoring the normal window frame.
        extended_style = (extended_style & ~0x00000080) | 0x00040000
        user32.SetWindowLongW(window.winfo_id(), -20, extended_style)
        user32.SetWindowPos(
            window.winfo_id(), 0, 0, 0, 0, 0,
            0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020,  # no move/size/activate, frame changed
        )
    except (AttributeError, OSError, tk.TclError):
        # The overlay remains usable on an unsupported Tk/Windows combination.
        pass


class ContextOverlayApp:
    def __init__(self, *, position: str) -> None:
        self.position = position
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.root = tk.Tk()
        self.root.title("GYUVIS Overlay")
        self.root.overrideredirect(True)
        self.root.configure(bg=TRANSPARENT)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.0)
        try:
            self.root.wm_attributes("-transparentcolor", TRANSPARENT)
            self.root.wm_attributes("-toolwindow", False)
        except tk.TclError:
            # Windows supports both. The fallback preserves functional local demos.
            pass
        self.canvas = tk.Canvas(self.root, bg=TRANSPARENT, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.current_payload: dict[str, Any] = {}
        self.state = "idle"
        self._hide_job: str | None = None
        self._fade_job: str | None = None
        self._analysis_job: str | None = None
        self._analysis_step = 0
        self._remaining_ms: int | None = None
        self._hovered = False
        self._minimized_to_taskbar = False
        self._manual_position: tuple[int, int] | None = None
        self._drag_origin: tuple[int, int, int, int] | None = None
        # The comparison canvas remains on the main window.  A selected spot
        # gets its own transient detail window so the comparison is still
        # available behind it.
        self._spot_detail_window: tk.Toplevel | None = None
        self._draw_idle()
        self.canvas.bind("<Enter>", self._pause_auto_hide)
        self.canvas.bind("<Leave>", self._resume_auto_hide)
        self.canvas.bind("<ButtonPress-1>", self._begin_drag, add="+")
        self.canvas.bind("<B1-Motion>", self._drag_overlay, add="+")
        self.canvas.bind("<ButtonRelease-1>", self._finish_drag, add="+")
        self.root.after(70, self._drain_messages)
        self.root.after(1_400, self._keep_on_top)
        self.root.after_idle(self._minimize_to_taskbar)

    def enqueue(self, payload: dict[str, Any]) -> None:
        self.messages.put(payload)

    def run(self) -> None:
        self.root.mainloop()

    def show(self, payload: dict[str, Any]) -> None:
        incoming_state = self._state_for(payload)
        # Once the full comparison is open it is user-owned: wake/listening
        # notifications must not replace or dismiss it.  The user explicitly
        # closes the panel when finished.
        if self.state == "comparison_detail" and incoming_state != "comparison_detail":
            return
        self._close_spot_detail()
        self.current_payload = payload
        self.state = incoming_state
        self._present_current(visible_alpha=None)
        self._fade_to(0.98)
        if self.state == "analyzing":
            self._analysis_step = 0
            self._animate_analysis()

    def _present_current(self, *, visible_alpha: float | None = 0.98) -> None:
        """Redraw and explicitly restore the popup after any state transition."""
        self._draw_current()
        self._place_window()
        self.root.deiconify()
        self.root.overrideredirect(True)
        self._minimized_to_taskbar = False
        _make_taskbar_window(self.root)
        self.root.attributes("-topmost", True)
        self.root.lift()
        if visible_alpha is not None:
            self.root.attributes("-alpha", visible_alpha)

    def hide(self) -> None:
        self._close_spot_detail()
        self._cancel_timers()
        self.state = "idle"
        self._draw_idle()
        self._fade_to(0.0, on_complete=self._minimize_to_taskbar)

    def _minimize_to_taskbar(self) -> None:
        """Keep a persistent GYUVIS button without leaving a desktop window."""
        if self.root.state() == "withdrawn":
            self.root.deiconify()
        # Tk cannot iconify an override-redirect window.  Temporarily restore
        # the normal style to create the taskbar button; it is made frameless
        # again before any Overlay card is shown.
        self.root.overrideredirect(False)
        _make_taskbar_window(self.root)
        self._minimized_to_taskbar = True
        self.root.iconify()

    def _state_for(self, payload: dict[str, Any]) -> str:
        # Comparison results go straight to the persistent panel.  Check the
        # event type before a legacy state value so older API senders cannot
        # reintroduce the transient summary card.
        if payload.get("type") == "night_sky_spot_comparison":
            return "comparison_detail"
        state = str(payload.get("state") or "")
        if state in {"listening", "analyzing", "result_good", "result_bad", "detail", "result_comparison", "comparison_detail", "comparison_spot_detail"}:
            return state
        if payload.get("type") == "night_sky":
            return "result_good" if payload.get("grade") == "good" else "result_bad"
        return "result_bad"

    def _draw_current(self) -> None:
        if self.state == "listening":
            self._draw_listening()
        elif self.state == "analyzing":
            self._draw_analyzing()
        elif self.state == "detail":
            self._draw_detail()
        elif self.state == "result_comparison":
            self._draw_comparison_result()
        elif self.state == "comparison_detail":
            self._draw_comparison_detail()
        elif self.state == "comparison_spot_detail":
            self._draw_comparison_spot_detail()
        else:
            self._draw_result()

    def _draw_idle(self) -> None:
        self.canvas.configure(width=1, height=1)
        self.root.geometry("1x1+0+0")

    def _draw_listening(self) -> None:
        width, height = 430, 100
        self._prepare_canvas(width, height)
        self._glass_card(width, height, radius=22)
        self._core(50, 50, 16)
        self._waveform(96, 50, BLUE)
        transcript = str(self.current_payload.get("transcript") or "")
        self._text(157, 39, "듣고 있어요...", size=13, bold=True)
        self._text(157, 62, transcript or "말씀해 주세요", size=9, color=TEXT_SECONDARY)

    def _draw_analyzing(self) -> None:
        width, height = 500, 204
        self._prepare_canvas(width, height)
        self._glass_card(width, height, radius=22)
        self._core(64, 66, 19)
        self._text(105, 49, "조사 중입니다...", size=14, bold=True)
        transcript = str(self.current_payload.get("transcript") or "")
        self._text(105, 73, transcript[:48] or "요청을 확인하고 있어요", size=9, color=TEXT_SECONDARY)
        self.canvas.create_line(250, 99, 250, 174, fill="#415161")
        steps = self.current_payload.get("steps") or ["날씨 정보 확인", "천문 데이터 조회", "촬영 조건 분석", "결과 정리"]
        for index, step in enumerate(steps[:4]):
            y = 106 + index * 22
            done = index < self._analysis_step
            active = index == self._analysis_step
            color = GOOD if done else BLUE if active else DIM
            marker = "✓" if done else "◉" if active else "○"
            self._text(276, y, marker, size=10, color=color, bold=done or active)
            self._text(299, y, str(step), size=9, color=TEXT_PRIMARY if done or active else TEXT_MUTED)

    def _draw_result(self) -> None:
        width, height = 530, 330
        self._prepare_canvas(width, height)
        self._glass_card(width, height, radius=22)
        grade = str(self.current_payload.get("grade") or "unknown")
        accent = _grade_color(grade)
        title = str(self.current_payload.get("title") or "오늘 밤 촬영 조건")
        best_time = str(self.current_payload.get("best_time") or "추천 시간 확인 불가")
        score = self.current_payload.get("score")
        weather = self.current_payload.get("weather") or {}
        moon = self.current_payload.get("moon") or {}
        self._core(39, 35, 10, accent)
        self._text(58, 35, "GYUVIS", size=8, color=TEXT_SECONDARY, bold=True)
        self._text(492, 35, "지금", anchor="e", size=8, color=TEXT_MUTED)
        self._text(30, 82, title, size=17, bold=True)
        self._text(30, 110, f"{best_time} 사이가 가장 좋습니다.", size=10, color=TEXT_SECONDARY)
        self._score_ring(459, 84, score, accent)
        self.canvas.create_line(30, 137, 500, 137, fill="#40505F")
        self._metric(30, 161, "구름량", self._percent(weather.get("cloud_cover_percent")), accent)
        self._metric(175, 161, "강수확률", self._percent(weather.get("precipitation_probability_percent")), BLUE)
        moon_label = self._moon_short(moon)
        self._metric(320, 161, "달 영향", moon_label, accent)
        location = str((self.current_payload.get("location") or {}).get("name") or "추천 지역 확인 중")
        self._text(30, 218, f"⌖  {location}", size=9, color=TEXT_SECONDARY)
        warning = self._first_warning()
        if warning:
            self._rounded_rect(30, 237, 500, 271, 8, fill="#2B2529", outline="#594047")
            self._text(42, 254, warning[:68], size=8, color="#E0B6B6")
        self._button(290, 286, 116, "자세히 보기", "detail")
        self._button(416, 286, 84, "닫기", "close")

    def _draw_detail(self) -> None:
        width, height = 720, 570
        self._prepare_canvas(width, height)
        self._glass_card(width, height, radius=22)
        grade = str(self.current_payload.get("grade") or "unknown")
        accent = _grade_color(grade)
        weather = self.current_payload.get("weather") or {}
        moon = self.current_payload.get("moon") or {}
        self._core(35, 31, 8, accent)
        self._text(52, 31, "GYUVIS", size=8, color=TEXT_SECONDARY, bold=True)
        self._text(360, 31, "은하수 촬영 조건 상세 정보", size=9, bold=True, anchor="center")
        self._button(665, 18, 30, "×", "close")
        self._text(30, 78, str(self.current_payload.get("title") or "오늘 밤 촬영 조건"), size=17, bold=True)
        self._text(30, 107, f"{self.current_payload.get('best_time') or '추천 시간 확인 불가'} 사이가 가장 좋습니다.", size=10, color=TEXT_SECONDARY)
        score_breakdown = self.current_payload.get("score_breakdown") or {}
        overall_score = score_breakdown.get("overall_score")
        displayed_score = overall_score if overall_score is not None else _weather_score(self.current_payload)
        self._score_ring(401, 87, displayed_score, accent, label="/100" if overall_score is not None else "기상")
        self._text(464, 70, "천문 정보", size=10, bold=True)
        astronomy = [
            ("일몰", _format_time(weather.get("sunset"))),
            ("천문박명 종료", _format_time(weather.get("astronomical_twilight_end"))),
            ("천문박명 시작", _format_time(weather.get("astronomical_twilight_start"))),
            ("월출", _format_time(moon.get("moonrise"))),
            ("월몰", _format_time(moon.get("moonset"))),
            ("달 모양", self._moon_detail(moon)),
        ]
        for index, (label, value) in enumerate(astronomy):
            y = 70 + index * 16
            self._text(464, y, label, size=9, color=TEXT_SECONDARY)
            self._text(678, y, value, size=9, anchor="e")
        self.canvas.create_line(30, 165, 690, 165, fill="#40505F")
        self._text(30, 191, "시간대별 예상", size=10, bold=True)
        self._draw_timeline(30, 212, self.current_payload.get("hourly") or [], accent)
        self._text(30, 341, "추가 정보", size=10, bold=True)
        location = self.current_payload.get("location") or {}
        astronomy_score = score_breakdown.get("astronomy_score")
        confidence = score_breakdown.get("data_confidence_percent")
        gc = (self.current_payload.get("astronomy") or {}).get("galactic_center") or {}
        facts = [
            ("촬영지", str(location.get("name") or "—")),
            ("지역", str(location.get("region") or "—")),
            ("출사 적합도", "확인 중" if overall_score is None else f"{overall_score}점"),
            ("기상 조건", "확인 중" if _weather_score(self.current_payload) is None else f"{_weather_score(self.current_payload)}점"),
            ("천문 조건", "확인 중" if astronomy_score is None else f"{astronomy_score}점"),
            ("데이터 신뢰도", "확인 중" if confidence is None else f"{confidence}%"),
            ("구름량", self._percent(weather.get("cloud_cover_percent"))),
            ("강수확률", self._percent(weather.get("precipitation_probability_percent"))),
            ("달 영향", self._moon_short(moon)),
            ("달 고도", "—" if moon.get("altitude_degrees") is None else f"{moon.get('altitude_degrees')}°"),
            ("GC 가시", f"{_format_time(gc.get('best_start'))} ~ {_format_time(gc.get('best_end'))}"),
            ("GC 최고 고도", "—" if gc.get("max_altitude_degrees") is None else f"{gc.get('max_altitude_degrees')}°"),
        ]
        for index, (label, value) in enumerate(facts):
            column = index % 2
            row = index // 2
            x, y = 30 + column * 220, 363 + row * 27
            self._text(x, y, label, size=9, color=TEXT_SECONDARY)
            self._text(x + 175, y, value, size=9, anchor="e")
        self._text(490, 341, "판단", size=10, bold=True)
        lines = list(self.current_payload.get("reasons") or []) + list(self.current_payload.get("warnings") or [])
        if not lines:
            lines = [str(self.current_payload.get("summary") or "판단 정보를 확인 중입니다.")]
        judgement_lines: list[str] = []
        for line in lines[:4]:
            wrapped = _wrap_overlay_text(line, 20)
            judgement_lines.extend(
                [f"• {wrapped[0]}", *[f"  {continuation}" for continuation in wrapped[1:]]]
            )
        for index, line in enumerate(judgement_lines[:8]):
            self._text(490, 363 + index * 18, line, size=8, color=TEXT_SECONDARY)
        if self.state == "comparison_spot_detail":
            self._button(526, 530, 169, "5곳 비교로 돌아가기", "comparison-back")
        else:
            self._button(558, 530, 137, "카드로 돌아가기", "collapse")

    def _draw_comparison_result(self) -> None:
        width, height = 560, 330
        self._prepare_canvas(width, height)
        self._glass_card(width, height, radius=22)
        rows = self.current_payload.get("spots") or []
        good_count = self.current_payload.get("good_count") or 0
        available_count = self.current_payload.get("available_count") or 0
        best = next((row for row in rows if isinstance(row, dict) and row.get("recommended")), None)
        title = "오늘 밤 출사 조건"
        self._core(39, 35, 10, BLUE)
        self._text(58, 35, "GYUVIS", size=8, color=TEXT_SECONDARY, bold=True)
        source = "데모" if self.current_payload.get("mock_data") else "실제 데이터"
        self._text(530, 35, source, anchor="e", size=8, color=WARNING if source == "데모" else TEXT_MUTED)
        self._text(30, 82, title, size=17, bold=True)
        if available_count:
            self._text(30, 111, f"5곳 중 {good_count}곳이 현재 조건에서 비교 가능합니다.", size=10, color=TEXT_SECONDARY)
        else:
            self._text(30, 111, "촬영 지점 좌표를 확인하면 실제 조건을 비교합니다.", size=10, color=TEXT_SECONDARY)
        self._score_ring(491, 91, _weather_score(best) if isinstance(best, dict) else None, GOOD if best else DIM, label="기상")
        self.canvas.create_line(30, 140, 530, 140, fill="#40505F")
        if isinstance(best, dict):
            candidates = [row for row in rows if isinstance(row, dict) and row.get("available")][:3]
            self._text(30, 164, "추천 후보", size=9, color=TEXT_SECONDARY)
            for index, candidate in enumerate(candidates):
                score = _weather_score(candidate)
                self._text(30, 188 + index * 23, str(candidate.get("name") or "—"), size=10, bold=index == 0)
                self._text(250, 188 + index * 23, "—" if score is None else str(score), size=11, bold=True, color=_condition_status(candidate)[1], anchor="e")
                self._text(270, 188 + index * 23, str(candidate.get("best_time") or "시간 확인 중"), size=8, color=TEXT_SECONDARY)
        else:
            self._text(30, 184, "아직 확정된 촬영 좌표가 없습니다.", size=13, bold=True)
            self._text(30, 211, "config/favorite_observation_spots.json에서 각 촬영 지점을 입력하세요.", size=8, color=TEXT_SECONDARY)
        self._button(290, 282, 150, "5곳 비교하기", "comparison-detail")
        self._button(450, 282, 80, "닫기", "close")

    def _draw_comparison_detail(self) -> None:
        width, height = 900, 555
        self._prepare_canvas(width, height)
        self._glass_card(width, height, radius=22)
        rows = self.current_payload.get("spots") or []
        self._core(35, 31, 8, BLUE)
        self._text(52, 31, "GYUVIS", size=8, color=TEXT_SECONDARY, bold=True)
        self._text(450, 31, "자주 가는 5곳 촬영지 비교", size=10, bold=True, anchor="center")
        source = "데모 데이터" if self.current_payload.get("mock_data") else "실제 API 데이터"
        self._text(830, 31, source, size=8, color=WARNING if self.current_payload.get("mock_data") else TEXT_MUTED, anchor="e")
        self._button(845, 18, 30, "×", "close")
        self._text(30, 73, str(self.current_payload.get("summary") or "촬영 조건을 비교합니다."), size=10, color=TEXT_SECONDARY)
        headers = ((30, "현재"), (75, "촬영지"), (305, "상태"), (402, "추천 촬영 시간"), (540, "구름"), (598, "강수"), (655, "달 영향"), (734, "출사"))
        for x, label in headers:
            self._text(x, 112, label, size=8, color=TEXT_MUTED, bold=True)
        self.canvas.create_line(30, 126, 870, 126, fill="#40505F")
        for index, raw in enumerate(rows[:5]):
            if not isinstance(raw, dict):
                continue
            y = 146 + index * 67
            available = bool(raw.get("available"))
            weather_score = _weather_score(raw)
            score = _overall_score(raw)
            fill = "#233542" if raw.get("recommended") else SURFACE_MUTED
            self._rounded_rect(24, y - 19, 876, y + 36, 10, fill=fill, outline="#3A4C5D")
            prefix = "추천  " if raw.get("recommended") else f"{index + 1}.  "
            weather = raw.get("weather") or {}
            self._text(43, y + 1, _weather_icon(weather), size=15, color=BLUE, anchor="center")
            self._text(75, y - 5, prefix + str(raw.get("name") or "촬영지"), size=10, bold=True)
            self._text(75, y + 15, str(raw.get("region") or ""), size=8, color=TEXT_SECONDARY)
            if available:
                status, status_color = _condition_status(raw)
                rain = weather.get("precipitation_probability_percent")
                self._text(305, y - 5, status, size=10, bold=True, color=status_color)
                breakdown = raw.get("score_breakdown") or {}
                astronomy_score = breakdown.get("astronomy_score")
                score_caption = f"기상 {weather_score if weather_score is not None else '—'} · 천문 {astronomy_score if astronomy_score is not None else '확인 중'}"
                self._text(305, y + 15, score_caption, size=7, color=TEXT_SECONDARY)
                self._text(402, y, str(raw.get("best_time") or "확인 중"), size=9)
                self._text(540, y, self._percent(weather.get("cloud_cover_percent")), size=9)
                rain_text = (f"⚠ {self._percent(rain)}" if rain is not None and float(rain) >= 30 else self._percent(rain))
                self._text(598, y, rain_text, size=9, color=BAD if rain is not None and float(rain) >= 30 else TEXT_PRIMARY)
                self._text(655, y, self._moon_short(raw.get("moon") or {}), size=9)
                self._text(748, y, "—" if score is None else str(score), size=11, bold=True, color=status_color, anchor="center")
                self._button(785, y - 1, 70, "상세", f"comparison-spot-{index}")
            else:
                self._text(305, y, str(raw.get("error_message") or "데이터 확인 중"), size=9, color=WARNING)
                self._text(540, y, "좌표 입력 후 조회", size=9, color=TEXT_MUTED)
        self._text(30, 503, "출사 적합도는 기상 55% + 천문 45%입니다. 계산 누락 시 종합 적합도는 표시하지 않습니다.", size=8, color=TEXT_MUTED)

    def _draw_comparison_spot_detail(self) -> None:
        rows = self.current_payload.get("spots") or []
        index = int(self.current_payload.get("selected_spot_index") or 0)
        selected = rows[index] if 0 <= index < len(rows) and isinstance(rows[index], dict) else {}
        comparison_payload = self.current_payload
        self.current_payload = {
            **comparison_payload,
            **selected,
            "location": {"name": selected.get("name") or "촬영지", "region": selected.get("region") or ""},
            "title": f"{selected.get('name') or '촬영지'} 촬영 조건",
        }
        self._draw_detail()
        self.current_payload = comparison_payload

    def _prepare_canvas(self, width: int, height: int) -> None:
        self.canvas.configure(width=width, height=height)
        self.canvas.delete("all")

    def _glass_card(self, width: int, height: int, *, radius: int) -> None:
        self._rounded_rect(1, 1, width - 1, height - 1, radius, fill=CARD_BACKGROUND, outline=CARD_EDGE)
        self._rounded_rect(3, 3, width - 3, 45, radius - 3, fill="#21303E", outline="")

    def _core(self, x: int, y: int, radius: int, color: str = BLUE) -> None:
        self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill="#17324A", outline="#36698B")
        self.canvas.create_oval(x - radius // 2, y - radius // 2, x + radius // 2, y + radius // 2, fill=color, outline="")

    def _waveform(self, x: int, y: int, color: str) -> None:
        for index, height in enumerate((7, 13, 21, 13, 7)):
            offset = index * 8
            self.canvas.create_line(x + offset, y - height / 2, x + offset, y + height / 2, fill=color, width=2, capstyle="round")

    def _score_ring(self, x: int, y: int, score: Any, color: str, *, label: str = "/100") -> None:
        self.canvas.create_oval(x - 31, y - 31, x + 31, y + 31, outline="#3B4A58", width=3)
        if score is not None:
            extent = max(0, min(100, int(score))) * 3.6
            self.canvas.create_arc(x - 31, y - 31, x + 31, y + 31, start=90, extent=-extent, style="arc", outline=color, width=3)
        self._text(x, y - 4, "—" if score is None else str(score), size=16, bold=True, anchor="center")
        self._text(x, y + 15, label, size=7, color=TEXT_SECONDARY, anchor="center")

    def _metric(self, x: int, y: int, label: str, value: str, color: str) -> None:
        self.canvas.create_oval(x, y - 5, x + 11, y + 6, outline=color, width=1)
        self._text(x + 19, y - 4, label, size=8, color=TEXT_SECONDARY)
        self._text(x + 19, y + 13, value, size=11, bold=True, color=TEXT_PRIMARY)

    def _draw_timeline(self, x: int, y: int, hourly: list[Any], accent: str) -> None:
        data = hourly[:7] or [{"time": "—", "cloud_cover_percent": None}] * 6
        width = 64
        for index, item in enumerate(data):
            point_x = x + index * 85
            cloud = item.get("cloud_cover_percent") if isinstance(item, dict) else None
            rain = item.get("precipitation_probability_percent") if isinstance(item, dict) else None
            bar_height = 18 if cloud is None else 18 + int(max(0, min(100, int(cloud))) * 0.35)
            fill = accent if cloud is not None and int(cloud) <= 30 else WARNING if cloud is not None and int(cloud) <= 60 else DIM
            self._rounded_rect(point_x, y + 46 - bar_height, point_x + width, y + 46, 6, fill=fill, outline="")
            self._text(point_x + width / 2, y + 64, str(item.get("time") or "—"), size=10, bold=True, anchor="center", color=TEXT_PRIMARY)
            cloud_text = "—" if cloud is None else f"{cloud}%"
            rain_text = "" if rain is None else f" · 비 {rain}%"
            self._text(point_x + width / 2, y + 85, cloud_text + rain_text, size=9, anchor="center", color=TEXT_SECONDARY)
            moon_altitude = item.get("moon_altitude_degrees") if isinstance(item, dict) else None
            gc_altitude = item.get("galactic_center_altitude_degrees") if isinstance(item, dict) else None
            if moon_altitude is not None or gc_altitude is not None:
                moon_text = "—" if moon_altitude is None else f"{moon_altitude:+g}°"
                gc_text = "—" if gc_altitude is None else f"{gc_altitude:+g}°"
                self._text(point_x + width / 2, y + 106, f"달 {moon_text}  GC {gc_text}", size=8, anchor="center", color=TEXT_SECONDARY)

    def _button(self, x: int, y: int, width: int, label: str, tag: str) -> None:
        canvas = self.canvas
        item = self._rounded_rect(x, y, x + width, y + 28, 8, fill="#253441", outline="#536A7C", tags=(tag,))
        canvas.create_text(x + width / 2, y + 14, text=label, fill=TEXT_PRIMARY, font=(FONT_FAMILY, 9), tags=(tag,))
        canvas.tag_bind(tag, "<Button-1>", self._on_button)
        canvas.tag_bind(tag, "<Enter>", lambda _event, c=canvas: c.itemconfigure(item, fill="#2D4050"))
        canvas.tag_bind(tag, "<Leave>", lambda _event, c=canvas: c.itemconfigure(item, fill="#253441"))

    def _on_button(self, event) -> None:
        tags = event.widget.gettags("current")
        if "close" in tags:
            self.hide()
        elif "detail" in tags:
            self.state = "detail"
            self._cancel_auto_hide()
            self._present_current()
        elif "comparison-detail" in tags:
            self.state = "comparison_detail"
            self._cancel_auto_hide()
            self._present_current()
        elif "comparison-back" in tags:
            self.state = "comparison_detail"
            self._present_current()
        elif any(tag.startswith("comparison-spot-") for tag in tags):
            selected_tag = next(tag for tag in tags if tag.startswith("comparison-spot-"))
            self.current_payload["selected_spot_index"] = int(selected_tag.rsplit("-", 1)[1])
            self._open_spot_detail()
        elif "collapse" in tags:
            self.state = "result_good" if self.current_payload.get("grade") == "good" else "result_bad"
            self._present_current()

    def _open_spot_detail(self) -> None:
        """Open a selected location above the persistent comparison panel."""
        self._close_spot_detail()
        selected_index = int(self.current_payload.get("selected_spot_index") or 0)
        rows = self.current_payload.get("spots") or []
        selected = rows[selected_index] if 0 <= selected_index < len(rows) and isinstance(rows[selected_index], dict) else {}
        payload = {
            **self.current_payload,
            **selected,
            "location": {"name": selected.get("name") or "촬영지", "region": selected.get("region") or ""},
            "title": f"{selected.get('name') or '촬영지'} 촬영 조건",
        }

        detail = tk.Toplevel(self.root)
        detail.title("GYUVIS 촬영지 상세")
        detail.overrideredirect(True)
        detail.configure(bg=TRANSPARENT)
        detail.attributes("-topmost", True)
        detail.attributes("-alpha", 0.98)
        try:
            detail.wm_attributes("-transparentcolor", TRANSPARENT)
        except tk.TclError:
            pass
        canvas = tk.Canvas(detail, bg=TRANSPARENT, highlightthickness=0, bd=0)
        canvas.pack()

        # Reuse the established detail renderer without replacing the main
        # comparison window's state or canvas.
        main_root, main_canvas, main_state, main_payload = self.root, self.canvas, self.state, self.current_payload
        self.root, self.canvas, self.state, self.current_payload = detail, canvas, "comparison_spot_detail", payload
        self._draw_detail()
        self._place_window()
        self.root, self.canvas, self.state, self.current_payload = main_root, main_canvas, main_state, main_payload

        canvas.tag_bind("close", "<Button-1>", self._close_spot_detail)
        canvas.tag_bind("comparison-back", "<Button-1>", self._close_spot_detail)
        detail.protocol("WM_DELETE_WINDOW", self._close_spot_detail)
        detail.deiconify()
        detail.attributes("-topmost", True)
        detail.lift()
        self._spot_detail_window = detail

    def _close_spot_detail(self, _event=None) -> None:
        detail, self._spot_detail_window = self._spot_detail_window, None
        if detail is not None and detail.winfo_exists():
            detail.destroy()

    def _pause_auto_hide(self, _event) -> None:
        self._hovered = True
        if self.state.startswith("result"):
            self._remaining_ms = RESULT_TIMEOUT_MS
            self._cancel_auto_hide()

    def _resume_auto_hide(self, _event) -> None:
        self._hovered = False
        if self.state.startswith("result"):
            self._schedule_auto_hide(self._remaining_ms or RESULT_TIMEOUT_MS)

    def _schedule_auto_hide(self, duration: int | None = None) -> None:
        # Overlay cards are user-owned.  They stay visible across listening,
        # analysis, results, comparison, and detail until the close button is
        # pressed; no timer is allowed to dismiss them.
        self._cancel_auto_hide()
        self._remaining_ms = None
        return

    def _cancel_auto_hide(self) -> None:
        if self._hide_job:
            self.root.after_cancel(self._hide_job)
            self._hide_job = None

    def _cancel_timers(self) -> None:
        self._cancel_auto_hide()
        if self._analysis_job:
            self.root.after_cancel(self._analysis_job)
            self._analysis_job = None

    def _animate_analysis(self) -> None:
        if self.state != "analyzing":
            return
        self._analysis_step = min(3, self._analysis_step + 1)
        self._draw_analyzing()
        self._analysis_job = self.root.after(780, self._animate_analysis)

    def _drain_messages(self) -> None:
        latest: dict[str, Any] | None = None
        while True:
            try:
                latest = self.messages.get_nowait()
            except queue.Empty:
                break
        if latest is not None:
            self.show(latest)
        self.root.after(70, self._drain_messages)

    def _keep_on_top(self) -> None:
        if self.root.state() == "normal":
            self.root.attributes("-topmost", True)
            if self._spot_detail_window is not None and self._spot_detail_window.winfo_exists():
                self._spot_detail_window.attributes("-topmost", True)
                self._spot_detail_window.lift()
            else:
                self.root.lift()
        self.root.after(1_400, self._keep_on_top)

    def _begin_drag(self, event) -> None:
        """Move from any card surface that is not an interactive button."""
        tags = self.canvas.gettags("current")
        if any(tag in {"close", "detail", "comparison-detail", "comparison-back", "collapse"} or tag.startswith("comparison-spot-") for tag in tags):
            self._drag_origin = None
            return
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_overlay(self, event) -> None:
        if self._drag_origin is None:
            return
        pointer_x, pointer_y, start_x, start_y = self._drag_origin
        width = int(float(self.canvas.cget("width")))
        height = int(float(self.canvas.cget("height")))
        max_x = max(0, self.root.winfo_screenwidth() - width)
        max_y = max(0, self.root.winfo_screenheight() - height)
        x = min(max(0, start_x + event.x_root - pointer_x), max_x)
        y = min(max(0, start_y + event.y_root - pointer_y), max_y)
        self._manual_position = (x, y)
        self.root.geometry(f"+{x}+{y}")

    def _finish_drag(self, _event) -> None:
        self._drag_origin = None

    def _place_window(self) -> None:
        # Tk reports canvas dimensions as strings such as "500.0" on Windows.
        width = int(float(self.canvas.cget("width")))
        height = int(float(self.canvas.cget("height")))
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        if self._manual_position is not None:
            x, y = self._manual_position
            x = min(max(0, x), max(0, screen_width - width))
            y = min(max(0, y), max(0, screen_height - height))
            self._manual_position = (x, y)
        else:
            center = self.state in {"listening", "analyzing"} or self.position == "center"
            x = (screen_width - width) // 2 if center else screen_width - width - MARGIN
            y = screen_height - height - MARGIN - 42
        self.root.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")

    def _fade_to(self, target: float, *, on_complete=None) -> None:
        if self._fade_job:
            self.root.after_cancel(self._fade_job)
        current = float(self.root.attributes("-alpha"))
        direction = 0.06 if target > current else -0.06

        def step() -> None:
            nonlocal current
            current += direction
            finished = current >= target if direction > 0 else current <= target
            self.root.attributes("-alpha", target if finished else max(0.0, min(1.0, current)))
            if finished:
                self._fade_job = None
                if on_complete:
                    on_complete()
                return
            self._fade_job = self.root.after(18, step)

        step()

    def _percent(self, value: Any) -> str:
        return "—" if value is None else f"{value}%"

    def _moon_short(self, moon: dict[str, Any]) -> str:
        impact = moon.get("impact")
        if impact in {"low", "medium", "high"}:
            return {"low": "낮음", "medium": "보통", "high": "높음"}[impact]
        illumination = moon.get("illumination_percent")
        return "확인 중" if illumination is None else ("낮음" if float(illumination) <= 35 else "보통" if float(illumination) <= 65 else "높음")

    def _moon_detail(self, moon: dict[str, Any]) -> str:
        illumination = moon.get("illumination_percent")
        phase = moon.get("phase_degrees")
        if illumination is None:
            return "확인 중"
        phase_name = "초승" if phase is not None and float(phase) < 90 else "상현" if phase is not None and float(phase) < 180 else "보름 이후"
        return f"{phase_name} · {illumination}%"

    def _first_warning(self) -> str:
        warnings = self.current_payload.get("warnings") or []
        if warnings:
            return str(warnings[0])
        if self.current_payload.get("grade") in {"poor", "fair"}:
            return "조건이 좋지 않아 촬영 전 다시 확인하는 것을 권합니다."
        return ""

    def _text(self, x, y, text, *, size: int, color: str = TEXT_PRIMARY, bold: bool = False, anchor: str = "w") -> None:
        weight = "bold" if bold else "normal"
        self.canvas.create_text(x, y, text=str(text), anchor=anchor, fill=color, font=(FONT_FAMILY, size, weight))

    def _rounded_rect(self, x1, y1, x2, y2, radius, **kwargs):
        points = [x1 + radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius, x2, y2 - radius, x2, y2, x2 - radius, y2, x1 + radius, y2, x1, y2, x1, y2 - radius, x1, y1 + radius, x1, y1]
        return self.canvas.create_polygon(points, smooth=True, **kwargs)


def make_handler(app: ContextOverlayApp):
    class ContextOverlayRequestHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path != "/context-card":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                # A five-spot result includes per-hour weather and astronomy
                # rows.  It is intentionally larger than a transient card.
                if length <= 0 or length > 512 * 1024:
                    raise ValueError("invalid content length")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict) or not isinstance(payload.get("state") or payload.get("title"), str):
                    raise ValueError("invalid overlay payload")
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            app.enqueue(payload)
            self.send_response(HTTPStatus.ACCEPTED)
            self.end_headers()

        def log_message(self, _format, *_args) -> None:
            return

    return ContextOverlayRequestHandler


def start_server(app: ContextOverlayApp, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    threading.Thread(target=server.serve_forever, name="gyuvis-context-overlay", daemon=True).start()
    return server


def demo_payload(mode: str) -> dict[str, Any]:
    if mode.startswith("spot-comparison"):
        rows = [
            ("청옥산 육백마지기", "강원특별자치도 평창군", 70, 12, "22:50 ~ 01:20", True),
            ("영월 접산활공장", "강원특별자치도 영월군", 66, 28, "23:20 ~ 01:00", False),
            ("박달고치전망대", "강원특별자치도 정선군", 70, 5, "22:40 ~ 01:30", False),
            ("도롱이연못", "강원특별자치도 평창군", 49, 45, "00:10 ~ 01:30", False),
            ("만항재", "강원특별자치도 정선군", 63, 20, "23:00 ~ 00:50", False),
        ]
        if mode == "spot-comparison-error":
            rows = [(name, region, None, None, "좌표 확인 필요", False) for name, region, *_rest in rows]
        elif mode == "spot-comparison-mixed":
            rows[3] = (rows[3][0], rows[3][1], None, None, "좌표 확인 필요", False)
        spots = []
        for index, (name, region, score, cloud, best_time, recommended) in enumerate(rows, start=1):
            available = score is not None
            spots.append({
                "id": f"demo-{index}", "name": name, "region": region, "available": available,
                "recommended": recommended and available, "coordinate_status": "ready" if available else "requires_confirmation",
                "error_message": None if available else "촬영 지점 좌표 확인 필요",
                "score": score, "grade": "good" if score is not None and score >= 70 else "fair" if score is not None and score >= 50 else "unknown",
                "best_time": best_time,
                "weather": {"cloud_cover_percent": cloud, "precipitation_probability_percent": 0, "sunset": "18:30", "sunrise": "06:20"},
                "moon": {"illumination_percent": 18, "moonrise": "08:00", "moonset": "20:30"},
                "hourly": [{"time": hour, "cloud_cover_percent": cloud, "precipitation_probability_percent": 0} for hour in ("20시", "21시", "22시", "23시", "00시", "01시")],
                "reasons": ["Overlay UI 확인용 고정 데이터입니다."],
                "warnings": ["데모 데이터입니다. 실제 날씨·천문 API를 호출하지 않았습니다."],
            })
        return {
            "type": "night_sky_spot_comparison", "state": "comparison_detail", "title": "오늘 밤 출사 조건",
            "summary": "5곳 비교 화면을 위한 고정 데모 데이터입니다.", "good_count": sum(1 for row in spots if row.get("score") and row["score"] >= 60),
            "available_count": sum(1 for row in spots if row["available"]), "mock_data": True, "spots": spots,
        }
    base = {
        "type": "night_sky",
        "title": "오늘 밤 촬영 조건이 좋습니다",
        "summary": "현재 기상과 달 영향을 기준으로 추천 시간대입니다.",
        "best_time": "22:40 ~ 00:30",
        "condition": "구름량 낮음 · 달 영향 적음",
        "score": 87,
        "grade": "good",
        "weather": {"cloud_cover_percent": 10, "precipitation_probability_percent": 0, "sunset": "17:38", "astronomical_twilight": "19:12"},
        "moon": {"phase_degrees": 61, "illumination_percent": 18, "moonrise": "01:12", "moonset": "12:47"},
        "hourly": [{"time": time, "cloud_cover_percent": cloud, "precipitation_probability_percent": 0} for time, cloud in (("20시", 30), ("21시", 20), ("22시", 10), ("23시", 10), ("00시", 10), ("01시", 20))],
        "location": {"name": "양구군 일대"},
        "reasons": ["구름량이 낮아 별 관측에 유리합니다.", "달 밝기 영향이 비교적 적습니다."],
        "warnings": [],
    }
    if mode == "listening":
        return {"type": "ambient_state", "state": "listening", "title": "듣고 있어요...", "transcript": "규비스, 오늘 은하수 어때?"}
    if mode == "analyzing":
        return {"type": "ambient_state", "state": "analyzing", "title": "조사 중입니다...", "transcript": "오늘 은하수 촬영 조건을 확인해 주세요"}
    if mode == "bad":
        base.update({"state": "result_bad", "title": "오늘은 촬영을 추천하지 않습니다", "score": 32, "grade": "poor", "best_time": "내일 밤 재확인", "weather": {"cloud_cover_percent": 80, "precipitation_probability_percent": 60, "sunset": "17:38", "astronomical_twilight": "19:12"}, "warnings": ["밤 늦게까지 구름량과 강수확률이 높습니다."]})
    elif mode == "detail":
        base["state"] = "detail"
    else:
        base["state"] = "result_good"
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description="GYUVIS local Windows Ambient AI Overlay")
    parser.add_argument("--demo", choices=("listening", "analyzing", "good", "bad", "detail", "spot-comparison-good", "spot-comparison-mixed", "spot-comparison-error"), help="Show one UI state on launch")
    parser.add_argument("--position", choices=("right", "center"), default="right")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    app = ContextOverlayApp(position=args.position)
    start_server(app, args.port)
    if args.demo:
        app.root.after(250, lambda: app.show(demo_payload(args.demo)))
    app.run()


if __name__ == "__main__":
    main()
