"""AI 개발 직원용 개발 도구와 프로젝트 권한.

- 기존 Tool Registry 에 project.* / code.* / terminal.run / git.* 를 등록한다(risk="project"). 별도 실행 엔진이나 승인 시스템은 없다.
- 도구는 호출마다 승인을 요청하지 않는다. 대신 사용자가 미리 부여한 범위(프로젝트 등록 + 직원별 읽기/수정/실행 권한)를 **도구가 직접 검사**하며,
  범위를 벗어난 호출은 실행하지 않고 오류로 돌려준다(그러면 LLM 이 다시 판단한다). 직원·실행 ID 는 서버가 넣는 `_ctx` 이고 모델이 만들 수 없다.
- 경로는 모델이 준 문자열을 그대로 쓰지 않는다: 절대 경로·드라이브·`..`·심볼릭 링크/정션을 푼 실제 경로가 프로젝트 안인지 확인한다.
- 명령 실행은 셸 문자열이 아니라 **사용자가 등록한 실행 프로파일의 argv 배열**만 쓴다(AI 는 프로파일 이름과 검증된 추가 인자만 고른다).
  주의: 프로파일이 실행하는 프로젝트 코드(테스트 등)는 OS 사용자 권한으로 돈다. 이것은 샌드박스가 아니다(README 의 제한 사항 참고).
- push/commit/reset/clean 같은 변경형 git 기능과 삭제 도구는 만들지 않았다.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from .activity import Activity
from .config import Settings
from .db import Database
from .models import DevProject, ProjectChange, Worker, WorkerProjectGrant, row_dict, utcnow
from .textutil import redact
from .tools import Tool, ToolError, ToolRegistry

logger = logging.getLogger("gyunexus")

EXCLUDED_DIRS = {".git", "node_modules", ".venv", "venv", "env", "dist", "build", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".next", ".nuxt",
                 "target", ".tox", ".gradle", "coverage", ".idea"}
SENSITIVE_DIRS = {".git", ".ssh", ".aws", ".gnupg", ".azure", ".kube"}
_SAFE_SUFFIX = (".example", ".sample", ".template", ".dist")
_SENSITIVE_FILE = re.compile(
    r"^(\.env(\..+)?|\.envrc|id_(rsa|dsa|ecdsa|ed25519)(\..*)?|.*\.(pem|key|pfx|p12|jks|keystore|kdbx|ppk)|\.npmrc|\.pypirc|\.netrc|\.git-credentials|\.htpasswd|"
    r"credentials(\..+)?|secrets?(\..+)?|.*_secret(s)?(\..+)?)$", re.I)
SHELLS = {"sh", "bash", "zsh", "dash", "fish", "csh", "tcsh", "ksh", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe", "wscript", "cscript", "mshta"}
PROFILE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,29}$")
ARG_RE = re.compile(r"^[A-Za-z0-9_./:=,@+\-\[\]]{1,200}$")
KINDS = ("test", "build", "lint", "other")
SECRET_ENV = re.compile(r"(key|token|secret|passw|credential|auth|cookie|session|private)", re.I)
TEXT_EXT_HINT = {".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".md", ".css", ".html", ".toml", ".yaml", ".yml", ".txt", ".cfg", ".ini", ".sh", ".bat", ".java", ".kt", ".go", ".rs",
                 ".c", ".h", ".cpp", ".cs", ".rb", ".php", ".sql", ".vue", ".svelte"}
MAX_FILE_BYTES = 1_000_000  # 읽기·검색 대상으로 삼는 파일의 최대 크기


class DevError(Exception):
    """프로젝트·권한 관리(CRUD) 오류. code: validation | not_found | conflict"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def _within(path: str, root: str) -> bool:
    a, b = _norm(path), _norm(root)
    try:
        return os.path.commonpath([a, b]) == b
    except ValueError:  # 다른 드라이브
        return False


def is_sensitive(rel: str) -> bool:
    parts = [p for p in rel.replace("\\", "/").split("/") if p]
    if any(p.lower() in SENSITIVE_DIRS for p in parts):
        return True
    if not parts:
        return False
    name = parts[-1]
    if name.lower().endswith(_SAFE_SUFFIX):
        return False
    return bool(_SENSITIVE_FILE.match(name))


def make_diff(path: str, before: str | None, after: str) -> tuple[str, int, int]:
    a = (before or "").splitlines(keepends=True)
    b = after.splitlines(keepends=True)
    lines = list(difflib.unified_diff(a, b, fromfile=f"a/{path}" if before is not None else "/dev/null", tofile=f"b/{path}", n=3))
    added = sum(1 for x in lines if x.startswith("+") and not x.startswith("+++"))
    removed = sum(1 for x in lines if x.startswith("-") and not x.startswith("---"))
    return "".join(lines), added, removed


