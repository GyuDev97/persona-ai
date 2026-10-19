import { useEffect, useMemo, useState } from "react";
import { api, useApi, type ProjectChangeRow, type ProjectGrant, type ProjectRow, type WorkerDetailT, type WorkerOptions, type WorkerProjects, type WorkerRow, type WorkerRunRow, type WorkerTaskRow } from "../api";
import type { Nav } from "../App";
import { MarkdownPane } from "../components/Markdown";
import { Async, Collapse, ConfirmDialog, EmptyState, Field, fmtAgo, fmtTime, MasterDetail, PageHeader, StatusBadge, Tabs } from "../components/ui";
import { CrudDialog } from "../components/crud/CrudDialog";
import { CrudList } from "../components/crud/CrudList";
import { DeleteConfirmDialog } from "../components/crud/DeleteConfirmDialog";
import { FormSection } from "../components/crud/FormParts";
import { useCrudForm } from "../components/crud/useCrudForm";

const ERR: Record<string, string> = {
  timeout: "제한 시간 초과", llm_error: "LLM 호출 실패", budget_exceeded: "업무 예산 초과(호출 전 차단)", daily_budget: "오늘 자율 예산 소진",
  verification_failed: "결과물 검증 실패", interrupted: "서버 재시작으로 중단", workspace_violation: "작업 공간 규칙 위반",
  artifact_changed: "승인 후 결과물 변경됨", artifact_missing: "결과물 파일 없음", disabled: "비활성화됨", internal: "내부 오류", no_input: "필요한 자료 없음",
  tests_failed: "테스트 실패(코드는 수정됨)", changes_failed: "코드 변경 실패", dev_incomplete: "개발 작업 미완료(한도·반복 오류)", no_project: "부여된 프로젝트 없음",
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

  const [deact, setDeact] = useState<{ id: number; name: string; task_count: number } | null>(null);
  const [bump, setBump] = useState(0); // 목록에서 바꾼 뒤 상세도 다시 읽게 하는 신호
  const [listError, setListError] = useState<string | null>(null);
  const tpl = opts.data?.templates[0];
  const openNew = (from?: Partial<WorkerForm>) => setEditor({ form: { ...emptyWorker(opts.data), ...from } });
  const toForm = (w: WorkerRow | WorkerDetailT): WorkerForm => ({ name: w.name, role: w.role, description: w.description, model: w.model, permission_level: w.permission_level, max_cost_usd: w.max_cost_usd, allowed_tools: w.allowed_tools, enabled: w.enabled });
  const setEnabled = async (w: WorkerRow, enabled: boolean) => {
    try { await api(`/workers/${w.id}`, { method: "PUT", json: { enabled } }); setListError(null); } catch (e) { setListError((e as Error).message); }
    list.reload(); setBump((b) => b + 1);
  };

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
                  {listError && <div className="notice bad" onClick={() => setListError(null)}>{listError}</div>}
                  <CrudList items={rows} rowKey={(w) => w.id} empty={null} selectedKey={sel} onSelect={(w) => setSel(w.id)}
                    actions={(w) => [
                      { label: "수정", onClick: () => setEditor({ id: w.id, form: toForm(w) }) },
                      w.enabled ? { label: "비활성화", danger: true, onClick: () => setDeact({ id: w.id, name: w.name, task_count: w.task_count }) } : { label: "활성화", onClick: () => void setEnabled(w, true) },
                    ]}
                    renderCard={(w) => (
                      <>
                        <div className="row between"><span className="t">{w.name}</span><StatusBadge status={w.state} /></div>
                        <div className="muted small">{w.role}</div>
                        <div className="muted small">{w.last_run ? `최근 실행 #${w.last_run.id} · ${w.last_run.status === "completed" ? "완료" : w.last_run.status} · ${fmtAgo(w.last_run.ended_at)}` : "실행 기록 없음"} · 업무 {w.task_count}</div>
                      </>
                    )} />
                  {tpl && <button className="secondary sm" onClick={() => openNew(tpl.worker as Partial<WorkerForm>)}>템플릿: {tpl.label}</button>}
                </>
              }
              detail={sel !== null && opts.data ? <WorkerDetail key={sel} id={sel} opts={opts.data} version={version + bump} nav={nav} onBack={() => setSel(null)} onChanged={list.reload}
                onDeactivate={(w) => setDeact({ id: w.id, name: w.name, task_count: w.tasks.length })}
                onEdit={(w) => setEditor({ id: w.id, form: toForm(w) })} /> : null}
            />
          )
        }
      </Async>
      <DeactivateDialog target={deact} onCancel={() => setDeact(null)} onDone={() => (setDeact(null), list.reload(), setBump((b) => b + 1))} />
      {editor && opts.data && <WorkerModal opts={opts.data} id={editor.id} initial={editor.form} onClose={() => setEditor(null)} onSaved={(id) => (setEditor(null), list.reload(), setSel(id))} />}
    </div>
  );
}

