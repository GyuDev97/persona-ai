"""Create silent 1080p Notion/document-style inserts for Premiere editing."""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, concatenate_videoclips


WIDTH, HEIGHT, FPS = 1920, 1080, 24
OUT = Path(__file__).resolve().parent / "renders" / "premiere_notion_assets"
PLAN = Path(__file__).resolve().parent / "Structure" / "구조도.png"
FONT = r"C:\Windows\Fonts\malgun.ttf"


def typeface(size: int):
    return ImageFont.truetype(FONT, size)


def page(section: str, title: str, body: str, filename: str, duration: float, image_crop=None) -> None:
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#fbfbfa")
    draw = ImageDraw.Draw(canvas)
    draw.text((148, 88), "GyuLab / Projects / GyuVIS", font=typeface(26), fill="#8b8b8b")
    draw.text((148, 190), section, font=typeface(24), fill="#9a9a9a")
    draw.text((148, 244), title, font=typeface(62), fill="#252525")
    draw.line((148, 340, 1772, 340), fill="#e5e5e3", width=2)
    if image_crop:
        source = Image.open(PLAN).convert("RGB").crop(image_crop)
        source.thumbnail((1420, 520), Image.Resampling.LANCZOS)
        canvas.paste(source, ((WIDTH - source.width) // 2, 390))
        y = 950
    else:
        y = 420
    draw.multiline_text((148, y), body, font=typeface(36), fill="#575757", spacing=20)
    draw.text((148, 1015), "GyuVIS Making Of", font=typeface(22), fill="#a0a0a0")
    clip = ImageClip(np.array(canvas)).with_duration(duration)
    clip.write_videofile(str(OUT / filename), fps=FPS, codec="libx264", audio=False, preset="ultrafast", logger=None)
    clip.close()


def why_canvas(stage: int) -> Image.Image:
    """A document page that becomes denser as the narration explains the need."""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#fbfbfa")
    draw = ImageDraw.Draw(canvas)
    draw.text((148, 88), "GyuLab / Projects / GyuVIS", font=typeface(26), fill="#8b8b8b")
    draw.text((148, 190), "02 / WHY", font=typeface(24), fill="#9a9a9a")
    draw.text((148, 244), "왜 규비스를 만들었나", font=typeface(62), fill="#252525")
    draw.line((148, 340, 1772, 340), fill="#e5e5e3", width=2)
    draw.text((148, 402), "흩어진 개인 작업을 한 곳에서 연결하고 싶었습니다.", font=typeface(35), fill="#565656")

    items = [
        (148, 500, "개인 프로젝트", "기획 · 개발 · 진행 상황"),
        (540, 500, "블로그 작업", "초안 · 아이디어 · 자료"),
        (148, 710, "메모", "할 일 · 떠오른 생각"),
        (540, 710, "사진 · 문서", "필요할 때 다시 찾기"),
    ]
    for number, (x, y, label, detail) in enumerate(items):
        if stage == 0:
            break
        if stage == 1 and number > 1:
            break
        draw.rounded_rectangle((x, y, x + 330, y + 150), radius=15, fill="#ffffff", outline="#e4e4e1", width=2)
        draw.text((x + 24, y + 25), label, font=typeface(26), fill="#303030")
        draw.text((x + 24, y + 76), detail, font=typeface(21), fill="#868686")
        draw.ellipse((x + 280, y + 30, x + 294, y + 44), fill="#58a6ff" if number < 2 else "#f2b750")

    if stage >= 2:
        draw.line((930, 505, 1040, 505), fill="#c8c8c4", width=3)
        draw.line((930, 785, 1040, 785), fill="#c8c8c4", width=3)
        draw.line((1040, 505, 1040, 645), fill="#c8c8c4", width=3)
        draw.line((1040, 785, 1040, 645), fill="#c8c8c4", width=3)
        draw.polygon([(1055, 645), (1036, 634), (1036, 656)], fill="#c8c8c4")
        draw.rounded_rectangle((1090, 542, 1680, 746), radius=18, fill="#f1f7f6", outline="#bfded8", width=2)
        draw.text((1132, 580), "GyuVIS", font=typeface(38), fill="#1f5550")
        draw.text((1132, 642), "필요할 때 정리하고, 찾고,\n작업을 옆에서 도와주는 개인 AI 비서", font=typeface(27), fill="#456762", spacing=12)
        draw.text((148, 958), "문제: 정보가 흩어져 있음  →  목표: 내 작업을 이해하는 한 곳의 동반자", font=typeface(24), fill="#777777")
    draw.text((148, 1015), "GyuVIS Making Of", font=typeface(22), fill="#a0a0a0")
    return canvas


def why_page() -> None:
    stages = [(0, 5), (1, 8), (2, 12)]
    clips = [ImageClip(np.array(why_canvas(stage))).with_duration(duration) for stage, duration in stages]
    video = concatenate_videoclips(clips, method="chain")
    video.write_videofile(str(OUT / "02_why_gyuvis.mp4"), fps=FPS, codec="libx264", audio=False, preset="ultrafast", logger=None)
    video.close()
    for clip in clips:
        clip.close()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    page("01 / INTRO", "규비스는 어떻게 만들었을까?", "기획도에서 시작해\nCodex와 기능을 하나씩 만들었습니다.", "01_intro.mp4", 8)
    why_page()
    page("03 / MAP", "먼저 전체 지도를 그렸다", "초기 기획도입니다. 현재 구현과 앞으로의 로드맵을 함께 담고 있습니다.", "03_structure_overview.mp4", 14, (350, 170, 1980, 1060))
    page("04 / BUILD", "전체를 한 번에 만들지 않았다", "구조도에서 필요한 섹션 하나를 고르고\n현재 상태 · 목표 · 제약 · 완료 기준을 Codex에 전달했습니다.", "04_build_with_codex.mp4", 14)
    page("05 / NEXT", "계속 만드는 중입니다", "필요한 기능부터 하나씩 붙여\n규비스를 개인 AI 비서로 키우고 있습니다.", "05_outro.mp4", 8)


if __name__ == "__main__":
    main()
