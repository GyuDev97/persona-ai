"""Render the GyuVIS making-of video with the user's recorded narration."""

import sys
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import AudioClip, AudioFileClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips
import imageio_ffmpeg

from build_gyuvis_making_video import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    CAPTURE_FAILURE,
    CAPTURE_SUCCESS,
    FPS,
    HEIGHT,
    OUTPUT,
    PLAN_IMAGE,
    WIDTH,
    card,
    code_card,
    diagram_card,
    draw_centered,
    font,
    plan_crop_card,
    prompt_card,
)


NARRATION_DIR = Path(r"C:\Users\bgpoi\OneDrive\Desktop\새 폴더")
CHUNK_DIR = OUTPUT / "user_narrated_chunks"
WAKE_SOURCE = Path(__file__).resolve().parent / "pc_wake_listener.py"
LAUNCHER_SOURCE = Path(__file__).resolve().parent / "startup_jarvis_stack.bat"
CONSOLE_SCREENSHOT = Path(r"C:\Users\bgpoi\AppData\Local\Temp\codex-clipboard-ad7d3e1b-67e5-41c0-9637-1f1c421bde8e.png")


def source_audio(index: int) -> AudioFileClip:
    files = sorted(NARRATION_DIR.glob("음성 260818_*.m4a"))
    return AudioFileClip(str(files[index - 1]))


def video_with_hold(path: Path, caption: str, duration: float) -> CompositeVideoClip:
    source = VideoFileClip(str(path)).without_audio().resized(width=WIDTH)
    visible = min(duration, source.duration)
    moving = source.subclipped(0, visible).with_position((0, (HEIGHT - source.h) / 2))
    layers = [moving]
    if duration > visible:
        hold = source.to_ImageClip(t=max(0, visible - 0.1)).with_duration(duration - visible).with_position((0, (HEIGHT - source.h) / 2)).with_start(visible)
        layers.append(hold)
    shade = Image.new("RGBA", (WIDTH, 74), (0, 0, 0, 190))
    draw = ImageDraw.Draw(shade)
    draw_centered(draw, (32, 10, WIDTH - 32, 64), caption, font(27), "#ffffff", spacing=8)
    layers.append(ImageClip(np.array(shade)).with_duration(duration).with_position((0, HEIGHT - 74)))
    return CompositeVideoClip(layers, size=(WIDTH, HEIGHT)).with_duration(duration)


def user_codex_card(title: str, body: str) -> ImageClip:
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#070b12")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CANVAS_WIDTH, 10), fill="#38d8c7")
    draw.text((72, 62), title, font=font(46), fill="#ffffff")
    draw.rounded_rectangle((64, 150, CANVAS_WIDTH - 64, 616), radius=20, fill="#101b2b", outline="#24384f", width=3)
    draw.multiline_text((104, 205), body, font=font(33), fill="#e8f5f4", spacing=22)
    return ImageClip(np.array(image)).resized(width=WIDTH)


def source_code_clip(path: Path, first_line: int, last_line: int, duration: float, title: str) -> ImageClip:
    lines = path.read_text(encoding="utf-8").splitlines()[first_line - 1:last_line]
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#101317")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CANVAS_WIDTH, 72), fill="#1c2128")
    draw.text((42, 20), f"{path.name}  ·  {title}", font=font(25), fill="#d7e2ef")
    mono = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 27)
    y = 112
    for line_number, line in enumerate(lines, start=first_line):
        draw.text((46, y), f"{line_number:>4}", font=mono, fill="#6e7681")
        draw.text((158, y), line[:72], font=mono, fill="#c9d1d9")
        y += 40
    return ImageClip(np.array(image)).resized(width=WIDTH).with_duration(duration)


