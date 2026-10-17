"""Create Korean SRT/ASS captions and a hard-subtitled copy of 01_intro.mp4."""

from __future__ import annotations

import math
import subprocess
import urllib.request
from pathlib import Path

import imageio_ffmpeg
import speech_recognition as sr


SOURCE = Path(r"C:\Users\bgpoi\OneDrive\Desktop\01_intro.mp4")
OUT_DIR = Path(__file__).resolve().parent / "renders"
WAV = OUT_DIR / "01_intro_caption_source.wav"
SRT = OUT_DIR / "01_intro_ko.srt"
ASS = OUT_DIR / "01_intro_ko.ass"
VIDEO = OUT_DIR / "01_intro_subtitled.mp4"
CHUNK_SECONDS = 8.0


def stamp(seconds: float, ass: bool = False) -> str:
    seconds = max(0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    if ass:
        return f"{hours}:{minutes:02}:{secs:05.2f}"
    millis = int(round((secs - int(secs)) * 1000))
    return f"{hours:02}:{minutes:02}:{int(secs):02},{millis:03}"


def subtitle_lines(text: str) -> list[str]:
    corrections = {
        "안녕하세요 그림입니다": "안녕하세요, 규랩입니다",
        "깁스를": "규비스를",
        "깁스가": "규비스가",
        "깁스는": "규비스는",
        "깁스": "규비스",
        "코덱스": "Codex",
    }
    for source, replacement in corrections.items():
        text = text.replace(source, replacement)
    words = text.split()
    groups: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > 27:
            groups.append(current)
            current = word
        else:
            current = candidate
    if current:
        groups.append(current)
    return groups or [text]


def wrap_two_lines(text: str) -> str:
    if len(text) <= 17:
        return text
    words = text.split()
    if len(words) < 2:
        return text
    midpoint = len(words) // 2
    return " ".join(words[:midpoint]) + "\\N" + " ".join(words[midpoint:])


def extract_wav() -> None:
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(SOURCE), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(WAV)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def transcribe() -> list[tuple[float, float, str]]:
    # Windows의 남아 있는 로컬 프록시 설정이 Google ASR 연결을 가로채지 않게 한다.
    urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False
    duration = 0.0
    with sr.AudioFile(str(WAV)) as source:
        duration = source.DURATION
        blocks: list[tuple[float, float, str]] = []
        for index in range(math.ceil(duration / CHUNK_SECONDS)):
            start = index * CHUNK_SECONDS
            raw = recognizer.record(source, duration=CHUNK_SECONDS)
            if not raw.frame_data:
                break
            try:
                spoken = recognizer.recognize_google(raw, language="ko-KR").strip()
            except sr.UnknownValueError:
                continue
            lines = subtitle_lines(spoken)
            line_duration = CHUNK_SECONDS / len(lines)
            for line_index, line in enumerate(lines):
                line_start = start + line_index * line_duration + 0.08
                line_end = min(start + (line_index + 1) * line_duration - 0.08, duration)
                if line_end > line_start:
                    blocks.append((line_start, line_end, line))
    return blocks


def write_subtitles(blocks: list[tuple[float, float, str]]) -> None:
    srt_chunks = []
    ass_chunks = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "PlayResX: 1920",
        "PlayResY: 1080",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: Default,Malgun Gothic,38,&H00FFFFFF,&H000000FF,&H00101010,&H7F000000,1,0,0,0,100,100,0,0,1,2.0,0.4,2,120,120,150,1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    for index, (start, end, text) in enumerate(blocks, start=1):
        ass_text = wrap_two_lines(text)
        srt_text = ass_text.replace("\\N", "\n")
        srt_chunks.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n{srt_text}\n")
        ass_chunks.append(f"Dialogue: 0,{stamp(start, True)},{stamp(end, True)},Default,,0,0,0,,{ass_text}")
    SRT.write_text("\n".join(srt_chunks), encoding="utf-8")
    ASS.write_text("\n".join(ass_chunks) + "\n", encoding="utf-8-sig")


def burn() -> None:
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(SOURCE),
            "-vf", "ass=filename=renders/01_intro_ko.ass", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "copy", "-movflags", "+faststart", str(VIDEO),
        ],
        check=True,
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    extract_wav()
    blocks = transcribe()
    write_subtitles(blocks)
    burn()
    print(f"captions={len(blocks)}")
    print(SRT)
    print(VIDEO)


if __name__ == "__main__":
    main()
