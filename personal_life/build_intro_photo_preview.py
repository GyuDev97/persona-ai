"""Render one denser document-style intro still for approval before editing video."""

from pathlib import Path

from moviepy import VideoFileClip
from PIL import Image, ImageDraw, ImageFont, ImageFilter


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "renders" / "premiere_notion_intro_photo_preview.png"
SUCCESS = Path(r"C:\Users\bgpoi\OneDrive\문서\oCam\녹화_2026_08_18_20_09_50_549.mp4")
FONT = r"C:\Windows\Fonts\malgun.ttf"
WIDTH, HEIGHT = 1920, 1080


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT, size)


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *size), radius=radius, fill=255)
    return mask


def main() -> None:
    video = VideoFileClip(str(SUCCESS))
    frame = Image.fromarray(video.get_frame(min(9, video.duration - 0.1))).convert("RGB")
    video.close()

    canvas = Image.new("RGB", (WIDTH, HEIGHT), "#f9f9f7")
    draw = ImageDraw.Draw(canvas)
    draw.text((134, 84), "GyuLab  /  Making Of", font=font(24), fill="#888884")
    draw.text((134, 169), "PROJECT NOTE  ·  2026.08", font=font(22), fill="#9a9a94")
    draw.text((134, 225), "규비스 제작기", font=font(78), fill="#20201e")
    draw.line((134, 336, 1786, 336), fill="#deded9", width=2)

    draw.multiline_text((134, 418), "나만의 작업을 이해하고\n필요할 때 옆에서\n도와주는 AI 비서.", font=font(41), fill="#474743", spacing=11)
    draw.multiline_text((134, 604), "기획도에서 출발해, Codex와\n기능을 하나씩 만들었습니다.", font=font(27), fill="#777772", spacing=10)

    draw.rounded_rectangle((134, 740, 650, 918), radius=18, fill="#f0f6f4", outline="#cfe1db", width=2)
    draw.text((170, 779), "이번 영상에서", font=font(23), fill="#5c7c73")
    draw.text((170, 826), "왜 만들었는지 · 어떻게 설계했는지", font=font(25), fill="#325e52")
    draw.text((170, 870), "첫 음성 호출 기능을 고친 과정", font=font(25), fill="#325e52")

    frame.thumbnail((850, 480), Image.Resampling.LANCZOS)
    card = Image.new("RGB", (frame.width + 24, frame.height + 66), "#ffffff")
    card_draw = ImageDraw.Draw(card)
    card_draw.rectangle((0, 0, card.width, 48), fill="#222522")
    card_draw.ellipse((18, 16, 28, 26), fill="#ff5f57")
    card_draw.ellipse((35, 16, 45, 26), fill="#febc2e")
    card_draw.ellipse((52, 16, 62, 26), fill="#28c840")
    card_draw.text((82, 11), "GyuVIS  ·  voice wake demo", font=font(18), fill="#d7dedb")
    card.paste(frame, (12, 54))
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((0, 0, card.width - 1, card.height - 1), radius=18, fill=(70, 70, 66, 80))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    x, y = 850, 418
    canvas.paste(shadow, (x + 10, y + 12), shadow)
    canvas.paste(card, (x, y), rounded_mask(card.size, 18))
    draw.text((850, 986), "“일어나, 규비스”  —  음성 호출 시연", font=font(24), fill="#777772")
    draw.text((134, 1018), "GyuVIS / Personal AI Assistant Project", font=font(21), fill="#a0a09a")
    canvas.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
