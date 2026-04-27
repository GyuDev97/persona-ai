from __future__ import annotations

import os
import queue
import re
import sys
import time
from pathlib import Path

import numpy as np
import sounddevice as sd
import torch
import whisper


APP_DIR = Path(__file__).resolve().parent
INDEX_HTML = APP_DIR / "index.html"
WHISPER_CACHE = Path.home() / ".cache" / "whisper"
MODEL_NAME = "medium"
SAMPLE_RATE = 16000
BLOCK_SECONDS = 0.5
WINDOW_SECONDS = 3.0
MIN_AUDIO_LEVEL = 0.008
WAKE_PATTERNS = (
    "\uc77c\uc5b4\ub098",
)


def normalize_korean(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z\uac00-\ud7a3]+", "", text).lower()


def launch_jarvis_app() -> None:
    if not INDEX_HTML.exists():
        raise FileNotFoundError(f"index.html not found: {INDEX_HTML}")

    os.startfile(str(INDEX_HTML))


def detect_wake_phrase(text: str) -> bool:
    normalized = normalize_korean(text)
    return any(pattern in normalized for pattern in WAKE_PATTERNS)


def load_model() -> whisper.Whisper:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading Whisper model '{MODEL_NAME}' on {device}...")
    return whisper.load_model(MODEL_NAME, device=device, download_root=str(WHISPER_CACHE))


def transcribe_chunk(model: whisper.Whisper, audio: np.ndarray) -> str:
    audio = whisper.pad_or_trim(audio.astype(np.float32))
    result = model.transcribe(
        audio,
        language="ko",
        task="transcribe",
        fp16=torch.cuda.is_available(),
        temperature=0,
        verbose=False,
        compression_ratio_threshold=2.4,
        logprob_threshold=-1.0,
        no_speech_threshold=0.6,
    )
    return (result.get("text") or "").strip()


def main() -> int:
    if not WHISPER_CACHE.joinpath(f"{MODEL_NAME}.pt").exists():
        print(f"Whisper cache not found: {WHISPER_CACHE / (MODEL_NAME + '.pt')}")
        return 1

    model = load_model()
    audio_queue: "queue.Queue[np.ndarray]" = queue.Queue()
    buffer = np.zeros(0, dtype=np.float32)
    window_samples = int(SAMPLE_RATE * WINDOW_SECONDS)
    blocksize = int(SAMPLE_RATE * BLOCK_SECONDS)
    cooldown_until = 0.0
    last_run_at = 0.0

    def audio_callback(indata: np.ndarray, frames: int, _time: object, status: sd.CallbackFlags) -> None:
        if status:
            print(f"Audio callback status: {status}")
        if frames <= 0:
            return
        audio_queue.put(indata[:, 0].copy())

    print("Jarvis whisper wake listener starting...")
    print("Wake phrase configured: il-eo-na")
    print("Microphone is armed and listening.")

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=blocksize,
            callback=audio_callback,
        ):
            while True:
                chunk = audio_queue.get()
                buffer = np.concatenate((buffer, chunk))
                if buffer.size > window_samples:
                    buffer = buffer[-window_samples:]

                now = time.time()
                if now - last_run_at < 1.2:
                    continue
                last_run_at = now

                if buffer.size < window_samples:
                    continue

                level = float(np.sqrt(np.mean(np.square(buffer))))
                if level < MIN_AUDIO_LEVEL:
                    continue

                text = transcribe_chunk(model, buffer)
                if not text:
                    continue

                print(f'heard="{text}" level={level:.4f}')

                if now < cooldown_until:
                    continue

                if detect_wake_phrase(text):
                    print("Wake phrase detected. Launching JARVIS...")
                    launch_jarvis_app()
                    cooldown_until = now + 6.0
    except KeyboardInterrupt:
        print("\nStopping wake listener.")
        return 0
    except Exception as exc:
        print(f"Wake listener failed: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
