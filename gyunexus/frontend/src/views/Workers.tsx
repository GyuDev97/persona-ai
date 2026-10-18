import { useEffect, useMemo, useState } from "react";
import { api, useApi, type WorkerDetailT, type WorkerOptions, type WorkerRow, type WorkerRunRow, type WorkerTaskRow } from "../api";
import type { Nav } from "../App";
import { MarkdownPane } from "../components/Markdown";
import { Async, Collapse, ConfirmDialog, EmptyState, Field, fmtAgo, fmtTime, MasterDetail, Modal, PageHeader, StatusBadge, Tabs } from "../components/ui";

const ERR: Record<string, string> = {
  timeout: "제한 시간 초과", llm_error: "LLM 호출 실패", budget_exceeded: "업무 예산 초과(호출 전 차단)", daily_budget: "오늘 자율 예산 소진",
  verification_failed: "결과물 검증 실패", interrupted: "서버 재시작으로 중단", workspace_violation: "작업 공간 규칙 위반",
  artifact_changed: "승인 후 결과물 변경됨", artifact_missing: "결과물 파일 없음", disabled: "비활성화됨", internal: "내부 오류", no_input: "필요한 자료 없음",
};
const lines = (s: string) => s.split("\n").map((x) => x.trim()).filter(Boolean);
type Tab = "overview" | "tasks" | "runs" | "inputs" | "settings";

type WorkerForm = { name: string; role: string; description: string; model: string; permission_level: string; max_cost_usd: number; allowed_tools: string[]; enabled: boolean };
const emptyWorker = (opts?: WorkerOptions | null): WorkerForm => ({ name: "", role: "", description: "", model: opts?.models[0] ?? "", permission_level: "read_only", max_cost_usd: 0.05, allowed_tools: [], enabled: true });

export default function Workers({ version, nav }: { version: number; nav: Nav }) {
  const list = useApi<WorkerRow[]>("/workers", version);
  const opts = useApi<WorkerOptions>("/workers/options", 0);
  const [sel, setSel] = useState<number | null>(null);
  const [editor, setEditor] = useState<{ id?: number; form: WorkerForm } | null>(null);

  useEffect(() => {
    if (sel === null && list.data?.length && window.matchMedia("(min-width: 901px)").matches) setSel(list.data[0].id);
  }, [list.data, sel]);

  const tpl = opts.data?.templates[0];
  const openNew = (from?: Partial<WorkerForm>) => setEditor({ form: { ...emptyWorker(opts.data), ...from } });

  return (
    <div className="page-inner fill">
      <PageHeader title="AI 직원" desc="업무를 맡기고 결과물을 관리하는 공간입니다. 직원은 등록해도 자동으로 일하지 않습니다." actions={<button onClick={() => openNew()}>＋ 직원 등록</button>} />
      <Async q={list}>
        {(rows) =>
          rows.length === 0 ? (
            <div className="card">
              <EmptyState title="아직 등록된 직원이 없습니다" desc="직원을 등록하고 업무를 배정하면 결과물을 만들어 줍니다. 등록만으로는 아무 업무도 실행되지 않습니다."
                action={<div className="row wrap"><button onClick={() => openNew()}>＋ 직원 등록</button>{tpl && <button className="secondary" onClick={() => openNew(tpl.worker as Partial<WorkerForm>)}>템플릿으로 시작: {tpl.label}</button>}</div>} />
            </div>
          ) : (
            <MasterDetail hasDetail={sel !== null}
              list={
                <>
                  {rows.map((w) => (
                    <button key={w.id} className={`sel-item ${sel === w.id ? "active" : ""}`} onClick={() => setSel(w.id)}>
                      <div className="row between"><span className="t">{w.name}</span><StatusBadge status={w.state} /></div>
                      <div className="muted small">{w.role}</div>
                      <div className="muted small">{w.last_run ? `최근 실행 #${w.last_run.id} · ${w.last_run.status === "completed" ? "완료" : w.last_run.status} · ${fmtAgo(w.last_run.ended_at)}` : "실행 기록 없음"} · 업무 {w.task_count}</div>
                    </button>
                  ))}
                  {tpl && <button className="secondary sm" onClick={() => openNew(tpl.worker as Partial<WorkerForm>)}>템플릿: {tpl.label}</button>}
                </>
              }
              detail={sel !== null && opts.data ? <WorkerDetail key={sel} id={sel} opts={opts.data} version={version} nav={nav} onBack={() => setSel(null)} onChanged={list.reload}
                onEdit={(w) => setEditor({ id: w.id, form: { name: w.name, role: w.role, description: w.description, model: w.model, permission_level: w.permission_level, max_cost_usd: w.max_cost_usd, allowed_tools: w.allowed_tools, enabled: w.enabled } })} /> : null}
            />
          )
        }
      </Async>
      {editor && opts.data && <WorkerModal opts={opts.data} id={editor.id} initial={editor.form} onClose={() => setEditor(null)} onSaved={(id) => (setEditor(null), list.reload(), setSel(id))} />}
    </div>
  );
}

