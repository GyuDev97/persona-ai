"""Create a silent Premiere-ready insert explaining why GyuVIS was started."""

from moviepy import concatenate_videoclips

from build_gyuvis_making_video import OUTPUT, card


def main() -> None:
    clips = [
        card("왜 규비스를 만들었을까?", "프로젝트 · 블로그 · 메모 · 자료\n여기저기 흩어진 정보를 한곳으로").with_duration(12),
        card("옆에서 도와주는 개인 AI 비서", "필요할 때 정리하고 · 찾아주고 · 작업을 연결하는\n나만의 자비스 같은 친구를 만들고 싶었습니다.").with_duration(13),
    ]
    result = concatenate_videoclips(clips, method="compose")
    target = OUTPUT / "why_gyuvis_visual_insert_silent.mp4"
    result.write_videofile(str(target), fps=10, codec="libx264", audio=False, preset="ultrafast", threads=4, logger=None)
    result.close()
    print(target)


if __name__ == "__main__":
    main()
