"""Extract the approved narration timeline as one Premiere-ready M4A track."""

from pathlib import Path
import subprocess

import imageio_ffmpeg


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "renders" / "gyuvis_how_it_was_built_user_narration_documentary.mp4"
TARGET = ROOT / "renders" / "premiere_gyuvis_narration_timeline.m4a"


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(SOURCE)
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(SOURCE), "-vn",
            "-c:a", "aac", "-b:a", "192k", str(TARGET),
        ],
        check=True,
    )
    print(TARGET)


if __name__ == "__main__":
    main()
