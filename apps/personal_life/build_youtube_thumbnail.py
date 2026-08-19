"""Build a 1280x720 YouTube thumbnail from the real GyuVIS demo screen."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "renders" / "youtube_thumbnail_gyuvis_making_of.png"
DEMO_CAPTURE = ROOT / "renders" / "premiere_notion_intro_photo_preview.png"
FONT = r"C:\Windows\Fonts\malgunbd.ttf"
REGULAR = r"C:\Windows\Fonts\malgun.ttf"
W, H = 1280, 720


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT if bold else REGULAR, size)


def main() -> None:
    source = Image.open(DEMO_CAPTURE).convert("RGB")
    # The intro preview already contains the real GyuVIS demo inside a browser frame.
    frame = source.crop((850, 418, 1728, 958))
    frame = frame.resize((990, 557), Image.Resampling.LANCZOS)

    base = Image.new("RGB", (W, H), "#0d1822")
    blurred = frame.resize((W, H), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(20))
    base.paste(blurred)
    dark = Image.new("RGBA", (W, H), (7, 15, 23, 188))
    base = Image.alpha_composite(base.convert("RGBA"), dark).convert("RGB")
    draw = ImageDraw.Draw(base)

    card_x, card_y = 618, 122
    shadow = Image.new("RGBA", (1010, 578), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((0, 0, 1010, 578), fill=(0, 0, 0, 145))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    base.paste(shadow, (card_x + 7, card_y + 11), shadow)
    base.paste(frame, (card_x, card_y))
    draw = ImageDraw.Draw(base)
    draw.text((60, 103), "GyuLab", font=font(25, False), fill="#a4b3bf")
    draw.text((60, 215), "규비스 제작기", font=font(72), fill="#ffffff")
    draw.multiline_text((63, 318), "개인 AI 비서,\n어떻게 만들었을까?", font=font(39, False), fill="#d4e0e8", spacing=12)
    draw.line((63, 450, 470, 450), fill="#6d8c9d", width=2)
    draw.text((63, 481), "기획 · 화면 시안 · Codex", font=font(25, False), fill="#aabac4")

    base.convert("RGB").save(OUT, quality=96)
    print(OUT)


if __name__ == "__main__":
    main()
