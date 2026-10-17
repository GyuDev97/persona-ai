"""Build two Korean GyuVIS-making-of video drafts from the supplied captures."""

import asyncio
import sys
from pathlib import Path

import edge_tts
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import AudioFileClip, CompositeVideoClip, ImageClip, VideoFileClip, concatenate_videoclips


WIDTH, HEIGHT, FPS = 640, 360, 10
CANVAS_WIDTH, CANVAS_HEIGHT = 1280, 720
FONT_PATH = Path(r"C:\Windows\Fonts\malgun.ttf")
CAPTURE_FAILURE = Path(r"C:\Users\bgpoi\OneDrive\문서\oCam\녹화_2026_08_18_20_03_37_62.mp4")
CAPTURE_SUCCESS = Path(r"C:\Users\bgpoi\OneDrive\문서\oCam\녹화_2026_08_18_20_09_50_549.mp4")
PLAN_IMAGE = Path(__file__).resolve().parent / "Structure" / "구조도.png"
OUTPUT = Path(__file__).resolve().parent / "renders"
VOICE = "ko-KR-InJoonNeural"

SEGMENTS = [
    ("card", "개인 AI 비서, 어떻게 만들었나요?", "규비스는 이렇게 만들었습니다.", "오늘은 규비스를 어떤 구조로 만들었는지, 그리고 코딩 에이전트 Codex를 어떻게 활용했는지 공개하겠습니다."),
    ("success", "완성된 모습", "“일어나, 규비스.”\n한 번의 호출로 화면이 열립니다.", "먼저 결과부터 보시죠. 규비스는 음성 호출을 듣고 바로 대기 화면을 엽니다."),
    ("plan-core", "처음에는 전체 지도를 그렸습니다", "", "처음에는 규비스가 어떤 입력을 받고, 코어에서 어떻게 판단하고, 어떤 결과를 내보낼지를 큰 구조도로 먼저 그렸습니다."),
    ("plan-modules", "큰 기능을 섹션으로 나눴습니다", "", "그리고 이 전체 시스템을 한 번에 만들지 않았습니다. 음성, 일정과 작업, 콘텐츠, 차량, 메모리처럼 실제로 필요한 섹션으로 나눴습니다."),
    ("card", "규비스가 하는 일", "음성 인식 · 작업 자동화\nPC 제어 · 브리핑 · 웹 화면", "규비스는 단순 채팅 화면이 아니라, 음성을 받아서 필요한 작업을 분류하고 PC와 웹 화면을 연결하는 개인 비서입니다."),
    ("diagram", "전체 구조", "", "규비스는 한 덩어리의 프로그램이 아닙니다. PC에서 듣고 실행하는 계층, 명령을 판단하는 규비스 코어, 그리고 데이터와 에이전트 작업 계층으로 나뉘어 있습니다."),
    ("card", "Codex와 만든 방식", "기능을 한 줄씩 외워서 만들기보다\n원하는 동작을 구체적으로 요청했습니다.", "저는 기능을 먼저 말로 정의하고 Codex에게 구현을 요청했습니다. 이후 실제로 실행해 보고, 오류 로그를 보면서 수정하는 식으로 만들었습니다."),
    ("prompt", "1. 구조도에서 한 섹션을 고릅니다", "[구현 위치] 입력 시스템의 ‘음성 입력’\n[사용자 행동] “일어나, 규비스”\n[기대 결과] 화면이 열리고 다음 명령을 듣기", "먼저 전체 구조도에서 이번에 만들 기능 하나만 고릅니다. 이번에는 음성 입력 섹션을 골랐고, 사용자가 말했을 때 어떤 결과가 나와야 하는지 한 장면으로 정의했습니다."),
    ("prompt", "2. 동작 규칙과 제약을 붙입니다", "[입력] 노트북 내장 마이크\n[수정 범위] 리스너와 실행 배치만\n[유지할 것] 기존 명령·데이터·화면\n[확인 방법] 콘솔 로그로 입력값 확인", "그다음에는 단순히 만들어 달라고 하지 않고, 어떤 마이크를 쓰는지, 어디까지 바꿔도 되는지, 기존 기능 중 무엇을 지켜야 하는지를 같이 전달했습니다."),
    ("prompt", "3. 안 되면 오류를 그대로 전달합니다", "[관찰] 첫 호출은 누락, 두 번째에 성공\n[로그] PaErrorCode -9999 · Realtek 입력 오류\n[질문] 고정 녹음 구간과 입력 장치가 원인인지 확인", "실행 결과가 기대와 다르면 막연히 안 된다고 하지 않고, 실제 동작 영상과 콘솔 로그를 함께 전달합니다. 그러면 추측이 아니라 증거를 바탕으로 다음 수정을 정할 수 있습니다."),
    ("prompt", "4. 수정 결과의 합격 기준을 확인합니다", "[수정] 내장 마이크 배열 선택\n[수정] 말 시작부터 녹음, 끝난 뒤 인식\n[통과] 한 번의 ‘일어나’로 화면 열기\n[변경 파일] Listener · Launcher", "마지막에는 어떤 파일을 고쳤는지와 성공 조건을 확인합니다. 이 과정을 반복하면서 한 섹션씩 전체 구조도를 실제 기능으로 바꿔 나갔습니다."),
    ("failure", "개발 중 실제 문제", "첫 호출은 못 듣고\n두 번째 호출에서야 반응했습니다.", "만들다 보면 항상 한 번에 되지는 않습니다. 실제로 처음에는 호출어가 녹음 구간의 끝에 걸려서 놓치는 문제가 있었습니다."),
    ("code", "문제를 고친 코드", "마이크 배열을 선택하고\n말이 시작될 때까지 기다린 뒤\n발화가 끝나면 한 번에 인식", "그래서 불안정한 입력 장치를 피하고, 말이 시작되는 순간부터 녹음해서 끝난 뒤 인식하도록 바꿨습니다."),
    ("card", "사용한 기술", "Python · sounddevice · SpeechRecognition\nGoogle Speech Recognition · FastAPI", "핵심 기술은 파이썬, 마이크 입력, 음성 인식, 그리고 규비스 화면을 연결하는 웹 서버입니다."),
    ("card", "다음 편", "Codex에 어떤 식으로 요청하는지\n직접 따라 만드는 과정도 공개할까요?", "다음에는 실제 요청 문장부터 설치와 실행까지, 따라 만들 수 있는 튜토리얼로 이어가 보겠습니다."),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = FONT_PATH if FONT_PATH.exists() else Path(r"C:\Windows\Fonts\arial.ttf")
    return ImageFont.truetype(str(path), size=size)


def draw_centered(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, text_font, fill, spacing=12):
    left, top, right, bottom = box
    bbox = draw.multiline_textbbox((0, 0), text, font=text_font, spacing=spacing, align="center")
    x = left + ((right - left) - (bbox[2] - bbox[0])) / 2
    y = top + ((bottom - top) - (bbox[3] - bbox[1])) / 2
    draw.multiline_text((x, y), text, font=text_font, fill=fill, spacing=spacing, align="center")


def card(title: str, body: str) -> ImageClip:
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#090d17")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CANVAS_WIDTH, 10), fill="#38d8c7")
    draw.text((72, 112), title, font=font(55), fill="#ffffff")
    draw.line((72, 193, 230, 193), fill="#38d8c7", width=6)
    draw_centered(draw, (80, 255, CANVAS_WIDTH - 80, 570), body, font(43), "#d7e2ef", spacing=20)
    draw.text((72, 650), "GyuVIS MAKING OF", font=font(20), fill="#6f8095")
    return ImageClip(np.array(image)).resized(width=WIDTH)


def code_card(title: str, body: str) -> ImageClip:
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#070b12")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CANVAS_WIDTH, 10), fill="#38d8c7")
    draw.text((52, 55), title, font=font(35), fill="#ffffff")
    draw.rounded_rectangle((48, 125, CANVAS_WIDTH - 48, CANVAS_HEIGHT - 50), radius=16, fill="#101b2b", outline="#24384f", width=2)
    draw.multiline_text((78, 164), body, font=font(28), fill="#92f7e7", spacing=20)
    draw.text((78, CANVAS_HEIGHT - 94), "# Codex와 요구사항을 주고받으며 구현", font=font(18), fill="#6f8095")
    return ImageClip(np.array(image)).resized(width=WIDTH)


def diagram_card() -> ImageClip:
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#090d17")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CANVAS_WIDTH, 10), fill="#38d8c7")
    draw.text((72, 58), "규비스 전체 구조", font=font(52), fill="#ffffff")
    draw.text((74, 122), "PC에서 듣고 → 코어에서 판단하고 → 데이터·에이전트가 일을 처리합니다.", font=font(25), fill="#9fb2c7")

    groups = [
        (54, 190, 372, 650, "1. PC 계층"),
        (480, 190, 798, 650, "2. GyuVIS Core"),
        (906, 190, 1224, 650, "3. 데이터·에이전트"),
    ]
    for left, top, right, bottom, label in groups:
        draw.rounded_rectangle((left, top, right, bottom), radius=22, outline="#4d6478", width=3)
        draw.text((left + 24, top + 20), label, font=font(31), fill="#d7e2ef")

    def node(bounds, label, tone="#112235"):
        left, top, right, bottom = bounds
        draw.rounded_rectangle(bounds, radius=12, fill=tone, outline="#38d8c7", width=2)
        draw_centered(draw, (left + 8, top + 8, right - 8, bottom - 8), label, font(25), "#e8f5f4", spacing=9)

    node((88, 276, 338, 372), "PC Wake Listener\n마이크·음성 인식")
    node((88, 446, 338, 542), "HUD · 자막 · TTS\nPC / 웹 실행")
    node((514, 276, 764, 372), "FastAPI 명령 API\n호출·명령 전달")
    node((514, 446, 764, 542), "의도 분류 · 브리핑\n작업 서비스")
    node((940, 276, 1190, 372), "SQLite\n일정 · 메모리 · 작업")
    node((940, 446, 1190, 542), "PC Agent Runner\n뉴스 · 에이전트 작업")

    def arrow(start, end):
        draw.line((start, end), fill="#38d8c7", width=5)
        x, y = end
        draw.polygon([(x, y), (x - 18, y - 11), (x - 18, y + 11)], fill="#38d8c7")

    arrow((338, 324), (490, 324))
    arrow((764, 324), (916, 324))
    arrow((640, 372), (640, 428))
    arrow((1065, 372), (1065, 428))
    arrow((514, 494), (356, 494))
    return ImageClip(np.array(image)).resized(width=WIDTH)


def prompt_card(title: str, body: str) -> ImageClip:
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#070b12")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CANVAS_WIDTH, 10), fill="#38d8c7")
    draw.text((52, 55), title, font=font(35), fill="#ffffff")
    draw.rounded_rectangle((48, 125, CANVAS_WIDTH - 48, CANVAS_HEIGHT - 78), radius=16, fill="#101b2b", outline="#24384f", width=2)
    draw.multiline_text((78, 164), body, font=font(28), fill="#ffffff", spacing=20)
    draw.text((78, CANVAS_HEIGHT - 50), "전체 요청 예시와 기술 목록은 영상 설명란에", font=font(18), fill="#92f7e7")
    return ImageClip(np.array(image)).resized(width=WIDTH)


def plan_crop_card(title: str, crop_box: tuple[int, int, int, int]) -> ImageClip:
    source = Image.open(PLAN_IMAGE).convert("RGB").crop(crop_box)
    source.thumbnail((1140, 480), Image.Resampling.LANCZOS)
    image = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), "#090d17")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, CANVAS_WIDTH, 10), fill="#38d8c7")
    draw.text((72, 50), title, font=font(45), fill="#ffffff")
    x = (CANVAS_WIDTH - source.width) // 2
    y = 146 + (480 - source.height) // 2
    image.paste(source, (x, y))
    draw.text((72, 658), "초안 기획도: 현재 구현과 앞으로의 로드맵을 함께 담은 설계 지도", font=font(20), fill="#9fb2c7")
    return ImageClip(np.array(image)).resized(width=WIDTH)


