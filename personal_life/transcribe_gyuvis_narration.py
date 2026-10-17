"""Transcribe the user-approved narration clips for video timing and editing."""

from pathlib import Path
import sys
import math

from moviepy import AudioFileClip
import speech_recognition as sr


SOURCE_DIR = Path(r"C:\Users\bgpoi\OneDrive\Desktop\새 폴더")
OUTPUT_DIR = Path(__file__).resolve().parent / "renders" / "narration_transcripts"
CHUNK_SECONDS = 42


def convert_to_wav(source: Path, target: Path) -> None:
    clip = AudioFileClip(str(source))
    try:
        clip.write_audiofile(str(target), fps=16_000, nbytes=2, codec="pcm_s16le", logger=None)
    finally:
        clip.close()


def transcribe(wav_path: Path) -> list[str]:
    recognizer = sr.Recognizer()
    lines: list[str] = []
    duration = AudioFileClip(str(wav_path)).duration
    with sr.AudioFile(str(wav_path)) as source:
        offset = 0.0
        for _ in range(math.ceil(duration / CHUNK_SECONDS)):
            audio = recognizer.record(source, duration=CHUNK_SECONDS)
            if not audio.frame_data:
                break
            try:
                text = recognizer.recognize_google(audio, language="ko-KR").strip()
            except sr.UnknownValueError:
                text = "[인식하지 못함]"
            except sr.RequestError as error:
                text = f"[음성 인식 서비스 오류: {error}]"
            lines.append(f"[{offset:05.1f}s] {text}")
            offset += CHUNK_SECONDS
    return lines


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    clips = sorted(SOURCE_DIR.glob("음성 260818_*.m4a"))
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end = int(sys.argv[2]) if len(sys.argv) > 2 else len(clips)
    for index, source in enumerate(clips, start=1):
        if index < start or index > end:
            continue
        wav_path = OUTPUT_DIR / f"{index:02d}.wav"
        if not wav_path.exists():
            convert_to_wav(source, wav_path)
        lines = transcribe(wav_path)
        (OUTPUT_DIR / f"{index:02d}.md").write_text(
            f"## {index:02d}. {source.name}\n\n" + "\n".join(lines) + "\n",
            encoding="utf-8",
        )
        print(f"완료: {source.name}")
    pieces = [path.read_text(encoding="utf-8") for path in sorted(OUTPUT_DIR.glob("[0-9][0-9].md"))]
    (OUTPUT_DIR / "transcript.md").write_text("\n".join(pieces), encoding="utf-8")


if __name__ == "__main__":
    main()