function ToolPicker({ opts, level, value, onChange, within }: { opts: WorkerOptions; level: string; value: string[]; onChange: (v: string[]) => void; within?: string[] }) {
  const tools = opts.tools.filter((t) => !within || within.includes(t.name));
  if (tools.length === 0) return <div className="small muted">선택할 수 있는 도구가 없습니다. 직원 설정에서 먼저 허용하세요.</div>;
  return (
    <div className="stack tight">
      {tools.map((t) => {
        const ok = level === "write_with_approval" ? t.available_with_write : t.available_read_only;
        const why = t.unavailable_reason || (t.risk !== "read" && level === "read_only" ? "읽기 전용 직원은 쓰기·외부 도구를 쓸 수 없습니다 (실행 권한을 ‘승인 후 쓰기’로 바꾸세요)" : "현재 사용할 수 없습니다");
        return (
          <label key={t.name} className="check" style={{ opacity: ok ? 1 : 0.55 }} title={ok ? t.description : why}>
            <input type="checkbox" disabled={!ok} checked={value.includes(t.name)} onChange={(e) => onChange(e.target.checked ? [...value, t.name] : value.filter((x) => x !== t.name))} />
            <span><b>{t.name}</b> <span className={`badge plain ${t.risk === "read" ? "ok" : "warn"}`}>{t.risk === "read" ? "읽기" : "쓰기·승인 필요"}</span>
              <div className="small muted">{ok ? t.description : `선택 불가: ${why}`}</div></span>
          </label>
        );
      })}
    </div>
  );
}

