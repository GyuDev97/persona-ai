"""Render the technology insert in the same light project-note style as the intro."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "renders" / "gyuvis_tech_stack_note.png"
FONT = r"C:\Windows\Fonts\malgun.ttf"
MONO = r"C:\Windows\Fonts\consola.ttf"
W, H = 1920, 1080


def f(size: int, mono: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(MONO if mono else FONT, size)


def tag(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, color: str) -> int:
    width = int(draw.textlength(label, font=f(22, True))) + 54
    draw.rounded_rectangle((x, y, x + width, y + 48), radius=12, fill="#ffffff", outline=color, width=2)
    draw.ellipse((x + 16, y + 18, x + 28, y + 30), fill=color)
    draw.text((x + 40, y + 11), label, font=f(22, True), fill="#4e5351")
    return x + width + 14


def section(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], number: str, title: str, description: str, accent: str) -> None:
    x1, y1, x2, y2 = rect
    draw.rounded_rectangle(rect, radius=18, fill="#ffffff", outline="#e4e1dc", width=2)
    draw.text((x1 + 30, y1 + 28), number, font=f(20, True), fill=accent)
    draw.text((x1 + 30, y1 + 66), title, font=f(30), fill="#313230")
    draw.multiline_text((x1 + 30, y1 + 116), description, font=f(21), fill="#777873", spacing=7)


def main() -> None:
    image = Image.new("RGB", (W, H), "#faf9f6")
    draw = ImageDraw.Draw(image)
    draw.text((104, 70), "GyuLab  /  Making Of", font=f(22), fill="#94948e")
    draw.text((104, 142), "PROJECT NOTE  ·  TECH STACK", font=f(20), fill="#a1a19b")
    draw.text((104, 195), "규비스를 구성하는 기술", font=f(61), fill="#242523")
    draw.line((104, 296, 1816, 296), fill="#deddd8", width=2)
    draw.text((104, 354), "입력 방식이 다르기 때문에, 음성·손 제스처·서버를 각각의 도구로 나눴습니다.", font=f(29), fill="#5d5e59")

    section(draw, (104, 450, 625, 676), "01 / VOICE", "음성 호출과 명령", "PC 마이크 입력을 받아\n호출어와 다음 명령을 인식합니다.", "#d9742d")
    section(draw, (700, 450, 1221, 676), "02 / GESTURE", "카메라 기반 손 제스처", "손 랜드마크와 손가락 거리를 이용해\n클릭·확대·스와이프를 해석합니다.", "#438dda")
    section(draw, (1296, 450, 1816, 676), "03 / SERVICE", "개인 AI 비서 기능", "요청을 받고 필요한 서비스와\n로컬 데이터를 연결합니다.", "#44a88b")

    draw.text((104, 754), "Voice", font=f(22), fill="#a36c4c")
    x = 104
    for label, color in [("Python", "#e3ad36"), ("sounddevice", "#d9742d"), ("SpeechRecognition", "#aa78ce")]:
        x = tag(draw, x, 790, label, color)

    draw.text((104, 874), "Gesture HUD", font=f(22), fill="#5d86ae")
    x = 104
    for label, color in [("Electron", "#438dda"), ("JavaScript", "#d9a326"), ("MediaPipe Hands", "#38aaa0"), ("Camera Utils", "#d9742d"), ("Canvas API", "#8a70c8")]:
        x = tag(draw, x, 910, label, color)

    draw.text((104, 1017), "Backend & Data  ·  FastAPI  ·  SQLite", font=f(24), fill="#5d866f")
    draw.text((104, 1048), "GyuVIS / Personal AI Assistant Project", font=f(20), fill="#a5a49e")
    image.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
