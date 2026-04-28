import json
import os
import pathlib
import subprocess
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
FOLLOWUP_RECORD_SECONDS = float(os.getenv("GYUVIS_FOLLOWUP_RECORD_SECONDS", "6.0"))
COOLDOWN_SECONDS = float(os.getenv("GYUVIS_WAKE_COOLDOWN_SECONDS", "2.2"))
VOICE_ONLY_WAKE = os.getenv("GYUVIS_VOICE_ONLY_WAKE", "1") == "1"
SERVER_URL = os.getenv("GYUVIS_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
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
GREETING = os.getenv("GYUVIS_GREETING", "어서오세요 보스.")
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
    "부탁해",
    "그래",
    "해줘",
    "시작해",
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
EVENING_BRIEFING_ACK = os.getenv("GYUVIS_EVENING_BRIEFING_ACK", "네 알겠습니다 보스.")
SOCIAL_CLOSE_ACK = os.getenv("GYUVIS_SOCIAL_CLOSE_ACK", "네 보스. 감사합니다. 필요하시면 언제든 다시 부르십시오.")
SLEEP_ACKNOWLEDGEMENT = os.getenv("GYUVIS_SLEEP_ACK", "\ub124 \uc54c\uaca0\uc2b5\ub2c8\ub2e4.")
SLEEP_PHRASES = ("잘자", "대기", "꺼져", "수면 모드", "sleep")


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
        self._awaiting_evening_briefing = False

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
        command_audio = self._record_audio(FOLLOWUP_RECORD_SECONDS)
        command_text = self._transcribe(command_audio)

        if not command_text:
            self._log("명령이 들리지 않았습니다. 계속 대기합니다.")
            return

        self._log(f"추가 명령: {command_text}")
        self._publish_subtitle(input_text=command_text)
        if self._looks_like_sleep_phrase(command_text):
            self._stay_awake = False
            self._awaiting_evening_briefing = False
            self._speak(SLEEP_ACKNOWLEDGEMENT)
            self._log("Pause command acknowledged. Returning to standby mode.")
            return
            self._speak("대기 모드로 돌아갑니다.")
            self._log("대기 모드로 돌아갑니다. 다시 깨우려면 박수와 호출어가 필요합니다.")
            return

        if self._looks_like_social_close(command_text):
            self._stay_awake = False
            self._awaiting_evening_briefing = False
            self._speak(SOCIAL_CLOSE_ACK)
            self._log("Social close acknowledged. Returning to standby mode.")
            return

        if self._awaiting_evening_briefing:
            if self._looks_like_affirmative(command_text):
                self._awaiting_evening_briefing = False
                self._speak(EVENING_BRIEFING_ACK)
                briefing_text = self._build_evening_briefing_text()
                self._speak(briefing_text)
                return

            self._awaiting_evening_briefing = False

        if self._handle_browser_command(command_text):
            return

        if SEND_FOLLOWUP_TO_SERVER:
            response_text = self._send_followup_to_server(command_text)
            if response_text:
                self._speak(response_text)
        else:
            self._log("서버 연동이 꺼져 있어 추가 명령은 출력만 합니다.")
            self._speak("서버 연동이 꺼져 있습니다.")

    def _build_wake_greeting(self) -> str:
        if EVENING_BRIEFING_ENABLED and datetime.now().hour >= EVENING_START_HOUR:
            self._awaiting_evening_briefing = True
            return EVENING_GREETING

        self._awaiting_evening_briefing = False
        return GREETING

    def _looks_like_affirmative(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        if normalized in {self._normalize_text(phrase) for phrase in SHORT_AFFIRMATIVE_PHRASES}:
            return True
        return any(self._normalize_text(phrase) in normalized for phrase in AFFIRMATIVE_PHRASES)

    def _looks_like_social_close(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        return any(self._normalize_text(phrase) in normalized for phrase in SOCIAL_CLOSE_PHRASES)

    def _handle_browser_command(self, text: str) -> bool:
        normalized = self._normalize_text(text)

        if "유튜브" in normalized and any(token in normalized for token in ("틀어", "재생", "음악", "ncs")):
            query = "NCS music playlist" if "ncs" in normalized else text.replace("유튜브", "")
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

    def _open_url(self, url: str) -> None:
        webbrowser.open(url)

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
                return str(detail.get("result_summary") or summary or "확인했습니다.")
            if status == "failed":
                return str(detail.get("error_message") or "작업 처리 중 오류가 발생했습니다.")

        return summary or "작업을 시작했습니다. 결과 확인에 조금 더 시간이 필요합니다."

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