function WorkerModal({ opts, initial, id, onClose, onSaved }: { opts: WorkerOptions; initial: WorkerForm; id?: number; onClose: () => void; onSaved: (id: number) => void }) {
  const [f, setF] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = <K extends keyof WorkerForm>(k: K, v: WorkerForm[K]) => setF((p) => ({ ...p, [k]: v }));
  const save = async () => {
    setBusy(true);
    try {
      const w = await api<WorkerRow>(id ? `/workers/${id}` : "/workers", { method: id ? "PUT" : "POST", json: f });
      onSaved(w.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const risky = f.permission_level === "write_with_approval";
  return (
    <Modal open title={id ? "직원 수정" : "직원 등록"} onClose={onClose}
      footer={<><button className="secondary" onClick={onClose}>취소</button><button onClick={save} disabled={busy || !f.name.trim() || !f.role.trim()}>{id ? "저장" : "등록"}</button></>}>
      <div className="stack">
        {error && <div className="notice bad">{error}</div>}
        <div className="grid g2">
          <Field label="이름" required><input value={f.name} maxLength={80} onChange={(e) => set("name", e.target.value)} placeholder="예: 콘텐츠 담당" /></Field>
          <Field label="담당 역할" required><input value={f.role} maxLength={200} onChange={(e) => set("role", e.target.value)} placeholder="예: 기술 블로그 초안 작성" /></Field>
        </div>
        <Field label="업무 목적 및 설명"><textarea rows={3} value={f.description} onChange={(e) => set("description", e.target.value)} placeholder="이 직원이 맡을 업무와 목표" /></Field>
        <div className="grid g2">
          <Field label="LLM 모델"><select value={f.model} onChange={(e) => set("model", e.target.value)}>{opts.models.map((m) => <option key={m}>{m}</option>)}</select></Field>
          <Field label="1회 최대 비용(USD)" hint="업무별 한도와 함께 작은 값이 적용됩니다"><input type="number" min={0.0001} step={0.01} value={f.max_cost_usd} onChange={(e) => set("max_cost_usd", Number(e.target.value))} /></Field>
        </div>
        <div className={risky ? "danger-zone" : "card flat"}>
          <h4 style={{ marginTop: 0 }}>{risky ? "⚠ 권한 설정 (위험)" : "권한 설정"}</h4>
          <Field label="실행 권한">
            <select value={f.permission_level} onChange={(e) => setF((p) => ({ ...p, permission_level: e.target.value, allowed_tools: e.target.value === "read_only" ? p.allowed_tools.filter((t) => opts.tools.find((x) => x.name === t)?.available_read_only) : p.allowed_tools }))}>
              <option value="read_only">읽기 전용 — 조회 도구만 사용</option>
              <option value="write_with_approval">승인 후 쓰기 — 파일 변경 등은 사용자 승인 후 실행</option>
            </select>
          </Field>
          {risky && <div className="small" style={{ color: "var(--warn)", margin: "6px 0" }}>쓰기 도구는 실행 전에 항상 승인 요청이 만들어집니다. 승인하지 않으면 실행되지 않습니다.</div>}
          <h4>허용 도구</h4>
          <ToolPicker opts={opts} level={f.permission_level} value={f.allowed_tools} onChange={(v) => set("allowed_tools", v)} />
        </div>
        <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => set("enabled", e.target.checked)} /><span>활성화<div className="small muted">등록·활성화만으로는 업무가 자동 실행되지 않습니다.</div></span></label>
      </div>
    </Modal>
  );
}

function WorkerDetail({ id, opts, version, nav, onBack, onChanged, onEdit }: { id: number; opts: WorkerOptions; version: number; nav: Nav; onBack: () => void; onChanged: () => void; onEdit: (w: WorkerDetailT) => void }) {
  const detail = useApi<WorkerDetailT>(`/workers/${id}`, version);
  const runs = useApi<WorkerRunRow[]>(`/workers/runs?worker_id=${id}&limit=40`, version);
  const [tab, setTab] = useState<Tab>("overview");
  const [taskEdit, setTaskEdit] = useState<WorkerTaskRow | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<null | { title: string; message: string; label: string; danger?: boolean; run: () => Promise<unknown> }>(null);
  const w = detail.data;

  const act = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    detail.reload();
    runs.reload();
    onChanged();
  };
  const stats = useMemo(() => {
    const r = runs.data ?? [];
    return { done: r.filter((x) => x.status === "completed").length, failed: r.filter((x) => x.status === "failed").length, wait: r.filter((x) => x.status === "awaiting_approval").length,
      cost: r.reduce((s, x) => s + x.cost_usd, 0) };
  }, [runs.data]);
  if (!w) return <Async q={detail}>{() => null}</Async>;
  const running = (runs.data ?? []).filter((r) => ["pending", "running", "reviewing"].includes(r.status));

  return (
    <div className="stack">
      <div className="card">
        <div className="row between wrap">
          <div className="row"><button className="ghost back-btn" onClick={onBack}>← 목록</button><h2>{w.name}</h2><StatusBadge status={w.state} /></div>
          <div className="row">
            <button className="secondary" onClick={() => onEdit(w)}>수정</button>
            <button className={w.enabled ? "danger" : "secondary"} onClick={() => w.enabled
              ? setConfirm({ title: "직원을 비활성화할까요?", message: "비활성화하면 이 직원의 업무는 수동·정기 모두 실행되지 않습니다. 기록은 삭제되지 않습니다.", label: "비활성화", danger: true, run: () => api(`/workers/${w.id}`, { method: "PUT", json: { enabled: false } }) })
              : act(() => api(`/workers/${w.id}`, { method: "PUT", json: { enabled: true } }))}>{w.enabled ? "비활성화" : "활성화"}</button>
          </div>
        </div>
        <div className="muted">{w.role}</div>
      </div>
      {error && <div className="notice bad" onClick={() => setError(null)}>{error}</div>}
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "overview", label: "개요" }, { id: "tasks", label: "담당 업무", count: w.tasks.length }, { id: "runs", label: "실행 이력", count: runs.data?.length }, { id: "inputs", label: "입력 파일", count: w.inputs.length }, { id: "settings", label: "설정" }]} />

      {tab === "overview" && (
        <div className="stack">
          {w.awaiting_approval > 0 && <div className="notice">승인 대기 {w.awaiting_approval}건 <button className="link" onClick={() => setTab("runs")}>실행 이력에서 확인</button> · <button className="link" onClick={() => nav.go("approvals")}>승인 화면</button></div>}
          <div className="grid g4">
            <div className="card flat"><div className="small muted">업무</div><b style={{ fontSize: 22 }}>{w.tasks.length}</b></div>
            <div className="card flat"><div className="small muted">완료</div><b style={{ fontSize: 22 }}>{stats.done}</b></div>
            <div className="card flat"><div className="small muted">실패</div><b style={{ fontSize: 22, color: stats.failed ? "var(--bad)" : undefined }}>{stats.failed}</b></div>
            <div className="card flat"><div className="small muted">승인 대기</div><b style={{ fontSize: 22 }}>{w.awaiting_approval}</b></div>
          </div>
          <div className="grid g2">
            <div className="card">
              <div className="card-title"><h3>기본 정보</h3></div>
              <dl className="kv">
                <dt>설명</dt><dd>{w.description || <span className="muted">없음</span>}</dd>
                <dt>모델</dt><dd>{w.model}</dd>
                <dt>실행 권한</dt><dd>{w.permission_level === "read_only" ? "읽기 전용" : "승인 후 쓰기"}</dd>
                <dt>1회 최대 비용</dt><dd>${w.max_cost_usd}</dd>
                <dt>실행 비용 합계</dt><dd>${stats.cost.toFixed(4)} <span className="muted small">(최근 {runs.data?.length ?? 0}건)</span></dd>
                <dt>허용 도구</dt><dd>{w.allowed_tools.length ? w.allowed_tools.map((t) => <span key={t} className="badge plain" style={{ marginRight: 4 }}>{t}</span>) : <span className="muted">없음</span>}</dd>
              </dl>
            </div>
            <div className="card">
              <div className="card-title"><h3>진행 중인 업무</h3></div>
              {running.length === 0 ? <div className="muted">진행 중인 실행이 없습니다.</div> : running.map((r) => <div key={r.id} className="item row between"><span>#{r.id} {r.task_title}</span><StatusBadge status={r.status} /></div>)}
              <h4>최근 결과</h4>
              {(runs.data ?? []).slice(0, 3).map((r) => <div key={r.id} className="item row between"><span className="grow">#{r.id} {r.task_title}</span><StatusBadge status={r.status} /></div>)}
              {(runs.data ?? []).length === 0 && <div className="muted">아직 실행 기록이 없습니다.</div>}
            </div>
          </div>
        </div>
      )}

      {tab === "tasks" && (
        <div className="stack">
          <div className="row between"><span className="muted small">업무를 만들어도 자동 실행되지 않습니다. 직접 실행하거나 정기 실행으로 설정하세요.</span><button onClick={() => setTaskEdit("new")} disabled={!w.enabled}>＋ 업무 추가</button></div>
          {w.tasks.length === 0 && <div className="card"><EmptyState title="배정된 업무가 없습니다" desc="업무 추가에서 지시, 완료 기준, 사용할 도구를 정해 주세요." /></div>}
          {w.tasks.map((t) => (
            <div key={t.id} className="card">
              <div className="row between wrap">
                <div className="row wrap"><h3>{t.title}</h3><span className="badge plain">{t.mode === "scheduled" ? `정기 ${t.interval_minutes}분` : "수동"}</span>{t.status === "paused" && <StatusBadge status="paused" />}
                  {t.requires_approval && <span className="badge plain warn">승인 필요</span>}<span className="badge plain">{t.output_type}</span></div>
                <div className="row wrap">
                  <button disabled={!w.enabled || t.status !== "active"} onClick={() => act(() => api(`/workers/tasks/${t.id}/run`, { method: "POST" }).then(() => setTab("runs")))}>지금 실행</button>
                  <button className="secondary" onClick={() => act(() => api(`/workers/tasks/${t.id}/${t.status === "active" ? "pause" : "resume"}`, { method: "POST" }))}>{t.status === "active" ? "일시정지" : "재개"}</button>
                  <button className="secondary" onClick={() => setTaskEdit(t)}>수정</button>
                </div>
              </div>
              <p className="muted" style={{ margin: "6px 0" }}>{t.instructions.length > 180 ? t.instructions.slice(0, 180) + "…" : t.instructions}</p>
              <div className="small muted">완료 기준 {t.completion_criteria.length}건{t.checks.required_sections?.length ? ` · 필수 섹션 ${t.checks.required_sections.length}` : ""} · 도구 {t.tools.join(", ") || "없음"} · 최대 {t.max_seconds}초 / ${t.max_cost_usd}
                {t.mode === "scheduled" && ` · 다음 실행 ${fmtTime(t.next_run_at)}`} · 마지막 실행 {fmtTime(t.last_run_at)}</div>
              <Collapse title="완료 기준 보기"><ul>{t.completion_criteria.map((c, i) => <li key={i}>{c}</li>)}</ul>{t.checks.required_sections?.length ? <div className="small muted">필수 섹션: {t.checks.required_sections.join(" / ")}</div> : null}</Collapse>
            </div>
          ))}
        </div>
      )}

      {tab === "runs" && (
        <div className="stack tight">
          {runs.data?.length === 0 && <div className="card"><EmptyState title="아직 실행 기록이 없습니다" desc="담당 업무 탭에서 ‘지금 실행’을 눌러 보세요." /></div>}
          {runs.data?.map((r) => (
            <details key={r.id} className="collapse" open={r.status === "awaiting_approval"}>
              <summary>
                <span className="grow"><b>#{r.id}</b> {r.task_title} <span className="muted small">· {r.trigger === "schedule" ? "정기" : "수동"} · {fmtTime(r.started_at ?? r.created_at)} · ${r.cost_usd.toFixed(5)} · LLM {r.llm_calls}회</span></span>
                <StatusBadge status={r.status} />
              </summary>
              <div className="collapse-body">
                {r.error_kind && <div className="notice bad">{ERR[r.error_kind] ?? r.error_kind}{r.error ? `: ${r.error}` : ""}</div>}
                <RunDetail id={r.id} version={version} nav={nav} onChanged={() => (runs.reload(), detail.reload(), onChanged())} />
              </div>
            </details>
          ))}
        </div>
      )}

      {tab === "inputs" && <InputsPanel w={w} onSaved={() => act(async () => {})} />}

      {tab === "settings" && (
        <div className="stack">
          <div className="card"><div className="card-title"><h3>직원 설정</h3><button className="secondary" onClick={() => onEdit(w)}>수정</button></div>
            <dl className="kv"><dt>이름</dt><dd>{w.name}</dd><dt>역할</dt><dd>{w.role}</dd><dt>모델</dt><dd>{w.model}</dd><dt>실행 권한</dt><dd>{w.permission_level === "read_only" ? "읽기 전용" : "승인 후 쓰기"}</dd><dt>최대 비용</dt><dd>${w.max_cost_usd}</dd></dl></div>
          <div className="danger-zone"><h4>상태 변경</h4>
            <div className="row between wrap"><span className="small">{w.enabled ? "비활성화하면 업무가 실행되지 않습니다. 데이터는 삭제되지 않습니다." : "활성화하면 업무를 다시 실행할 수 있습니다."}</span>
              <button className={w.enabled ? "danger" : ""} onClick={() => w.enabled ? setConfirm({ title: "직원을 비활성화할까요?", message: "수동·정기 업무가 모두 실행되지 않습니다. 기록은 삭제되지 않습니다.", label: "비활성화", danger: true, run: () => api(`/workers/${w.id}`, { method: "PUT", json: { enabled: false } }) }) : act(() => api(`/workers/${w.id}`, { method: "PUT", json: { enabled: true } }))}>{w.enabled ? "비활성화" : "활성화"}</button></div></div>
        </div>
      )}

      {taskEdit && <TaskModal worker={w} opts={opts} task={taskEdit === "new" ? undefined : taskEdit} onClose={() => setTaskEdit(null)} onSaved={() => (setTaskEdit(null), detail.reload())} />}
      <ConfirmDialog open={!!confirm} title={confirm?.title ?? ""} message={confirm?.message} confirmLabel={confirm?.label} danger={confirm?.danger}
        onCancel={() => setConfirm(null)} onConfirm={() => { const c = confirm; setConfirm(null); if (c) void act(c.run); }} />
    </div>
  );
}

function InputsPanel({ w, onSaved }: { w: WorkerDetailT; onSaved: () => void }) {
  const [inp, setInp] = useState({ name: "", content: "" });
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try {
      await api(`/workers/${w.id}/inputs`, { method: "PUT", json: inp });
      setInp({ name: "", content: "" });
      setError(null);
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <div className="grid g2">
      <div className="card">
        <div className="card-title"><h3>저장된 입력 파일</h3></div>
        <p className="small muted">서버 작업 공간의 inputs/ 에만 저장됩니다. 업무의 ‘입력 파일 이름’에 적으면 읽습니다.</p>
        {w.inputs.length === 0 ? <EmptyState title="입력 파일이 없습니다" /> : w.inputs.map((i) => <div key={i.name} className="item row between"><span>{i.name}</span><span className="muted small">{i.size}B</span></div>)}
      </div>
      <div className="card stack">
        <h3>파일 추가</h3>
        {error && <div className="notice bad">{error}</div>}
        <Field label="파일 이름"><input value={inp.name} onChange={(e) => setInp({ ...inp, name: e.target.value })} placeholder="devlog.md (md, txt, json, log, csv)" /></Field>
        <Field label="내용"><textarea rows={8} value={inp.content} onChange={(e) => setInp({ ...inp, content: e.target.value })} /></Field>
        <div><button disabled={!inp.name.trim() || !inp.content.trim()} onClick={save}>파일 저장</button></div>
      </div>
    </div>
  );
}

type TaskForm = {
  title: string; instructions: string; criteria: string; min_chars: string; sections: string; mode: string; interval_minutes: string; tools: string[];
  max_seconds: number; max_cost_usd: number; output_type: string; requires_approval: boolean; allow_agents: boolean; requires_materials: boolean;
  materials: { name: string; content: string }[]; input_files: string;
  max_tool_calls: number; tool_rounds: number; report_kind: string; max_age_hours: string; min_items: string;
};
const emptyTask = (): TaskForm => ({ title: "", instructions: "", criteria: "", min_chars: "", sections: "", mode: "manual", interval_minutes: "60", tools: [], max_seconds: 120, max_cost_usd: 0.03,
  output_type: "markdown", requires_approval: true, allow_agents: false, requires_materials: false, materials: [], input_files: "", max_tool_calls: 4, tool_rounds: 1, report_kind: "generic", max_age_hours: "", min_items: "" });
const fromTask = (t: Partial<WorkerTaskRow>): TaskForm => ({
  ...emptyTask(), title: t.title ?? "", instructions: t.instructions ?? "", criteria: (t.completion_criteria ?? []).join("\n"),
  min_chars: t.checks?.min_chars ? String(t.checks.min_chars) : "", sections: (t.checks?.required_sections ?? []).join("\n"), mode: t.mode ?? "manual",
  interval_minutes: String(t.interval_minutes ?? 60), tools: t.tools ?? [], max_seconds: t.max_seconds ?? 120, max_cost_usd: t.max_cost_usd ?? 0.03,
  output_type: t.output_type ?? "markdown", requires_approval: t.requires_approval ?? true, allow_agents: t.allow_agents ?? false,
  requires_materials: t.requires_materials ?? false, materials: t.materials ?? [], input_files: (t.input_files ?? []).join(", "),
  max_tool_calls: t.max_tool_calls ?? 4, tool_rounds: t.tool_rounds ?? 1, report_kind: t.report_kind ?? "generic",
  max_age_hours: t.checks?.max_age_hours ? String(t.checks.max_age_hours) : "", min_items: t.checks?.min_items ? String(t.checks.min_items) : "",
});

function TaskModal({ worker, opts, task, onClose, onSaved }: { worker: WorkerDetailT; opts: WorkerOptions; task?: WorkerTaskRow; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState<TaskForm>(task ? fromTask(task) : emptyTask());
  const [error, setError] = useState<string | null>(null);
  const set = <K extends keyof TaskForm>(k: K, v: TaskForm[K]) => setF((p) => ({ ...p, [k]: v }));
  const save = async () => {
    const checks: Record<string, unknown> = {};
    if (f.min_chars) checks.min_chars = Number(f.min_chars);
    if (lines(f.sections).length) checks.required_sections = lines(f.sections);
    if (f.max_age_hours) checks.max_age_hours = Number(f.max_age_hours);
    if (f.min_items) checks.min_items = Number(f.min_items);
    const body = {
      title: f.title, instructions: f.instructions, completion_criteria: lines(f.criteria), checks, mode: f.mode,
      interval_minutes: f.mode === "scheduled" ? Number(f.interval_minutes) : null, tools: f.tools, max_seconds: f.max_seconds, max_cost_usd: f.max_cost_usd,
      output_type: f.output_type, requires_approval: f.requires_approval, allow_agents: f.allow_agents, requires_materials: f.requires_materials,
      materials: f.materials.filter((m) => m.name.trim() && m.content.trim()), input_files: f.input_files.split(",").map((x) => x.trim()).filter(Boolean),
      max_tool_calls: f.max_tool_calls, tool_rounds: f.tool_rounds, report_kind: f.report_kind,
    };
    try {
      await api(task ? `/workers/tasks/${task.id}` : `/workers/${worker.id}/tasks`, { method: task ? "PUT" : "POST", json: body });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const tpl = opts.templates.find((t) => t.worker.name === worker.name) ?? opts.templates[0];
  return (
    <Modal open size="wide" title={task ? "업무 수정" : "업무 추가"} onClose={onClose}
      footer={<><button className="secondary" onClick={onClose}>취소</button><button onClick={save} disabled={!f.title.trim() || !f.instructions.trim()}>{task ? "저장" : "추가"}</button></>}>
      <div className="stack">
        {!task && tpl && <button className="secondary" onClick={() => setF(fromTask(tpl.task as Partial<WorkerTaskRow>))}>템플릿 업무 채우기: {tpl.label}</button>}
        {error && <div className="notice bad">{error}</div>}
        <Field label="업무 제목" required><input value={f.title} onChange={(e) => set("title", e.target.value)} /></Field>
        <Field label="상세 지시" required><textarea rows={5} value={f.instructions} onChange={(e) => set("instructions", e.target.value)} /></Field>
        <Field label="완료 기준 (한 줄에 하나)" hint="결과물 본문의 문장을 인용해 증명되어야 통과합니다"><textarea rows={3} value={f.criteria} onChange={(e) => set("criteria", e.target.value)} /></Field>
        <div className="grid g2">
          <Field label="최소 글자 수"><input type="number" value={f.min_chars} onChange={(e) => set("min_chars", e.target.value)} /></Field>
          <Field label="필수 섹션 (한 줄에 하나)"><textarea rows={2} value={f.sections} onChange={(e) => set("sections", e.target.value)} /></Field>
        </div>
        <div className="grid g4">
          <Field label="실행 방식"><select value={f.mode} onChange={(e) => set("mode", e.target.value)}><option value="manual">수동</option><option value="scheduled">정기</option></select></Field>
          {f.mode === "scheduled" && <Field label={`주기(분, 최소 ${opts.min_interval_minutes})`}><input type="number" value={f.interval_minutes} onChange={(e) => set("interval_minutes", e.target.value)} /></Field>}
          <Field label="결과물 유형"><select value={f.output_type} onChange={(e) => set("output_type", e.target.value)}>{opts.output_types.map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="최대 시간(초)"><input type="number" value={f.max_seconds} onChange={(e) => set("max_seconds", Number(e.target.value))} /></Field>
          <Field label="최대 비용(USD)"><input type="number" step={0.01} value={f.max_cost_usd} onChange={(e) => set("max_cost_usd", Number(e.target.value))} /></Field>
        </div>
        <div><h4>이 업무에서 쓸 도구</h4><ToolPicker opts={opts} level={worker.permission_level} value={f.tools} onChange={(v) => set("tools", v)} within={worker.allowed_tools} /></div>
        <div className="grid g4">
          <Field label="보고서 종류"><select value={f.report_kind} onChange={(e) => set("report_kind", e.target.value)}><option value="generic">일반 문서</option><option value="news">뉴스 조사 보고서 (코드가 출처·날짜·검증 상태 기록)</option></select></Field>
          <Field label="도구 호출 상한(건)"><input type="number" min={1} max={30} value={f.max_tool_calls} onChange={(e) => set("max_tool_calls", Number(e.target.value))} /></Field>
          <Field label="도구 계획 라운드"><input type="number" min={1} max={3} value={f.tool_rounds} onChange={(e) => set("tool_rounds", Number(e.target.value))} /></Field>
          {f.report_kind === "news" && <Field label="기사 최대 연령(시간)"><input type="number" value={f.max_age_hours} placeholder="48" onChange={(e) => set("max_age_hours", e.target.value)} /></Field>}
        </div>
        <label className="check"><input type="checkbox" checked={f.requires_approval} onChange={(e) => set("requires_approval", e.target.checked)} />결과물 확정에 사용자 승인 필요</label>
        <label className="check"><input type="checkbox" checked={f.requires_materials} onChange={(e) => set("requires_materials", e.target.checked)} />자료가 없으면 지어내지 않고 자료를 요청</label>
        <label className="check"><input type="checkbox" checked={f.allow_agents} onChange={(e) => set("allow_agents", e.target.checked)} />기존 에이전트 토론 결과를 근거로 사용 허용 (새 토론은 시작하지 않음)</label>
        <div>
          <h4>제공 자료</h4>
          <div className="stack tight">
            {f.materials.map((m, i) => (
              <div key={i} className="card flat stack tight">
                <div className="row"><input className="grow" value={m.name} placeholder="자료 이름 (예: devlog.md)" onChange={(e) => set("materials", f.materials.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                  <button className="ghost" onClick={() => set("materials", f.materials.filter((_, j) => j !== i))} aria-label="자료 삭제">✕</button></div>
                <textarea rows={4} value={m.content} placeholder="자료 내용" onChange={(e) => set("materials", f.materials.map((x, j) => (j === i ? { ...x, content: e.target.value } : x)))} />
              </div>
            ))}
            <div><button className="secondary sm" onClick={() => set("materials", [...f.materials, { name: "", content: "" }])}>＋ 자료 추가</button></div>
          </div>
          <Field label="작업 공간 입력 파일 이름 (쉼표로 구분)"><input value={f.input_files} onChange={(e) => set("input_files", e.target.value)} placeholder="입력 파일 탭에 올린 파일: devlog.md" /></Field>
        </div>
      </div>
    </Modal>
  );
}

function RunDetail({ id, version, nav, onChanged }: { id: number; version: number; nav: Nav; onChanged: () => void }) {
  const run = useApi<WorkerRunRow>(`/workers/runs/${id}`, version);
  const [error, setError] = useState<string | null>(null);
  const [ask, setAsk] = useState<"approve" | "reject" | "cancel" | null>(null);
  const r = run.data;
  if (!r) return <div className="muted small">불러오는 중…</div>;
  const decide = async () => {
    const kind = ask;
    setAsk(null);
    try {
      if (kind === "cancel") await api(`/workers/runs/${r.id}/cancel`, { method: "POST" });
      else await api(`/approvals/${r.approval_id}/${kind}`, { method: "POST" });
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    run.reload();
    onChanged();
  };
  return (
    <div className="stack">
      {error && <div className="notice bad">{error}</div>}
      {r.status === "awaiting_approval" && (
        <div className="card flat">
          <b>승인 대기</b> — 검증을 통과한 결과물입니다. 승인하면 ‘완료’로 확정되며 외부 전송·게시는 일어나지 않습니다. 승인 시점에 파일이 승인 요청 때와 같은지 다시 확인합니다.
          <div className="row wrap" style={{ marginTop: 8 }}>
            <button onClick={() => setAsk("approve")}>승인</button><button className="danger" onClick={() => setAsk("reject")}>반려</button>
            <button className="link" onClick={() => nav.go("approvals")}>승인 화면에서 인자 보기</button>
          </div>
        </div>
      )}
      {["pending", "running", "reviewing"].includes(r.status) && <div><button className="secondary" onClick={() => setAsk("cancel")}>실행 취소</button></div>}
      {r.artifact && (
        <div>
          <div className="row between wrap"><b>결과물 {r.artifact.filename}</b><StatusBadge status={r.artifact.verified ? "completed" : "failed"} label={r.artifact.verified ? "검증됨" : "검증 실패(미확정)"} /></div>
          <div className="small muted">{r.artifact.size}B · sha256 {r.artifact.sha256.slice(0, 12)}… · {r.artifact.rel_path}</div>
          {r.content == null ? <pre>(파일을 읽을 수 없습니다)</pre> : r.artifact.filename.endsWith(".md") ? <MarkdownPane source={r.content} /> : <pre>{r.content}</pre>}
        </div>
      )}
      {r.verification && (
        <Collapse title={`검증 결과 (${r.verification.attempt}번째 시도) — ${r.verification.passed ? "통과" : "실패"}`} open={!r.verification.passed}>
          <table className="checks"><tbody>{r.verification.checks.map((c) => <tr key={c.name}><td>{c.passed ? "✓" : "✗"}</td><td>{c.name}</td><td>{c.detail}</td></tr>)}</tbody></table>
          {r.verification.warnings.map((w, i) => <div key={i} className="small" style={{ color: "var(--warn)" }}>⚠ {w}</div>)}
        </Collapse>
      )}
      <Collapse title="실행 단계" aside={`${r.steps?.length ?? 0}건 (권한·예산·도구·LLM·검증)`}><pre>{JSON.stringify(r.steps, null, 2)}</pre></Collapse>
      <ConfirmDialog open={ask !== null} danger={ask !== "approve"} confirmLabel={ask === "approve" ? "승인" : ask === "reject" ? "반려" : "취소 실행"}
        title={ask === "approve" ? "결과물을 승인할까요?" : ask === "reject" ? "결과물을 반려할까요?" : "실행을 취소할까요?"}
        message={ask === "approve" ? "승인하면 이 결과물이 ‘완료’로 확정됩니다." : ask === "reject" ? "반려하면 이 실행은 종료되고 결과물은 확정되지 않습니다." : "진행 중인 실행을 중단합니다."}
        onCancel={() => setAsk(null)} onConfirm={decide} />
    </div>
  );
}