def kill_tree(proc: subprocess.Popen) -> None:
    """프로세스와 자식 프로세스를 모두 종료한다(장시간 실행 정리)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True, timeout=10)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def run_process(argv: list[str], cwd: str, env: dict, timeout: float, cap: int) -> dict:
    """셸 없이 argv 배열로 실행한다. stdout/stderr 는 cap 바이트까지만 보관하고, 시간 초과 시 프로세스 트리를 종료한다."""
    kw: dict[str, Any] = {"cwd": cwd, "env": env, "stdin": subprocess.DEVNULL, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "shell": False}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        kw["start_new_session"] = True
    started = time.monotonic()
    try:
        proc = subprocess.Popen(argv, **kw)
    except FileNotFoundError:
        raise ToolError(f"실행 파일을 찾을 수 없습니다: {argv[0]}", kind="exec_not_found") from None
    except OSError as e:
        raise ToolError(f"실행하지 못했습니다: {type(e).__name__}", kind="exec_failed") from None
    bufs = {"out": bytearray(), "err": bytearray()}
    totals = {"out": 0, "err": 0}

    def drain(stream, key):
        try:
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                totals[key] += len(chunk)
                if len(bufs[key]) < cap:
                    bufs[key] += chunk[: cap - len(bufs[key])]
        except Exception:
            pass

    threads = [threading.Thread(target=drain, args=(proc.stdout, "out"), daemon=True), threading.Thread(target=drain, args=(proc.stderr, "err"), daemon=True)]
    for t in threads:
        t.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    for t in threads:
        t.join(timeout=3)
    return {"exit_code": proc.returncode if not timed_out else None, "timed_out": timed_out, "duration_s": round(time.monotonic() - started, 2),
            "stdout": bytes(bufs["out"]).decode("utf-8", errors="replace"), "stderr": bytes(bufs["err"]).decode("utf-8", errors="replace"),
            "truncated": totals["out"] > cap or totals["err"] > cap}


class DevService:
    def __init__(self, settings: Settings, db: Database, activity: Activity):
        self.settings, self.db, self.activity = settings, db, activity
        self._locks: dict[int, asyncio.Lock] = {}

    # ------------------------------------------------------------------ 프로젝트 등록·권한 관리(CRUD)

    def _lock(self, pid: int) -> asyncio.Lock:
        return self._locks.setdefault(pid, asyncio.Lock())

    def _data_dir(self) -> str:
        return os.path.realpath(str(self.settings.data_dir))

    def validate_profiles(self, raw: Any) -> list[dict]:
        if raw is None:
            return []
        if not isinstance(raw, list) or len(raw) > 12:
            raise DevError("validation", "실행 프로파일은 12개 이하의 목록이어야 합니다")
        out, names = [], set()
        for i, p in enumerate(raw, 1):
            if not isinstance(p, dict):
                raise DevError("validation", f"프로파일 {i}: 객체여야 합니다")
            name = p.get("name")
            if not isinstance(name, str) or not PROFILE_NAME.match(name):
                raise DevError("validation", f"프로파일 {i}: 이름은 소문자로 시작하는 영문·숫자·-_ 30자 이내여야 합니다")
            if name in names:
                raise DevError("validation", f"프로파일 이름 중복: {name}")
            names.add(name)
            kind = p.get("kind", "other")
            if kind not in KINDS:
                raise DevError("validation", f"프로파일 '{name}': kind 는 {', '.join(KINDS)} 중 하나여야 합니다")
            argv = p.get("argv")
            if not isinstance(argv, list) or not (1 <= len(argv) <= 30) or not all(isinstance(a, str) and 1 <= len(a) <= 300 and "\x00" not in a for a in argv):
                raise DevError("validation", f"프로파일 '{name}': argv 는 비어 있지 않은 문자열 배열(30개 이하)이어야 합니다")
            base = os.path.basename(argv[0].replace("\\", "/")).lower()
            if base in SHELLS or base.rsplit(".", 1)[0] in SHELLS:
                raise DevError("validation", f"프로파일 '{name}': 셸({base})은 실행할 수 없습니다. 실행 파일과 인자를 배열로 지정하세요")
            tmo = p.get("timeout_seconds", 120)
            if not isinstance(tmo, int) or isinstance(tmo, bool) or not (1 <= tmo <= self.settings.dev_exec_max_seconds):
                raise DevError("validation", f"프로파일 '{name}': 제한 시간은 1~{self.settings.dev_exec_max_seconds}초 정수여야 합니다")
            flags = p.get("allowed_flags", [])
            if not isinstance(flags, list) or not all(isinstance(f, str) and f.startswith("-") and ARG_RE.match(f) for f in flags):
                raise DevError("validation", f"프로파일 '{name}': allowed_flags 는 '-' 로 시작하는 문자열 배열이어야 합니다")
            out.append({"name": name, "kind": kind, "argv": list(argv), "timeout_seconds": tmo, "allow_args": bool(p.get("allow_args", False)), "allowed_flags": list(flags)})
        return out

    def _validate_project(self, data: dict, current: DevProject | None = None) -> dict:
        errors: list[str] = []
        cur = row_dict(current) if current else {}
        d = {**cur, **{k: v for k, v in data.items() if v is not None}}
        name = str(d.get("name") or "").strip()
        if not (1 <= len(name) <= 80):
            errors.append("프로젝트 이름은 1~80자여야 합니다")
        desc = d.get("description", "")
        if not isinstance(desc, str) or len(desc) > 2000:
            errors.append("설명은 2000자 이하여야 합니다")
        root = d.get("root_path")
        real = ""
        if not isinstance(root, str) or not root.strip():
            errors.append("프로젝트 경로를 입력하세요")
        else:
            p = Path(os.path.expanduser(root.strip()))
            if not p.is_absolute():
                errors.append("프로젝트 경로는 절대 경로여야 합니다")
            elif not p.is_dir():
                errors.append("존재하는 디렉터리가 아닙니다")
            else:
                real = os.path.realpath(str(p))
                if Path(real).parent == Path(real):
                    errors.append("파일 시스템 루트(드라이브 전체)는 등록할 수 없습니다")
                elif _norm(real) == _norm(os.path.expanduser("~")):
                    errors.append("홈 디렉터리 전체는 등록할 수 없습니다. 프로젝트 폴더를 지정하세요")
                elif _within(real, self._data_dir()):  # (프로젝트가 GyuNexus 자신이라 데이터 디렉터리를 포함하는 경우는 허용하되, 접근 시 그 하위를 막는다)
                    errors.append("GyuNexus 데이터 디렉터리 안은 등록할 수 없습니다")
        flags = {}
        for k in ("allow_read", "allow_write", "allow_exec", "allow_git", "enabled"):
            v = d.get(k, k in ("allow_read", "allow_git", "enabled"))
            if not isinstance(v, bool):
                errors.append(f"{k} 는 true/false 여야 합니다")
            flags[k] = bool(v)
        if (flags["allow_write"] or flags["allow_exec"] or flags["allow_git"]) and not flags["allow_read"]:
            errors.append("수정·실행·Git 권한은 읽기 권한이 있어야 부여할 수 있습니다")
        try:
            profiles = self.validate_profiles(d.get("exec_profiles", []))
        except DevError as e:
            errors.append(str(e))
            profiles = []
        if flags["allow_exec"] is False and profiles:
            pass  # 프로파일을 미리 적어 둘 수는 있지만 실행 권한이 있어야 쓸 수 있다
        if name:
            with self.db.session() as s:
                other = s.scalars(select(DevProject).where(DevProject.name == name)).first()
                if other is not None and (current is None or other.id != current.id):
                    errors.append(f"같은 이름의 프로젝트가 이미 있습니다: {name}")
        if errors:
            raise DevError("validation", "; ".join(errors))
        return {"name": name, "root_path": real, "description": desc, "exec_profiles": profiles, **flags}

    def create_project(self, data: dict) -> DevProject:
        v = self._validate_project(data)
        with self.db.session() as s:
            p = DevProject(**v)
            s.add(p)
            s.flush()
            pid = p.id
        self.activity.record("dev", "project.created", project_id=pid, name=v["name"], write=v["allow_write"], exec=v["allow_exec"])
        return self.get_project(pid)

    def update_project(self, pid: int, data: dict) -> DevProject:
        cur = self.get_project(pid)
        v = self._validate_project(data, cur)
        with self.db.session() as s:
            p = s.get(DevProject, pid)
            for k, val in v.items():
                setattr(p, k, val)
            p.updated_at = utcnow()
        self.activity.record("dev", "project.updated", project_id=pid, write=v["allow_write"], exec=v["allow_exec"])
        return self.get_project(pid)

    def delete_project(self, pid: int) -> None:
        self.get_project(pid)
        with self.db.session() as s:
            if s.scalar(select(func.count()).select_from(ProjectChange).where(ProjectChange.project_id == pid)):
                raise DevError("conflict", "변경 기록이 있는 프로젝트는 삭제할 수 없습니다(이력 보존). 비활성화하세요")
            for g in s.scalars(select(WorkerProjectGrant).where(WorkerProjectGrant.project_id == pid)):
                s.delete(g)
            s.delete(s.get(DevProject, pid))
        self.activity.record("dev", "project.deleted", project_id=pid)

    def get_project(self, pid: int) -> DevProject:
        with self.db.session() as s:
            p = s.get(DevProject, pid)
        if p is None:
            raise DevError("not_found", "project not found")
        return p

    def list_projects(self) -> list[dict]:
        with self.db.session() as s:
            rows = list(s.scalars(select(DevProject).order_by(DevProject.id)))
            counts = dict(s.execute(select(WorkerProjectGrant.project_id, func.count()).group_by(WorkerProjectGrant.project_id)).all())
            changes = dict(s.execute(select(ProjectChange.project_id, func.count()).group_by(ProjectChange.project_id)).all())
        return [{**row_dict(p), "worker_count": counts.get(p.id, 0), "change_count": changes.get(p.id, 0)} for p in rows]

    def get_grants(self, worker_id: int) -> list[dict]:
        with self.db.session() as s:
            rows = list(s.scalars(select(WorkerProjectGrant).where(WorkerProjectGrant.worker_id == worker_id).order_by(WorkerProjectGrant.id)))
        return [row_dict(g) for g in rows]

    def set_grants(self, worker_id: int, grants: Any) -> list[dict]:
        """직원의 프로젝트 권한을 통째로 교체한다. 프로젝트가 허용하지 않은 권한은 부여할 수 없다(교집합 규칙을 저장 시점에도 명확히 한다)."""
        if not isinstance(grants, list) or len(grants) > 50:
            raise DevError("validation", "grants 는 50개 이하의 목록이어야 합니다")
        seen: set[int] = set()
        norm = []
        with self.db.session() as s:
            if s.get(Worker, worker_id) is None:
                raise DevError("not_found", "worker not found")
            for i, g in enumerate(grants, 1):
                if not isinstance(g, dict) or not isinstance(g.get("project_id"), int) or isinstance(g.get("project_id"), bool):
                    raise DevError("validation", f"{i}번째 항목에 project_id 가 필요합니다")
                pid = g["project_id"]
                if pid in seen:
                    raise DevError("validation", f"프로젝트 #{pid}가 중복되었습니다")
                seen.add(pid)
                p = s.get(DevProject, pid)
                if p is None:
                    raise DevError("validation", f"존재하지 않는 프로젝트입니다: #{pid}")
                r, w, x = (bool(g.get(k, d)) for k, d in (("can_read", True), ("can_write", False), ("can_exec", False)))
                if (w or x) and not r:
                    raise DevError("validation", f"'{p.name}': 수정·실행 권한은 읽기 권한이 있어야 합니다")
                if (w and not p.allow_write) or (x and not p.allow_exec) or (r and not p.allow_read):
                    raise DevError("validation", f"'{p.name}': 프로젝트가 허용하지 않은 권한은 직원에게 부여할 수 없습니다(프로젝트 설정에서 먼저 허용하세요)")
                norm.append((pid, r, w, x))
            for old in s.scalars(select(WorkerProjectGrant).where(WorkerProjectGrant.worker_id == worker_id)):
                s.delete(old)
            s.flush()
            for pid, r, w, x in norm:
                s.add(WorkerProjectGrant(worker_id=worker_id, project_id=pid, can_read=r, can_write=w, can_exec=x))
        self.activity.record("dev", "project.grants_changed", worker_id=worker_id, projects=[n[0] for n in norm])
        return self.get_grants(worker_id)

    def worker_projects(self, worker_id: int) -> list[dict]:
        """직원이 실제로 쓸 수 있는 프로젝트와 유효 권한(프로젝트 설정 ∩ 직원 부여)."""
        out = []
        with self.db.session() as s:
            q = select(WorkerProjectGrant, DevProject).join(DevProject, DevProject.id == WorkerProjectGrant.project_id).where(WorkerProjectGrant.worker_id == worker_id, DevProject.enabled.is_(True))
            for g, p in s.execute(q).all():
                read = p.allow_read and g.can_read
                out.append({"project_id": p.id, "name": p.name, "root_path": p.root_path, "description": p.description,
                            "permissions": {"read": read, "write": read and p.allow_write and g.can_write, "exec": read and p.allow_exec and g.can_exec, "git": read and p.allow_git},
                            "exec_profiles": [{"name": x["name"], "kind": x["kind"], "timeout_seconds": x["timeout_seconds"], "allow_args": x["allow_args"]} for x in (p.exec_profiles or [])]})
        return out

    def changes(self, *, run_id: int | None = None, project_id: int | None = None, limit: int = 100, with_diff: bool = True) -> list[dict]:
        q = select(ProjectChange).order_by(ProjectChange.id.desc()).limit(limit)
        if run_id is not None:
            q = q.where(ProjectChange.run_id == run_id)
        if project_id is not None:
            q = q.where(ProjectChange.project_id == project_id)
        with self.db.session() as s:
            rows = list(s.scalars(q))
        return [row_dict(c, exclude=() if with_diff else ("diff", "before_text")) for c in rows]

    # ------------------------------------------------------------------ 권한·경로 검사(도구 공통)

    def _ctx(self, args: dict) -> dict:
        ctx = args.get("_ctx")
        if not isinstance(ctx, dict) or not isinstance(ctx.get("worker_id"), int):
            raise ToolError("직원 업무 실행 안에서만 쓸 수 있는 도구입니다", kind="no_context")
        return ctx

    def _access(self, args: dict, need: str) -> tuple[DevProject, str, dict]:
        """(프로젝트, 실제 루트 경로, ctx). need: read | write | exec | git. 권한이 없으면 도구 오류로 돌려준다."""
        ctx = self._ctx(args)
        name = args.get("project")
        if not isinstance(name, str) or not name.strip():
            raise ToolError("project(프로젝트 이름)가 필요합니다", kind="invalid_args")
        with self.db.session() as s:
            p = s.scalars(select(DevProject).where(DevProject.name == name.strip())).first()
            g = s.scalars(select(WorkerProjectGrant).where(WorkerProjectGrant.worker_id == ctx["worker_id"], WorkerProjectGrant.project_id == p.id)).first() if p else None
        if p is None or g is None or not p.enabled:
            raise ToolError(f"이 직원에게 허용된 프로젝트가 아닙니다: {str(name)[:60]} (project.list 로 허용된 프로젝트를 확인하세요)", kind="not_granted")
        ok = {"read": p.allow_read and g.can_read, "write": p.allow_read and g.can_read and p.allow_write and g.can_write,
              "exec": p.allow_read and g.can_read and p.allow_exec and g.can_exec, "git": p.allow_read and g.can_read and p.allow_git}[need]
        if not ok:
            raise ToolError(f"'{p.name}' 프로젝트에서 이 직원은 '{need}' 권한이 없습니다", kind="permission_denied")
        root = os.path.realpath(p.root_path)
        if not os.path.isdir(root):
            raise ToolError("등록된 프로젝트 경로를 찾을 수 없습니다(이동·삭제됨)", kind="project_missing")
        return p, root, ctx

    @staticmethod
    def _rel(rel: Any, *, allow_empty: bool = False) -> str:
        if rel is None or rel == "":
            if allow_empty:
                return ""
            raise ToolError("path 가 필요합니다", kind="invalid_args")
        if not isinstance(rel, str) or len(rel) > 500 or "\x00" in rel:
            raise ToolError("잘못된 경로입니다", kind="invalid_args")
        r = rel.replace("\\", "/")
        if r.startswith("/") or re.match(r"^[A-Za-z]:", r) or r.startswith("~"):
            raise ToolError("프로젝트 상대 경로만 쓸 수 있습니다(절대 경로 금지)", kind="path_escape")
        parts = [x for x in r.split("/") if x not in ("", ".")]
        if any(x == ".." for x in parts):
            raise ToolError("상위 경로(..)는 쓸 수 없습니다", kind="path_escape")
        return "/".join(parts)

    def _target(self, root: str, rel: str, *, write: bool) -> str:
        """프로젝트 안의 실제 경로를 돌려준다. 심볼릭 링크·정션을 푼 결과가 프로젝트 밖이거나 보호 대상이면 거부한다."""
        full = os.path.join(root, *rel.split("/")) if rel else root
        real = os.path.realpath(full)
        if not _within(real, root):
            raise ToolError("프로젝트 밖의 경로입니다(심볼릭 링크 포함)", kind="path_escape")
        if _within(real, self._data_dir()):
            raise ToolError("GyuNexus 데이터 디렉터리는 접근할 수 없습니다", kind="path_denied")
        relreal = os.path.relpath(real, root).replace("\\", "/")
        if is_sensitive(rel) or (relreal != "." and is_sensitive(relreal)):
            raise ToolError("민감 파일(키·환경변수·자격 증명 등)은 읽거나 쓸 수 없습니다", kind="sensitive_path")
        if write:
            if os.path.islink(full):
                raise ToolError("심볼릭 링크로는 쓸 수 없습니다", kind="path_escape")
            if any(x == ".git" for x in rel.split("/")):
                raise ToolError(".git 은 수정할 수 없습니다", kind="path_denied")
        return real

    @staticmethod
    def _read_text(path: str) -> tuple[str, bytes]:
        try:
            size = os.path.getsize(path)
        except OSError:
            raise ToolError("파일이 없습니다", kind="not_found") from None
        if size > MAX_FILE_BYTES:
            raise ToolError(f"파일이 너무 큽니다({size}바이트 > {MAX_FILE_BYTES}). 다른 방법으로 일부만 확인하세요", kind="too_large")
        data = Path(path).read_bytes()
        if b"\x00" in data[:8000]:
            raise ToolError("바이너리 파일은 읽을 수 없습니다", kind="binary_file")
        try:
            return data.decode("utf-8"), data
        except UnicodeDecodeError:
            raise ToolError("UTF-8 텍스트 파일이 아닙니다", kind="not_utf8") from None

    def _walk(self, root: str, rel_dir: str, *, max_depth: int, limit: int, exts: set[str] | None = None, files_only: bool = False):
        """제외 디렉터리·민감 파일·심볼릭 링크를 건너뛰며 순회한다. (rel, is_dir, size) 를 limit 개까지 돌려준다."""
        base = self._target(root, rel_dir, write=False)
        real_root = os.path.realpath(root)
        out, stack = [], [(base, rel_dir, 0)]
        while stack and len(out) < limit:
            cur, cur_rel, depth = stack.pop()
            try:
                entries = sorted(os.scandir(cur), key=lambda e: e.name.lower())
            except OSError:
                continue
            for e in entries:
                rel = f"{cur_rel}/{e.name}" if cur_rel else e.name
                try:
                    if e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction()):  # Windows 정션은 is_symlink() 가 False 라서 따로 확인한다
                        continue
                    is_dir = e.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    if e.name in EXCLUDED_DIRS or e.name.endswith(".egg-info") or _within(e.path, self._data_dir()):
                        continue
                    if not _within(os.path.realpath(e.path), real_root):  # 어떤 종류의 링크든 실제 위치가 프로젝트 밖이면 따라가지 않는다
                        continue
                    if not files_only:
                        out.append((rel, True, 0))
                    if depth + 1 < max_depth:
                        stack.append((e.path, rel, depth + 1))
                else:
                    if is_sensitive(rel):
                        continue
                    if exts and Path(e.name).suffix.lower() not in exts:
                        continue
                    try:
                        size = e.stat(follow_symlinks=False).st_size
                    except OSError:
                        size = 0
                    out.append((rel, False, size))
                if len(out) >= limit:
                    break
        return out

    # ------------------------------------------------------------------ 도구: 프로젝트 탐색

    async def project_list(self, args: dict) -> dict:
        ctx = self._ctx(args)
        return {"projects": self.worker_projects(ctx["worker_id"])}

    async def project_files(self, args: dict) -> dict:
        _, root, _ = self._access(args, "read")
        rel = self._rel(args.get("path"), allow_empty=True)
        depth = args.get("depth", 2)
        limit = args.get("limit", 200)
        if not isinstance(depth, int) or not (1 <= depth <= 8) or not isinstance(limit, int) or not (1 <= limit <= 500):
            raise ToolError("depth 는 1~8, limit 은 1~500 정수여야 합니다", kind="invalid_args")
        exts = args.get("ext")
        ext_set = None
        if exts is not None:
            if not isinstance(exts, list) or not all(isinstance(x, str) and re.match(r"^\.?[A-Za-z0-9]{1,10}$", x) for x in exts):
                raise ToolError("ext 는 확장자 문자열 배열이어야 합니다(예: [\"py\", \"ts\"])", kind="invalid_args")
            ext_set = {"." + x.lstrip(".").lower() for x in exts}
        items = await asyncio.to_thread(self._walk, root, rel, max_depth=depth, limit=limit + 1, exts=ext_set)
        truncated = len(items) > limit
        return {"path": rel or ".", "entries": [{"path": r, "type": "dir" if d else "file", "size": s} for r, d, s in items[:limit]], "truncated": truncated,
                "note": "node_modules·.git·.venv·dist 등과 민감 파일은 제외됨"}

    async def project_inspect(self, args: dict) -> dict:
        p, root, _ = self._access(args, "read")
        return await asyncio.to_thread(self._inspect, p, root)

    def _inspect(self, p: DevProject, root: str) -> dict:
        files = self._walk(root, "", max_depth=6, limit=3000, files_only=True)
        langs: dict[str, int] = {}
        names = {r for r, _, _ in files}
        names_top = {r for r in names if "/" not in r}
        lang_map = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript(React)", ".jsx": "JavaScript(React)", ".java": "Java", ".kt": "Kotlin",
                    ".go": "Go", ".rs": "Rust", ".cs": "C#", ".cpp": "C++", ".c": "C", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".dart": "Dart", ".vue": "Vue", ".css": "CSS", ".html": "HTML"}
        for r, _, _ in files:
            lang = lang_map.get(Path(r).suffix.lower())
            if lang:
                langs[lang] = langs.get(lang, 0) + 1
        markers = [m for m in ("package.json", "pyproject.toml", "requirements.txt", "setup.py", "pom.xml", "build.gradle", "Cargo.toml", "go.mod", "pubspec.yaml", "Makefile", "tsconfig.json",
                               "vite.config.ts", "pytest.ini", "tox.ini", "Dockerfile", "README.md") if m in names_top or any(n.endswith("/" + m) and n.count("/") <= 1 for n in names)]
        frameworks: set[str] = set()
        candidates: list[dict] = []
        for rel in [n for n in names if n.endswith("package.json") and n.count("/") <= 1]:
            try:
                pkg = json.loads(self._read_text(os.path.join(root, *rel.split("/")))[0])
            except (ToolError, ValueError):
                continue
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            for d, label in (("react", "React"), ("vue", "Vue"), ("next", "Next.js"), ("vite", "Vite"), ("express", "Express"), ("jest", "Jest"), ("vitest", "Vitest"), ("typescript", "TypeScript")):
                if d in deps:
                    frameworks.add(label)
            for sname, cmd in (pkg.get("scripts") or {}).items():
                if sname in ("test", "build", "lint", "typecheck", "check"):
                    candidates.append({"source": f"{rel} scripts.{sname}", "command_hint": f"npm run {sname}  ({str(cmd)[:80]})", "kind": "test" if sname == "test" else "build" if sname == "build" else "lint"})
        for rel in [n for n in names if n.endswith(("pyproject.toml", "requirements.txt")) and n.count("/") <= 1]:
            try:
                text = self._read_text(os.path.join(root, *rel.split("/")))[0].lower()
            except ToolError:
                continue
            for d, label in (("fastapi", "FastAPI"), ("django", "Django"), ("flask", "Flask"), ("pytest", "pytest"), ("sqlalchemy", "SQLAlchemy")):
                if d in text:
                    frameworks.add(label)
        if "pytest" in frameworks or "pytest.ini" in names_top or any(n.startswith("tests/") or n.startswith("test_") for n in names):
            candidates.append({"source": "heuristic", "command_hint": "python -m pytest", "kind": "test"})
        top = sorted({r.split("/")[0] + ("/" if "/" in r else "") for r in names})[:60]
        profiles = [{"name": x["name"], "kind": x["kind"], "argv": x["argv"], "allow_args": x["allow_args"]} for x in (p.exec_profiles or [])]
        return {"project": p.name, "description": p.description, "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])), "frameworks": sorted(frameworks), "config_files": markers,
                "top_level": top, "file_count_sampled": len(files), "command_candidates": candidates, "registered_exec_profiles": profiles,
                "note": "command_candidates 는 참고용입니다. 실제로 실행할 수 있는 것은 사용자가 등록한 registered_exec_profiles 뿐입니다(terminal.run)"}

    # ------------------------------------------------------------------ 도구: 코드 읽기·검색

    async def code_read(self, args: dict) -> dict:
        _, root, _ = self._access(args, "read")
        rel = self._rel(args.get("path"))
        real = self._target(root, rel, write=False)
        if not os.path.isfile(real):
            raise ToolError("파일이 없습니다(디렉터리이거나 존재하지 않음)", kind="not_found")
        text, data = await asyncio.to_thread(self._read_text, real)
        lines = text.splitlines()
        start = args.get("start_line", 1)
        end = args.get("end_line")
        cap = self.settings.dev_read_max_lines
        if not isinstance(start, int) or isinstance(start, bool) or start < 1 or (end is not None and (not isinstance(end, int) or isinstance(end, bool) or end < start)):
            raise ToolError("start_line/end_line 이 올바르지 않습니다", kind="invalid_args")
        end = min(end if end is not None else start + cap - 1, start + cap - 1, len(lines))
        shown = lines[start - 1:end]
        width = len(str(max(end, 1)))
        body = "\n".join(f"{i:>{width}}| {ln}" for i, ln in enumerate(shown, start))
        return {"path": rel, "sha256": hashlib.sha256(data).hexdigest(), "total_lines": len(lines), "start_line": start, "end_line": end if shown else start - 1,
                "truncated": end < len(lines), "content": body, "note": "content 의 'N| ' 접두는 줄 번호이며 파일 내용이 아닙니다. 수정할 때는 sha256 을 expected_sha256 으로 넘기세요"}

    async def code_search(self, args: dict) -> dict:
        _, root, _ = self._access(args, "read")
        query = args.get("query")
        if not isinstance(query, str) or not (1 <= len(query) <= 200):
            raise ToolError("query 는 1~200자 문자열이어야 합니다", kind="invalid_args")
        mode = args.get("mode", "content")
        if mode not in ("content", "name"):
            raise ToolError("mode 는 content 또는 name 이어야 합니다", kind="invalid_args")
        rel = self._rel(args.get("path"), allow_empty=True)
        limit = args.get("limit", 30)
        if not isinstance(limit, int) or isinstance(limit, bool) or not (1 <= limit <= self.settings.dev_search_max_results):
            raise ToolError(f"limit 은 1~{self.settings.dev_search_max_results} 정수여야 합니다", kind="invalid_args")
        exts = args.get("ext")
        ext_set = None
        if exts is not None:
            if not isinstance(exts, list) or not all(isinstance(x, str) and re.match(r"^\.?[A-Za-z0-9]{1,10}$", x) for x in exts):
                raise ToolError("ext 는 확장자 문자열 배열이어야 합니다", kind="invalid_args")
            ext_set = {"." + x.lstrip(".").lower() for x in exts}
        single = self._target(root, rel, write=False) if rel else None
        if single is not None and os.path.isfile(single):  # path 가 파일이면 그 파일 하나만 검색한다(조용히 0건을 돌려주지 않는다)
            files = [(rel, False, os.path.getsize(single))]
        else:
            files = await asyncio.to_thread(self._walk, root, rel, max_depth=12, limit=self.settings.dev_search_max_files, exts=ext_set, files_only=True)
        q = query.lower()

        def scan() -> dict:
            matches, scanned = [], 0
            for r, _, size in files:
                if mode == "name":
                    if q in r.lower():
                        matches.append({"path": r, "size": size})
                elif size <= MAX_FILE_BYTES:
                    try:
                        text = self._read_text(os.path.join(root, *r.split("/")))[0]
                    except ToolError:
                        continue
                    scanned += 1
                    for n, line in enumerate(text.splitlines(), 1):
                        if q in line.lower():
                            matches.append({"path": r, "line": n, "text": line.strip()[:200]})
                            if len(matches) >= limit:
                                break
                if len(matches) >= limit:
                    break
            return {"matches": matches, "scanned_files": scanned if mode == "content" else len(files), "truncated": len(matches) >= limit or len(files) >= self.settings.dev_search_max_files}

        out = await asyncio.to_thread(scan)
        return {"query": query, "mode": mode, **out}

    # ------------------------------------------------------------------ 도구: 코드 수정(쓰기·패치)

    def _record_change(self, p: DevProject, ctx: dict, rel: str, tool: str, before: str | None, after: str, before_bytes: bytes | None, after_bytes: bytes) -> dict:
        diff, added, removed = make_diff(rel, before, after)
        with self.db.session() as s:
            c = ProjectChange(project_id=p.id, worker_id=ctx["worker_id"], run_id=ctx.get("run_id"), path=rel, action="create" if before is None else "modify", tool=tool,
                              before_sha256=hashlib.sha256(before_bytes).hexdigest() if before_bytes is not None else None, after_sha256=hashlib.sha256(after_bytes).hexdigest(),
                              before_text=before if before is not None and len(before) <= 200_000 else None, diff=diff[:60_000], added_lines=added, removed_lines=removed)
            s.add(c)
            s.flush()
            cid = c.id
        self.activity.record("dev", "code.changed", project_id=p.id, worker_id=ctx["worker_id"], run_id=ctx.get("run_id"), path=rel, tool=tool, added=added, removed=removed)
        return {"change_id": cid, "diff": diff[:4000], "added_lines": added, "removed_lines": removed}

    @staticmethod
    def _atomic_write(path: str, data: bytes) -> None:
        tmp = f"{path}.gn-{os.getpid()}-{threading.get_ident()}.tmp"
        try:
            with open(tmp, "xb") as f:
                f.write(data)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    async def code_write(self, args: dict) -> dict:
        p, root, ctx = self._access(args, "write")
        rel = self._rel(args.get("path"))
        content = args.get("content")
        mode = args.get("mode", "create")
        if mode not in ("create", "overwrite"):
            raise ToolError("mode 는 create 또는 overwrite 여야 합니다", kind="invalid_args")
        if not isinstance(content, str):
            raise ToolError("content 는 문자열이어야 합니다", kind="invalid_args")
        data = content.encode("utf-8")
        if len(data) > self.settings.dev_write_max_bytes:
            raise ToolError(f"내용이 너무 큽니다({len(data)}바이트 > {self.settings.dev_write_max_bytes})", kind="too_large")
        real = self._target(root, rel, write=True)
        async with self._lock(p.id):
            exists = os.path.isfile(real)
            if os.path.isdir(real):
                raise ToolError("디렉터리에는 쓸 수 없습니다", kind="invalid_args")
            if mode == "create":
                if exists:
                    raise ToolError("이미 존재하는 파일입니다. 수정하려면 code.patch 를, 전체 교체는 mode=overwrite + expected_sha256 을 쓰세요", kind="already_exists")
                os.makedirs(os.path.dirname(real), exist_ok=True)
                if not _within(os.path.realpath(os.path.dirname(real)), root):
                    raise ToolError("프로젝트 밖의 경로입니다", kind="path_escape")
                try:
                    self._atomic_write(real, data)
                except OSError as e:
                    raise ToolError(f"파일을 쓰지 못했습니다: {type(e).__name__}", kind="write_failed") from None
                res = self._record_change(p, ctx, rel, "code.write", None, content, None, data)
                return {"path": rel, "action": "create", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), **res}
            if not exists:
                raise ToolError("덮어쓸 파일이 없습니다. 새 파일은 mode=create 로 만드세요", kind="not_found")
            before, before_bytes = self._read_text(real)
            expected = args.get("expected_sha256")
            if not isinstance(expected, str) or expected != hashlib.sha256(before_bytes).hexdigest():
                raise ToolError("expected_sha256 가 없거나 현재 파일과 다릅니다. code.read 로 최신 내용과 sha256 을 다시 확인하세요", kind="patch_conflict")
            if before == content:
                raise ToolError("변경 내용이 없습니다", kind="no_change")
            try:
                self._atomic_write(real, data)
            except OSError as e:
                raise ToolError(f"파일을 쓰지 못했습니다: {type(e).__name__}", kind="write_failed") from None
            res = self._record_change(p, ctx, rel, "code.write", before, content, before_bytes, data)
            return {"path": rel, "action": "modify", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), **res}

    async def code_patch(self, args: dict) -> dict:
        p, root, ctx = self._access(args, "write")
        rel = self._rel(args.get("path"))
        old, new = args.get("old"), args.get("new")
        if not isinstance(old, str) or not old or not isinstance(new, str):
            raise ToolError("old(바꿀 원본 텍스트, 비어 있지 않음)와 new(문자열)가 필요합니다", kind="invalid_args")
        real = self._target(root, rel, write=True)
        async with self._lock(p.id):
            if not os.path.isfile(real):
                raise ToolError("파일이 없습니다", kind="not_found")
            text, raw = self._read_text(real)
            expected = args.get("expected_sha256")
            if expected is not None and expected != hashlib.sha256(raw).hexdigest():
                raise ToolError("파일이 code.read 이후 바뀌었습니다(expected_sha256 불일치). 다시 읽고 분석하세요", kind="patch_conflict")
            o, n = old, new
            if "\r\n" in text and "\r\n" not in o:  # 파일이 CRLF 이면 줄바꿈 표기를 맞춘다
                o, n = o.replace("\n", "\r\n"), n.replace("\n", "\r\n")
            count = text.count(o)
            if count == 0:
                first = next((ln.strip() for ln in o.splitlines() if ln.strip()), "")
                hint = ""
                if first:
                    hits = [i for i, ln in enumerate(text.splitlines(), 1) if first[:60] in ln]
                    hint = f" 첫 줄과 비슷한 위치: {hits[:3]}번째 줄 근처" if hits else ""
                raise ToolError("old 와 일치하는 내용이 파일에 없습니다(공백·들여쓰기·줄 번호 접두까지 정확히 같아야 합니다)." + hint + " code.read 로 다시 확인하세요", kind="patch_conflict")
            if count > 1 and not args.get("replace_all"):
                raise ToolError(f"old 가 {count}곳에서 발견됩니다. 앞뒤 문맥을 더 포함해 한 곳만 지정하거나 replace_all=true 를 쓰세요", kind="patch_conflict")
            after = text.replace(o, n) if args.get("replace_all") else text.replace(o, n, 1)
            if after == text:
                raise ToolError("변경 내용이 없습니다", kind="no_change")
            data = after.encode("utf-8")
            if len(data) > self.settings.dev_write_max_bytes:
                raise ToolError("패치 후 파일이 너무 큽니다", kind="too_large")
            try:
                self._atomic_write(real, data)
            except OSError as e:
                raise ToolError(f"파일을 쓰지 못했습니다: {type(e).__name__}", kind="write_failed") from None
            res = self._record_change(p, ctx, rel, "code.patch", text, after, raw, data)
            return {"path": rel, "action": "modify", "replacements": count if args.get("replace_all") else 1, "sha256": hashlib.sha256(data).hexdigest(), **res}

    # ------------------------------------------------------------------ 도구: 테스트·빌드 실행

    def _env(self, extra: dict | None = None) -> dict:
        env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k) and not k.upper().startswith(("OPENAI", "GYUNEXUS"))}
        env.update({"CI": "1", "NO_COLOR": "1", "PYTHONUNBUFFERED": "1", "GIT_TERMINAL_PROMPT": "0", **(extra or {})})
        return env

    def _check_args(self, profile: dict, raw: Any) -> list[str]:
        if raw is None or raw == []:
            return []
        if not profile.get("allow_args"):
            raise ToolError(f"프로파일 '{profile['name']}'은 추가 인자를 받지 않습니다", kind="args_not_allowed")
        if not isinstance(raw, list) or len(raw) > 10 or not all(isinstance(a, str) for a in raw):
            raise ToolError("args 는 문자열 10개 이하의 배열이어야 합니다", kind="invalid_args")
        out = []
        flags = set(profile.get("allowed_flags") or [])
        for a in raw:
            if not ARG_RE.match(a):
                raise ToolError(f"허용되지 않는 인자 문자입니다: {a[:40]!r}", kind="args_not_allowed")
            if a.startswith("-"):
                if a.split("=", 1)[0] not in flags:
                    raise ToolError(f"허용되지 않은 옵션입니다: {a[:40]} (허용: {sorted(flags) or '없음'})", kind="args_not_allowed")
            elif "/" in a or "\\" in a or a.startswith("."):
                self._rel(a)  # 경로처럼 보이면 프로젝트 안의 상대 경로여야 한다
                if is_sensitive(a):
                    raise ToolError("민감 파일 경로는 인자로 쓸 수 없습니다", kind="sensitive_path")
            out.append(a)
        return out

    async def terminal_run(self, args: dict) -> dict:
        p, root, ctx = self._access(args, "exec")
        name = args.get("profile")
        profile = next((x for x in (p.exec_profiles or []) if x.get("name") == name), None)
        if profile is None:
            names = [x["name"] for x in (p.exec_profiles or [])]
            raise ToolError(f"등록된 실행 프로파일이 아닙니다: {str(name)[:40]} (사용 가능: {names or '없음 — 사용자가 프로젝트에 프로파일을 등록해야 합니다'})", kind="profile_not_found")
        extra = self._check_args(profile, args.get("args"))
        argv = list(profile["argv"]) + extra
        exe = argv[0]
        if os.sep not in exe and "/" not in exe:
            found = shutil.which(exe, path=self._env().get("PATH"))
            if found is None:
                raise ToolError(f"실행 파일을 찾을 수 없습니다: {exe}", kind="exec_not_found")
            argv[0] = found
        timeout = min(int(profile.get("timeout_seconds", 120)), self.settings.dev_exec_max_seconds)
        async with self._lock(p.id):
            res = await asyncio.to_thread(run_process, argv, root, self._env(), timeout, self.settings.dev_exec_output_bytes)
        passed = res["exit_code"] == 0 and not res["timed_out"]
        self.activity.record("dev", "terminal.run", project_id=p.id, worker_id=ctx["worker_id"], run_id=ctx.get("run_id"), profile=profile["name"], exit_code=res["exit_code"],
                             timed_out=res["timed_out"], duration_s=res["duration_s"])
        return {"profile": profile["name"], "kind": profile["kind"], "command": " ".join(profile["argv"] + extra)[:300], "passed": passed, **{k: redact(v) if isinstance(v, str) else v for k, v in res.items()},
                "failure_type": None if passed else ("timeout" if res["timed_out"] else "nonzero_exit")}

    # ------------------------------------------------------------------ 도구: Git(조회 전용)

    def git_exe(self) -> str | None:
        if self.settings.git_executable:
            return self.settings.git_executable if os.path.isfile(self.settings.git_executable) else None
        found = shutil.which("git")
        if found:
            return found
        if os.name == "nt":
            base = os.path.join(os.environ.get("LOCALAPPDATA", ""), "GitHubDesktop")
            if os.path.isdir(base):
                for d in sorted(os.listdir(base), reverse=True):
                    cand = os.path.join(base, d, "resources", "app", "git", "cmd", "git.exe")
                    if os.path.isfile(cand):
                        return cand
        return None

    async def _git(self, root: str, argv: list[str]) -> dict:
        exe = self.git_exe()
        if exe is None:
            raise ToolError("git 실행 파일을 찾을 수 없습니다(PATH 또는 GYUNEXUS_GIT_EXECUTABLE)", kind="git_unavailable")
        full = [exe, "--no-pager", "-c", "core.fsmonitor=false", "-c", "core.pager=cat", "-c", f"safe.directory={root.replace(os.sep, '/')}", *argv]
        res = await asyncio.to_thread(run_process, full, root, self._env({"GIT_OPTIONAL_LOCKS": "0", "GIT_EXTERNAL_DIFF": ""}), 30, 60_000)
        if res["timed_out"]:
            raise ToolError("git 명령이 시간 초과되었습니다", kind="timeout")
        return res

    async def git_status(self, args: dict) -> dict:
        p, root, ctx = self._access(args, "git")
        res = await self._git(root, ["status", "--porcelain=v1", "-b", "--untracked-files=normal"])
        if res["exit_code"] != 0:
            return {"is_repo": False, "error": res["stderr"][:300], "tracked_changes": self._run_summary(ctx)}
        lines = res["stdout"].splitlines()
        branch = lines[0][3:] if lines and lines[0].startswith("##") else None
        files = [{"status": ln[:2].strip() or "?", "path": ln[3:]} for ln in lines[1:] if ln.strip()]
        return {"is_repo": True, "branch": branch, "changed_files": files, "clean": not files, "tracked_changes": self._run_summary(ctx)}

    async def git_diff(self, args: dict) -> dict:
        p, root, ctx = self._access(args, "git")
        rel = self._rel(args.get("path"), allow_empty=True)
        if rel and is_sensitive(rel):
            raise ToolError("민감 파일은 조회할 수 없습니다", kind="sensitive_path")
        staged = bool(args.get("staged", False))
        argv = ["diff", "--no-color", "--no-ext-diff", "-U3"] + (["--cached"] if staged else []) + (["--", rel] if rel else [])
        out: dict[str, Any] = {"run_changes": self._run_summary(ctx, with_diff=True)}
        try:
            res = await self._git(root, argv)
        except ToolError as e:
            if e.kind != "git_unavailable":
                raise
            return {**out, "source": "tracked_changes", "git_diff": None, "note": "git 을 쓸 수 없어 이 실행에서 적용한 변경 기록만 돌려줍니다"}
        if res["exit_code"] != 0:
            return {**out, "source": "tracked_changes", "git_diff": None, "note": "git 저장소가 아니어서 이 실행에서 적용한 변경 기록만 돌려줍니다"}
        diff = res["stdout"]
        # 민감 파일이 diff 에 섞이지 않도록 해당 파일 블록을 제거한다
        blocks = re.split(r"(?m)^(?=diff --git )", diff)
        kept = [b for b in blocks if not (b.startswith("diff --git") and is_sensitive(re.sub(r"^diff --git a/(.*?) b/.*$", r"\1", b.splitlines()[0])))]
        diff = "".join(kept)
        return {**out, "source": "git", "git_diff": redact(diff[:30_000]), "truncated": len(diff) > 30_000 or res["truncated"], "staged": staged}

    async def git_log(self, args: dict) -> dict:
        _, root, _ = self._access(args, "git")
        n = args.get("limit", 10)
        if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= 30):
            raise ToolError("limit 은 1~30 정수여야 합니다", kind="invalid_args")
        res = await self._git(root, ["log", f"-n{n}", "--no-color", "--date=short", "--pretty=format:%h\t%ad\t%an\t%s"])
        if res["exit_code"] != 0:
            return {"is_repo": False, "commits": [], "error": res["stderr"][:300]}
        commits = []
        for ln in res["stdout"].splitlines():
            h, d, a, *s = ln.split("\t")
            commits.append({"hash": h, "date": d, "author": a, "subject": "\t".join(s)[:200]})
        return {"is_repo": True, "commits": commits}

    def _run_summary(self, ctx: dict, with_diff: bool = False) -> list[dict]:
        if ctx.get("run_id") is None:
            return []
        return [{"path": c["path"], "action": c["action"], "added": c["added_lines"], "removed": c["removed_lines"], **({"diff": c["diff"][:6000]} if with_diff else {})}
                for c in self.changes(run_id=ctx["run_id"], limit=200)][::-1]

    # ------------------------------------------------------------------ 등록

    def register(self, reg: ToolRegistry) -> None:
        proj = {"project": "프로젝트 이름(project.list 로 확인)"}
        T = lambda name, desc, params, handler, group: reg.register(Tool(name, desc, "project", params, self._wrap(handler), group))  # noqa: E731
        T("project.list", "이 직원에게 허용된 개발 프로젝트와 권한(읽기·수정·실행·Git)·실행 프로파일 목록", {}, self.project_list, "project")
        T("project.inspect", "프로젝트 구조 분석: 언어·프레임워크·설정 파일·테스트/빌드 명령 후보·등록된 실행 프로파일", proj, self.project_inspect, "project")
        T("project.files", "프로젝트 파일·디렉터리 목록(node_modules·.git·.venv·dist·민감 파일 제외)", {**proj, "path": "하위 디렉터리(선택)", "depth": "1~8(기본 2)", "ext": "확장자 배열(선택)", "limit": "최대 500"},
          self.project_files, "project")
        T("code.read", "파일 읽기(줄 번호 포함, 부분 읽기 지원). 반환된 sha256 은 수정 시 expected_sha256 으로 쓴다", {**proj, "path": "상대 경로", "start_line": "시작 줄(기본 1)", "end_line": "끝 줄(선택)"},
          self.code_read, "code")
        T("code.search", "파일명 또는 소스 내용 검색(대소문자 무시, 결과 수 제한)", {**proj, "query": "검색어", "mode": "content|name", "path": "검색 시작 디렉터리(선택)", "ext": "확장자 배열(선택)", "limit": "최대 결과 수"},
          self.code_search, "code")
        T("code.write", "파일 생성(mode=create) 또는 전체 교체(mode=overwrite, expected_sha256 필수). 변경 전후가 기록된다", {**proj, "path": "상대 경로", "content": "전체 내용(UTF-8)", "mode": "create|overwrite", "expected_sha256": "overwrite 일 때 필수"},
          self.code_write, "code")
        T("code.patch", "기존 파일의 일부 교체: old(정확히 일치하는 원본) -> new. 위치가 맞지 않으면 충돌 오류를 돌려준다", {**proj, "path": "상대 경로", "old": "바꿀 원본 텍스트", "new": "새 텍스트", "expected_sha256": "code.read 의 sha256(선택)", "replace_all": "true 면 모두 교체"},
          self.code_patch, "code")
        T("terminal.run", "등록된 실행 프로파일(테스트·빌드·린트)을 프로젝트 디렉터리에서 실행하고 종료 코드·출력을 반환. 임의 명령은 실행할 수 없다", {**proj, "profile": "프로파일 이름", "args": "추가 인자 배열(프로파일이 허용한 경우)"},
          self.terminal_run, "exec")
        T("git.status", "현재 브랜치와 변경 파일 확인(조회 전용)", proj, self.git_status, "git")
        T("git.diff", "변경된 코드(diff) 확인. 이 실행에서 적용한 변경 기록을 함께 반환(조회 전용)", {**proj, "path": "특정 파일(선택)", "staged": "true 면 staged 변경"}, self.git_diff, "git")
        T("git.log", "최근 커밋 조회(조회 전용)", {**proj, "limit": "1~30(기본 10)"}, self.git_log, "git")

    @staticmethod
    def _wrap(fn):
        return fn