def screenshot_clip(path: Path, duration: float, title: str) -> ImageClip:
    source = Image.open(path).convert("RGB")
    source.thumbnail((CANVAS_WIDTH - 120, CANVAS_HEIGHT - 150), Image.Resampling.LANCZOS)
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#090d17")
    draw = ImageDraw.Draw(image)
    draw.text((60, 45), title, font=font(40), fill="#ffffff")
    image.paste(source, ((CANVAS_WIDTH - source.width) // 2, 120))
    return ImageClip(np.array(image)).resized(width=WIDTH).with_duration(duration)


def motive_clip(duration: float) -> ImageClip:
    source = Image.open(PLAN_IMAGE).convert("RGB")
    source.thumbnail((CANVAS_WIDTH, CANVAS_HEIGHT), Image.Resampling.LANCZOS)
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#0a0d13")
    image.paste(source, ((CANVAS_WIDTH - source.width) // 2, (CANVAS_HEIGHT - source.height) // 2))
    overlay = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), (0, 0, 0, 120))
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.text((70, 80), "왜 규비스를 만들었을까?", font=font(54), fill="#ffffff")
    draw.multiline_text((70, 520), "프로젝트 · 블로그 · 메모 · 자료가 흩어져 있어\n필요할 때 옆에서 정리하고 연결해 주는 친구가 필요했습니다.", font=font(31), fill="#ffffff", spacing=15)
    return ImageClip(np.array(image)).resized(width=WIDTH).with_duration(duration)


# audio_file, audio_start, audio_end, visual type
TIMELINE = [
    (1, 0, None, "intro"),
    (0, 0, 25, "motive"),
    (2, 0, None, "demo"),
    (3, 0, None, "call"),
    (4, 0, 42, "plan_core"),
    (4, 42, 84, "architecture"),
    (4, 84, None, "plan_modules"),
    (5, 0, None, "role"),
    (6, 0, None, "codex_method"),
    (7, 0, None, "feature"),
    (8, 0, None, "constraints"),
    (9, 0, None, "failure"),
    (10, 0, 16, "fix"),
    (10, 16, None, "success"),
    (11, 0, None, "tech"),
    (12, 0, None, "outro"),
]


def build_visual(kind: str, duration: float):
    if kind == "intro":
        return card("규비스는 어떻게 만들었을까?", "기획도에서 시작해\nCodex와 기능을 하나씩 만들었습니다.").with_duration(duration)
    if kind == "motive":
        return motive_clip(duration)
    if kind == "demo":
        return video_with_hold(CAPTURE_SUCCESS, "“일어나, 규비스”  ·  음성 호출 시연", duration)
    if kind == "call":
        return video_with_hold(CAPTURE_SUCCESS, "일어나, 규비스", duration)
    if kind == "plan_core":
        return plan_crop_card("처음에는 전체 지도를 그렸습니다", (350, 170, 1980, 610)).with_duration(duration)
    if kind == "architecture":
        return diagram_card().with_duration(duration)
    if kind == "plan_modules":
        return plan_crop_card("큰 기능을 섹션으로 나눴습니다", (350, 500, 1980, 1060)).with_duration(duration)
    if kind == "role":
        return video_with_hold(CAPTURE_SUCCESS, "듣고 · 판단하고 · PC와 웹 작업을 연결하는 개인 AI 비서", duration)
    if kind == "codex_method":
        return source_code_clip(WAKE_SOURCE, 134, 183, duration, "음성 호출 기능부터 구현")
    if kind == "feature":
        return source_code_clip(WAKE_SOURCE, 243, 270, duration, "호출어를 듣고 규비스를 깨우는 흐름")
    if kind == "constraints":
        return source_code_clip(LAUNCHER_SOURCE, 20, 37, duration, "실행 환경과 마이크 설정")
    if kind == "failure":
        return screenshot_clip(CONSOLE_SCREENSHOT, duration, "실제 오류 로그 · 첫 호출 누락")
    if kind == "fix":
        return code_card("오류를 고친 방식", "내장 마이크 배열 선택\n말이 시작될 때까지 대기\n말이 끝난 뒤 한 번에 인식").with_duration(duration)
    if kind == "success":
        return video_with_hold(CAPTURE_SUCCESS, "수정 후: 한 번의 호출로 규비스 열기", duration)
    if kind == "tech":
        return source_code_clip(WAKE_SOURCE, 28, 60, duration, "Python · sounddevice · SpeechRecognition · FastAPI")
    if kind == "outro":
        return card("계속 만드는 중입니다", "필요한 기능부터 하나씩 붙여\n규비스를 개인 AI 비서로 키우고 있습니다.").with_duration(duration)
    raise ValueError(f"Unknown visual type: {kind}")


def render_chunk(index: int) -> Path:
    audio_index, start, end, kind = TIMELINE[index - 1]
    original_audio = None
    if audio_index == 0:
        audio = AudioClip(lambda _t: 0, duration=end, fps=44_100)
    else:
        original_audio = source_audio(audio_index)
        end = original_audio.duration if end is None else min(end, original_audio.duration)
        audio = original_audio.subclipped(start, end)
    visual = build_visual(kind, audio.duration).with_audio(audio)
    CHUNK_DIR.mkdir(parents=True, exist_ok=True)
    target = CHUNK_DIR / f"{index:02d}.mp4"
    visual.write_videofile(str(target), fps=FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)
    visual.close()
    if original_audio:
        original_audio.close()
    return target


def assemble() -> Path:
    target = OUTPUT / "gyuvis_how_it_was_built_user_narration_documentary.mp4"
    manifest = CHUNK_DIR / "concat.txt"
    manifest.write_text(
        "".join(f"file '{(CHUNK_DIR / f'{index:02d}.mp4').as_posix()}'\n" for index in range(1, len(TIMELINE) + 1)),
        encoding="utf-8",
    )
    subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c", "copy", str(target)],
        check=True,
        capture_output=True,
        text=True,
    )
    return target


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python build_gyuvis_user_narrated_video.py <chunk-number|assemble>")
    command = sys.argv[1]
    if command == "assemble":
        print(assemble())
        return
    print(render_chunk(int(command)))


if __name__ == "__main__":
    main()
