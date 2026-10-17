"""Render a dense static tech-stack insert for the GyuVIS making-of video."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "renders" / "gyuvis_tech_stack_visual.png"
FONT = r"C:\Windows\Fonts\malgun.ttf"
MONO = r"C:\Windows\Fonts\consola.ttf"
W, H = 1920, 1080


def f(size: int, mono: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(MONO if mono else FONT, size)


def box(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], title: str, subtitle: str, accent: str) -> None:
    x1, y1, x2, y2 = rect
    draw.rounded_rectangle(rect, radius=20, fill="#121c2d", outline="#263650", width=2)
    draw.rounded_rectangle((x1 + 22, y1 + 24, x1 + 30, y1 + 74), radius=4, fill=accent)
    draw.text((x1 + 48, y1 + 23), title, font=f(30), fill="#f1f7ff")
    draw.multiline_text((x1 + 48, y1 + 76), subtitle, font=f(22), fill="#aab8cc", spacing=8)


def pill(draw: ImageDraw.ImageDraw, x: int, y: int, label: str, color: str) -> int:
    width = int(draw.textlength(label, font=f(22, True))) + 56
    draw.rounded_rectangle((x, y, x + width, y + 50), radius=25, fill="#182842", outline=color, width=2)
    draw.ellipse((x + 17, y + 18, x + 29, y + 30), fill=color)
    draw.text((x + 42, y + 12), label, font=f(22, True), fill="#e6f0ff")
    return x + width + 16


def main() -> None:
    image = Image.new("RGB", (W, H), "#070d18")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, W, 10), fill="#36dbc9")
    draw.text((106, 72), "GyuLab / GyuVIS / TECH SNAPSHOT", font=f(24, True), fill="#6f8aa9")
    draw.text((106, 130), "규비스는 이렇게 동작합니다", font=f(62), fill="#f4f7fb")
    draw.text((108, 218), "음성·손 제스처·개인 데이터를 받아  개인 AI 비서 화면과 작업으로 연결합니다.", font=f(30), fill="#b9c7d9")

    box(draw, (106, 326, 550, 610), "INPUT", "Voice wake & command\nCamera-based hand gesture", "#5fe0d2")
    box(draw, (738, 326, 1182, 610), "GYUVIS RUNTIME", "Request routing\nLocal services & data", "#80aaff")
    box(draw, (1370, 326, 1814, 610), "INTERACTION", "Desktop HUD & web screen\nVisual feedback", "#ffb45b")
    draw.line((550, 468, 708, 468), fill="#3ddbc9", width=4)
    draw.polygon([(728, 468), (704, 454), (704, 482)], fill="#3ddbc9")
    draw.line((1182, 468, 1340, 468), fill="#ffb45b", width=4)
    draw.polygon([(1360, 468), (1336, 454), (1336, 482)], fill="#ffb45b")

    draw.text((106, 692), "사용 기술", font=f(34), fill="#f4f7fb")
    draw.text((106, 741), "백엔드 · 음성", font=f(22), fill="#8194ad")
    x = 106
    for label, color in [("Python", "#ffd166"), ("FastAPI", "#36dbc9"), ("SQLite", "#77a9ff"), ("sounddevice", "#ffb45b"), ("SpeechRecognition", "#caa6ff")]:
        x = pill(draw, x, 776, label, color)

    draw.text((106, 860), "손 제스처 HUD", font=f(22), fill="#8194ad")
    x = 106
    for label, color in [("Electron", "#80aaff"), ("JavaScript", "#ffd166"), ("MediaPipe Hands", "#5fe0d2"), ("Camera Utils", "#ffb45b"), ("Canvas API", "#caa6ff")]:
        x = pill(draw, x, 895, label, color)

    draw.text((106, 1018), "MediaPipe Hands가 손 랜드마크를 인식하고, 엄지·검지 거리와 손 위치를 클릭·확대·스와이프 제스처로 해석합니다.", font=f(23), fill="#91a1b8")
    image.save(OUT)
    print(OUT)


if __name__ == "__main__":
    main()
