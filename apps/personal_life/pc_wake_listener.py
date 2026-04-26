import json
import os
import pathlib
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.request
from collections import deque
from typing import Any

import numpy as np
import pyttsx3
import sounddevice as sd
import speech_recognition as sr


SAMPLE_RATE = 16_000
BLOCK_SECONDS = 0.08
CLAP_THRESHOLD = float(os.getenv("GYUVIS_CLAP_THRESHOLD", "0.11"))
CLAP_MIN_GAP_SECONDS = 0.10
CLAP_MAX_WINDOW_SECONDS = 1.6
CLAP_COUNT_TO_WAKE = int(os.getenv("GYUVIS_CLAP_COUNT", "2"))
WAKE_RECORD_SECONDS = float(os.getenv("GYUVIS_WAKE_RECORD_SECONDS", "4.0"))
FOLLOWUP_RECORD_SECONDS = float(os.getenv("GYUVIS_FOLLOWUP_RECORD_SECONDS", "6.0"))
COOLDOWN_SECONDS = float(os.getenv("GYUVIS_WAKE_COOLDOWN_SECONDS", "2.2"))
SERVER_URL = os.getenv("GYUVIS_SERVER_URL", "http://127.0.0.1:8000").rstrip("/")
SEND_FOLLOWUP_TO_SERVER = os.getenv("GYUVIS_SEND_FOLLOWUP", "1") == "1"
AUTO_LISTEN_FOLLOWUP = os.getenv("GYUVIS_AUTO_LISTEN_FOLLOWUP", "1") == "1"
DEBUG_AUDIO = os.getenv("GYUVIS_DEBUG_AUDIO", "0") == "1"
STAY_AWAKE_AFTER_WAKE = os.getenv("GYUVIS_STAY_AWAKE", "1") == "1"
WAKE_PHRASES = (
    "일어나",
    "일어",
    "규비스",
    "규비",
    "보스",
    "깨어",
    "wake up",
    "wake",
)
GREETING = os.getenv("GYUVIS_GREETING", "어서오세요 보스.")
TTS_BACKEND = os.getenv("GYUVIS_TTS_BACKEND", "auto").lower()
EDGE_TTS_VOICE = os.getenv("GYUVIS_EDGE_TTS_VOICE", "ko-KR-SunHiNeural")
TEMP_AUDIO_DIR = pathlib.Path(os.getenv("GYUVIS_TEMP_AUDIO_DIR", os.path.join(os.getcwd(), ".tmp_tts")))
SLEEP_PHRASES = ("잘자", "대기", "꺼져", "수면 모드", "sleep")


class GyuvisWakeListener:
    def __init__(self) -> None:
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = False
        self.recognizer.energy_threshold = 180
        self.recognizer.pause_threshold = 0.8
        self.recognizer.non_speaking_duration = 0.45

        self.tts = None
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

    def _handle_wake_cycle(self) -> None:
        self._log("박수 패턴을 감지했습니다. 호출어를 듣는 중입니다...")
        wake_audio = self._record_audio(WAKE_RECORD_SECONDS)
        wake_text = self._transcribe(wake_audio)

        if not wake_text:
            self._log("호출어를 알아듣지 못했습니다.")
            self._speak("호출어를 듣지 못했습니다.")
            return

        self._log(f"호출어 인식: {wake_text}")
        if not self._looks_like_wake_phrase(wake_text):
            self._log("호출어가 맞지 않아 다시 대기합니다.")
            self._speak("호출어가 맞지 않습니다.")
            return

        self._speak(GREETING)
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
        if self._looks_like_sleep_phrase(command_text):
            self._stay_awake = False
            self._speak("대기 모드로 돌아갑니다.")
            self._log("대기 모드로 돌아갑니다. 다시 깨우려면 박수와 호출어가 필요합니다.")
            return

        if SEND_FOLLOWUP_TO_SERVER:
            response_text = self._send_followup_to_server(command_text)
            if response_text:
                self._speak(response_text)
        else:
            self._log("서버 연동이 꺼져 있어 추가 명령은 출력만 합니다.")
            self._speak("서버 연동이 꺼져 있습니다.")

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
        return any(self._normalize_text(phrase) in normalized for phrase in WAKE_PHRASES)

    def _looks_like_sleep_phrase(self, text: str) -> bool:
        normalized = self._normalize_text(text)
        return any(self._normalize_text(phrase) in normalized for phrase in SLEEP_PHRASES)

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

    def _speak(self, text: str) -> None:
        self._log(f"규비스: {text}")
        if TTS_BACKEND in ("auto", "edge", "edge-tts"):
            if self._speak_with_edge_tts(text):
                return
            self._log("edge-tts 재생에 실패해 다음 엔진으로 넘어갑니다.")

        if TTS_BACKEND in ("powershell", "ps"):
            if self._speak_with_powershell(text):
                return
            self._log("PowerShell TTS 재생에 실패해 pyttsx3로 fallback합니다.")

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

        try:
            subprocess.run(
                [
                    os.sys.executable,
                    "-m",
                    "edge_tts",
                    "--voice",
                    EDGE_TTS_VOICE,
                    "--text",
                    text,
                    "--write-media",
                    str(media_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except Exception as error:
            self._log(f"edge-tts 생성 실패: {error}")
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
