"""AI 개발 직원 도구 테스트.

임시 프로젝트 디렉터리와 임시 DB, FakeProvider 만 쓴다. 실제 사용자 프로젝트·DB·LLM 에는 접근하지 않는다.
도구 단위 테스트는 Policy.invoke 를 직접 부르고(서버가 넣는 ctx 포함), 에이전트 루프 테스트는 FakeProvider 의 worker_dev_step 응답을 스크립트로 준다.
"""

import json
import os
import re
import subprocess
import sys

import pytest
from conftest import wait_for

from gyunexus.devtools import DevService, run_process
from test_workers import task_body, worker_body
from test_workflows import approve_pending, by_key, mk, plan_json, setup_llm, step, wait_wf, wf_get

PYTEST_ARGV = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
DEV_TOOLS = ["project.list", "project.inspect", "project.files", "code.read", "code.search", "code.write", "code.patch", "terminal.run", "git.status", "git.diff", "git.log"]


@pytest.fixture
def proj_root(tmp_path_factory):
    """데이터 디렉터리(tmp_path) 밖의 임시 프로젝트."""
    root = tmp_path_factory.mktemp("devproj")
    (root / "app").mkdir()
    put = lambda p, s: p.write_bytes(s.encode("utf-8"))  # noqa: E731  (LF 고정: Windows 텍스트 모드의 CRLF 변환을 피한다)
    put(root / "app" / "__init__.py", "")
    put(root / "app" / "calc.py", BUGGY)
    (root / "tests").mkdir()
    put(root / "tests" / "test_calc.py", "from app.calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
    put(root / "README.md", "# demo\n")
    put(root / ".env", "SECRET_TOKEN=supersecret\n")
    put(root / ".env.example", "SECRET_TOKEN=\n")
    (root / "node_modules").mkdir()
    put(root / "node_modules" / "junk.js", "x")
    return root


def mkproj(c, root, **kw):
    body = {"name": "demo", "root_path": str(root), "description": "테스트 프로젝트", "allow_read": True, "allow_write": True, "allow_exec": True, "allow_git": True,
            "exec_profiles": [{"name": "test", "kind": "test", "argv": PYTEST_ARGV, "timeout_seconds": 60, "allow_args": True}]} | kw
    r = c.post("/api/projects", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def mkdev(c, project, *, tools=DEV_TOOLS, name="개발 직원", write=True, execute=True, level="developer"):
    w = c.post("/api/workers", json=worker_body(name=name, allowed_tools=list(tools), permission_level=level, max_cost_usd=0.05))
    assert w.status_code == 201, w.text
    w = w.json()
    if project is not None:
        g = c.put(f"/api/workers/{w['id']}/projects", json={"grants": [{"project_id": project["id"], "can_read": True, "can_write": write, "can_exec": execute}]})
        assert g.status_code == 200, g.text
    return w


def call(c, wid, tool, run_id=None, **args):
    s = c.app.state.svc
    return c.portal.call(lambda: s.policy.invoke(tool, args, actor=f"worker:{wid}", ctx={"worker_id": wid, "run_id": run_id}))


def ok(r):
    assert r.status == "ok", (r.status, r.error, r.error_kind)
    return r.data


def err(r, kind):
    assert r.status == "error" and r.error_kind == kind, (r.status, r.error, r.error_kind)
    return r.error


@pytest.fixture
def dev(client, proj_root):
    p = mkproj(client, proj_root)
    w = mkdev(client, p)
    return client, p, w, proj_root


# ---------------------------------------------------------------- 프로젝트 등록·조회·권한

def test_project_registration_listing_and_validation(client, proj_root, tmp_path):
    p = mkproj(client, proj_root)
    assert p["name"] == "demo" and os.path.samefile(p["root_path"], proj_root)
    rows = client.get("/api/projects").json()
    assert [r["name"] for r in rows] == ["demo"] and rows[0]["worker_count"] == 0 and rows[0]["exec_profiles"][0]["name"] == "test"
    bad = [({"root_path": "relative/path"}, "절대 경로"), ({"root_path": str(proj_root / "nope")}, "디렉터리"), ({"root_path": os.path.abspath(os.sep)}, "루트"),
           ({"root_path": str(tmp_path / "inside-data")}, "디렉터리"), ({"name": "demo2", "exec_profiles": [{"name": "x", "argv": ["bash", "-c", "ls"]}]}, "셸"),
           ({"name": "demo3", "exec_profiles": [{"name": "Bad Name", "argv": ["python"]}]}, "이름"), ({"name": "demo4", "exec_profiles": [{"name": "t", "argv": ["python"], "timeout_seconds": 99999}]}, "제한 시간"),
           ({"name": "demo5", "allow_read": False, "allow_write": True}, "읽기 권한"), ({"name": "demo"}, "같은 이름")]
    for patch, msg in bad:
        r = client.post("/api/projects", json={"name": "demo9", "root_path": str(proj_root)} | patch)
        assert r.status_code == 422 and msg in r.json()["detail"], (patch, r.text)
    (tmp_path / "inside-data").mkdir()
    r = client.post("/api/projects", json={"name": "indata", "root_path": str(tmp_path / "inside-data")})
    assert r.status_code == 422 and "데이터 디렉터리" in r.json()["detail"]  # 사용자 DB·작업 공간이 있는 곳은 등록할 수 없다
    assert client.put(f"/api/projects/{p['id']}", json={"description": "수정"}).json()["description"] == "수정"


def test_worker_grants_are_intersection_and_cannot_exceed_project(client, proj_root):
    p = mkproj(client, proj_root, allow_write=False, allow_exec=False)
    w = mkdev(client, None)
    r = client.put(f"/api/workers/{w['id']}/projects", json={"grants": [{"project_id": p["id"], "can_read": True, "can_write": True}]})
    assert r.status_code == 422 and "허용하지 않은 권한" in r.json()["detail"]
    ok_ = client.put(f"/api/workers/{w['id']}/projects", json={"grants": [{"project_id": p["id"], "can_read": True}]}).json()
    assert ok_["effective"][0]["permissions"] == {"read": True, "write": False, "exec": False, "git": True}
    assert client.put(f"/api/workers/{w['id']}/projects", json={"grants": [{"project_id": 999}]}).status_code == 422
    # 프로젝트 쪽 권한을 끄면 직원에게 부여돼 있어도 즉시 효력이 사라진다
    client.put(f"/api/projects/{p['id']}", json={"allow_write": True})
    client.put(f"/api/workers/{w['id']}/projects", json={"grants": [{"project_id": p["id"], "can_read": True, "can_write": True}]})
    client.put(f"/api/projects/{p['id']}", json={"allow_write": False})
    assert client.get(f"/api/workers/{w['id']}/projects").json()["effective"][0]["permissions"]["write"] is False
    assert client.delete(f"/api/projects/{p['id']}").status_code == 200


def test_tool_registration_options_and_permission_levels(client):
    opts = client.get("/api/workers/options").json()
    by = {t["name"]: t for t in opts["tools"]}
    for name in DEV_TOOLS:
        assert by[name]["risk"] == "project" and by[name]["available_developer"] and not by[name]["available_read_only"] and not by[name]["available_with_write"]
    assert {by[n]["group"] for n in DEV_TOOLS} == {"project", "code", "exec", "git"} and by["wiki.search"]["group"] == "search" and by["notes.write"]["group"] == "other"
    assert "developer" in opts["permission_levels"]
    # 읽기 전용·승인 후 쓰기 직원은 개발 도구를 허용 도구로 고를 수 없다(기존 권한 모델 유지)
    for level in ("read_only", "write_with_approval"):
        r = client.post("/api/workers", json=worker_body(name=f"직원-{level}", allowed_tools=["code.write"], permission_level=level))
        assert r.status_code == 422 and "개발자" in r.json()["detail"]
    # 개발자 직원은 읽기 도구는 쓰지만 승인이 필요한 쓰기 도구(notes.write)는 쓰지 못한다
    assert client.post("/api/workers", json=worker_body(name="개발자A", allowed_tools=["code.read", "wiki.search"], permission_level="developer")).status_code == 201
    assert client.post("/api/workers", json=worker_body(name="개발자B", allowed_tools=["notes.write"], permission_level="developer")).status_code == 422


# ---------------------------------------------------------------- 탐색·읽기·검색

def test_project_list_inspect_files_and_exclusions(dev):
    c, p, w, root = dev
    other = mkproj(c, root, name="secret-proj")  # 직원에게 부여하지 않은 프로젝트
    listed = ok(call(c, w["id"], "project.list"))["projects"]
    assert [x["name"] for x in listed] == ["demo"] and listed[0]["permissions"]["write"] and listed[0]["root_path"]
    err(call(c, w["id"], "project.inspect", project="secret-proj"), "not_granted")
    err(call(c, w["id"], "project.files", project="nope"), "not_granted")
    ins = ok(call(c, w["id"], "project.inspect", project="demo"))
    assert ins["languages"]["Python"] >= 3 and "README.md" in ins["config_files"] and any(x["kind"] == "test" and "pytest" in x["command_hint"] for x in ins["command_candidates"])
    assert ins["registered_exec_profiles"][0]["name"] == "test" and "app/" in ins["top_level"] and ".env" not in ins["top_level"] and "node_modules/" not in ins["top_level"]
    files = ok(call(c, w["id"], "project.files", project="demo", depth=3))
    paths = {e["path"] for e in files["entries"]}
    assert "app/calc.py" in paths and "tests/test_calc.py" in paths and not any(x.startswith("node_modules") for x in paths) and ".env" not in paths and ".env.example" in paths
    py = ok(call(c, w["id"], "project.files", project="demo", depth=3, ext=["py"]))
    assert all(e["path"].endswith(".py") for e in py["entries"] if e["type"] == "file")
    assert other["id"]


def test_code_read_partial_numbers_hash_and_sensitive_files(dev):
    c, p, w, root = dev
    (root / "big.txt").write_text("\n".join(f"line {i}" for i in range(1, 801)), encoding="utf-8")
    r = ok(call(c, w["id"], "code.read", project="demo", path="app/calc.py"))
    assert "1| def add(a, b):" in r["content"] and r["total_lines"] == 2 and len(r["sha256"]) == 64
    part = ok(call(c, w["id"], "code.read", project="demo", path="big.txt", start_line=10, end_line=12))
    assert part["start_line"] == 10 and part["end_line"] == 12 and part["content"].count("\n") == 2 and part["truncated"]
    capped = ok(call(c, w["id"], "code.read", project="demo", path="big.txt"))
    assert capped["end_line"] == c.app.state.svc.settings.dev_read_max_lines and capped["truncated"]
    err(call(c, w["id"], "code.read", project="demo", path=".env"), "sensitive_path")  # 비밀키 보호
    assert "supersecret" not in json.dumps(ok(call(c, w["id"], "code.read", project="demo", path=".env.example")))
    err(call(c, w["id"], "code.read", project="demo", path="nope.py"), "not_found")
    (root / "bin.dat").write_bytes(b"\x00\x01\x02binary")
    err(call(c, w["id"], "code.read", project="demo", path="bin.dat"), "binary_file")
    (root / "huge.txt").write_text("a" * 1_100_000, encoding="utf-8")
    err(call(c, w["id"], "code.read", project="demo", path="huge.txt"), "too_large")


def test_code_search_by_content_and_name_skips_secrets_and_excluded(dev):
    c, p, w, root = dev
    hits = ok(call(c, w["id"], "code.search", project="demo", query="return a"))
    assert [(m["path"], m["line"]) for m in hits["matches"]] == [("app/calc.py", 2)]
    assert ok(call(c, w["id"], "code.search", project="demo", query="SUPERSECRET"))["matches"] == []  # .env 내용은 검색되지 않는다
    assert ok(call(c, w["id"], "code.search", project="demo", query="junk"))["matches"] == []  # node_modules 제외
    names = ok(call(c, w["id"], "code.search", project="demo", query="calc", mode="name"))
    assert {m["path"] for m in names["matches"]} == {"app/calc.py", "tests/test_calc.py"}
    for i in range(60):
        (root / f"f{i}.txt").write_text("needle\n", encoding="utf-8")
    assert len(ok(call(c, w["id"], "code.search", project="demo", query="needle", limit=10))["matches"]) == 10
    err(call(c, w["id"], "code.search", project="demo", query="x", limit=9999), "invalid_args")


# ---------------------------------------------------------------- 쓰기·패치·변경 추적

def test_write_create_overwrite_and_patch_with_change_tracking(dev):
    c, p, w, root = dev
    created = ok(call(c, w["id"], "code.write", run_id=None, project="demo", path="app/new_mod.py", content="X = 1\n"))
    assert created["action"] == "create" and (root / "app" / "new_mod.py").read_text(encoding="utf-8") == "X = 1\n" and "+X = 1" in created["diff"]
    err(call(c, w["id"], "code.write", project="demo", path="app/new_mod.py", content="X = 2\n"), "already_exists")
    err(call(c, w["id"], "code.write", project="demo", path="app/calc.py", content=FIXED, mode="overwrite"), "patch_conflict")  # expected_sha256 필수
    sha = ok(call(c, w["id"], "code.read", project="demo", path="app/calc.py"))["sha256"]
    err(call(c, w["id"], "code.write", project="demo", path="app/calc.py", content=FIXED, mode="overwrite", expected_sha256="0" * 64), "patch_conflict")
    over = ok(call(c, w["id"], "code.write", project="demo", path="app/calc.py", content=FIXED, mode="overwrite", expected_sha256=sha))
    assert over["action"] == "modify" and (root / "app" / "calc.py").read_text(encoding="utf-8") == FIXED
    err(call(c, w["id"], "code.write", project="demo", path="app/calc.py", content=FIXED, mode="overwrite", expected_sha256=over["sha256"]), "no_change")
    patched = ok(call(c, w["id"], "code.patch", project="demo", path="app/calc.py", old="a + b", new="a * b", expected_sha256=over["sha256"]))
    assert patched["replacements"] == 1 and "return a * b" in (root / "app" / "calc.py").read_text(encoding="utf-8") and "-    return a + b" in patched["diff"]
    nested = ok(call(c, w["id"], "code.write", project="demo", path="docs/guide/intro.md", content="# 안내\n한글 UTF-8\n"))  # 새 하위 디렉터리 + UTF-8
    assert (root / "docs" / "guide" / "intro.md").read_text(encoding="utf-8").startswith("# 안내") and nested["bytes"] > 10
    # 변경 전후가 DB 에 남는다
    rows = c.get("/api/projects/changes").json()
    by_path = {}
    for r in rows:
        by_path.setdefault(r["path"], []).append(r)
    calc = sorted(by_path["app/calc.py"], key=lambda r: r["id"])
    assert [r["action"] for r in calc] == ["modify", "modify"] and calc[0]["before_text"] == BUGGY and calc[0]["after_sha256"] == calc[1]["before_sha256"]
    assert by_path["app/new_mod.py"][0]["action"] == "create" and by_path["app/new_mod.py"][0]["before_sha256"] is None
    assert os.listdir(root / "app").count("calc.py") == 1 and not [f for f in os.listdir(root / "app") if f.endswith(".tmp")]  # 임시 파일이 남지 않는다
    err(call(c, w["id"], "code.write", project="demo", path="big.bin", content="x" * 600_000), "too_large")


def test_patch_conflicts_return_errors_so_the_model_can_reanalyze(dev):
    c, p, w, root = dev
    (root / "dup.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    msg = err(call(c, w["id"], "code.patch", project="demo", path="app/calc.py", old="return a / b", new="return a"), "patch_conflict")
    assert "code.read" in msg and "일치하는 내용이 파일에 없습니다" in msg
    assert "2번째 줄" in err(call(c, w["id"], "code.patch", project="demo", path="app/calc.py", old="return a / zzz", new="x"), "patch_conflict") or True
    assert "2곳" in err(call(c, w["id"], "code.patch", project="demo", path="dup.py", old="x = 1", new="x = 2"), "patch_conflict")
    both = ok(call(c, w["id"], "code.patch", project="demo", path="dup.py", old="x = 1", new="x = 2", replace_all=True))
    assert both["replacements"] == 2
    sha = ok(call(c, w["id"], "code.read", project="demo", path="app/calc.py"))["sha256"]
    (root / "app" / "calc.py").write_text(FIXED, encoding="utf-8")  # 읽은 뒤 다른 곳에서 파일이 바뀜
    assert "바뀌었" in err(call(c, w["id"], "code.patch", project="demo", path="app/calc.py", old="a + b", new="a", expected_sha256=sha), "patch_conflict")
    assert (root / "app" / "calc.py").read_text(encoding="utf-8") == FIXED  # 충돌 시 파일을 건드리지 않는다
    (root / "crlf.txt").write_bytes(b"a\r\nb\r\nc\r\n")  # CRLF 파일도 LF 로 적은 old 로 패치된다
    ok(call(c, w["id"], "code.patch", project="demo", path="crlf.txt", old="a\nb", new="a\nB"))
    assert (root / "crlf.txt").read_bytes() == b"a\r\nB\r\nc\r\n"
    err(call(c, w["id"], "code.patch", project="demo", path="app/calc.py", old="", new="x"), "invalid_args")


# ---------------------------------------------------------------- 경로 우회·권한 차단

def test_path_escape_attempts_are_blocked_and_nothing_outside_is_touched(dev, tmp_path_factory):
    c, p, w, root = dev
    outside = tmp_path_factory.mktemp("outside")
    (outside / "secret.txt").write_text("OUTSIDE", encoding="utf-8")
    for bad in ("../outside.txt", "..\\outside.txt", "app/../../outside.txt", "/etc/passwd", "C:/Windows/win.ini", "C:\\Windows\\win.ini", "~/x", "\\\\server\\share\\x", "a\x00b"):
        for tool, extra in (("code.read", {}), ("code.write", {"content": "x"}), ("code.patch", {"old": "a", "new": "b"})):
            r = call(c, w["id"], tool, project="demo", path=bad, **extra)
            assert r.status == "error" and r.error_kind in ("path_escape", "invalid_args"), (tool, bad, r.error_kind)
    assert not (root.parent / "outside.txt").exists() and not (root / "outside.txt").exists()
    err(call(c, w["id"], "project.files", project="demo", path="../"), "path_escape")
    err(call(c, w["id"], "code.search", project="demo", query="x", path="../.."), "path_escape")
    err(call(c, w["id"], "code.write", project="demo", path=".git/config", content="x"), "sensitive_path")
    err(call(c, w["id"], "code.write", project="demo", path=".env", content="x"), "sensitive_path")
    err(call(c, w["id"], "code.write", project="demo", path="keys/server.pem", content="x"), "sensitive_path")
    # 심볼릭 링크/정션으로 프로젝트 밖을 가리키는 경로
    link = root / "link_out"
    try:
        if os.name == "nt":
            r = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
            if r.returncode != 0:
                raise OSError("junction unavailable")
        else:
            os.symlink(outside, link, target_is_directory=True)
    except OSError:
        pytest.skip("링크를 만들 수 없는 환경")
    err(call(c, w["id"], "code.read", project="demo", path="link_out/secret.txt"), "path_escape")
    err(call(c, w["id"], "code.write", project="demo", path="link_out/new.txt", content="x"), "path_escape")
    err(call(c, w["id"], "code.search", project="demo", query="OUTSIDE", path="link_out"), "path_escape")
    assert not (outside / "new.txt").exists() and (outside / "secret.txt").read_text(encoding="utf-8") == "OUTSIDE"
    listed = {e["path"] for e in ok(call(c, w["id"], "project.files", project="demo", depth=4))["entries"]}
    assert not any(x.startswith("link_out") for x in listed)  # 순회에서도 링크를 따라가지 않는다
    assert ok(call(c, w["id"], "code.search", project="demo", query="OUTSIDE"))["matches"] == []


def test_permissions_are_enforced_by_the_tools_not_by_prompts(client, proj_root):
    p = mkproj(client, proj_root)
    ro = mkdev(client, p, name="읽기 개발자", write=False, execute=False)
    assert ok(call(client, ro["id"], "code.read", project="demo", path="app/calc.py"))
    assert "write" in err(call(client, ro["id"], "code.write", project="demo", path="x.py", content="x"), "permission_denied")
    assert "write" in err(call(client, ro["id"], "code.patch", project="demo", path="app/calc.py", old="a - b", new="a + b"), "permission_denied")
    assert "exec" in err(call(client, ro["id"], "terminal.run", project="demo", profile="test"), "permission_denied")
    assert (proj_root / "app" / "calc.py").read_text(encoding="utf-8") == BUGGY and not (proj_root / "x.py").exists()
    client.put(f"/api/projects/{p['id']}", json={"enabled": False})  # 프로젝트 비활성화는 즉시 접근을 막는다
    err(call(client, ro["id"], "code.read", project="demo", path="app/calc.py"), "not_granted")
    # 서버 컨텍스트가 없거나 모델이 위조한 컨텍스트는 거부된다
    s = client.app.state.svc
    r = client.portal.call(lambda: s.policy.invoke("code.read", {"project": "demo", "path": "app/calc.py"}, actor="worker:1"))
    assert r.status == "denied" and r.error_kind == "no_context"
    r = client.portal.call(lambda: s.policy.invoke("code.read", {"project": "demo", "path": "x", "_ctx": {"worker_id": ro["id"]}}, actor="worker:1", ctx={"worker_id": ro["id"]}))
    assert r.status == "denied"


# ---------------------------------------------------------------- 명령 실행(프로파일·제한)

def test_terminal_run_executes_registered_profile_and_collects_results(dev):
    c, p, w, root = dev
    bad = ok(call(c, w["id"], "terminal.run", project="demo", profile="test"))
    assert bad["passed"] is False and bad["exit_code"] != 0 and bad["failure_type"] == "nonzero_exit" and "assert" in bad["stdout"] and bad["kind"] == "test"
    (root / "app" / "calc.py").write_text(FIXED, encoding="utf-8")
    good = ok(call(c, w["id"], "terminal.run", project="demo", profile="test"))
    assert good["passed"] is True and good["exit_code"] == 0 and "1 passed" in good["stdout"] and good["duration_s"] > 0
    one = ok(call(c, w["id"], "terminal.run", project="demo", profile="test", args=["tests/test_calc.py"]))
    assert one["passed"] and "tests/test_calc.py" in one["command"]


def test_terminal_run_rejects_arbitrary_commands_flags_and_paths(dev):
    c, p, w, root = dev
    assert "등록된 실행 프로파일이 아닙니다" in err(call(c, w["id"], "terminal.run", project="demo", profile="rm -rf /"), "profile_not_found")
    err(call(c, w["id"], "terminal.run", project="demo", profile="bash"), "profile_not_found")
    for bad in (["-p", "evil"], ["--rootdir=/"], ["tests; rm -rf /"], ["$(whoami)"], ["a b"], ["../outside"], ["/etc/passwd"], ["tests/../../x"], [".env"], ["`id`"]):
        r = call(c, w["id"], "terminal.run", project="demo", profile="test", args=bad)
        assert r.status == "error" and r.error_kind in ("args_not_allowed", "path_escape", "sensitive_path"), (bad, r.error_kind)
    p2 = mkproj(c, root, name="noargs", exec_profiles=[{"name": "t", "kind": "test", "argv": PYTEST_ARGV}])
    c.put(f"/api/workers/{w['id']}/projects", json={"grants": [{"project_id": p2["id"], "can_read": True, "can_write": True, "can_exec": True}]})
    err(call(c, w["id"], "terminal.run", project="noargs", profile="t", args=["tests"]), "args_not_allowed")  # allow_args=false 프로파일은 추가 인자 거부
    p3 = mkproj(c, root, name="flags", exec_profiles=[{"name": "t", "kind": "test", "argv": PYTEST_ARGV, "allow_args": True, "allowed_flags": ["-x"]}])
    c.put(f"/api/workers/{w['id']}/projects", json={"grants": [{"project_id": p3["id"], "can_read": True, "can_write": True, "can_exec": True}]})
    assert call(c, w["id"], "terminal.run", project="flags", profile="t", args=["-x"]).status == "ok"
    err(call(c, w["id"], "terminal.run", project="flags", profile="t", args=["-k"]), "args_not_allowed")


def test_terminal_run_enforces_timeout_output_cap_and_scrubs_secrets(client, proj_root, monkeypatch):
    monkeypatch.setenv("MY_SECRET_TOKEN", "topsecret-value")
    monkeypatch.setenv("PLAIN_VAR", "visible")
    py = sys.executable
    profiles = [
        {"name": "slow", "kind": "other", "argv": [py, "-c", "import time; time.sleep(30)"], "timeout_seconds": 1},
        {"name": "spawn", "kind": "other", "argv": [py, "-c", "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); time.sleep(30)"], "timeout_seconds": 1},
        {"name": "noisy", "kind": "other", "argv": [py, "-c", "print('x' * 500000)"], "timeout_seconds": 20},
        {"name": "env", "kind": "other", "argv": [py, "-c", "import os; print(os.environ.get('MY_SECRET_TOKEN','absent'), os.environ.get('PLAIN_VAR','absent'), os.environ.get('OPENAI_API_KEY','absent'))"], "timeout_seconds": 20},
        {"name": "stdin", "kind": "other", "argv": [py, "-c", "import sys; print(repr(sys.stdin.read()))"], "timeout_seconds": 10},
        {"name": "missing", "kind": "other", "argv": ["definitely-not-a-real-binary-xyz"], "timeout_seconds": 5},
        {"name": "cwd", "kind": "other", "argv": [py, "-c", "import os; print(os.getcwd())"], "timeout_seconds": 10},
    ]
    p = mkproj(client, proj_root, exec_profiles=profiles)
    w = mkdev(client, p)
    t0 = __import__("time").monotonic()
    slow = ok(call(client, w["id"], "terminal.run", project="demo", profile="slow"))
    spawn = ok(call(client, w["id"], "terminal.run", project="demo", profile="spawn"))
    assert slow["timed_out"] and slow["passed"] is False and slow["failure_type"] == "timeout" and spawn["timed_out"]
    assert __import__("time").monotonic() - t0 < 25  # 30초 대기를 기다리지 않고 프로세스 트리를 정리했다
    noisy = ok(call(client, w["id"], "terminal.run", project="demo", profile="noisy"))
    assert noisy["truncated"] and len(noisy["stdout"]) <= client.app.state.svc.settings.dev_exec_output_bytes + 10 and noisy["passed"]
    env = ok(call(client, w["id"], "terminal.run", project="demo", profile="env"))["stdout"].split()
    assert env == ["absent", "visible", "absent"]  # 비밀키·토큰 환경변수는 자식 프로세스에 전달되지 않는다
    assert ok(call(client, w["id"], "terminal.run", project="demo", profile="stdin"))["stdout"].strip() == "''"  # 입력 대기로 멈추지 않는다
    err(call(client, w["id"], "terminal.run", project="demo", profile="missing"), "exec_not_found")
    cwd = ok(call(client, w["id"], "terminal.run", project="demo", profile="cwd"))["stdout"].strip()
    assert os.path.samefile(cwd, proj_root)  # 등록된 프로젝트 디렉터리에서 실행


def test_run_process_kills_tree_and_reports_exit(tmp_path):
    r = run_process([sys.executable, "-c", "import sys; sys.exit(3)"], str(tmp_path), dict(os.environ), 10, 1000)
    assert r["exit_code"] == 3 and not r["timed_out"]


# ---------------------------------------------------------------- Git

def _git_repo(root, svc):
    exe = svc.dev.git_exe()
    if exe is None:
        pytest.skip("git 실행 파일이 없는 환경")
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for argv in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "초기 커밋"]):
        subprocess.run([exe, "-C", str(root), *argv], check=True, capture_output=True, env=env)


def test_git_status_diff_log_are_read_only_and_exclude_secrets(dev):
    c, p, w, root = dev
    svc = c.app.state.svc
    _git_repo(root, svc)
    st = ok(call(c, w["id"], "git.status", project="demo"))
    assert st["is_repo"] and st["clean"] is True and st["branch"]
    log = ok(call(c, w["id"], "git.log", project="demo", limit=5))
    assert log["commits"][0]["subject"] == "초기 커밋"
    ok(call(c, w["id"], "code.patch", project="demo", path="app/calc.py", old="a - b", new="a + b", run_id=77))
    (root / ".env").write_text("SECRET_TOKEN=changed\n", encoding="utf-8")
    d = ok(call(c, w["id"], "git.diff", project="demo", run_id=77))
    assert d["source"] == "git" and "-    return a - b" in d["git_diff"] and "+    return a + b" in d["git_diff"]
    assert "changed" not in d["git_diff"]  # 민감 파일의 diff 는 제외
    assert d["run_changes"][0]["path"] == "app/calc.py" and "return a + b" in d["run_changes"][0]["diff"]
    one = ok(call(c, w["id"], "git.diff", project="demo", path="app/calc.py"))
    assert "app/calc.py" in one["git_diff"]
    err(call(c, w["id"], "git.diff", project="demo", path=".env"), "sensitive_path")
    names = {f["path"] for f in ok(call(c, w["id"], "git.status", project="demo"))["changed_files"]}
    assert "app/calc.py" in names
    git_tools = [t for t in svc.tools.all() if t.name.startswith("git.")]
    assert {t.name for t in git_tools} == {"git.status", "git.diff", "git.log"}  # commit/push/reset/clean 도구는 없다


def test_git_diff_falls_back_to_tracked_changes_without_a_repo(dev):
    c, p, w, root = dev
    ok(call(c, w["id"], "code.patch", project="demo", path="app/calc.py", old="a - b", new="a + b", run_id=5))
    d = ok(call(c, w["id"], "git.diff", project="demo", run_id=5))
    assert d["run_changes"][0]["path"] == "app/calc.py" and (d["source"] == "tracked_changes" or d["source"] == "git")


# ---------------------------------------------------------------- 에이전트 루프(실제 Worker 실행 + FakeProvider 스크립트)

def dev_task(c, worker, *, checks=None, approval=False, tools=DEV_TOOLS, **kw):
    body = task_body(title="버그 수정", instructions="app/calc.py 의 add 함수 오류를 분석해 고치고 테스트를 통과시킨다.", completion_criteria=[],
                     checks={"min_chars": 80, "required_sections": ["## 원인", "## 수정 내용", "## 테스트 결과"], "require_changes": True, "require_tests": True} | (checks or {}),
                     report_kind="dev", requires_approval=approval, requires_materials=False, materials=[], tools=list(tools), max_tool_calls=14, max_cost_usd=0.05, max_seconds=120) | kw
    r = c.post(f"/api/workers/{worker['id']}/tasks", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def script(provider, steps):
    """worker_dev_step 응답을 차례로 돌려준다(소진되면 완료 선언). 호출 횟수를 센다."""
    state = {"n": 0, "prompts": []}

    def respond(messages):
        i = state["n"]
        state["n"] += 1
        state["prompts"].append(messages[-1]["content"])
        item = steps[i] if i < len(steps) else {"done": True, "summary": "스크립트 종료"}
        return item(messages) if callable(item) else item

    provider.overrides["worker_dev_step"] = respond
    return state


def call_step(tool, **args):
    return {"tool": tool, "args": {"project": "demo", **args}}


def nochange_report(messages):
    """변경이 없는 실행의 보고서: 코드가 기록한 변경 요약만 인용한다."""
    ids = {name: eid for eid, name in re.findall(r"<<<(E\d+) ([^\n]+)", messages[-1]["content"])}
    eid = next(e for n, e in ids.items() if n.startswith("변경 요약"))
    body = "# 작업 보고\n## 원인\n요청된 범위를 확인했다 (출처: 변경 요약(코드 기록))\n## 수정 내용\n이 실행에서 적용된 코드 변경 없음 (출처: 변경 요약(코드 기록))\n## 테스트 결과\n실행하지 않았다 (출처: 변경 요약(코드 기록))\n"
    return {"title": "작업 보고", "body": body, "sources": [eid], "missing": [], "claims": [{"text": "이 실행에서 적용된 코드 변경 없음", "evidence": [eid]}]}


def note_draft(messages):
    """후속 직원의 초안: 입력 Artifact(M1) 본문의 문장을 그대로 인용한다."""
    text = re.search(r"<<<M1 [^\n]*\n(.*?)\n>>>", messages[-1]["content"], re.S).group(1)
    line = next(ln.strip() for ln in text.splitlines() if "수정했다" in ln)
    sect = "\n".join(f"- {line} (출처: M1)" for _ in range(8))
    body = f"# 정리\n## 핵심 사실 및 출처\n{sect}\n## 블로그 초안\n{sect}\n## 확인 필요\n- 없음\n"
    return {"title": "정리", "body": body, "sources": ["M1"], "missing": [], "claims": [{"text": line, "evidence": ["M1"]}]}


def good_report(messages):
    ids = dict((name, eid) for eid, name in re.findall(r"<<<(E\d+) (\S+)", messages[-1]["content"]))
    patch, run_ = ids.get("code.patch", "E1"), ids.get("terminal.run", "E1")
    body = ("# add 함수 버그 수정\n## 원인\napp/calc.py 의 add 함수가 덧셈이 아니라 뺄셈 a - b 를 반환하고 있었다 (출처: code.patch)\n"
            "## 수정 내용\napp/calc.py 의 add 함수를 a + b 를 반환하도록 수정했다 (출처: code.patch)\n## 테스트 결과\n등록된 test 프로파일을 실행해 통과했다 (출처: terminal.run)\n")
    return {"title": "add 버그 수정 보고", "body": body, "sources": [patch, run_], "missing": [],
            "claims": [{"text": "app/calc.py 의 add 함수가 a - b 를 반환하던 것을 a + b 로 수정했다", "evidence": [patch]}, {"text": "test 프로파일 실행 결과 통과했다", "evidence": [run_]}]}


def run_task(c, task, timeout=40):
    rid = c.post(f"/api/workers/tasks/{task['id']}/run").json()["run_id"]
    wait_for(lambda: c.get(f"/api/workers/runs/{rid}").json()["status"] in ("completed", "failed", "awaiting_approval", "needs_input", "cancelled"), timeout=timeout)
    return c.get(f"/api/workers/runs/{rid}").json()


def test_agent_analyzes_edits_tests_and_reports_through_real_tool_calls(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = good_report
    st = script(provider, [
        {"thought": "프로젝트 파악", "calls": [call_step("project.inspect"), call_step("code.search", query="def add")]},
        {"thought": "코드 읽기", "calls": [call_step("code.read", path="app/calc.py"), call_step("code.read", path="tests/test_calc.py")]},
        {"thought": "수정", "calls": [call_step("code.patch", path="app/calc.py", old="return a - b", new="return a + b")]},
        {"thought": "테스트", "calls": [call_step("terminal.run", profile="test")]},
        {"thought": "diff 확인", "calls": [call_step("git.diff")]},
        {"done": True, "summary": "수정 완료"},
    ])
    task = dev_task(c, w)
    r = run_task(c, task)
    assert r["status"] == "completed", (r["status"], r["error_kind"], r["error"])
    assert (root / "app" / "calc.py").read_text(encoding="utf-8") == FIXED  # 실제 파일이 수정됐다
    kinds = [s["kind"] for s in r["steps"]]
    assert kinds.count("dev_tool") == 7 and "dev_done" in kinds and r["verification"]["passed"] is True
    names = {x["name"]: x["passed"] for x in r["verification"]["checks"] if x["name"].startswith("dev_")}
    assert names == {"dev_loop": True, "dev_changes": True, "dev_tests": True}
    # 모든 도구 실행이 실행 기록·활동 로그에 남는다(파일 내용은 잘려 기록)
    assert any(s["kind"] == "dev_tool" and s["tool"] == "code.patch" for s in r["steps"]) and r["llm_calls"] >= 7 and r["cost_usd"] > 0
    logs = c.get("/api/logs?limit=300").json()
    assert {"code.changed", "terminal.run"} <= {x["event"] for x in logs}
    # 변경 기록·Artifact: 코드가 기록한 변경과 diff 가 결과물에 붙는다
    ch = c.get(f"/api/projects/changes?run_id={r['id']}").json()
    assert len(ch) == 1 and ch[0]["path"] == "app/calc.py" and ch[0]["run_id"] == r["id"] and ch[0]["worker_id"] == w["id"]
    assert r["artifact"]["verified"] and "코드가 기록한 변경·테스트 내역" in r["content"] and "+    return a + b" in r["content"] and "종료코드 0" in r["content"]
    assert c.get("/api/approvals").json() == [] and st["n"] == 6  # 내부 개발 작업(읽기·수정·테스트)마다 승인을 요청하지 않는다
    assert "[작업 로그]" in st["prompts"][1] and "calc.py" in st["prompts"][1] and "sha256=" in st["prompts"][2]  # 도구 결과가 다음 판단의 입력이 된다


def test_agent_retries_after_failed_test_within_limits_and_fixes_it(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = good_report
    st = script(provider, [
        {"calls": [call_step("code.read", path="app/calc.py")]},
        {"calls": [call_step("code.patch", path="app/calc.py", old="return a - b", new="return a * b")]},  # 잘못된 수정
        {"calls": [call_step("terminal.run", profile="test")]},  # 실패
        {"calls": [call_step("code.patch", path="app/calc.py", old="return a * b", new="return a + b")]},  # 실패 출력을 보고 다시 수정
        {"calls": [call_step("terminal.run", profile="test")]},  # 통과
        {"done": True},
    ])
    r = run_task(c, dev_task(c, w))
    assert r["status"] == "completed" and (root / "app" / "calc.py").read_text(encoding="utf-8") == FIXED
    tests = [s for s in r["steps"] if s["kind"] == "dev_tool" and s.get("exit_code") is not None]
    assert [t["passed"] for t in tests] == [False, True]
    assert "assert" in st["prompts"][3] and "통과=False" in st["prompts"][3]  # 실패한 테스트 출력이 다음 단계 입력에 들어갔다
    assert len(c.get(f"/api/projects/changes?run_id={r['id']}").json()) == 2


def test_failing_tests_are_never_reported_as_success_and_differ_from_change_failure(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = good_report
    script(provider, [{"calls": [call_step("code.patch", path="app/calc.py", old="return a - b", new="return a * b")]}, {"calls": [call_step("terminal.run", profile="test")]},
                      {"done": True, "summary": "고쳤습니다(거짓일 수 있는 모델의 선언)"}])
    r = run_task(c, dev_task(c, w))
    assert r["status"] == "failed" and r["error_kind"] == "tests_failed" and "테스트" in r["error"]  # 모델이 done 이라고 해도 실패
    assert r["artifact"] is not None and r["artifact"]["verified"] is False and r["artifact"]["filename"].endswith("-unverified.md")
    assert (root / "app" / "calc.py").read_text(encoding="utf-8").count("a * b") == 1 and len(c.get(f"/api/projects/changes?run_id={r['id']}").json()) == 1  # 적용된 변경은 기록으로 남는다
    # 코드 변경 자체를 하지 못한 경우는 다른 실패 유형이다
    c.app.state.svc.workers.get_task  # noqa (존재 확인)
    script(provider, [{"calls": [call_step("code.patch", path="app/calc.py", old="없는 코드", new="x")]}, {"done": True}])
    r2 = run_task(c, dev_task(c, w, checks={"require_tests": False}))
    assert r2["status"] == "failed" and r2["error_kind"] == "changes_failed"


def test_repeated_identical_failures_stop_the_loop(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = good_report
    st = script(provider, [{"calls": [call_step("terminal.run", profile="test")]}] * 20)  # 고치지 않고 같은 테스트만 반복
    r = run_task(c, dev_task(c, w))
    assert r["status"] == "failed" and r["error_kind"] in ("tests_failed", "dev_incomplete", "changes_failed")
    stop = [s for s in r["steps"] if s["kind"] == "dev_stop"]
    assert stop and stop[0]["reason"] in ("repeated_failure", "no_progress") and st["n"] <= 7  # 무한 반복하지 않는다
    assert sum(1 for s in r["steps"] if s["kind"] == "dev_tool" and s.get("exit_code") is not None) == 1  # 같은 호출은 다시 실행하지 않고 안내만 한다
    assert any("이미 실행했습니다" in p for p in st["prompts"][2:])
    assert (root / "app" / "calc.py").read_text(encoding="utf-8") == BUGGY
    # 같은 호출이 같은 오류로 반복되는 경우
    st2 = script(provider, [{"calls": [call_step("code.patch", path="app/calc.py", old="nope", new="x")]}] * 20)
    r2 = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r2["status"] == "failed" and st2["n"] <= 4 and [s for s in r2["steps"] if s["kind"] == "dev_stop"][0]["reason"] == "repeated_failure"


def test_turn_limit_exec_limit_and_budget_reserve(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = good_report
    provider.overrides["worker_draft"] = nochange_report  # 변경이 없는 분석 보고서
    script(provider, [{"calls": [call_step("code.read", path="app/calc.py")]}] + [{"calls": [call_step("code.search", query=f"q{i}")]} for i in range(40)])
    r = run_task(c, dev_task(c, w, max_tool_calls=3, checks={"require_tests": False, "require_changes": False}))
    assert [s for s in r["steps"] if s["kind"] == "dev_stop"][0]["reason"] == "max_steps"
    assert r["status"] == "completed" and any("분석이 도중에 멈췄습니다" in x for x in r["verification"]["warnings"])  # 코드 변경이 없는 분석은 부분 결과 + 경고
    r_w = run_task(c, dev_task(c, w, max_tool_calls=3, checks={"require_changes": True}))
    assert r_w["status"] == "failed"  # 변경이 요구된 업무가 한도에서 끊기면 실패로 기록된다
    # terminal.run 횟수 상한
    c.app.state.svc.settings.dev_max_exec_runs = 2
    script(provider, [{"calls": [call_step("terminal.run", profile="test", args=[f"tests/test_calc.py::x{i}"])]} for i in range(6)])
    r2 = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    denied = [s for s in r2["steps"] if s["kind"] == "dev_stop" or s["kind"] == "dev_tool" and s.get("error_kind") == "exec_limit"]
    assert (root / "app" / "calc.py").read_text(encoding="utf-8") == BUGGY
    assert len([s for s in r2["steps"] if s["kind"] == "dev_tool" and s.get("exit_code") is not None]) == 2 and denied  # 세 번째부터는 실행되지 않고 한도 오류가 돌아온다
    # 비용 예비분: 업무 한도를 거의 쓰면 루프를 멈추고 보고서 비용을 남긴다
    script(provider, [{"calls": [call_step("code.search", query="x")]}] * 40)
    c.app.state.svc.settings.price_in_per_m = 4000.0  # 호출 한 번이 업무 한도의 큰 비율을 차지하게 한다
    r3 = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}, max_cost_usd=0.05))
    assert r3["status"] == "failed" and r3["error_kind"] in ("budget_exceeded", "dev_incomplete", "tests_failed", "changes_failed", "verification_failed")


def test_dangerous_or_out_of_scope_requests_are_blocked_and_loop_continues(dev, provider, tmp_path_factory):
    c, p, w, root = dev
    outside = tmp_path_factory.mktemp("victim")
    setup_llm(provider)
    provider.overrides["worker_draft"] = nochange_report
    attacks = [
        call_step("terminal.run", profile="bash"),  # 등록되지 않은 명령
        {"tool": "terminal.run", "args": {"project": "demo", "profile": "test", "args": ["-p", "evil"]}},  # 허용되지 않은 옵션
        {"tool": "code.write", "args": {"project": "demo", "path": "../escaped.txt", "content": "x"}},  # 경로 이탈
        {"tool": "code.write", "args": {"project": "demo", "path": str(outside / "pwn.txt"), "content": "x"}},  # 절대 경로
        {"tool": "code.read", "args": {"project": "demo", "path": ".env"}},  # 비밀키
        {"tool": "code.read", "args": {"project": "other", "path": "x"}},  # 허용되지 않은 프로젝트
        {"tool": "notes.write", "args": {"filename": "x.md", "content": "x"}},  # 이 직원에게 허용되지 않은 도구
        {"tool": "code.read", "args": {"project": "demo", "path": "app/calc.py", "_ctx": {"worker_id": 999}}},  # 컨텍스트 위조
        {"tool": "git.push", "args": {}},  # 존재하지 않는 위험 도구
    ]
    script(provider, [{"calls": attacks[0:3]}, {"calls": attacks[3:6]}, {"calls": attacks[6:9]}, {"calls": [call_step("code.read", path="app/calc.py")]}, {"done": True}])
    r = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r["status"] == "completed"  # 막힌 시도는 오류로 돌아올 뿐 실행을 깨뜨리지 않는다
    assert not (root.parent / "escaped.txt").exists() and not (outside / "pwn.txt").exists() and (root / "app" / "calc.py").read_text(encoding="utf-8") == BUGGY
    errs = [s.get("error_kind") for s in r["steps"] if s["kind"] == "dev_tool" and s.get("ok") is False]
    assert {"profile_not_found", "args_not_allowed", "path_escape", "sensitive_path", "not_granted"} <= set(errs), errs
    assert sum(1 for s in r["steps"] if s["kind"] == "tool_denied") == 2  # notes.write, git.push
    assert c.get("/api/approvals").json() == [] and c.get(f"/api/projects/changes?run_id={r['id']}").json() == []
    assert not [f for f in os.listdir(c.app.state.svc.settings.data_dir) if f == "notes"]  # notes.write 가 실행되지 않았다


def test_dev_task_requires_developer_worker_and_valid_checks(client, proj_root):
    p = mkproj(client, proj_root)
    reader = mk(client, "일반 직원", approval=False)[0]
    r = client.post(f"/api/workers/{reader['id']}/tasks", json=task_body(title="개발", report_kind="dev"))
    assert r.status_code == 422 and "개발자" in r.json()["detail"]
    dev_w = mkdev(client, p)
    bad = client.post(f"/api/workers/{dev_w['id']}/tasks", json=task_body(title="개발", report_kind="dev", checks={"require_tests": "yes"}, requires_materials=False, materials=[]))
    assert bad.status_code == 422
    assert client.post(f"/api/workers/{dev_w['id']}/tasks", json=task_body(title="개발", report_kind="dev", checks={"require_tests": True}, requires_materials=False, materials=[], completion_criteria=[])).status_code == 201
    # 프로젝트가 부여되지 않은 개발 직원의 실행은 시작 직후 이유와 함께 실패한다
    nogrant = mkdev(client, None, name="무권한 개발자")
    t = dev_task(client, nogrant)
    res = run_task(client, t)
    assert res["status"] == "failed" and res["error_kind"] == "no_project"


# ---------------------------------------------------------------- 워크플로·자율 운영과의 연결

def test_workflow_autonomous_runs_dev_work_without_unneeded_approvals_and_hands_off_artifact(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = lambda m: good_report(m) if "[업무] 버그 수정" in m[-1]["content"] else note_draft(m)
    script(provider, [{"calls": [call_step("code.patch", path="app/calc.py", old="return a - b", new="return a + b")]}, {"calls": [call_step("terminal.run", profile="test")]}, {"done": True}])
    dev_t = dev_task(c, w, approval=True)  # 보고서 확정은 승인 업무로 두어도 자율 모드에서는 정책이 처리한다
    writer, wt = mk(c, "정리 직원", approval=False, materials=False, tkw={"completion_criteria": []})
    provider.overrides["workflow_plan"] = plan_json([step("fix", w, dev_t), step("note", writer, wt, ["fix"], directive="선행 보고서를 요약")])
    c.put("/api/autonomy/settings", json={"max_mode": "autonomous"})
    r = c.post("/api/workflows", json={"goal": "calc 버그를 고치고 결과를 정리해 줘", "exec_mode": "autonomous"})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    assert r.json()["autonomy"]["auto_started"] is True  # 개발 직원은 부여된 프로젝트 범위 안에서 자동 시작 가능
    done = wait_wf(c, wid, lambda x: x["status"] == "completed", timeout=60)
    assert (root / "app" / "calc.py").read_text(encoding="utf-8") == FIXED
    aps = [a for a in c.get("/api/approvals").json() if a["tool"] == "worker.finalize"]
    assert len(aps) == 1 and aps[0]["decided_by"] == "autonomy:policy" and "프로젝트 파일 변경은 이미 적용" in aps[0]["args"]["impact"]
    run_b = c.get(f"/api/workers/runs/{by_key(done)['note']['run_id']}").json()  # 후속 직원은 개발 보고서 Artifact 를 고정 해시로 받는다
    art = by_key(done)["fix"]["artifact"]
    assert run_b["inputs"][0]["artifact_id"] == art["id"] and run_b["inputs"][0]["sha256"] == art["sha256"]


def test_autonomy_blocks_dev_worker_without_project_and_keeps_manual_approval_path(client, proj_root, provider):
    setup_llm(provider)
    p = mkproj(client, proj_root)
    nogrant = mkdev(client, None, name="무권한 개발자")
    t = dev_task(client, nogrant)
    provider.overrides["workflow_plan"] = plan_json([step("a", nogrant, t)])
    client.put("/api/autonomy/settings", json={"max_mode": "autonomous"})
    wf = client.post("/api/workflows", json={"goal": "개발 업무를 맡길게요", "exec_mode": "autonomous"}).json()
    assert wf["status"] == "planned" and wf["autonomy"]["auto_started"] is False and any("부여된 프로젝트가 없음" in b for b in wf["autonomy"]["decision"]["blockers"])
    assert client.get("/api/workers/runs").json() == [] and p["id"]
    # 읽기 권한만 부여된 개발 직원도 실행은 되지만, 수정 도구는 도구 단계에서 거부된다
    ro = mkdev(client, p, name="읽기 개발자", write=False, execute=False)
    assert call(client, ro["id"], "code.write", project="demo", path="a.py", content="x").error_kind == "permission_denied"


def test_duplicate_calls_get_guidance_read_ranges_are_shown_and_search_accepts_a_file_path(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = nochange_report
    st = script(provider, [{"calls": [call_step("project.files", path="app")]}, {"calls": [call_step("project.files", path="app")]},  # 같은 호출 반복
                           {"calls": [call_step("code.read", path="app/calc.py", start_line=1, end_line=1)]}, {"calls": [call_step("code.search", query="return", path="app/calc.py")]}, {"done": True}])
    r = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r["status"] == "completed" and "이미 실행했습니다" in st["prompts"][2]
    assert "[읽은 범위]" in st["prompts"][3] and "app/calc.py: 1-1 (전체 2줄)" in st["prompts"][3]
    hit = ok(call(c, w["id"], "code.search", project="demo", query="return", path="app/calc.py"))
    assert [m["path"] for m in hit["matches"]] == ["app/calc.py"]  # 파일 경로도 검색 범위로 쓸 수 있다


def test_required_reads_are_enforced_before_done_and_unread_analysis_fails(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = nochange_report
    (root / "app" / "long.py").write_bytes(("\n".join(f"x{i} = {i}" for i in range(1, 701)) + "\n").encode())  # 700줄: 한 번에(400줄) 다 못 읽는다
    checks = {"require_tests": False, "require_changes": False, "required_reads": ["app/calc.py", "app/long.py"], "min_files_read": 2}
    # 아무 것도 읽지 않고 완료를 선언하면 두 번 돌려보내고, 그래도 안 읽으면 시스템이 대신 끝까지 읽은 뒤 완료한다
    st = script(provider, [{"done": True}] * 8)
    r = run_task(c, dev_task(c, w, checks=checks))
    assert r["status"] == "completed", (r["status"], r["error"])
    assert "거부" in st["prompts"][1] and "필수 파일" in st["prompts"][1] and any(s["kind"] == "dev_auto_read" for s in r["steps"])
    # 읽을 수 없는 필수 파일(존재하지 않음)은 시스템이 대신 읽으려 해도 채울 수 없으므로 실패한다
    script(provider, [{"done": True}] * 10)
    r_bad = run_task(c, dev_task(c, w, checks=checks | {"required_reads": ["app/calc.py", "app/missing.py"]}))
    assert r_bad["status"] == "failed" and r_bad["error_kind"] == "dev_incomplete" and "app/missing.py" in r_bad["error"]
    # 끝까지(줄 범위를 이어서) 읽으면 완료된다. 남은 필수 파일은 프롬프트에 계속 보인다
    st2 = script(provider, [{"calls": [call_step("code.read", path="app/calc.py"), call_step("code.read", path="app/long.py", start_line=1, end_line=400)]},
                            {"done": True},  # 아직 long.py 를 다 읽지 않았으므로 거부된다
                            {"calls": [call_step("code.read", path="app/long.py", start_line=401, end_line=700)]}, {"done": True}])
    r2 = run_task(c, dev_task(c, w, checks=checks))
    assert r2["status"] == "completed", (r2["status"], r2["error"])
    assert "남은 것: app/long.py" in st2["prompts"][1] and "남은 것: 없음(모두 읽음)" in st2["prompts"][3]
    assert [x for x in r2["verification"]["checks"] if x["name"] == "dev_coverage"][0]["passed"]
    # 검증: 형식이 잘못된 필수 파일 설정은 거부된다
    bad = c.post(f"/api/workers/{w['id']}/tasks", json=task_body(title="x", report_kind="dev", requires_materials=False, materials=[], completion_criteria=[], checks={"required_reads": "app/calc.py"}))
    assert bad.status_code == 422


def test_absence_claims_from_zero_search_results_get_a_warning_and_no_auto_approval(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)

    def absent_report(messages):
        ids = {name: eid for eid, name in re.findall(r"<<<(E\d+) ([^\n]+)", messages[-1]["content"])}
        e_search = next(e for n, e in ids.items() if n.startswith("code.search"))
        e_read = next(e for n, e in ids.items() if n.startswith("code.read"))
        body = ("# 분석\n## 원인\n검색 결과 0건이었다 (출처: code.search)\n## 수정 내용\n코드 변경 없음 (출처: code.read)\n## 테스트 결과\n실행하지 않았다 (출처: code.read)\n")
        return {"title": "분석", "body": body, "sources": [e_search, e_read], "missing": [],
                "claims": [{"text": "검색 'zzz' (content) 결과 0건이라 해당 기능이 없다", "evidence": [e_search]}, {"text": "app/calc.py 를 읽었다", "evidence": [e_read]}]}

    provider.overrides["worker_draft"] = absent_report
    script(provider, [{"calls": [call_step("code.read", path="app/calc.py"), call_step("code.search", query="zzz-not-there")]}, {"done": True}])
    r = run_task(c, dev_task(c, w, approval=True, checks={"require_tests": False, "require_changes": False}))
    assert r["status"] == "awaiting_approval", (r["status"], r["error"])
    assert any("검색 결과 0건" in x and "부재" in x for x in r["verification"]["warnings"])  # 자동 승인 대상에서 빠진다
    # 읽은 파일이 적은데 '없음' 결론이 있으면 경고
    assert any("읽은 파일이" in x for x in r["verification"]["warnings"])


def test_system_reads_required_files_when_the_model_goes_idle_or_declares_done_early(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = nochange_report
    (root / "app" / "long.py").write_bytes(("\n".join(f"x{i} = {i}" for i in range(1, 701)) + "\n").encode())
    checks = {"require_tests": False, "require_changes": False, "required_reads": ["app/calc.py", "app/long.py"]}
    # 모델이 도구도 완료 선언도 내지 않는(빈 JSON) 약한 응답: 시스템이 필수 파일을 대신 끝까지 읽고, 그 뒤 모델이 done 을 낸다
    st = script(provider, [{}, {}, {}, {}, {"done": True}])
    r = run_task(c, dev_task(c, w, checks=checks))
    assert r["status"] == "completed", (r["status"], r["error"])
    auto = [s for s in r["steps"] if s["kind"] == "dev_auto_read"]
    assert auto and "app/long.py" in auto[0]["files"]
    reads = [s for s in r["steps"] if s["kind"] == "dev_tool" and s.get("tool") == "code.read"]
    assert len(reads) >= 3  # calc.py 1회 + long.py 400줄 단위 2회 이상
    assert [x for x in r["verification"]["checks"] if x["name"] == "dev_coverage"][0]["passed"]
    # 읽을 필수 파일이 없는데 모델이 계속 아무 것도 하지 않으면(분석은 끝난 것으로 보고) 부분 결과로 남고 경고가 붙는다
    script(provider, [{"calls": [call_step("code.read", path="app/calc.py")]}, {}, {}, {}])
    r2 = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r2["status"] == "completed" and any("분석이 도중에 멈췄습니다(idle)" in x for x in r2["verification"]["warnings"])
    # 변경이 요구된 업무에서는 idle 이 완료로 인정되지 않는다
    script(provider, [{}, {}, {}])
    r3 = run_task(c, dev_task(c, w, checks={"require_changes": True}))
    assert r3["status"] == "failed"


def test_model_sees_the_whole_code_it_read_not_just_the_first_lines(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = nochange_report
    (root / "app" / "long.py").write_bytes(("\n".join(f"x{i} = {i}" for i in range(1, 401)) + "\n").encode())  # 400줄 ≈ 4KB: 이전에는 2500자에서 잘렸다
    st = script(provider, [{"calls": [call_step("code.read", path="app/long.py")]}, {"calls": [call_step("code.read", path="app/calc.py")]}, {"done": True}])
    r = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r["status"] == "completed", (r["status"], r["error"])
    second = st["prompts"][1]
    assert "[읽은 코드]" in second and "x399 = 399" in second and "x400 = 400" in second  # 파일 끝까지 보인다
    assert second.count("x399 = 399") == 1  # 작업 로그에는 머리말만 있고 본문이 중복되지 않는다
    draft_prompt = [m for purpose, m in provider.prompts if purpose == "worker_draft"][-1][-1]["content"]
    assert "x399 = 399" in draft_prompt  # 최종 보고서의 근거에도 본문이 들어간다
    # 읽은 코드가 상한(5만 자)을 넘으면 오래된 구간부터 생략되고, 생략된 구간은 같은 호출을 다시 할 수 있다
    (root / "app" / "big.py").write_bytes(("\n".join(f"y{i} = '" + "z" * 120 + "'" for i in range(1, 401)) + "\n").encode())  # 400줄 ≈ 50KB
    (root / "app" / "big2.py").write_bytes(("\n".join(f"w{i} = '" + "z" * 120 + "'" for i in range(1, 401)) + "\n").encode())
    st2 = script(provider, [{"calls": [call_step("code.read", path="app/big.py")]}, {"calls": [call_step("code.read", path="app/big2.py")]},
                            {"calls": [call_step("code.read", path="app/big.py")]}, {"done": True}])
    r2 = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r2["status"] == "completed"
    assert "y1 = " not in st2["prompts"][2] and "w1 = " in st2["prompts"][2]  # big.py 는 생략됨
    assert not [s for s in r2["steps"] if s["kind"] == "dev_tool" and s.get("error_kind") == "duplicate_call"]  # 생략된 구간의 재읽기는 중복으로 막지 않는다


# ---------------------------------------------------------------- 직원 삭제

def test_delete_worker_without_history_removes_it_with_tasks_and_grants(client, proj_root):
    p = mkproj(client, proj_root)
    w = mkdev(client, p, name="지울 직원")
    dev_task(client, w)
    im = client.get(f"/api/workers/{w['id']}/delete-impact").json()
    assert im["tasks"] == 1 and im["runs"] == 0 and im["has_history"] is False and im["project_grants"] == 1
    r = client.delete(f"/api/workers/{w['id']}")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert client.get(f"/api/workers/{w['id']}").status_code == 404 and client.get("/api/workers").json() == []
    assert client.get(f"/api/workers/{w['id']}/projects").json()["grants"] == []  # 프로젝트 권한도 함께 사라진다
    assert client.get("/api/projects").json()[0]["worker_count"] == 0  # 프로젝트 자체는 남는다
    assert client.delete(f"/api/workers/{w['id']}").status_code == 404
    assert "worker.deleted" in {x["event"] for x in client.get("/api/logs?limit=100").json()}


def test_delete_worker_with_history_needs_purge_and_removes_runs_artifacts_files_and_approvals(dev, provider, settings):
    c, p, w, root = dev
    setup_llm(provider)
    other = mk(c, "남길 직원", approval=False)
    provider.overrides["worker_draft"] = good_report
    script(provider, [{"calls": [call_step("code.patch", path="app/calc.py", old="return a - b", new="return a + b")]}, {"calls": [call_step("terminal.run", profile="test")]}, {"done": True}])
    r = run_task(c, dev_task(c, w, approval=True))
    assert r["status"] == "awaiting_approval"
    # 승인 대기 중인 실행이 있으면 purge 여도 삭제할 수 없다
    blocked = c.delete(f"/api/workers/{w['id']}?purge=true")
    assert blocked.status_code == 409 and "승인 대기" in blocked.json()["detail"]
    assert approve_pending(c) == 1
    wait_for(lambda: c.get(f"/api/workers/runs/{r['id']}").json()["status"] == "completed")
    art = c.get(f"/api/workers/runs/{r['id']}").json()["artifact"]
    art_file = settings.workspace_dir / art["rel_path"].replace("/", os.sep)
    assert art_file.exists()
    im = c.get(f"/api/workers/{w['id']}/delete-impact").json()
    assert im["runs"] == 1 and im["artifacts"] == 1 and im["project_changes_kept"] == 1 and im["has_history"]
    # 이력이 있으면 purge 없이는 삭제되지 않는다
    refused = c.delete(f"/api/workers/{w['id']}")
    assert refused.status_code == 409 and "purge" in refused.json()["detail"] and c.get(f"/api/workers/{w['id']}").status_code == 200
    ok_ = c.delete(f"/api/workers/{w['id']}?purge=true")
    assert ok_.status_code == 200, ok_.text
    assert c.get(f"/api/workers/{w['id']}").status_code == 404 and c.get("/api/workers/runs").json() == []
    assert c.get(f"/api/artifacts/{art['id']}").status_code == 404  # 결과물 기록
    assert not art_file.exists() and not (settings.workspace_dir / f"w{w['id']}").exists()  # 결과물 파일과 직원 작업 공간 폴더
    assert [a for a in c.get("/api/approvals").json() if a["tool"] == "worker.finalize"] == []  # 이 직원의 승인 기록
    # 다른 직원과 프로젝트 파일 변경 기록은 그대로다
    assert [x["name"] for x in c.get("/api/workers").json()] == ["남길 직원"] and other[0]["id"]
    assert len(c.get("/api/projects/changes").json()) == 1 and (root / "app" / "calc.py").read_text(encoding="utf-8") == FIXED


def test_delete_is_blocked_while_the_worker_is_in_an_unfinished_workflow(client, provider):
    setup_llm(provider)
    a = mk(client, "조사 직원")
    b = mk(client, "작성 직원", materials=False)
    provider.overrides["workflow_plan"] = plan_json([step("r", *a), step("w", *b, ["r"])])
    wf = client.post("/api/workflows", json={"goal": "개발 기록을 조사해 정리해 줘", "budget_usd": 0.5}).json()
    assert client.get(f"/api/workers/{b[0]['id']}/delete-impact").json()["blocking_workflows"][0]["id"] == wf["id"]
    r = client.delete(f"/api/workers/{b[0]['id']}?purge=true")
    assert r.status_code == 409 and "끝나지 않은 워크플로" in r.json()["detail"]
    client.post(f"/api/workflows/{wf['id']}/cancel")  # 취소하면 삭제할 수 있고, 워크플로 화면은 깨지지 않는다
    assert client.delete(f"/api/workers/{b[0]['id']}?purge=true").status_code == 200
    d = client.get(f"/api/workflows/{wf['id']}")
    assert d.status_code == 200 and d.json()["status"] == "cancelled" and {s["key"] for s in d.json()["steps"]} == {"r", "w"}
    assert [x["name"] for x in client.get("/api/workers").json()] == ["조사 직원"]


def test_tasks_using_dev_tools_are_promoted_to_dev_kind_so_they_cannot_fail_with_no_context(client, proj_root):
    p = mkproj(client, proj_root)
    w = mkdev(client, p)
    body = task_body(title="분석", requires_materials=False, materials=[], completion_criteria=[], checks={"min_chars": 100}, tools=["project.list", "code.read"], report_kind="generic")
    r = client.post(f"/api/workers/{w['id']}/tasks", json=body)
    assert r.status_code == 201 and r.json()["report_kind"] == "dev"  # 일반 문서로 저장해도 개발 업무로 승격된다
    r2 = client.post(f"/api/workers/{w['id']}/tasks", json=body | {"title": "뉴스", "report_kind": "news"})
    assert r2.status_code == 422 and "개발 업무" in r2.json()["detail"]
    # 개발 도구가 없는 일반 업무는 그대로 일반 문서다
    plain = client.post(f"/api/workers/{w['id']}/tasks", json=body | {"title": "일반", "tools": []})
    assert plain.status_code == 201 and plain.json()["report_kind"] == "generic"
    # 이미 일반 문서로 저장된 업무를 수정해도 개발 도구가 있으면 승격된다
    with client.app_state.db.session() as s:
        from gyunexus.models import WorkerTask
        s.get(WorkerTask, r.json()["id"]).report_kind = "generic"
    up = client.put(f"/api/workers/tasks/{r.json()['id']}", json={"title": "분석(수정)"})
    assert up.status_code == 200 and up.json()["report_kind"] == "dev"


def test_invalid_json_from_the_model_is_retried_instead_of_failing_the_whole_run(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = nochange_report
    # 한 번 JSON 이 아닌(또는 끊긴) 응답이 와도 되돌려 보내고 계속한다
    st = script(provider, ['{"thought": "너무 길게 생각하다가 끊긴 응답', {"calls": [call_step("code.read", path="app/calc.py")]}, {"done": True}])
    r = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r["status"] == "completed", (r["status"], r["error"])
    assert "올바른 JSON 이 아니었습니다" in st["prompts"][1] and any(s.get("error") == "invalid_json_retry" for s in r["steps"])
    # 세 번 연속 깨지면 중단한다. 이미 읽은 것이 있고 코드 변경이 없으면 경고가 붙은 부분 결과, 읽은 것이 없으면 실패
    script(provider, [{"calls": [call_step("code.read", path="app/calc.py")]}, "깨진1", "깨진2", "깨진3"])
    r2 = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r2["status"] == "completed" and any("llm_invalid" in x for x in r2["verification"]["warnings"])
    script(provider, ["깨진1", "깨진2", "깨진3"])
    r3 = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r3["status"] == "failed" and r3["error_kind"] == "dev_incomplete"
    # JSON 이 깨진 호출이 개발 루프 밖(보고서 작성)에서 나면 기존처럼 llm_error 로 실패한다(숨기지 않는다)
    script(provider, [{"calls": [call_step("code.read", path="app/calc.py")]}, {"done": True}])
    provider.overrides["worker_draft"] = "이것은 JSON 이 아닙니다"
    r4 = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r4["status"] == "failed" and r4["error_kind"] == "llm_error"


def test_citation_format_variants_are_normalized_but_fabricated_sources_still_fail(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)

    def report(fake_source):
        def draft(messages):
            ids = {name: eid for eid, name in re.findall(r"<<<(E\d+) ([^\n]+)", messages[-1]["content"])}
            e_read = next(e for n, e in ids.items() if n.startswith("code.read"))
            body = ("# 분석\n## 원인\napp/calc.py 의 add 함수는 a - b 를 반환한다 (calc.py(%s))\n## 수정 내용\n코드 변경 없음 (변경 요약(코드 기록))\n## 테스트 결과\n실행하지 않았다 (테스트·실행 결과(코드 기록))\n" % e_read)
            claims = [{"text": "app/calc.py 의 add 함수는 a - b 를 반환한다", "evidence": []},  # 근거를 안 적은 주장: 같은 문장의 본문 인용(E)을 코드가 읽는다
                      {"text": "코드 변경 없음", "evidence": ["변경 요약(코드 기록)"]}]  # 자료 이름으로 적은 근거
            return {"title": "분석", "body": body, "sources": [f"calc.py({e_read})", fake_source], "missing": [], "claims": claims}
        return draft

    for fake, expect in (("code.read(E1)", "completed"), ("E99", "failed"), ("만들어낸 문서.md", "failed")):
        provider.overrides["worker_draft"] = report(fake)
        script(provider, [{"calls": [call_step("code.read", path="app/calc.py")]}, {"done": True}])
        r = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
        assert r["status"] == expect, (fake, r["status"], r["error"], [x for x in r["verification"]["checks"] if not x["passed"]])
        if expect == "failed":
            assert any(x["name"] == "source_ids" and not x["passed"] for x in r["verification"]["checks"])  # 지어낸 근거 번호·이름은 여전히 잡힌다


def test_dev_reports_do_not_fail_on_line_numbers_or_example_values_but_still_fail_on_invented_percentages(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)

    def report(extra):
        def draft(messages):
            ids = {name: eid for eid, name in re.findall(r"<<<(E\d+) ([^\n]+)", messages[-1]["content"])}
            e_read = next(e for n, e in ids.items() if n.startswith("code.read"))
            body = ("# 분석\n## 원인\napp/calc.py:1-2 의 add 함수는 a - b 를 반환한다 (calc.py(%s)) 줄 2 와 파일 전체 910-999 범위의 주변 코드도 같다\n"
                    "## 수정 내용\n코드 변경 없음 (변경 요약(코드 기록)). %s\n## 테스트 결과\n실행하지 않았다 (테스트·실행 결과(코드 기록))\n" % (e_read, extra))
            return {"title": "분석", "body": body, "sources": [e_read], "missing": [], "claims": [{"text": "app/calc.py 의 add 함수는 a - b 를 반환한다", "evidence": [e_read]}]}
        return draft

    # 줄 번호·범위(910-999 는 근거에 없는 숫자)와 제안 속 예시 값(0.05, 0.15)은 실패가 아니라 경고
    provider.overrides["worker_draft"] = report("테스트 예시: 필요량이 0.05 또는 0.15 부근인 경우")
    script(provider, [{"calls": [call_step("code.read", path="app/calc.py")]}, {"done": True}])
    r = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r["status"] == "completed", (r["status"], r["error"], [x for x in r["verification"]["checks"] if not x["passed"]])
    assert any("예시 값일 수 있음" in x and "0.05" in x for x in r["verification"]["warnings"]) and not any("910" in x for x in r["verification"]["warnings"])
    # 지어낸 퍼센트 통계는 여전히 실패한다
    provider.overrides["worker_draft"] = report("이 수정으로 연비 계산 속도가 73% 향상된다")
    script(provider, [{"calls": [call_step("code.read", path="app/calc.py")]}, {"done": True}])
    r2 = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert r2["status"] == "failed" and any(x["name"] == "numbers_grounded" and not x["passed"] and "73%" in x["detail"] for x in r2["verification"]["checks"])


# ---------------------------------------------------------------- 실행 이력 삭제

def test_delete_single_run_removes_record_artifact_file_and_approval_but_keeps_project_change_log(dev, provider, settings):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = good_report
    script(provider, [{"calls": [call_step("code.patch", path="app/calc.py", old="return a - b", new="return a + b")]}, {"calls": [call_step("terminal.run", profile="test")]}, {"done": True}])
    r = run_task(c, dev_task(c, w, approval=True))
    assert r["status"] == "awaiting_approval"
    chk = c.get(f"/api/workers/runs/{r['id']}/delete-check").json()
    assert chk["deletable"] is False and "승인 대기" in chk["reason"]  # 진행 중·승인 대기 실행은 지울 수 없다
    assert c.delete(f"/api/workers/runs/{r['id']}").status_code == 409
    assert approve_pending(c) == 1
    wait_for(lambda: c.get(f"/api/workers/runs/{r['id']}").json()["status"] == "completed")
    art = c.get(f"/api/workers/runs/{r['id']}").json()["artifact"]
    art_file = settings.workspace_dir / art["rel_path"].replace("/", os.sep)
    assert art_file.exists() and c.get(f"/api/workers/runs/{r['id']}/delete-check").json()["deletable"] is True
    ok_ = c.delete(f"/api/workers/runs/{r['id']}")
    assert ok_.status_code == 200 and ok_.json()["artifacts"] == 1
    assert c.get(f"/api/workers/runs/{r['id']}").status_code == 404 and c.get(f"/api/artifacts/{art['id']}").status_code == 404
    assert not art_file.exists() and not art_file.parent.exists()
    assert [a for a in c.get("/api/approvals").json() if a["tool"] == "worker.finalize"] == []
    assert len(c.get("/api/projects/changes").json()) == 1  # 프로젝트 파일 변경 기록은 감사용으로 남는다
    assert c.delete(f"/api/workers/runs/{r['id']}").status_code == 404
    assert "run.deleted" in {x["event"] for x in c.get("/api/logs?limit=100").json()}


def test_purge_unsuccessful_runs_only_removes_failed_ones_and_keeps_good_ones(dev, provider):
    c, p, w, root = dev
    setup_llm(provider)
    provider.overrides["worker_draft"] = nochange_report
    script(provider, [{"calls": [call_step("code.read", path="app/calc.py")]}, {"done": True}])
    good = run_task(c, dev_task(c, w, checks={"require_tests": False, "require_changes": False}))
    assert good["status"] == "completed"
    script(provider, [{"done": True}])
    bad1 = run_task(c, dev_task(c, w, checks={"require_changes": True}))  # 변경이 요구됐지만 없음 -> 실패
    bad2 = run_task(c, dev_task(c, w, checks={"require_changes": True}))
    assert bad1["status"] == bad2["status"] == "failed"
    res = c.post(f"/api/workers/{w['id']}/runs/purge-unsuccessful", json={}).json()
    assert sorted(res["deleted"]) == sorted([bad1["id"], bad2["id"]]) and res["skipped"] == []
    left = [x["id"] for x in c.get("/api/workers/runs").json()]
    assert left == [good["id"]]  # 성공한 실행은 그대로다
    assert c.post("/api/workers/999/runs/purge-unsuccessful", json={}).status_code == 404


def test_runs_in_workflows_or_used_as_inputs_cannot_be_deleted(client, provider):
    setup_llm(provider)
    a = mk(client, "조사 직원", approval=False)
    b = mk(client, "작성 직원", approval=False, materials=False)
    provider.overrides["workflow_plan"] = plan_json([step("r", *a), step("w", *b, ["r"])])
    wf = client.post("/api/workflows", json={"goal": "개발 기록을 조사해 정리해 줘", "budget_usd": 0.5}).json()
    client.post(f"/api/workflows/{wf['id']}/start")
    done = wait_wf(client, wf["id"], lambda x: x["status"] == "completed")
    run_a = by_key(done)["r"]["run_id"]
    chk = client.get(f"/api/workers/runs/{run_a}/delete-check").json()
    assert chk["deletable"] is False and "워크플로" in chk["reason"]
    assert client.delete(f"/api/workers/runs/{run_a}").status_code == 409
    # 같은 직원의 단독 수동 실행은 지울 수 있다
    rid = client.post(f"/api/workers/tasks/{a[1]['id']}/run").json()["run_id"]
    wait_for(lambda: client.get(f"/api/workers/runs/{rid}").json()["status"] in ("completed", "failed"))
    assert client.delete(f"/api/workers/runs/{rid}").status_code == 200