const TOOL_GROUPS: [string, string][] = [["search", "정보 검색"], ["project", "프로젝트 탐색"], ["code", "코드 작성"], ["exec", "테스트 및 빌드"], ["git", "Git"], ["other", "기타 기존 도구"]];
const PERM_LABEL: Record<string, string> = { read_only: "읽기 전용", write_with_approval: "승인 후 쓰기", developer: "개발자(프로젝트 범위)" };
const toolOk = (t: WorkerOptions["tools"][number], level: string) => (level === "developer" ? t.available_developer : level === "write_with_approval" ? t.available_with_write : t.available_read_only);

function ToolPicker({ opts, level, value, onChange, within }: { opts: WorkerOptions; level: string; value: string[]; onChange: (v: string[]) => void; within?: string[] }) {
  const tools = opts.tools.filter((t) => !within || within.includes(t.name));
  if (tools.length === 0) return <div className="small muted">선택할 수 있는 도구가 없습니다. 직원 설정에서 먼저 허용하세요.</div>;
  const badge = (t: WorkerOptions["tools"][number]) => (t.risk === "read" ? <span className="badge plain ok">읽기</span> : t.risk === "project" ? <span className="badge plain info">프로젝트 범위 안에서 자동</span> : <span className="badge plain warn">쓰기·승인 필요</span>);
  return (
    <div className="stack">
      {TOOL_GROUPS.map(([g, label]) => {
        const items = tools.filter((t) => (t.group || "other") === g);
        if (items.length === 0) return null;
        return (
          <div key={g} className="stack tight" role="group" aria-label={label}>
            <h5 style={{ margin: 0 }}>{label}</h5>
            {items.map((t) => {
              const ok = toolOk(t, level);
              const why = t.risk === "project" ? "개발 도구는 실행 권한을 ‘개발자(프로젝트 범위)’로 바꿔야 선택할 수 있습니다" : t.unavailable_reason || (t.risk !== "read" && level !== "write_with_approval" ? "쓰기·외부 도구는 실행 권한을 ‘승인 후 쓰기’로 바꿔야 합니다(개발자 권한에서도 불가)" : "현재 사용할 수 없습니다");
              return (
                <label key={t.name} className="check" style={{ opacity: ok ? 1 : 0.55 }} title={ok ? t.description : why}>
                  <input type="checkbox" disabled={!ok} checked={value.includes(t.name)} onChange={(e) => onChange(e.target.checked ? [...value, t.name] : value.filter((x) => x !== t.name))} />
                  <span><b>{t.name}</b> {badge(t)}
                    <div className="small muted">{ok ? t.description : `선택 불가: ${why}`}</div></span>
                </label>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

/** 개발자 직원의 접근 프로젝트와 프로젝트별 읽기·수정·실행 권한. 프로젝트가 허용하지 않은 권한은 고를 수 없다(서버도 다시 검사한다). */
function GrantEditor({ projects, grants, onChange }: { projects: ProjectRow[]; grants: Record<number, ProjectGrant>; onChange: (g: Record<number, ProjectGrant>) => void }) {
  if (projects.length === 0) return <div className="notice">등록된 프로젝트가 없습니다. 프로젝트 화면에서 먼저 등록하세요.</div>;
  const set = (p: ProjectRow, patch: Partial<ProjectGrant> | null) => {
    const next = { ...grants };
    if (patch === null) delete next[p.id];
    else {
      const base: ProjectGrant = grants[p.id] ?? { project_id: p.id, can_read: true, can_write: false, can_exec: false };
      next[p.id] = { ...base, ...patch, project_id: p.id };
    }
    onChange(next);
  };
  return (
    <div className="stack tight">
      {projects.map((p) => {
        const g = grants[p.id];
        return (
          <div key={p.id} className="card flat stack tight">
            <label className="check"><input type="checkbox" checked={!!g} disabled={!p.enabled || !p.allow_read} onChange={(e) => set(p, e.target.checked ? {} : null)} />
              <span><b>{p.name}</b>{!p.enabled && <span className="badge plain" style={{ marginLeft: 6 }}>비활성</span>}<div className="small muted" style={{ wordBreak: "break-all" }}>{p.root_path}</div></span></label>
            {g && (
              <div className="row wrap" style={{ paddingLeft: 26 }}>
                <label className="check"><input type="checkbox" checked disabled />읽기</label>
                <label className="check" title={p.allow_write ? undefined : "프로젝트가 수정을 허용하지 않습니다"}><input type="checkbox" checked={g.can_write} disabled={!p.allow_write} onChange={(e) => set(p, { can_write: e.target.checked })} />파일 수정</label>
                <label className="check" title={p.allow_exec ? undefined : "프로젝트가 실행을 허용하지 않습니다"}><input type="checkbox" checked={g.can_exec} disabled={!p.allow_exec} onChange={(e) => set(p, { can_exec: e.target.checked })} />테스트·빌드 실행</label>
                <span className="small muted">Git 조회는 프로젝트 설정({p.allow_git ? "허용" : "불가"})을 따릅니다</span>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
const validateWorker = (f: WorkerForm) => ({
  name: f.name.trim() ? undefined : "이름을 입력하세요",
  role: f.role.trim() ? undefined : "담당 역할을 입력하세요",
  model: f.model ? undefined : "모델을 선택하세요",
  max_cost_usd: f.max_cost_usd > 0 ? undefined : "0보다 큰 금액이어야 합니다",
});

/** 직원 등록·수정 공통 폼. id 가 있으면 수정(PUT), 없으면 등록(POST) 이고 필드는 같은 컴포넌트를 쓴다. */
function WorkerModal({ opts, initial, id, onClose, onSaved }: { opts: WorkerOptions; initial: WorkerForm; id?: number; onClose: () => void; onSaved: (id: number) => void }) {
  const form = useCrudForm<WorkerForm>(initial, validateWorker);
  const f = form.values;
  const risky = f.permission_level === "write_with_approval";
  const isDev = f.permission_level === "developer";
  const projects = useApi<ProjectRow[]>("/projects", 0);
  const current = useApi<WorkerProjects>(id ? `/workers/${id}/projects` : null, 0);
  const [grants, setGrants] = useState<Record<number, ProjectGrant>>({});
  useEffect(() => { if (current.data) setGrants(Object.fromEntries(current.data.grants.map((g) => [g.project_id, g]))); }, [current.data]);
  const bind = (k: keyof WorkerForm) => ({ onBlur: () => form.touch(k) });
  return (
    <CrudDialog mode={id ? "update" : "create"} title={id ? "직원 수정" : "직원 등록"} description="등록·수정만으로는 업무가 자동 실행되지 않습니다." dirty={form.dirty} validate={form.check}
      onClose={onClose} onSubmit={async () => {
        const w = await api<WorkerRow>(id ? `/workers/${id}` : "/workers", { method: id ? "PUT" : "POST", json: f });
        if (isDev) await api(`/workers/${w.id}/projects`, { method: "PUT", json: { grants: Object.values(grants) } });
        onSaved(w.id);
      }}>
      <FormSection title="기본 정보">
        <div className="grid g2">
          <Field label="이름" required error={form.errorOf("name")}><input value={f.name} maxLength={80} aria-invalid={!!form.errorOf("name")} {...bind("name")} onChange={(e) => form.set("name", e.target.value)} placeholder="예: 콘텐츠 담당" /></Field>
          <Field label="담당 역할" required error={form.errorOf("role")}><input value={f.role} maxLength={200} aria-invalid={!!form.errorOf("role")} {...bind("role")} onChange={(e) => form.set("role", e.target.value)} placeholder="예: 기술 블로그 초안 작성" /></Field>
        </div>
        <Field label="업무 목적 및 설명"><textarea rows={3} value={f.description} onChange={(e) => form.set("description", e.target.value)} placeholder="이 직원이 맡을 업무와 목표" /></Field>
      </FormSection>
      <FormSection title="실행 설정">
        <div className="grid g2">
          <Field label="LLM 모델" error={form.errorOf("model")}><select value={f.model} onChange={(e) => form.set("model", e.target.value)}>{opts.models.map((m) => <option key={m}>{m}</option>)}</select></Field>
          <Field label="1회 최대 비용(USD)" error={form.errorOf("max_cost_usd")} hint="업무별 한도와 함께 작은 값이 적용됩니다"><input type="number" min={0.0001} step={0.01} value={f.max_cost_usd} aria-invalid={!!form.errorOf("max_cost_usd")} {...bind("max_cost_usd")} onChange={(e) => form.set("max_cost_usd", Number(e.target.value))} /></Field>
        </div>
        <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => form.set("enabled", e.target.checked)} /><span>활성화<div className="small muted">등록·활성화만으로는 업무가 자동 실행되지 않습니다.</div></span></label>
      </FormSection>
      <FormSection title={risky ? "⚠ 권한 설정 (위험)" : "권한 및 허용 도구"} tone={risky ? "danger" : undefined}>
        <Field label="실행 권한">
          <select value={f.permission_level} onChange={(e) => form.patch({ permission_level: e.target.value, allowed_tools: f.allowed_tools.filter((t) => { const x = opts.tools.find((o) => o.name === t); return !!x && toolOk(x, e.target.value); }) })}>
            <option value="read_only">읽기 전용 — 조회 도구만 사용</option>
            <option value="write_with_approval">승인 후 쓰기 — 파일 변경 등은 사용자 승인 후 실행</option>
            <option value="developer">개발자(프로젝트 범위) — 부여된 프로젝트 안에서 코드 작성·테스트를 승인 없이 수행</option>
          </select>
        </Field>
        {risky && <div className="small" style={{ color: "var(--warn)" }}>쓰기 도구는 실행 전에 항상 승인 요청이 만들어집니다. 승인하지 않으면 실행되지 않습니다.</div>}
        {isDev && <div className="small" style={{ color: "var(--warn)" }}>개발자 권한: 아래에서 부여한 프로젝트 범위 안에서만 파일을 수정·실행합니다. 범위 밖 경로, 민감 파일(.env·키), 등록되지 않은 명령은 도구가 거부합니다. 배포·push 도구는 없습니다.</div>}
        <div><h4 style={{ marginTop: 0 }}>허용 도구</h4><ToolPicker opts={opts} level={f.permission_level} value={f.allowed_tools} onChange={(v) => form.set("allowed_tools", v)} /></div>
      </FormSection>
      {isDev && (
        <FormSection title="접근 가능한 프로젝트" desc="프로젝트마다 읽기·수정·실행 권한을 지정합니다. 프로젝트 화면에서 허용한 범위를 넘을 수 없습니다.">
          <GrantEditor projects={projects.data ?? []} grants={grants} onChange={setGrants} />
        </FormSection>
      )}
    </CrudDialog>
  );
}

/** 직원 비활성화 확인. 영향 범위는 목록·상세가 이미 가진 값(업무 수)과 기존 화면 문구에서 확인된 사실만 보여 준다. */
function DeactivateDialog({ target, onDone, onCancel }: { target: { id: number; name: string; task_count: number } | null; onDone: () => void; onCancel: () => void }) {
  return (
    <DeleteConfirmDialog open={!!target} title="직원을 비활성화할까요?" itemName={target?.name ?? ""} action="비활성화" confirmLabel="비활성화"
      impact={target ? [`담당 업무 ${target.task_count}개가 수동·정기 모두 실행되지 않습니다`, "실행 기록·결과물·업무 설정은 삭제되지 않습니다"] : []}
      recovery={{ reversible: true, note: "다시 활성화하면 업무를 다시 실행할 수 있습니다." }}
      onCancel={onCancel} onConfirm={async () => { await api(`/workers/${target!.id}`, { method: "PUT", json: { enabled: false } }); onDone(); }} />
  );
}
function WorkerDetail({ id, opts, version, nav, onBack, onChanged, onEdit, onDeactivate }: { id: number; opts: WorkerOptions; version: number; nav: Nav; onBack: () => void; onChanged: () => void; onEdit: (w: WorkerDetailT) => void; onDeactivate: (w: WorkerDetailT) => void }) {
  const detail = useApi<WorkerDetailT>(`/workers/${id}`, version);
  const runs = useApi<WorkerRunRow[]>(`/workers/runs?worker_id=${id}&limit=40`, version);
  const [tab, setTab] = useState<Tab>("overview");
  const [taskEdit, setTaskEdit] = useState<WorkerTaskRow | "new" | null>(null);
  const [error, setError] = useState<string | null>(null);
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
            <button className={w.enabled ? "danger" : "secondary"} onClick={() => w.enabled ? onDeactivate(w) : act(() => api(`/workers/${w.id}`, { method: "PUT", json: { enabled: true } }))}>{w.enabled ? "비활성화" : "활성화"}</button>
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
                <dt>실행 권한</dt><dd>{PERM_LABEL[w.permission_level] ?? w.permission_level}</dd>
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
            <dl className="kv"><dt>이름</dt><dd>{w.name}</dd><dt>역할</dt><dd>{w.role}</dd><dt>모델</dt><dd>{w.model}</dd><dt>실행 권한</dt><dd>{PERM_LABEL[w.permission_level] ?? w.permission_level}</dd><dt>최대 비용</dt><dd>${w.max_cost_usd}</dd></dl></div>
          <div className="danger-zone"><h4>상태 변경</h4>
            <div className="row between wrap"><span className="small">{w.enabled ? "비활성화하면 업무가 실행되지 않습니다. 데이터는 삭제되지 않습니다." : "활성화하면 업무를 다시 실행할 수 있습니다."}</span>
              <button className={w.enabled ? "danger" : ""} onClick={() => w.enabled ? onDeactivate(w) : act(() => api(`/workers/${w.id}`, { method: "PUT", json: { enabled: true } }))}>{w.enabled ? "비활성화" : "활성화"}</button></div></div>
        </div>
      )}

      {taskEdit && <TaskModal worker={w} opts={opts} task={taskEdit === "new" ? undefined : taskEdit} onClose={() => setTaskEdit(null)} onSaved={() => (setTaskEdit(null), detail.reload())} />}
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
  max_tool_calls: number; tool_rounds: number; report_kind: string; max_age_hours: string; min_items: string; require_changes: boolean; require_tests: boolean; required_reads: string; min_files_read: string;
};
const emptyTask = (): TaskForm => ({ title: "", instructions: "", criteria: "", min_chars: "", sections: "", mode: "manual", interval_minutes: "60", tools: [], max_seconds: 120, max_cost_usd: 0.03,
  output_type: "markdown", requires_approval: true, allow_agents: false, requires_materials: false, materials: [], input_files: "", max_tool_calls: 4, tool_rounds: 1, report_kind: "generic", max_age_hours: "", min_items: "", require_changes: false, require_tests: false, required_reads: "", min_files_read: "" });
const fromTask = (t: Partial<WorkerTaskRow>): TaskForm => ({
  ...emptyTask(), title: t.title ?? "", instructions: t.instructions ?? "", criteria: (t.completion_criteria ?? []).join("\n"),
  min_chars: t.checks?.min_chars ? String(t.checks.min_chars) : "", sections: (t.checks?.required_sections ?? []).join("\n"), mode: t.mode ?? "manual",
  interval_minutes: String(t.interval_minutes ?? 60), tools: t.tools ?? [], max_seconds: t.max_seconds ?? 120, max_cost_usd: t.max_cost_usd ?? 0.03,
  output_type: t.output_type ?? "markdown", requires_approval: t.requires_approval ?? true, allow_agents: t.allow_agents ?? false,
  requires_materials: t.requires_materials ?? false, materials: t.materials ?? [], input_files: (t.input_files ?? []).join(", "),
  max_tool_calls: t.max_tool_calls ?? 4, tool_rounds: t.tool_rounds ?? 1, report_kind: t.report_kind ?? "generic",
  max_age_hours: t.checks?.max_age_hours ? String(t.checks.max_age_hours) : "", min_items: t.checks?.min_items ? String(t.checks.min_items) : "",
  require_changes: !!t.checks?.require_changes, require_tests: !!t.checks?.require_tests,
  required_reads: (t.checks?.required_reads ?? []).join("\n"), min_files_read: t.checks?.min_files_read ? String(t.checks.min_files_read) : "",
});

/** 업무 등록·수정 공통 폼(task 가 있으면 수정). 항목이 많아 구역으로 나눠 보여 준다. */
function TaskModal({ worker, opts, task, onClose, onSaved }: { worker: WorkerDetailT; opts: WorkerOptions; task?: WorkerTaskRow; onClose: () => void; onSaved: () => void }) {
  const form = useCrudForm<TaskForm>(task ? fromTask(task) : emptyTask(), (v) => ({
    title: v.title.trim() ? undefined : "업무 제목을 입력하세요",
    instructions: v.instructions.trim() ? undefined : "상세 지시를 입력하세요",
    interval_minutes: v.mode === "scheduled" && !(Number(v.interval_minutes) >= opts.min_interval_minutes) ? `주기는 ${opts.min_interval_minutes}분 이상이어야 합니다` : undefined,
    max_seconds: v.max_seconds > 0 ? undefined : "0보다 커야 합니다",
    max_cost_usd: v.max_cost_usd > 0 ? undefined : "0보다 큰 금액이어야 합니다",
  }));
  const f = form.values;
  const set = form.set;
  const err = (k: keyof TaskForm) => form.errorOf(k);
  const save = async () => {
    const checks: Record<string, unknown> = {};
    if (f.min_chars) checks.min_chars = Number(f.min_chars);
    if (lines(f.sections).length) checks.required_sections = lines(f.sections);
    if (f.max_age_hours) checks.max_age_hours = Number(f.max_age_hours);
    if (f.min_items) checks.min_items = Number(f.min_items);
    if (f.report_kind === "dev") {
      checks.require_changes = f.require_changes; checks.require_tests = f.require_tests;
      if (lines(f.required_reads).length) checks.required_reads = lines(f.required_reads);
      if (f.min_files_read) checks.min_files_read = Number(f.min_files_read);
    }
    const body = {
      title: f.title, instructions: f.instructions, completion_criteria: lines(f.criteria), checks, mode: f.mode,
      interval_minutes: f.mode === "scheduled" ? Number(f.interval_minutes) : null, tools: f.tools, max_seconds: f.max_seconds, max_cost_usd: f.max_cost_usd,
      output_type: f.output_type, requires_approval: f.requires_approval, allow_agents: f.allow_agents, requires_materials: f.requires_materials,
      materials: f.materials.filter((m) => m.name.trim() && m.content.trim()), input_files: f.input_files.split(",").map((x) => x.trim()).filter(Boolean),
      max_tool_calls: f.max_tool_calls, tool_rounds: f.tool_rounds, report_kind: f.report_kind,
    };
    await api(task ? `/workers/tasks/${task.id}` : `/workers/${worker.id}/tasks`, { method: task ? "PUT" : "POST", json: body });
    onSaved();
  };
  const tpl = opts.templates.find((t) => t.worker.name === worker.name) ?? opts.templates[0];
  return (
    <CrudDialog mode={task ? "update" : "create"} size="wide" title={task ? "업무 수정" : "업무 추가"} submitLabel={task ? "저장" : "추가"} dirty={form.dirty} validate={form.check} onClose={onClose} onSubmit={save}>
      {!task && tpl && <div><button type="button" className="secondary" onClick={() => form.patch(fromTask(tpl.task as Partial<WorkerTaskRow>))}>템플릿 업무 채우기: {tpl.label}</button></div>}
      <FormSection title="기본 정보">
        <Field label="업무 제목" required error={err("title")}><input value={f.title} aria-invalid={!!err("title")} onBlur={() => form.touch("title")} onChange={(e) => set("title", e.target.value)} /></Field>
        <Field label="상세 지시" required error={err("instructions")}><textarea rows={5} value={f.instructions} aria-invalid={!!err("instructions")} onBlur={() => form.touch("instructions")} onChange={(e) => set("instructions", e.target.value)} /></Field>
      </FormSection>
      <FormSection title="완료 기준" desc="결과물 검증에 쓰입니다.">
        <Field label="완료 기준 (한 줄에 하나)" hint="결과물 본문의 문장을 인용해 증명되어야 통과합니다"><textarea rows={3} value={f.criteria} onChange={(e) => set("criteria", e.target.value)} /></Field>
        <div className="grid g2">
          <Field label="최소 글자 수"><input type="number" value={f.min_chars} onChange={(e) => set("min_chars", e.target.value)} /></Field>
          <Field label="필수 섹션 (한 줄에 하나)"><textarea rows={2} value={f.sections} onChange={(e) => set("sections", e.target.value)} /></Field>
        </div>
      </FormSection>
      <FormSection title="실행 설정">
        <div className="grid g4">
          <Field label="실행 방식"><select value={f.mode} onChange={(e) => set("mode", e.target.value)}><option value="manual">수동</option><option value="scheduled">정기</option></select></Field>
          {f.mode === "scheduled" && <Field label={`주기(분, 최소 ${opts.min_interval_minutes})`} error={err("interval_minutes")}><input type="number" value={f.interval_minutes} onChange={(e) => set("interval_minutes", e.target.value)} /></Field>}
          <Field label="결과물 유형"><select value={f.output_type} onChange={(e) => set("output_type", e.target.value)}>{opts.output_types.map((o) => <option key={o}>{o}</option>)}</select></Field>
          <Field label="최대 시간(초)" error={err("max_seconds")}><input type="number" value={f.max_seconds} onChange={(e) => set("max_seconds", Number(e.target.value))} /></Field>
          <Field label="최대 비용(USD)" error={err("max_cost_usd")}><input type="number" step={0.01} value={f.max_cost_usd} onChange={(e) => set("max_cost_usd", Number(e.target.value))} /></Field>
        </div>
        <label className="check"><input type="checkbox" checked={f.requires_approval} onChange={(e) => set("requires_approval", e.target.checked)} />결과물 확정에 사용자 승인 필요</label>
        <label className="check"><input type="checkbox" checked={f.requires_materials} onChange={(e) => set("requires_materials", e.target.checked)} />자료가 없으면 지어내지 않고 자료를 요청</label>
        <label className="check"><input type="checkbox" checked={f.allow_agents} onChange={(e) => set("allow_agents", e.target.checked)} />기존 에이전트 토론 결과를 근거로 사용 허용 (새 토론은 시작하지 않음)</label>
      </FormSection>
      <FormSection title="도구와 보고서">
        <div><h4 style={{ marginTop: 0 }}>이 업무에서 쓸 도구</h4><ToolPicker opts={opts} level={worker.permission_level} value={f.tools} onChange={(v) => set("tools", v)} within={worker.allowed_tools} /></div>
        <div className="grid g4">
          <Field label="보고서 종류"><select value={f.report_kind} onChange={(e) => set("report_kind", e.target.value)}><option value="generic">일반 문서</option><option value="news">뉴스 조사 보고서 (코드가 출처·날짜·검증 상태 기록)</option>{worker.permission_level === "developer" && <option value="dev">개발 업무 (분석 → 수정 → 테스트 반복, 코드가 변경·테스트 결과 기록)</option>}</select></Field>
          <Field label="도구 호출 상한(건)"><input type="number" min={1} max={30} value={f.max_tool_calls} onChange={(e) => set("max_tool_calls", Number(e.target.value))} /></Field>
          <Field label="도구 계획 라운드"><input type="number" min={1} max={3} value={f.tool_rounds} onChange={(e) => set("tool_rounds", Number(e.target.value))} /></Field>
          {f.report_kind === "dev" && (
            <div className="stack tight" style={{ gridColumn: "1 / -1" }}>
              <label className="check"><input type="checkbox" checked={f.require_changes} onChange={(e) => set("require_changes", e.target.checked)} /><span>코드 변경이 반드시 있어야 완료<div className="small muted">변경이 없으면 &apos;코드 변경 실패&apos;로 기록합니다.</div></span></label>
              <label className="check"><input type="checkbox" checked={f.require_tests} onChange={(e) => set("require_tests", e.target.checked)} /><span>마지막 변경 이후 테스트 통과가 반드시 있어야 완료<div className="small muted">끄더라도 코드를 바꿨고 테스트 프로파일이 있으면 통과해야 완료됩니다. 테스트가 실패하면 &apos;테스트 실패&apos;로 기록되며 성공으로 보고되지 않습니다.</div></span></label>
              <Field label="반드시 끝까지 읽을 파일 (프로젝트 기준 상대 경로, 한 줄에 하나)" hint="모델이 이 파일들을 줄 범위를 이어서 끝까지 읽기 전에는 완료할 수 없습니다. 큰 코드베이스에서 일부만 읽고 결론 내리는 것을 막습니다.">
                <textarea rows={3} value={f.required_reads} onChange={(e) => set("required_reads", e.target.value)} placeholder="lib/utils/target_octane_calculator.dart" />
              </Field>
              <Field label="최소로 읽어야 하는 파일 수" hint="코드를 바꾸지 않는 분석 업무는 기본적으로 1개 이상 읽어야 하고, 이 값으로 더 높일 수 있습니다."><input type="number" min={0} value={f.min_files_read} onChange={(e) => set("min_files_read", e.target.value)} /></Field>
              <div className="small muted">도구 호출 상한은 이 업무의 턴 수 상한으로 쓰입니다. 비용 한도의 약 65% 를 넘으면 보고서 작성을 위해 작업을 멈춥니다.</div>
            </div>
          )}
          {f.report_kind === "news" && <Field label="기사 최대 연령(시간)"><input type="number" value={f.max_age_hours} placeholder="48" onChange={(e) => set("max_age_hours", e.target.value)} /></Field>}
        </div>
      </FormSection>
      <FormSection title="제공 자료">
        <div className="stack tight">
          {f.materials.map((m, i) => (
            <div key={i} className="card flat stack tight">
              <div className="row"><input className="grow" value={m.name} placeholder="자료 이름 (예: devlog.md)" aria-label="자료 이름" onChange={(e) => set("materials", f.materials.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))} />
                <button type="button" className="ghost" onClick={() => set("materials", f.materials.filter((_, j) => j !== i))} aria-label="자료 삭제">✕</button></div>
              <textarea rows={4} value={m.content} placeholder="자료 내용" aria-label="자료 내용" onChange={(e) => set("materials", f.materials.map((x, j) => (j === i ? { ...x, content: e.target.value } : x)))} />
            </div>
          ))}
          <div><button type="button" className="secondary sm" onClick={() => set("materials", [...f.materials, { name: "", content: "" }])}>＋ 자료 추가</button></div>
        </div>
        <Field label="작업 공간 입력 파일 이름 (쉼표로 구분)"><input value={f.input_files} onChange={(e) => set("input_files", e.target.value)} placeholder="입력 파일 탭에 올린 파일: devlog.md" /></Field>
      </FormSection>
    </CrudDialog>
  );
}
/** 개발 업무가 프로젝트 파일에 적용한 변경(변경 전후 해시와 diff). 변경이 없으면 아무것도 그리지 않는다. */
function RunChanges({ runId, version }: { runId: number; version: number }) {
  const q = useApi<ProjectChangeRow[]>(`/projects/changes?run_id=${runId}`, version);
  const rows = q.data ?? [];
  if (rows.length === 0) return null;
  return (
    <Collapse title={`프로젝트 파일 변경 ${rows.length}건`} aside={`+${rows.reduce((s, c) => s + c.added_lines, 0)} / -${rows.reduce((s, c) => s + c.removed_lines, 0)}`} open>
      {[...rows].reverse().map((c) => (
        <Collapse key={c.id} title={<span className="small"><code>{c.path}</code> · {c.action === "create" ? "새 파일" : "수정"} ({c.tool}) · +{c.added_lines}/-{c.removed_lines}</span>}>
          <pre style={{ maxHeight: 300, overflow: "auto" }}>{c.diff || "(diff 없음)"}</pre>
          <div className="small muted">sha256 {c.before_sha256 ? c.before_sha256.slice(0, 10) : "(신규)"} → {c.after_sha256.slice(0, 10)}</div>
        </Collapse>
      ))}
      <div className="small muted">변경은 이미 프로젝트 파일에 적용되어 있습니다. 되돌리려면 변경 전 내용(프로젝트 화면의 변경 기록)을 참고하세요.</div>
    </Collapse>
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
      <RunChanges runId={r.id} version={version} />
      <Collapse title="실행 단계" aside={`${r.steps?.length ?? 0}건 (권한·예산·도구·LLM·검증)`}><pre>{JSON.stringify(r.steps, null, 2)}</pre></Collapse>
      <ConfirmDialog open={ask !== null} danger={ask !== "approve"} confirmLabel={ask === "approve" ? "승인" : ask === "reject" ? "반려" : "취소 실행"}
        title={ask === "approve" ? "결과물을 승인할까요?" : ask === "reject" ? "결과물을 반려할까요?" : "실행을 취소할까요?"}
        message={ask === "approve" ? "승인하면 이 결과물이 ‘완료’로 확정됩니다." : ask === "reject" ? "반려하면 이 실행은 종료되고 결과물은 확정되지 않습니다." : "진행 중인 실행을 중단합니다."}
        onCancel={() => setAsk(null)} onConfirm={decide} />
    </div>
  );
}
