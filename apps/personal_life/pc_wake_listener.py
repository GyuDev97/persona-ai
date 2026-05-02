import json
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import deque
from datetime import datetime
from typing import Any

import numpy as np
import pyttsx3
import sounddevice as sd
import speech_recognition as sr

from app.config import load_env_file
from app.services.jarvis_hud_service import launch_jarvis_hud


load_env_file()

SAMPLE_RATE = 16_000
BLOCK_SECONDS = 0.08
CLAP_THRESHOLD = float(os.getenv("GYUVIS_CLAP_THRESHOLD", "0.11"))
CLAP_MIN_GAP_SECONDS = 0.10
CLAP_MAX_WINDOW_SECONDS = 1.6
CLAP_COUNT_TO_WAKE = int(os.getenv("GYUVIS_CLAP_COUNT", "2"))
WAKE_RECORD_SECONDS = float(os.getenv("GYUVIS_WAKE_RECORD_SECONDS", "4.0"))
FOLLOWUP_RECORD_SECONDS = float(os.getenv("GYUVIS_FOLLOWUP_RECORD_SECONDS", "8.0"))
FOLLOWUP_MAX_RECORD_SECONDS = float(os.getenv("GYUVIS_FOLLOWUP_MAX_RECORD_SECONDS", "14.0"))
FOLLOWUP_SILENCE_SECONDS = float(os.getenv("GYUVIS_FOLLOWUP_SILENCE_SECONDS", "1.2"))
FOLLOWUP_VOICE_THRESHOLD = float(os.getenv("GYUVIS_FOLLOWUP_VOICE_THRESHOLD", "0.018"))
COOLDOWN_SECONDS = float(os.getenv("GYUVIS_WAKE_COOLDOWN_SECONDS", "2.2"))
VOICE_ONLY_WAKE = os.getenv("GYUVIS_VOICE_ONLY_WAKE", "1") == "1"
SERVER_URL = os.getenv("GYUVIS_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
NCS_PLAYLIST_URL = os.getenv(
    "GYUVIS_NCS_PLAYLIST_URL",
    "https://www.youtube.com/watch?v=K4DyBUG242c&list=PLRBp0Fe2Gpgn8Y9qI-p0aTxVtw8onBSFj",
)
SEND_FOLLOWUP_TO_SERVER = os.getenv("GYUVIS_SEND_FOLLOWUP", "1") == "1"
AUTO_LISTEN_FOLLOWUP = os.getenv("GYUVIS_AUTO_LISTEN_FOLLOWUP", "1") == "1"
DEBUG_AUDIO = os.getenv("GYUVIS_DEBUG_AUDIO", "0") == "1"
STAY_AWAKE_AFTER_WAKE = os.getenv("GYUVIS_STAY_AWAKE", "1") == "1"
OPEN_JARVIS_HUD_ON_WAKE = os.getenv("GYUVIS_OPEN_JARVIS_HUD", "1") == "1"
JARVIS_HUD_COOLDOWN_SECONDS = float(os.getenv("GYUVIS_JARVIS_HUD_COOLDOWN_SECONDS", "15"))
VOICE_WAKE_TARGET = os.getenv("GYUVIS_VOICE_WAKE_TARGET", "일어나")
WAKE_PHRASES = tuple(
    phrase.strip()
    for phrase in os.getenv("GYUVIS_WAKE_PHRASES", "일어나,규비스").split(",")
    if phrase.strip()
)
MORNING_GREETING = os.getenv("GYUVIS_MORNING_GREETING", "좋은 하루에요 보스. 아침 브리핑을 진행해드릴까요?")
AFTERNOON_GREETING = os.getenv("GYUVIS_AFTERNOON_GREETING", "좋은 오후에요 보스. 오후 브리핑을 진행해드릴까요?")
GREETING = os.getenv("GYUVIS_GREETING", AFTERNOON_GREETING)
EVENING_GREETING = os.getenv(
    "GYUVIS_EVENING_GREETING",
    "안녕하세요 보스. 오늘 하루도 고생하셨습니다. 저녁 브리핑을 진행해드릴까요?",
)
EVENING_BRIEFING_ENABLED = os.getenv("GYUVIS_EVENING_BRIEFING", "1") == "1"
EVENING_START_HOUR = int(os.getenv("GYUVIS_EVENING_START_HOUR", "18"))
TTS_BACKEND = os.getenv("GYUVIS_TTS_BACKEND", "edge").lower()
TTS_ALLOW_FALLBACK = os.getenv("GYUVIS_TTS_ALLOW_FALLBACK", "0") == "1"
EDGE_TTS_VOICE = os.getenv("GYUVIS_EDGE_TTS_VOICE", "ko-KR-InJoonNeural")
EDGE_TTS_RATE = os.getenv("GYUVIS_EDGE_TTS_RATE", "+12%")
EDGE_TTS_PITCH = os.getenv("GYUVIS_EDGE_TTS_PITCH", "-8Hz")
TEMP_AUDIO_DIR = pathlib.Path(os.getenv("GYUVIS_TEMP_AUDIO_DIR", os.path.join(os.getcwd(), ".tmp_tts")))
EXTRA_SLEEP_PHRASES = (
    "\uc7a0\uae50\uae30\ub2e4\ub824\uc918",
    "\uc7a0\uae50\ub9cc\uae30\ub2e4\ub824\uc918",
    "\uc870\uae08\uc774\ub2e4\uae30\ub2e4\ub824\uc918",
    "\uae30\ub2e4\ub824\uc918",
)
AFFIRMATIVE_PHRASES = (
    "네",
    "응",
    "좋아",
    "진행해",
    "진행하",
    "부탁해",
    "그래",
    "해줘",
    "해주세요",
    "시작해",
    "시작하",
)
SHORT_AFFIRMATIVE_PHRASES = ("어", "응", "네")
SOCIAL_CLOSE_PHRASES = (
    "수고해",
    "수고했어",
    "고생했어",
    "고마워",
    "감사",
    "됐어",
    "괜찮아",
    "그만",
    "쉬어",
)
BRIEFING_ACK = os.getenv("GYUVIS_BRIEFING_ACK", os.getenv("GYUVIS_EVENING_BRIEFING_ACK", "네 알겠습니다 보스."))
EVENING_BRIEFING_ACK = BRIEFING_ACK
SOCIAL_CLOSE_ACK = os.getenv("GYUVIS_SOCIAL_CLOSE_ACK", "네 보스. 감사합니다. 필요하시면 언제든 다시 부르십시오.")
SLEEP_ACKNOWLEDGEMENT = os.getenv("GYUVIS_SLEEP_ACK", "\ub124 \uc54c\uaca0\uc2b5\ub2c8\ub2e4.")
SLEEP_PHRASES = ("잘자", "대기", "꺼져", "수면 모드", "sleep")
GYUVIS_WELLBEING_REPLY = os.getenv(
    "GYUVIS_WELLBEING_REPLY",
    "저는 안정적으로 대기 중입니다, 보스. 보스의 하루를 돕는 것이 제 상태를 가장 좋게 만듭니다.",
)
USER_TIRED_REPLY = os.getenv(
    "GYUVIS_USER_TIRED_REPLY",
    "고생 많으셨습니다 보스. 오늘은 무리해서 정리하려 하기보다, 가장 무거운 것 하나만 내려놓아도 충분합니다. 제가 옆에서 천천히 도와드리겠습니다.",
)
USER_BAD_DAY_REPLY = os.getenv(
    "GYUVIS_USER_BAD_DAY_REPLY",
    "그런 하루였군요, 보스. 지금은 해결책부터 찾기보다 잠깐 숨을 고르는 게 먼저일 수 있습니다. 필요하시면 제가 일정이나 할 일을 가볍게 정리해드리겠습니다.",
)
USER_GOOD_DAY_REPLY = os.getenv(
    "GYUVIS_USER_GOOD_DAY_REPLY",
    "다행입니다 보스. 좋은 흐름은 기록해두면 다음에도 다시 꺼내 쓰기 좋습니다. 오늘 잘된 점 하나만 남겨둘까요?",
)
SOFT_CONFIRM_ACK = os.getenv("GYUVIS_SOFT_CONFIRM_ACK", "네 보스. 현재 흐름대로 계속 진행하겠습니다.")
GYUVIS_INTRO_REPLY = os.getenv(
    "GYUVIS_INTRO_REPLY",
    "안녕하세요. 저는 보스의 로컬 데스크톱 어시스턴트, 규비스입니다. 일정과 브리핑, 에이전트 상태 확인, 브라우저와 PC 작업 보조를 맡고 있습니다. 지금은 아직 성장 중이지만, 보스가 말하면 바로 움직이는 개인 비서가 되는 중입니다.",
)


class GyuvisWakeListener:
    def __init__(self) -> None:
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.energy_threshold = 180
        self.recognizer.pause_threshold = 0.8
        self.recognizer.non_speaking_duration = 0.45

        self.tts = None
        if TTS_BACKEND == "pyttsx3" or TTS_ALLOW_FALLBACK:
            try:
                self.tts = pyttsx3.init()
                self.tts.setProperty("rate", 185)
                self.tts.setProperty("volume", 1.0)
            except Exception:
                self.tts = None

        self._clap_hits: deque[float] = deque()
        self._wake_event = threading.Event()
        self._cooldown_until = 0.0
        self._running = True
        self._last_audio_debug_at = 0.0
        self._stay_awake = False
        self._last_hud_launch_at = 0.0
        self._pending_briefing_period: str | None = None
        self._pending_followup_action: str | None = None

    def run(self) -> None:
        self._log("웨이크 모드를 시작합니다. 박수 두 번 뒤에 '일어나'처럼 불러보세요.")
        self._log(f"서버 연동: {'켜짐' if SEND_FOLLOWUP_TO_SERVER else '꺼짐'} ({SERVER_URL})")
        self._log(
            "감도 설정: "
            f"clap_threshold={CLAP_THRESHOLD:.2f}, "
            f"wake_record={WAKE_RECORD_SECONDS:.1f}s, "
            f"followup_record={FOLLOWUP_RECORD_SECONDS:.1f}s"
        )
        self._log(f"상시 듣기 유지: {'켜짐' if STAY_AWAKE_AFTER_WAKE else '꺼짐'}")

        device_label = self._describe_input_device()
        if device_label:
            self._log(f"입력 장치: {device_label}")

        if VOICE_ONLY_WAKE:
            self._log("Voice-only wake mode enabled. Say the wake phrase directly.")
            while self._running:
                if self._stay_awake and AUTO_LISTEN_FOLLOWUP:
                    self._handle_followup_only()
                    continue
                self._handle_voice_wake_only()
            return

        blocksize = int(SAMPLE_RATE * BLOCK_SECONDS)
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            callback=self._audio_callback,
        ):
            while self._running:
                if self._stay_awake and AUTO_LISTEN_FOLLOWUP:
                    self._handle_followup_only()
                    continue

                if not self._wake_event.wait(timeout=0.2):
                    continue

                self._wake_event.clear()
                self._cooldown_until = time.monotonic() + COOLDOWN_SECONDS
                self._handle_wake_cycle()

    def stop(self) -> None:
        self._running = False
        self._wake_event.set()

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            self._log(f"오디오 경고: {status}")

        now = time.monotonic()
        if now < self._cooldown_until:
            return

        rms = float(np.sqrt(np.mean(np.square(indata))))
        if DEBUG_AUDIO and now - self._last_audio_debug_at >= 0.8:
            self._last_audio_debug_at = now
            self._log(f"[debug] mic rms={rms:.3f}")

        if rms < CLAP_THRESHOLD:
            return

        if self._clap_hits and now - self._clap_hits[-1] < CLAP_MIN_GAP_SECONDS:
            return

        self._log(f"박수 후보 감지: rms={rms:.3f}")
        self._clap_hits.append(now)
        while self._clap_hits and now - self._clap_hits[0] > CLAP_MAX_WINDOW_SECONDS:
            self._clap_hits.popleft()

        if len(self._clap_hits) >= CLAP_COUNT_TO_WAKE:
            self._clap_hits.clear()
            self._wake_event.set()

    def _handle_voice_wake_only(self) -> None:
        now = time.monotonic()
        if now < self._cooldown_until:
            time.sleep(0.2)
            return

        self._log("Listening for wake phrase...")
        wake_audio = self._record_audio(WAKE_RECORD_SECONDS)
        wake_text = self._transcribe(wake_audio)

        if not wake_text:
            return

        self._log(f"Wake phrase heard: {wake_text}")
        self._publish_subtitle(input_text=wake_text)
        if not self._looks_like_wake_phrase(wake_text):
            return

        self._cooldown_until = time.monotonic() + COOLDOWN_SECONDS
        self._launch_hud_if_needed()
        self._speak(self._build_wake_greeting())
        if STAY_AWAKE_AFTER_WAKE:
            self._stay_awake = True

        if not AUTO_LISTEN_FOLLOWUP:
            return

        self._handle_followup_only()

    def _handle_wake_cycle(self) -> None:
        self._log("박수 패턴을 감지했습니다. 호출어를 듣는 중입니다...")
        wake_audio = self._record_audio(WAKE_RECORD_SECONDS)
        wake_text = self._transcribe(wake_audio)

        if not wake_text:
            self._log("호출어를 알아듣지 못했습니다.")
            self._speak("호출어를 듣지 못했습니다.")
            return

        self._log(f"호출어 인식: {wake_text}")
        self._publish_subtitle(input_text=wake_text)
        if not self._looks_like_wake_phrase(wake_text):
            self._log("호출어가 맞지 않아 다시 대기합니다.")
            self._speak("호출어가 맞지 않습니다.")
            return

        self._launch_hud_if_needed()
        self._speak(self._build_wake_greeting())
        if STAY_AWAKE_AFTER_WAKE:
            self._stay_awake = True
            self._log("규비스가 깨어 있습니다. 이제 박수 없이 바로 명령을 들을게요.")

        if not AUTO_LISTEN_FOLLOWUP:
            return

        self._handle_followup_only()

    def _handle_followup_only(self) -> None:
        self._log("명령을 듣는 중입니다...")
        command_audio = self._record_followup_audio()
        command_text = self._transcribe(command_audio)

        if not command_text:
            self._log("명령이 들리지 않았습니다. 계속 대기합니다.")
            return

        self._log(f"추가 명령: {command_text}")
        self._publish_subtitle(input_text=command_text)
        if self._looks_like_sleep_phrase(command_text):
            self._stay_awake = False
            self._pending_briefing_period = None
            self._pending_followup_action = None
            self._speak(SLEEP_ACKNOWLEDGEMENT)
            self._log("Pause command acknowledged. Returning to standby mode.")
            return
            self._speak("대기 모드로 돌아갑니다.")
            self._log("대기 모드로 돌아갑니다. 다시 깨우려면 박수와 호출어가 필요합니다.")
            return

        if self._looks_like_social_close(command_text):
            self._stay_awake = False
            self._pending_briefing_period = None
            self._pending_followup_action = None
            self._speak(SOCIAL_CLOSE_ACK)
            self._log("Social close acknowledged. Returning to standby mode.")
            return

        if self._handle_pending_followup_action(command_text):
            return

        if self._handle_explicit_followup_command(command_text):
            return

        if self._pending_briefing_period:
            if self._looks_like_briefing_affirmative(command_text):
                briefing_period = self._pending_briefing_period
                self._pending_briefing_period = None
                self._speak(BRIEFING_ACK)
                briefing_text = self._build_briefing_text(briefing_period)
                self._speak(briefing_text)
                return

            self._pending_briefing_period = None

        if SEND_FOLLOWUP_TO_SERVER:
            response_text = self._send_followup_to_server(command_text)
            if response_text:
                self._speak(response_text)
        else:
            self._log("서버 연동이 꺼져 있어 추가 명령은 출력만 합니다.")
            self._speak("서버 연동이 꺼져 있습니다.")

    def _build_wake_greeting(self) -> str:
        current_hour = datetime.now().hour
        if EVENING_BRIEFING_ENABLED and current_hour >= EVENING_START_HOUR:
            self._pending_briefing_period = "evening"
            return EVENING_GREETING

        if current_hour < 12:
            self._pending_briefing_period = "morning"
            return MORNING_GREETING
        if current_hour < EVENING_START_HOUR:
            self._pending_briefing_period = "afternoon"
            return AFTERNOON_GREETING
        self._pending_briefing_period = None
        return GREETING

    def _get_current_briefing_period(self) -> str:
        current_hour = datetime.now().hour
        if current_hour >= EVENING_START_HOUR:
            return "evening"
        if current_hour < 12:
            return "morning"
        return "afternoon"

    def _looks_like_affirmative(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if normalized in {self._normalize_text(phrase) for phrase in SHORT_AFFIRMATIVE_PHRASES}:
            return True
        return any(self._normalize_text(phrase) in normalized for phrase in AFFIRMATIVE_PHRASES)

    def _looks_like_briefing_affirmative(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        short_affirmatives = {self._normalize_text(phrase) for phrase in SHORT_AFFIRMATIVE_PHRASES}
        if normalized in short_affirmatives:
            return True

        non_briefing_tokens = (
            "에이전트",
            "agent",
            "블로그",
            "초안",
            "네이버",
            "유튜브",
            "구글",
            "gpt",
            "뉴스",
            "날씨",
            "검색",
            "열어",
            "보여",
            "작성",
            "만들",
            "생성",
            "채워",
            "입력",
        )
        if "브리핑" not in normalized and any(token in normalized for token in non_briefing_tokens):
            return False

        if any(token in normalized for token in ("어진행", "응진행", "네진행", "진행", "시작")):
            return True

        return self._looks_like_affirmative(text)

    def _looks_like_social_close(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        return any(self._normalize_text(phrase) in normalized for phrase in SOCIAL_CLOSE_PHRASES)

    def _handle_explicit_followup_command(self, text: str) -> bool:
        handlers = (
            self._handle_incomplete_agent_fragment,
            self._handle_agent_news_readout_command,
            self._handle_agent_draft_to_blog_command,
            self._handle_agent_recovery_command,
            self._handle_agent_team_briefing_command,
            self._handle_agent_status_query,
            self._handle_agent_detail_command,
            self._handle_briefing_command,
            self._handle_soft_confirmation,
            self._handle_social_dialogue,
            self._handle_desktop_monitor_command,
            self._handle_browser_command,
        )
        for handler in handlers:
            if handler(text):
                self._pending_briefing_period = None
                return True
        return False

    def _handle_incomplete_agent_fragment(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if normalized not in {"에이전트", "에이전트들", "에이전트들의", "agent", "agents"}:
            return False

        self._speak("네 보스. 에이전트들의 상태를 확인할까요, 아니면 전체 에이전트 브리핑을 진행할까요?")
        return True

    def _handle_pending_followup_action(self, text: str) -> bool:
        if self._pending_followup_action is None:
            return False
        if not self._looks_like_pending_action_confirmation(text):
            return False

        action = self._pending_followup_action
        self._pending_followup_action = None
        self._pending_briefing_period = None

        if action == "naver_blog_fill_draft":
            self._speak("네 보스. 최신 초안을 네이버 블로그 글쓰기 화면에 입력하겠습니다.")
            if SEND_FOLLOWUP_TO_SERVER:
                response_text = self._send_followup_to_server("네이버 블로그 글쓰기 화면에 최신 초안을 입력해줘")
                if response_text:
                    self._speak(response_text)
            else:
                self._speak("서버 연동이 꺼져 있어 블로그 입력 작업을 시작할 수 없습니다.")
            return True

        return False

    def _looks_like_pending_action_confirmation(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        topic_tokens = (
            "브리핑",
            "보고",
            "에이전트",
            "agent",
            "뉴스",
            "날씨",
            "유튜브",
            "네이버",
            "구글",
            "gpt",
            "검색",
            "상태",
            "상세",
        )
        if any(token in normalized for token in topic_tokens):
            return False
        if normalized in {"어", "응", "네", "좋아", "그래", "ㅇㅇ", "오케이"}:
            return True
        return any(
            token in normalized
            for token in (
                "어진행",
                "응진행",
                "네진행",
                "좋아진행",
                "진행",
                "계속",
                "그렇게해",
                "그대로해",
                "해줘",
                "부탁",
            )
        )

    def _handle_agent_status_query(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        agent_related = (
            "에이전트" in normalized
            or "agent" in normalized
            or self._extract_agent_id(text) is not None
            or "뉴스보는애" in normalized
            or "뉴스수집" in normalized
            or "it뉴스" in normalized
            or "아이티뉴스" in normalized
            or "일하는애" in normalized
            or "노는애" in normalized
        )
        status_related = any(
            token in normalized
            for token in (
                "상태",
                "뭐해",
                "뭐하고",
                "뭘",
                "뭐할",
                "할거",
                "할거야",
                "어떤거",
                "어떤걸",
                "담당",
                "역할",
                "어때",
                "진행",
                "일하",
                "놀고",
                "완료",
                "수집",
                "몇건",
                "몇개",
                "보고됐",
                "잘되고",
                "모았",
                "모은",
            )
        )
        if not (agent_related and status_related):
            return False

        agent_id = self._extract_agent_id(text)
        if agent_id is None and any(token in normalized for token in ("뉴스", "it", "아이티", "모바일", "테크")):
            agent_id = 1

        try:
            state = self._get_json(f"{SERVER_URL}/agent/standby-status")
            self._speak(self._build_agent_status_reply_from_state(state, agent_id))
        except Exception as error:
            self._log(f"에이전트 상태 조회 실패: {error}")
            self._speak("에이전트 상태를 확인하는 중 문제가 발생했습니다.")
        return True

    def _build_agent_status_reply_from_state(self, state: dict[str, Any], agent_id: int | None = None) -> str:
        agents = state.get("agents") or []
        if agent_id is not None:
            agent = next((item for item in agents if int(item.get("id", 0)) == agent_id), None)
            if agent is None:
                return "현재 표시 가능한 에이전트는 1번부터 4번까지입니다."
            return self._build_single_agent_status_reply(agent)

        active_count = sum(1 for agent in agents if agent.get("tone") == "active")
        error_count = sum(1 for agent in agents if agent.get("tone") == "error")
        idle_count = max(len(agents) - active_count - error_count, 0)
        parts = [
            f"현재 에이전트는 총 {len(agents)}개입니다. 활성 {active_count}개, 대기 {idle_count}개, 확인 필요 {error_count}개로 보입니다."
        ]
        for agent in agents:
            parts.append(
                f"{agent.get('id')}번은 {agent.get('title')} 담당이고, 상태는 {agent.get('status')}, 처리는 {agent.get('processing')}입니다."
            )
        return " ".join(parts)

    def _build_single_agent_status_reply(self, agent: dict[str, Any]) -> str:
        base = (
            f"에이전트 {agent.get('id')}번은 {agent.get('title')} 담당입니다. "
            f"현재 상태는 {agent.get('status')}, 처리는 {agent.get('processing')}입니다."
        )
        if int(agent.get("id") or 0) != 1:
            return base

        collected_count = int(agent.get("collected_count") or 0)
        if agent.get("report"):
            return f"{base} 오늘 수집된 IT 뉴스는 {collected_count}건이고, 최종 보고가 생성되어 있습니다."
        if collected_count:
            return f"{base} 오늘 수집된 IT 뉴스는 {collected_count}건이며, 18시에 최종 보고로 정리됩니다."
        return f"{base} 상시 수집 시간은 10시부터 18시까지입니다. 아직 오늘 수집된 뉴스는 없습니다."

    def _handle_agent_news_readout_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        agent_id = self._extract_agent_id(text)
        asks_news_collection = (
            agent_id == 1
            and any(token in normalized for token in ("뭐모았", "뭐모은", "뭐수집", "오늘뭐", "뉴스읽", "상위", "세개", "3개"))
        )
        if not asks_news_collection:
            return False

        try:
            state = self._get_json(f"{SERVER_URL}/agent/standby-status")
            agents = state.get("agents") or []
            agent = next((item for item in agents if int(item.get("id", 0)) == 1), {})
            titles = [str(title).strip() for title in (agent.get("latest_titles") or []) if str(title).strip()]
            if not titles:
                self._speak("에이전트 1번이 오늘 수집한 뉴스는 아직 없습니다. 수집기를 확인하겠습니다.")
                return True

            self._post_json(f"{SERVER_URL}/agent/standby-status/detail/1", {})
            top_titles = titles[:3]
            lines = [f"에이전트 1번이 오늘 수집한 주요 IT 뉴스 상위 {len(top_titles)}개입니다."]
            lines.extend(f"{index + 1}. {title}" for index, title in enumerate(top_titles))
            self._speak(" ".join(lines))
        except Exception as error:
            self._log(f"에이전트 1번 뉴스 조회 실패: {error}")
            self._speak("에이전트 1번 수집 뉴스를 확인하는 중 문제가 발생했습니다.")
        return True

    def _handle_agent_draft_to_blog_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not (
            "초안" in normalized
            and "네이버" in normalized
            and any(token in normalized for token in ("넣어", "입력", "올려", "채워", "보내"))
        ):
            return False

        self._pending_followup_action = None
        self._pending_briefing_period = None
        self._speak("네 보스. 최신 초안을 네이버 블로그 글쓰기 화면에 입력하겠습니다.")
        if SEND_FOLLOWUP_TO_SERVER:
            response_text = self._send_followup_to_server("네이버 블로그 글쓰기 화면에 최신 초안을 입력해줘")
            if response_text:
                self._speak(response_text)
        else:
            self._speak("서버 연동이 꺼져 있어 블로그 입력 작업을 시작할 수 없습니다.")
        return True

    def _handle_agent_recovery_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        agent_id = self._extract_agent_id(text)
        if not (
            agent_id is not None
            and any(token in normalized for token in ("복구", "고쳐", "재시작", "리커버", "살려"))
            and ("에이전트" in normalized or "agent" in normalized)
        ):
            return False

        try:
            state = self._post_json(f"{SERVER_URL}/agent/standby-status/recover/{agent_id}", {})
            self._post_json(f"{SERVER_URL}/agent/standby-status/detail/{agent_id}", {})
            agent = next((item for item in state.get("agents", []) if int(item.get("id", 0)) == agent_id), None)
            if agent:
                self._speak(
                    f"네 보스. 에이전트 {agent_id}번 상태를 실제 작업 큐 기준으로 다시 조회했습니다. "
                    f"현재 상태는 {agent.get('status')}, 처리는 {agent.get('processing')}입니다."
                )
            else:
                self._speak(f"네 보스. 에이전트 {agent_id}번 상태를 다시 조회했습니다.")
        except Exception as error:
            self._log(f"에이전트 복구 요청 실패: {error}")
            self._speak(f"에이전트 {agent_id}번 복구 요청 중 문제가 발생했습니다.")
        return True

    def _handle_agent_team_briefing_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if not (
            any(token in normalized for token in ("전체에이전트", "에이전트전체", "모든에이전트", "에이전트들"))
            and any(token in normalized for token in ("브리핑", "보고", "상태"))
        ):
            return False

        try:
            state = self._get_json(f"{SERVER_URL}/agent/standby-status")
            agents = state.get("agents") or []
            active_count = sum(1 for agent in agents if agent.get("tone") == "active")
            idle_count = sum(1 for agent in agents if agent.get("tone") == "idle")
            error_count = sum(1 for agent in agents if agent.get("tone") == "error")
            lines = [
                f"전체 에이전트 브리핑입니다. 총 {len(agents)}개 중 활성 {active_count}개, 대기 {idle_count}개, 확인 필요 {error_count}개입니다."
            ]
            for agent in agents:
                lines.append(
                    f"{agent.get('id')}번 {agent.get('title')}. 상태 {agent.get('status')}, 처리 {agent.get('processing')}."
                )
            self._speak(" ".join(lines))
        except Exception as error:
            self._log(f"전체 에이전트 브리핑 실패: {error}")
            self._speak("전체 에이전트 상태를 확인하는 중 문제가 발생했습니다.")
        return True

    def _handle_agent_detail_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if "에이전트" not in normalized and "agent" not in normalized:
            return False
        if not any(token in normalized for token in ("열어", "보여", "상세", "확대", "펼쳐", "띄워", "확인")):
            return False

        agent_id = self._extract_agent_id(text)
        if agent_id is None:
            self._speak("어떤 에이전트를 열지 번호를 말씀해주시면 바로 표시하겠습니다.")
            return True
        if agent_id not in {1, 2, 3, 4}:
            self._speak("현재 표시 가능한 에이전트는 1번부터 4번까지입니다.")
            return True

        try:
            self._post_json(f"{SERVER_URL}/agent/standby-status/detail/{agent_id}", {})
            self._open_url(f"{SERVER_URL}/agent/report-center?agent={agent_id}")
            if agent_id == 2 and "초안" in normalized:
                self._pending_followup_action = "naver_blog_fill_draft"
            self._speak(f"네 보스. 에이전트 {agent_id}번 상세 화면을 열겠습니다.")
        except Exception as error:
            self._log(f"에이전트 상세 화면 요청 실패: {error}")
            self._speak("에이전트 상세 화면을 여는 중 문제가 발생했습니다.")
        return True

    def _extract_agent_id(self, text: str) -> int | None:
        normalized = self._normalize_text(text)
        digit_match = re.search(r"([1-4])번?", normalized)
        if digit_match:
            return int(digit_match.group(1))

        word_numbers = {
            "일": 1,
            "한": 1,
            "첫": 1,
            "첫번째": 1,
            "이": 2,
            "두": 2,
            "둘": 2,
            "두번째": 2,
            "삼": 3,
            "세": 3,
            "셋": 3,
            "세번째": 3,
            "사": 4,
            "네": 4,
            "넷": 4,
            "네번째": 4,
            "오": 5,
        }
        for token, value in word_numbers.items():
            if f"{token}번" in normalized or f"{token}번째" in normalized:
                return value
        return None

    def _handle_briefing_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        briefing_targets = ("브리핑", "보고", "오늘정리", "하루정리", "상황정리")
        if not any(target in normalized for target in briefing_targets):
            return False

        command_tokens = (
            "진행",
            "시작",
            "해줘",
            "해주세요",
            "하세요",
            "부탁",
            "들려",
            "알려",
            "보여",
            "말해",
            "정리",
            "보고",
        )
        if not any(token in normalized for token in command_tokens):
            return False

        briefing_period = self._pending_briefing_period or self._get_current_briefing_period()
        self._pending_briefing_period = None
        self._speak(BRIEFING_ACK)
        self._speak(self._build_briefing_text(briefing_period))
        return True

    def _handle_soft_confirmation(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        confirmation_tokens = (
            "계속진행",
            "진행하면될",
            "그대로진행",
            "그렇게해",
            "그렇게하",
            "오케이진행",
            "좋아진행",
            "그걸로해",
            "그걸로가",
            "괜찮아진행",
        )
        if any(token in normalized for token in confirmation_tokens):
            self._speak(SOFT_CONFIRM_ACK)
            return True
        return False

    def _handle_social_dialogue(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if any(
            token in normalized
            for token in (
                "자기소개",
                "너소개",
                "규비스소개",
                "한마디",
                "영상보고있는분들",
                "시청자",
                "구독자",
            )
        ):
            self._speak(GYUVIS_INTRO_REPLY)
            return True

        if any(token in normalized for token in ("너오늘어때", "규비스오늘어때", "기분어때", "상태어때", "괜찮아")):
            self._speak(GYUVIS_WELLBEING_REPLY)
            return True

        if any(token in normalized for token in ("나힘들", "힘들다", "힘들어", "지쳤", "피곤해", "피곤하다", "번아웃")):
            self._speak(USER_TIRED_REPLY)
            return True

        if any(token in normalized for token in ("우울", "속상", "짜증", "멘탈", "오늘별로", "오늘안좋", "최악", "죽겠", "빡세", "버거", "힘든하루")):
            self._speak(USER_BAD_DAY_REPLY)
            return True

        if any(token in normalized for token in ("오늘좋", "기분좋", "잘됐", "행복", "뿌듯", "괜찮았", "나쁘지않")):
            self._speak(USER_GOOD_DAY_REPLY)
            return True

        return False

    def _handle_browser_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)

        local_pages = [
            (("에이전트", "리포트", "대시보드", "agent report"), f"{SERVER_URL}/agent/report-center", "네 보스. 에이전트 리포트 센터를 열겠습니다."),
            (("크리에이터", "creator studio", "콘텐츠 작업실", "콘텐츠"), f"{SERVER_URL}/creator.html", "네 보스. 크리에이터 스튜디오를 열겠습니다."),
            (("돈 관리", "재정", "money core", "머니코어"), f"{SERVER_URL}/money-core", "네 보스. Money Core를 열겠습니다."),
            (("자동차", "차량", "drive"), f"{SERVER_URL}/drive.html", "네 보스. 자동차 관리 화면을 열겠습니다."),
            (("설정", "setting"), f"{SERVER_URL}/settings.html", "네 보스. 설정 화면을 열겠습니다."),
            (("일정", "스케줄", "schedule"), f"{SERVER_URL}/schedule.html", "네 보스. 일정 화면을 열겠습니다."),
            (("브리핑", "briefing"), f"{SERVER_URL}/briefing.html", "네 보스. 브리핑 화면을 열겠습니다."),
        ]
        open_tokens = ("열어", "보여", "띄워", "이동", "실행", "open", "show")
        if any(token in normalized for token in open_tokens):
            agent_id = self._extract_agent_id(text)
            if agent_id in {1, 2, 3, 4} and ("에이전트" in normalized or "agent" in normalized):
                self._open_url(f"{SERVER_URL}/agent/report-center?agent={agent_id}")
                self._speak(f"네 보스. 에이전트 {agent_id}번 상세 화면을 열겠습니다.")
                return True
            for keywords, url, reply in local_pages:
                if any(self._normalize_text(keyword) in normalized for keyword in keywords):
                    self._open_url(url)
                    self._speak(reply)
                    return True

        if "유튜브" in normalized and any(token in normalized for token in ("틀어", "재생", "음악", "ncs")):
            if "ncs" in normalized:
                self._open_url(NCS_PLAYLIST_URL)
            else:
                query = text.replace("유튜브", "")
                self._open_url(f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}")
            self._speak("네 보스. 유튜브에서 요청하신 음악을 검색하겠습니다.")
            return True

        page_commands = [
            (("네이버",), "https://www.naver.com", "네 보스. 네이버를 열겠습니다."),
            (("구글", "google"), "https://www.google.com", "네 보스. 구글을 열겠습니다."),
            (("유튜브", "youtube"), "https://www.youtube.com", "네 보스. 유튜브를 열겠습니다."),
            (("gpt", "지피티", "챗지피티", "chatgpt"), "https://chatgpt.com", "네 보스. GPT를 열겠습니다."),
        ]

        for keywords, url, reply in page_commands:
            if any(self._normalize_text(keyword) in normalized for keyword in keywords) and any(token in normalized for token in ("열어", "켜줘", "보여", "가자")):
                self._open_url(url)
                self._speak(reply)
                return True

        if "뉴스" in normalized and any(token in normalized for token in ("보여", "열어", "확인")):
            self._open_url("https://news.google.com/topstories?hl=ko&gl=KR&ceid=KR:ko")
            self._speak("네 보스. 최신 뉴스 화면을 열겠습니다.")
            return True

        if "날씨" in normalized and any(token in normalized for token in ("보여", "열어", "확인")):
            self._open_url("https://www.google.com/search?q=%ED%98%84%EC%9E%AC+%EB%82%A0%EC%94%A8")
            self._speak("네 보스. 현재 날씨 정보를 열겠습니다.")
            return True

        return False

    def _handle_desktop_monitor_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if "모니터" not in normalized:
            return False
        if re.search(r"\d+번모니터", normalized) is None:
            return False

        action_keywords = ("유튜브", "youtube", "엑셀", "excel", "네이버", "구글", "gpt", "지피티", "뉴스", "날씨")
        if not any(keyword in normalized for keyword in action_keywords):
            return False

        script_path = pathlib.Path(__file__).resolve().parent / "pc_desktop_actions.py"
        try:
            completed = subprocess.run(
                [sys.executable, str(script_path), "--text", text],
                cwd=str(script_path.parent),
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = (completed.stdout or completed.stderr or "").strip()
            result = json.loads(output) if output else {}
            message = str(result.get("message") or "").strip()
            if completed.returncode == 0 and result.get("ok", False):
                self._speak(f"네 보스. {message}")
            else:
                self._speak(message or "데스크톱 명령을 처리하는 중 문제가 발생했습니다.")
        except Exception as error:
            self._log(f"데스크톱 모니터 명령 실패: {error}")
            self._speak("데스크톱 명령을 실행하는 중 문제가 발생했습니다.")
        return True

    def _open_url(self, url: str) -> None:
        webbrowser.open(url)

    def _build_briefing_text(self, period: str) -> str:
        if period == "evening":
            return self._build_evening_briefing_text()

        endpoint = "morning" if period == "morning" else "today"
        fallback = (
            "오늘 등록된 일정은 모두 마무리되었습니다."
            if period == "afternoon"
            else "오늘은 크게 급한 건 없어 보입니다. 일정 확인만 하고 차분히 시작하시면 좋겠습니다."
        )

        try:
            briefing = self._get_json(f"{SERVER_URL}/briefing/{endpoint}")
        except Exception as error:
            self._log(f"{period} briefing fetch failed: {error}")
            return fallback

        if endpoint == "morning":
            headline = str(briefing.get("headline", "")).strip()
            bullets = briefing.get("bullets") or []
            bullet_text = " ".join(str(item).strip() for item in bullets if str(item).strip())
            return " ".join(part for part in (headline, bullet_text) if part) or fallback

        message = str(briefing.get("message", "")).strip()
        schedules = briefing.get("schedules") or []
        top_tasks = briefing.get("top_tasks") or []
        schedule_text = ""
        task_text = ""
        if schedules:
            first_schedule = schedules[0]
            title = str(first_schedule.get("title", "")).strip()
            start_time = str(first_schedule.get("start_time", "") or "").strip()
            schedule_text = f"남은 주요 일정은 {title} {start_time}입니다.".strip()
        else:
            schedule_text = "오늘 등록된 일정은 모두 마무리되었습니다."
        if top_tasks:
            title = str(top_tasks[0].get("title", "")).strip()
            task_text = f"확인할 할 일은 {title}부터 보시면 좋겠습니다."
        return " ".join(part for part in (message, schedule_text, task_text) if part) or fallback

    def _build_evening_briefing_text(self) -> str:
        try:
            briefing = self._get_json(f"{SERVER_URL}/briefing/evening")
        except Exception as error:
            self._log(f"Evening briefing fetch failed: {error}")
            return (
                "오늘 등록된 일정은 모두 마무리되었습니다. "
                "현재 4개의 에이전트 중 2개가 활성 상태입니다. "
                "1개는 대기 중이며, 1개는 서버 오류를 확인 중입니다. "
                "활성 에이전트 2개는 보스께서 요청하신 업무를 진행 중이며, 완료 후 보고드리겠습니다."
            )

        headline = str(briefing.get("headline", "")).strip()
        bullets = briefing.get("bullets") or []
        bullet_text = " ".join(str(item).strip() for item in bullets if str(item).strip())
        schedule_text = bullet_text or "오늘 등록된 일정은 모두 마무리되었습니다."
        agent_text = (
            "현재 4개의 에이전트 중 2개가 활성 상태입니다. "
            "1개는 대기 중이며, 1개는 서버 오류를 확인 중입니다. "
            "활성 에이전트 2개는 보스께서 요청하신 업무를 진행 중이며, 완료 후 보고드리겠습니다."
        )
        return " ".join(part for part in (headline, schedule_text, agent_text) if part)

    def _launch_hud_if_needed(self) -> None:
        if not OPEN_JARVIS_HUD_ON_WAKE:
            return

        now = time.monotonic()
        if now - self._last_hud_launch_at < JARVIS_HUD_COOLDOWN_SECONDS:
            return

        try:
            target = launch_jarvis_hud()
            self._last_hud_launch_at = now
            self._log(f"GYUVIS HUD opened: {target}")
        except Exception as error:
            self._log(f"GYUVIS HUD open failed: {error}")

    def _record_audio(self, seconds: float) -> np.ndarray:
        recording = sd.rec(
            int(seconds * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
        )
        sd.wait()
        return recording.reshape(-1)

    def _record_followup_audio(self) -> np.ndarray:
        block_seconds = 0.20
        blocksize = int(SAMPLE_RATE * block_seconds)
        min_samples = int(FOLLOWUP_RECORD_SECONDS * SAMPLE_RATE)
        max_samples = int(FOLLOWUP_MAX_RECORD_SECONDS * SAMPLE_RATE)
        silence_limit = max(1, int(FOLLOWUP_SILENCE_SECONDS / block_seconds))
        chunks: list[np.ndarray] = []
        silent_blocks = 0
        heard_voice = False

        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=blocksize) as stream:
            while sum(chunk.size for chunk in chunks) < max_samples:
                data, _overflowed = stream.read(blocksize)
                flat = data.reshape(-1).copy()
                chunks.append(flat)

                rms = float(np.sqrt(np.mean(np.square(flat.astype(np.float32) / 32768.0))))
                if rms >= FOLLOWUP_VOICE_THRESHOLD:
                    heard_voice = True
                    silent_blocks = 0
                elif heard_voice:
                    silent_blocks += 1

                sample_count = sum(chunk.size for chunk in chunks)
                if sample_count >= min_samples and heard_voice and silent_blocks >= silence_limit:
                    break

        if not chunks:
            return np.array([], dtype=np.int16)
        return np.concatenate(chunks).astype(np.int16)

    def _transcribe(self, samples: np.ndarray) -> str:
        audio = sr.AudioData(samples.tobytes(), SAMPLE_RATE, 2)
        try:
            return self.recognizer.recognize_google(audio, language="ko-KR").strip()
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as error:
            self._log(f"음성 인식 서비스 오류: {error}")
            return ""

    def _looks_like_wake_phrase(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        wake_phrases = WAKE_PHRASES or (VOICE_WAKE_TARGET,)
        return any(self._normalize_text(phrase) in normalized for phrase in wake_phrases)

    def _looks_like_sleep_phrase(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        return any(
            self._normalize_text(phrase) in normalized
            for phrase in SLEEP_PHRASES + EXTRA_SLEEP_PHRASES
        )

    def _send_followup_to_server(self, text: str) -> str:
        try:
            initial = self._post_json(
                f"{SERVER_URL}/mobile/assistant/command",
                {"text": text, "source": "pc-wake"},
            )
        except Exception as error:
            self._log(f"서버 전송 실패: {error}")
            return "서버 연결에 실패했습니다."

        mode = str(initial.get("mode", ""))
        summary = str(initial.get("summary", "")).strip()

        if mode != "agent_task":
            return summary or "확인했습니다."

        task = initial.get("task") or {}
        task_type = str(task.get("task_type", ""))
        task_id = task.get("id")
        if not task_id:
            return summary or "확인 중입니다."

        self._log(f"에이전트 작업 #{task_id} 결과를 기다립니다...")
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            time.sleep(2)
            try:
                detail = self._get_json(f"{SERVER_URL}/agent/tasks/{task_id}")
            except Exception as error:
                self._log(f"작업 상태 조회 실패: {error}")
                break

            status = str(detail.get("status", ""))
            if status == "completed":
                result_summary = str(detail.get("result_summary") or summary or "확인했습니다.")
                self._remember_followup_action(task_type, result_summary)
                return result_summary
            if status == "failed":
                return str(detail.get("error_message") or "작업 처리 중 오류가 발생했습니다.")

        return summary or "작업을 시작했습니다. 결과 확인에 조금 더 시간이 필요합니다."

    def _remember_followup_action(self, task_type: str, result_summary: str) -> None:
        if task_type == "agent2_it_blog_draft" and "글쓰기 화면" in result_summary and "입력" in result_summary:
            self._pending_followup_action = "naver_blog_fill_draft"

    def _post_json(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _get_json(self, url: str) -> dict[str, Any]:
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def _publish_subtitle(self, input_text: str | None = None, output_text: str | None = None) -> None:
        payload: dict[str, str] = {}
        if input_text is not None:
            payload["input"] = input_text
        if output_text is not None:
            payload["output"] = output_text
        if not payload:
            return

        try:
            self._post_json(f"{SERVER_URL}/assistant/subtitles", payload)
        except Exception:
            pass

    def _speak(self, text: str) -> None:
        if TTS_BACKEND in ("off", "none", "silent", "0"):
            self._log(f"TTS disabled: {text}")
            self._publish_subtitle(output_text=text)
            return
        self._log(f"규비스: {text}")
        self._publish_subtitle(output_text=text)
        if TTS_BACKEND in ("auto", "edge", "edge-tts"):
            if self._speak_with_edge_tts(text):
                return
            if not TTS_ALLOW_FALLBACK and TTS_BACKEND in ("edge", "edge-tts"):
                self._log("edge-tts playback failed. Windows TTS fallback is disabled.")
                return
            self._log("edge-tts 재생에 실패해 다음 엔진으로 넘어갑니다.")

        if TTS_BACKEND in ("powershell", "ps"):
            if self._speak_with_powershell(text):
                return
            if not TTS_ALLOW_FALLBACK:
                self._log("PowerShell TTS failed. fallback is disabled.")
                return
            self._log("PowerShell TTS 재생에 실패해 pyttsx3로 fallback합니다.")

        if TTS_BACKEND not in ("auto", "pyttsx3", "powershell", "ps") and not TTS_ALLOW_FALLBACK:
            return

        try:
            if self.tts is None:
                raise RuntimeError("pyttsx3 is unavailable")
            self.tts.stop()
            self.tts.say(text)
            self.tts.runAndWait()
        except Exception as error:
            self._log(f"pyttsx3 재생 실패: {error}")
            if TTS_BACKEND == "pyttsx3":
                return
            if not TTS_ALLOW_FALLBACK:
                return
            if self._speak_with_powershell(text):
                return
            self._log("PowerShell TTS fallback도 실패했습니다.")

    def _normalize_text(self, text: str) -> str:
        compact = text.lower().replace(" ", "")
        for token in ("?", "!", ".", ",", "~", "…", "”", "“", "\"", "'"):
            compact = compact.replace(token, "")
        return compact

    def _describe_input_device(self) -> str:
        try:
            device = sd.query_devices(kind="input")
        except Exception:
            return ""

        if not isinstance(device, dict):
            return ""

        name = str(device.get("name", "")).strip()
        channels = device.get("max_input_channels")
        samplerate = device.get("default_samplerate")
        details = [part for part in (name, f"{channels}ch" if channels else "", f"{int(samplerate)}Hz" if samplerate else "") if part]
        return " / ".join(details)

    def _speak_with_powershell(self, text: str) -> bool:
        escaped = text.replace("'", "''")
        command = (
            "Add-Type -AssemblyName System.Speech; "
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$synth.SetOutputToDefaultAudioDevice(); "
            f"$synth.Speak('{escaped}')"
        )
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    command,
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except Exception as error:
            self._log(f"PowerShell TTS 실패: {error}")
            return False

    def _speak_with_edge_tts(self, text: str) -> bool:
        try:
            import pygame
        except Exception as error:
            self._log(f"pygame import 실패: {error}")
            return False

        TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        media_path = TEMP_AUDIO_DIR / f"gyuvis_{uuid.uuid4().hex}.mp3"
        normalized_text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
        edge_rate = self._normalize_edge_tts_rate(EDGE_TTS_RATE)

        if not self._create_edge_tts_media(normalized_text, media_path, edge_rate):
            if edge_rate != "+0%":
                self._log("edge-tts option failed. Retrying with default rate.")
                if not self._create_edge_tts_media(normalized_text, media_path, "+0%"):
                    return False
            else:
                return False

        if not media_path.exists() or media_path.stat().st_size == 0:
            self._log("edge-tts generated no playable media.")
            return False

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(media_path))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                time.sleep(0.1)
            return True
        except Exception as error:
            self._log(f"edge-tts 재생 실패: {error}")
            return False
        finally:
            try:
                pygame.mixer.music.unload()
            except Exception:
                pass
            try:
                media_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _normalize_edge_tts_rate(self, value: str) -> str:
        rate = str(value or "+0%").strip()
        if not rate:
            return "+0%"
        if rate.endswith("%"):
            numeric = rate.rstrip("%")
            if numeric.lstrip("+-").isdigit():
                return f"{numeric}%"
            return "+0%"
        if rate.lstrip("+-").isdigit():
            return f"{rate}%"
        return "+0%"

    def _create_edge_tts_media(self, text: str, media_path: pathlib.Path, rate: str) -> bool:
        command = [
            os.sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            EDGE_TTS_VOICE,
            "--rate",
            rate,
            "--text",
            text,
            "--write-media",
            str(media_path),
        ]
        edge_pitch = str(EDGE_TTS_PITCH or "").strip()
        if edge_pitch:
            command.insert(7, f"--pitch={edge_pitch}")
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
            if completed.stderr.strip():
                self._log(f"edge-tts stderr: {completed.stderr.strip()}")
            return True
        except subprocess.CalledProcessError as error:
            details = (error.stderr or error.stdout or str(error)).strip()
            self._log(f"edge-tts generation failed: {details}")
            return False
        except Exception as error:
            self._log(f"edge-tts generation failed: {error}")
            return False

    def _log(self, message: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        print(f"[{stamp}] {message}")


def main() -> None:
    listener = GyuvisWakeListener()
    try:
        listener.run()
    except KeyboardInterrupt:
        print("\n종료 요청을 받아 웨이크 모드를 멈춥니다.")
        listener.stop()
    except urllib.error.URLError as error:
        print(f"서버 연결 오류: {error}")
    except Exception as error:
        print(f"예상치 못한 오류: {error}")


if __name__ == "__main__":
    main()