def footage(path: Path, caption: str, duration: float) -> CompositeVideoClip:
    source = VideoFileClip(str(path)).without_audio().resized(width=WIDTH)
    duration = min(duration, source.duration)
    source = source.subclipped(0, duration).with_position((0, (HEIGHT - source.h) / 2))
    shade = Image.new("RGBA", (WIDTH, 132), (0, 0, 0, 185))
    draw = ImageDraw.Draw(shade)
    draw_centered(draw, (48, 18, WIDTH - 48, 114), caption, font(31), "#ffffff", spacing=10)
    caption_clip = ImageClip(np.array(shade)).with_duration(duration).with_position((0, HEIGHT - 132))
    return CompositeVideoClip([source, caption_clip], size=(WIDTH, HEIGHT)).with_duration(duration)


async def tts(text: str, target: Path) -> None:
    await edge_tts.Communicate(text, VOICE, rate="+5%", pitch="-5Hz").save(str(target))


async def synthesize_all() -> None:
    await asyncio.gather(*(tts(item[3], OUTPUT / "audio" / f"{index:02d}.mp3") for index, item in enumerate(SEGMENTS)))


def build_variant(with_voice: bool) -> Path:
    label = "ai_narration" if with_voice else "caption_only"
    clips = []
    for index, (kind, title, body, narration) in enumerate(SEGMENTS):
        audio = None
        if with_voice:
            audio_path = OUTPUT / "audio" / f"{index:02d}.mp3"
            audio = AudioFileClip(str(audio_path))
            duration = max(audio.duration + 0.7, 5.0)
        else:
            duration = 8.0 if kind == "card" else (18.0 if kind == "failure" else (9.0 if kind == "prompt" else 12.0))

        if kind == "card":
            visual = card(title, body).with_duration(duration)
        elif kind == "plan-core":
            visual = plan_crop_card(title, (350, 170, 1980, 610)).with_duration(duration)
        elif kind == "plan-modules":
            visual = plan_crop_card(title, (350, 500, 1980, 1060)).with_duration(duration)
        elif kind == "diagram":
            visual = diagram_card().with_duration(duration)
        elif kind == "prompt":
            visual = prompt_card(title, body).with_duration(duration)
        elif kind == "code":
            visual = code_card(title, body).with_duration(duration)
        else:
            visual = footage(CAPTURE_FAILURE if kind == "failure" else CAPTURE_SUCCESS, body, duration)
        if audio:
            visual = visual.with_audio(audio)
        clips.append(visual)

    result = concatenate_videoclips(clips, method="compose")
    target = OUTPUT / f"gyuvis_how_it_was_built_{label}.mp4"
    result.write_videofile(str(target), fps=FPS, codec="libx264", audio_codec="aac", preset="ultrafast", threads=4, logger=None)
    result.close()
    return target


def main() -> None:
    if not CAPTURE_FAILURE.exists() or not CAPTURE_SUCCESS.exists():
        raise FileNotFoundError("The supplied oCam captures could not be found.")
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT / "audio").mkdir(exist_ok=True)
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "both"
    if mode in {"voice", "both"}:
        asyncio.run(synthesize_all())
        print(build_variant(with_voice=True))
    if mode in {"caption", "both"}:
        print(build_variant(with_voice=False))


if __name__ == "__main__":
    main()
