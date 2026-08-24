"""Small, server-safe GYUVIS text-to-speech entry point."""

from __future__ import annotations

import logging
import os
import pathlib
import subprocess
import sys
import time
import uuid


logger = logging.getLogger("gyuos.tts")


def speak_gyuvis_text(text: str, *, backend_override_env: str | None = None) -> bool:
    """Speak text on this (Core) PC without requiring a microphone listener.

    The wake listener owns its interactive audio loop, so it cannot safely be
    imported by FastAPI.  This helper follows its existing PowerShell fallback
    policy and intentionally keeps speech local to the Core laptop.
    """
    override = os.getenv(backend_override_env, "").strip() if backend_override_env else ""
    backend = (override or os.getenv("GYUVIS_TTS_BACKEND", "edge")).strip().lower()
    allow_fallback = os.getenv("GYUVIS_TTS_ALLOW_FALLBACK", "0") == "1"
    if backend in {"off", "none", "silent", "0"}:
        logger.info("TTS disabled; skipped speech: %s", text)
        return False

    if backend in {"auto", "edge", "edge-tts"}:
        if _speak_with_edge_tts(text):
            return True
        if not allow_fallback and backend in {"edge", "edge-tts"}:
            return False

    # PowerShell is the existing wake listener's fallback engine.
    if backend in {"powershell", "ps"} or (
        backend in {"auto", "edge", "edge-tts"} and allow_fallback
    ):
        return _speak_with_powershell(text)

    logger.warning("Server-side TTS backend '%s' is not available for arrival events.", backend)
    return False


def _speak_with_edge_tts(text: str) -> bool:
    try:
        import pygame
    except Exception:
        logger.exception("pygame is unavailable for Edge TTS playback")
        return False

    temp_dir = pathlib.Path(os.getenv("GYUVIS_TEMP_AUDIO_DIR", ".tmp_tts"))
    temp_dir.mkdir(parents=True, exist_ok=True)
    media_path = temp_dir / f"gyuvis_arrival_{uuid.uuid4().hex}.mp3"
    normalized_text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    rate = _normalize_edge_rate(os.getenv("GYUVIS_EDGE_TTS_RATE", "+0%"))
    voice = os.getenv("GYUVIS_EDGE_TTS_VOICE", "ko-KR-InJoonNeural")
    pitch = os.getenv("GYUVIS_EDGE_TTS_PITCH", "").strip()
    command = [sys.executable, "-m", "edge_tts", "--voice", voice, "--rate", rate, "--text", normalized_text, "--write-media", str(media_path)]
    if pitch:
        # A negative value such as -8Hz must be attached with '='; otherwise
        # argparse interprets it as a new option and exits with code 2.
        command[7:7] = [f"--pitch={pitch}"]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=45)
        if not media_path.exists() or media_path.stat().st_size == 0:
            logger.error("Edge TTS produced no playable media")
            return False
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(str(media_path))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.1)
        return True
    except Exception:
        logger.exception("GYUVIS Edge TTS failed")
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


def _normalize_edge_rate(value: str) -> str:
    rate = str(value or "+0%").strip()
    if rate.endswith("%") and rate.rstrip("%").lstrip("+-").isdigit():
        return rate
    if rate.lstrip("+-").isdigit():
        return f"{rate}%"
    return "+0%"


def _speak_with_powershell(text: str) -> bool:
    escaped = text.replace("'", "''")
    command = (
        "Add-Type -AssemblyName System.Speech; "
        "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$synth.SetOutputToDefaultAudioDevice(); "
        f"$synth.Speak('{escaped}')"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return True
    except Exception:
        logger.exception("GYUVIS PowerShell TTS failed")
        return False
