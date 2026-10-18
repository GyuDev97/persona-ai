"""AI 직원의 서버 관리 작업 공간. 결과물은 이 안에만 쓰고 읽는다.

파일명과 경로는 모두 서버가 검증한다. LLM이나 사용자가 준 문자열로 경로를 만들지 않는다.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

OUT_EXT = {"md": "text/markdown", "txt": "text/plain", "json": "application/json"}
IN_EXT = {"md", "txt", "json", "log", "csv"}
_NAME = re.compile(r"^[\w가-힣][\w가-힣.\- ]{0,95}$")
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}  # Windows 예약 이름


class WorkspaceError(Exception):
    pass


def safe_filename(name: str, allowed_ext: set[str]) -> str:
    """경로 구분자·상위 경로·예약 이름·허용되지 않은 확장자를 거부한다."""
    if not isinstance(name, str) or not _NAME.match(name) or ".." in name or name != name.strip():
        raise WorkspaceError(f"허용되지 않는 파일 이름: {str(name)[:40]!r}")
    stem, _, ext = name.rpartition(".")
    if not stem or ext.lower() not in allowed_ext or stem.lower() in _RESERVED:
        raise WorkspaceError(f"허용되지 않는 파일 이름/확장자: {name[:40]!r}")
    return name


def slugify(title: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "-", title).strip("-")[:40]
    return s or "result"


class Workspace:
    def __init__(self, root: Path):
        self.root = root

    def _inside(self, path: Path) -> Path:
        """심볼릭 링크를 풀어낸 실제 경로가 작업 공간 안에 있어야 한다."""
        root = self.root.resolve()
        real = path.resolve()
        try:
            real.relative_to(root)
        except ValueError:
            raise WorkspaceError("작업 공간 밖의 경로는 접근할 수 없습니다") from None
        return real

    def input_dir(self, worker_id: int) -> Path:
        return self.root / f"w{int(worker_id)}" / "inputs"

    def run_dir(self, worker_id: int, run_id: int) -> Path:
        return self.root / f"w{int(worker_id)}" / "runs" / f"r{int(run_id)}"

    def write_output(self, worker_id: int, run_id: int, filename: str, content: str) -> dict:
        """결과물 저장. 기존 파일을 덮어쓰지 않는다(x 모드). 메타데이터(상대경로, 크기, sha256)를 돌려준다."""
        ext = safe_filename(filename, set(OUT_EXT)).rsplit(".", 1)[1].lower()
        d = self.run_dir(worker_id, run_id)
        d.mkdir(parents=True, exist_ok=True)
        target = self._inside(d / filename)
        data = content.encode("utf-8")
        with open(target, "xb") as f:
            f.write(data)
        return {"rel_path": target.relative_to(self.root.resolve()).as_posix(), "size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "media_type": OUT_EXT[ext]}

    def write_input(self, worker_id: int, filename: str, content: str) -> dict:
        safe_filename(filename, IN_EXT)
        d = self.input_dir(worker_id)
        d.mkdir(parents=True, exist_ok=True)
        target = self._inside(d / filename)
        target.write_text(content, encoding="utf-8")
        return {"name": filename, "size": target.stat().st_size}

    def read_input(self, worker_id: int, filename: str, max_chars: int) -> str:
        safe_filename(filename, IN_EXT)
        target = self._inside(self.input_dir(worker_id) / filename)
        if not target.is_file():
            raise WorkspaceError(f"입력 파일이 없습니다: {filename}")
        return target.read_text(encoding="utf-8", errors="replace")[:max_chars]

    def read_rel(self, rel_path: str) -> bytes:
        """DB에 기록된 상대 경로로 결과물을 읽는다(이때도 작업 공간 안인지 다시 확인)."""
        if not rel_path or rel_path.startswith(("/", "\\")) or ":" in rel_path or ".." in Path(rel_path).parts:
            raise WorkspaceError("잘못된 결과물 경로")
        target = self._inside(self.root / rel_path)
        if not target.is_file():
            raise WorkspaceError("결과물 파일이 없습니다")
        return target.read_bytes()

    def list_inputs(self, worker_id: int) -> list[dict]:
        d = self.input_dir(worker_id)
        if not d.is_dir():
            return []
        return [{"name": p.name, "size": p.stat().st_size} for p in sorted(d.iterdir()) if p.is_file()]
