"""영상 시연용 임시 서버: 임시 DB + 가짜 LLM(FakeProvider). 사용자 DB·실제 LLM·외부 서비스에 접근하지 않는다."""
import json
import sys
import tempfile
import threading
import time

sys.path.insert(0, r"D:\github\persona-ai\gyunexus\backend")
sys.path.insert(0, r"D:\github\persona-ai\gyunexus\backend\tests")

import httpx
import uvicorn

from conftest import FakeProvider
from gyunexus.config import Settings
from gyunexus.main import create_app
from test_workers import MAT, good_draft, good_review, task_body, worker_body

tmp = tempfile.mkdtemp(prefix="gyunexus-demo-")
print("DATA_DIR", tmp, flush=True)
settings = Settings(data_dir=tmp, openai_api_key="", openai_model="gpt-4o-mini", price_in_per_m=0.15, price_out_per_m=0.60, latitude=None, longitude=None,
                    autonomous_enabled=False, proactive_quiet_hours="", scheduler_tick_seconds=3600, tool_retry_backoff=[0, 0])
provider = FakeProvider()
provider.overrides["worker_draft"] = lambda m: good_draft()
provider.overrides["worker_review"] = good_review


def plan(messages):
    cat = json.loads(messages[-1]["content"].split("[직원 카탈로그]\n")[1])
    steps = []
    for i, w in enumerate(cat[:2]):
        t = w["tasks"][0]
        steps.append({"key": f"s{i+1}", "title": f"{w['name']} 단계", "worker_id": w["worker_id"], "task_id": t["task_id"], "directive": "목표에 맞게 작성",
                      "depends_on": [f"s{i}"] if i else [], "reason": "카탈로그에서 선택"})
    return {"title": "개발 기록 조사와 글 정리", "steps": steps, "notes": ""}


provider.overrides["workflow_plan"] = plan
app = create_app(settings, provider, run_scheduler=False)
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(60):
    try:
        httpx.get("http://127.0.0.1:8765/api/health", timeout=1)
        break
    except Exception:
        time.sleep(0.2)

c = httpx.Client(base_url="http://127.0.0.1:8765", timeout=15)
for name, mats in (("조사 직원", True), ("작성 직원", False)):
    w = c.post("/api/workers", json=worker_body(name=name, role="자료 조사" if mats else "글 작성", allowed_tools=[])).json()
    tb = task_body(title=f"{name} 업무", requires_approval=True, tools=[], max_cost_usd=0.05, materials=[{"name": "devlog.md", "content": MAT}] if mats else [])
    if not mats:
        tb["materials"] = []
    print(name, c.post(f"/api/workers/{w['id']}/tasks", json=tb).status_code, flush=True)
print("READY", flush=True)
while True:
    time.sleep(3600)
