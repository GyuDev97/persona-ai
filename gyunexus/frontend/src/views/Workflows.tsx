import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { api, useApi, type ArtifactDetailT, type LineageNode, type WorkerDetailT, type WorkerRow, type WorkflowDetailT, type WorkflowOptions, type WorkflowRow, type WorkflowStepT } from "../api";
import type { Nav } from "../App";
import { MarkdownPane } from "../components/Markdown";
import { CrudDialog } from "../components/crud/CrudDialog";
import { DeleteConfirmDialog } from "../components/crud/DeleteConfirmDialog";
import { useCrudForm } from "../components/crud/useCrudForm";
import { Async, Collapse, EmptyState, Field, fmtAgo, fmtTime, MasterDetail, Modal, PageHeader, STATUS, StatusBadge } from "../components/ui";

const ERR: Record<string, string> = {
  llm_error: "LLM 호출 실패", timeout: "제한 시간 초과", verification_failed: "결과물 검증 실패", no_input: "필요한 자료 없음", interrupted: "서버 재시작으로 중단",
  rejected: "승인 반려", cancelled: "취소됨", workflow_budget: "워크플로 예산 초과(시작 전 차단)", input_unavailable: "선행 결과물을 입력으로 연결할 수 없음",
  budget_exceeded: "업무 예산 초과", daily_budget: "오늘 자율 예산 소진", disabled: "직원·업무 비활성화", internal: "내부 오류", artifact_changed: "입력 결과물이 변경됨",
};
const usd = (n: number) => `$${n.toFixed(4)}`;
const fmtMax = (n: number) => (Number.isInteger(n) ? n.toFixed(1) : String(n));
const STATUS_KO: Record<string, string> = { planned: "계획 확인 대기", running: "실행 중", paused: "일시정지", failed: "실패", completed: "완료", cancelled: "취소" };

/** 서버(workflows.py `_budget`, `_check_budget`)와 같은 규칙: 숫자, 0 초과, 상한 이하(USD), 그리고 이미 사용한 비용 + 남은 단계 상한 이상. */
export function budgetError(raw: string | number, max: number, min?: number): string | null {
  const v = typeof raw === "number" ? raw : raw.trim() === "" ? NaN : Number(raw);
  if (!Number.isFinite(v) || v <= 0 || v > max) return `예산은 0 초과 ${fmtMax(max)} 이하(USD)여야 합니다`;
  if (min !== undefined && v < min - 1e-9) return `예산 ${usd(v)}은 이미 사용한 비용과 남은 단계 상한의 합 ${usd(min)}보다 작아 남은 단계를 실행할 수 없습니다(최소 ${usd(min)})`;
  return null;
}

export default function Workflows({ version, nav }: { version: number; nav: Nav }) {
  const list = useApi<WorkflowRow[]>("/workflows", version);
  const [sel, setSel] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const opts = useApi<WorkflowOptions>("/workflows/options", 0);
  useEffect(() => {
    if (sel === null && list.data?.length && window.matchMedia("(min-width: 901px)").matches) setSel(list.data[0].id);
  }, [list.data, sel]);

  return (
    <div className="page-inner fill">
      <PageHeader title="워크플로" desc="하나의 목표를 여러 AI 직원이 나눠 수행합니다. 계획을 확인·수정한 뒤 실행하며, 승인이 필요한 단계는 승인 전에 다음 단계로 넘어가지 않습니다."
        actions={<button onClick={() => setCreating(true)}>＋ 새 워크플로</button>} />
      <Async q={list}>
        {(rows) => rows.length === 0 ? (
          <div className="card"><EmptyState title="아직 워크플로가 없습니다" desc="목표를 자연어로 입력하면 등록된 직원·업무로 실행 계획을 만들어 줍니다. 직원 화면에서 직원과 업무를 먼저 등록하세요."
            action={<button onClick={() => setCreating(true)}>＋ 새 워크플로</button>} /></div>
        ) : (
          <MasterDetail hasDetail={sel !== null}
            list={rows.map((w) => (
              <button key={w.id} className={`sel-item ${sel === w.id ? "active" : ""}`} onClick={() => setSel(w.id)}>
                <div className="row between"><span className="t">{w.title || w.goal}</span><StatusBadge status={w.status} /></div>
                <div className="small muted">{w.done_count ?? 0}/{w.step_count ?? 0}단계 완료{w.awaiting_approval ? ` · 승인 대기 ${w.awaiting_approval}` : ""} · {usd(w.cost_usd)} / {usd(w.budget_usd)}</div>
                <div className="small muted">{fmtAgo(w.created_at)}</div>
              </button>
            ))}
            detail={sel !== null ? <WorkflowView key={sel} id={sel} version={version} nav={nav} maxBudget={opts.data?.max_budget_usd ?? 5} onBack={() => setSel(null)} onChanged={list.reload} /> : null} />
        )}
      </Async>
      {creating && <NewModal maxBudget={opts.data?.max_budget_usd ?? 5} defaultBudget={opts.data?.default_budget_usd ?? 0.5} onClose={() => setCreating(false)} onCreated={(id) => (setCreating(false), list.reload(), setSel(id))} />}
    </div>
  );
}

function NewModal({ maxBudget, defaultBudget, onClose, onCreated }: { maxBudget: number; defaultBudget: number; onClose: () => void; onCreated: (id: number) => void }) {
  const form = useCrudForm({ goal: "", budget: String(defaultBudget), auto: false }, (v) => ({
    goal: v.goal.trim().length >= 3 ? undefined : "목표를 3자 이상 입력하세요",
    budget: budgetError(v.budget, maxBudget) ?? undefined,
  }));
  const f = form.values;
  return (
    <CrudDialog mode="create" title="새 워크플로" submitLabel="계획 생성" busyLabel="계획 생성 중…" dirty={form.dirty} validate={form.check} onClose={onClose}
      onSubmit={async () => { const wf = await api<WorkflowDetailT>("/workflows", { method: "POST", json: { goal: f.goal, budget_usd: Number(f.budget), auto_run: f.auto } }); onCreated(wf.id); }}>
      <Field label="목표" required error={form.errorOf("goal")} hint="예: 최근 IT·AI 뉴스를 조사하고, 개발자에게 의미 있는 기사 한 건을 골라 기술 블로그 초안을 써 줘"><textarea rows={4} value={f.goal} aria-invalid={!!form.errorOf("goal")} onBlur={() => form.touch("goal")} onChange={(e) => form.set("goal", e.target.value)} /></Field>
      <Field label="총 예산(USD)" error={form.errorOf("budget")} hint={`계획 생성과 모든 단계 실행의 합계 상한입니다(최대 ${fmtMax(maxBudget)}). 단계 상한의 합이 예산을 넘는 계획은 시작 전에 차단됩니다.`}><input type="number" min={0} max={maxBudget} step={0.05} value={f.budget} aria-invalid={!!form.errorOf("budget")} onBlur={() => form.touch("budget")} onChange={(e) => form.set("budget", e.target.value)} /></Field>
      <div className={f.auto ? "danger-zone" : "card flat"}>
        <label className="check"><input type="checkbox" checked={f.auto} onChange={(e) => form.set("auto", e.target.checked)} /><span>계획 확인 없이 자동 실행 허용<div className="small muted">체크하지 않으면 계획을 확인·수정한 뒤 직접 실행합니다. 체크해도 승인이 필요한 단계는 승인 전에 멈추고, 각 직원의 도구 권한과 비용 한도는 그대로 적용됩니다.</div></span></label>
      </div>
    </CrudDialog>
  );
}
function WorkflowView({ id, version, nav, maxBudget, onBack, onChanged }: { id: number; version: number; nav: Nav; maxBudget: number; onBack: () => void; onChanged: () => void }) {
  const q = useApi<WorkflowDetailT>(`/workflows/${id}`, version);
  const [selKey, setSelKey] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [budgetOpen, setBudgetOpen] = useState(false);
  const [artifact, setArtifact] = useState<number | null>(null);
  const [confirm, setConfirm] = useState<null | "cancel">(null);
  const [error, setError] = useState<string | null>(null);
  const wf = q.data;
  const [busy, setBusy] = useState(false);
  const act = async (path: string, json?: unknown) => {
    setBusy(true);
    try {
      await api(`/workflows/${id}/${path}`, { method: "POST", json });
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    setBusy(false);
    q.reload();
    onChanged();
  };
  if (!wf) return <Async q={q}>{() => null}</Async>;
  const step = wf.steps.find((s) => s.key === selKey) ?? null;
  const pct = Math.min(100, (wf.cost_usd / Math.max(wf.budget_usd, 0.0001)) * 100);
  const done = wf.counts.completed ?? 0;

  return (
    <div className="stack">
      <div className="card">
        <div className="row between wrap">
          <div className="row wrap"><button className="ghost back-btn" onClick={onBack}>← 목록</button><h2>{wf.title || "워크플로"}</h2><StatusBadge status={wf.status} />{wf.auto_run && <span className="badge plain warn">자동 실행 허용</span>}</div>
          <div className="row wrap">
            {wf.status === "planned" && <><button className="secondary" onClick={() => setEditing(true)}>계획 수정</button><button onClick={() => act("start")} disabled={busy || wf.steps.length === 0 || wf.plan_state !== "ok" || wf.start_check?.ok === false}>실행</button></>}
            {wf.status === "running" && <button className="secondary" onClick={() => act("pause")}>일시정지</button>}
            {(wf.status === "paused" || wf.status === "failed") && <><button className="secondary" onClick={() => setEditing(true)}>계획 수정</button><button onClick={() => act("resume")}>재개</button></>}
            {["planned", "running", "paused", "failed"].includes(wf.status) && <button className="danger" onClick={() => setConfirm("cancel")}>취소</button>}
          </div>
        </div>
        <p className="muted" style={{ margin: "6px 0" }}>{wf.goal}</p>
        <div className="row wrap small muted">
          <span>{done}/{wf.steps.length}단계 완료</span><span>· 비용 {usd(wf.cost_usd)} / 예산 {usd(wf.budget_usd)} (계획 생성 {usd(wf.planning_cost_usd)}{wf.budget_info.removed_steps_usd > 0 ? `, 삭제된 단계 ${usd(wf.budget_info.removed_steps_usd)}` : ""})</span><span>· 계획 v{wf.plan_version}</span><span>· 생성 {fmtTime(wf.created_at)}</span>
        </div>
        {wf.budget_info.editable && <div style={{ marginTop: 6 }}><button className="secondary sm" onClick={() => setBudgetOpen(true)}>예산 변경</button></div>}
        <div className={`meter ${pct > 90 ? "bad" : pct > 70 ? "warn" : ""}`} style={{ marginTop: 8 }} role="img" aria-label={`예산 ${Math.round(pct)}% 사용`}><i style={{ width: `${pct}%` }} /></div>
      </div>
      {error && <div className="notice bad" onClick={() => setError(null)}>{error}</div>}
      {wf.error && <div className="notice bad">{wf.error}</div>}
      {wf.start_check && !wf.start_check.ok && (
        <div className="notice bad">계획은 유효하지만 현재 예산 {usd(wf.budget_usd)}으로는 시작할 수 없습니다. {wf.start_check.error}{wf.start_check.kind === "budget" && wf.budget_info.editable && <> <button className="link" onClick={() => setBudgetOpen(true)}>예산 변경</button></>}</div>
      )}
      {wf.plan_notes && <Collapse title="플래너 설명" open={wf.steps.length === 0}><p style={{ whiteSpace: "pre-wrap" }} className="muted">{wf.plan_notes}</p></Collapse>}
      {wf.counts.awaiting_approval > 0 && <div className="notice">승인 대기 {wf.counts.awaiting_approval}건 — 승인하면 다음 단계가 자동으로 이어집니다. <button className="link" onClick={() => nav.go("approvals")}>승인 화면으로</button></div>}

      {wf.steps.length === 0 ? (wf.plan_failure ? <PlanFailureCard wf={wf} busy={busy} onReplan={(regenerate) => act("replan", { regenerate })} onEdit={() => setEditing(true)} onBudget={() => setBudgetOpen(true)} /> : <div className="card"><EmptyState title="실행 가능한 단계가 없습니다" desc="플래너가 유효한 계획을 만들지 못했습니다. 계획 수정에서 직접 단계를 추가하거나 목표를 바꿔 새로 만드세요." action={<button onClick={() => setEditing(true)}>계획 수정</button>} /></div>) : (
        <div className="card"><div className="card-title"><h3>실행 계획</h3><span className="small muted">단계를 누르면 아래에 상세가 열리고 연결선이 강조됩니다</span></div>
          <Dag steps={wf.steps} selected={selKey} onSelect={setSelKey} /></div>
      )}

      {wf.plan_attempts.length > 0 && (
        <Collapse title="계획 생성 이력" aside={`${wf.plan_attempts.length}건`} open={wf.plan_failure !== null}>
          {wf.plan_attempts.map((a) => (
            <div key={a.id} className="item small">
              <b>{PLAN_ATTEMPT_LABEL[a.kind] ?? a.kind}</b> <span className={a.status === "succeeded" ? "ok" : "muted"}>{a.status === "succeeded" ? `성공(${a.step_count}단계)` : "실패"}</span>
              <span className="muted"> · 당시 예산 {usd(a.budget_usd)} · {a.cost_usd > 0 ? `계획 비용 ${usd(a.cost_usd)}` : "LLM 호출 없음"} · {fmtTime(a.created_at)}</span>
              {a.error && <div className="muted" style={{ whiteSpace: "pre-wrap" }}>{a.error}</div>}
            </div>
          ))}
          <div className="small muted">실패 기록은 계획이 복구된 뒤에도 이력으로 남습니다.</div>
        </Collapse>
      )}

      {step && <StepPanel wf={wf} step={step} nav={nav} onOpenArtifact={setArtifact} onRetry={() => act(`steps/${step.key}/retry`)} />}

      {budgetOpen && <BudgetModal wf={wf} maxBudget={maxBudget} onClose={() => setBudgetOpen(false)} onSaved={() => (setBudgetOpen(false), q.reload(), onChanged())} />}
      {editing && <PlanEditor wf={wf} maxBudget={maxBudget} onClose={() => setEditing(false)} onSaved={() => (setEditing(false), q.reload(), onChanged())} />}
      {artifact !== null && <ArtifactModal id={artifact} onClose={() => setArtifact(null)} onOpen={setArtifact} />}
      <DeleteConfirmDialog open={confirm === "cancel"} title="워크플로를 취소할까요?" itemName={wf.title || wf.goal} action="워크플로 취소" confirmLabel="취소 실행"
        impact={["진행 중인 단계는 중단됩니다", "승인 대기 중인 요청은 반려 처리됩니다", "이미 완료된 결과물은 유지됩니다"]}
        onCancel={() => setConfirm(null)} onConfirm={async () => { setConfirm(null); await act("cancel"); }} />
    </div>
  );
}

const PLAN_ATTEMPT_LABEL: Record<string, string> = { initial: "최초 계획 생성", auto: "예산 증액 후 자동 재검증", revalidate: "저장된 제안 재검증", replan: "계획 다시 생성", manual: "직접 계획 저장" };

/** 계획 생성 자체가 실패해 단계가 없는 상태. 과거 실패(예산이 이후 늘어난 경우)와 현재 실패를 구분해 보여 주고, 복구 수단을 준다. */
function PlanFailureCard({ wf, busy, onReplan, onEdit, onBudget }: { wf: WorkflowDetailT; busy: boolean; onReplan: (regenerate: boolean) => void; onEdit: () => void; onBudget: () => void }) {
  const f = wf.plan_failure!;
  const budgetCause = f.kind === "budget";
  return (
    <div className="card stack">
      <div className="card-title"><h3>계획 생성에 실패했습니다</h3><span className="badge plain bad">단계 없음</span></div>
      {f.stale_budget ? (
        <div className="notice">
          이전 시도(예산 {usd(f.budget_at_failure_usd ?? 0)})에서 예산이 부족해 실패했습니다. 이후 예산이 {usd(wf.budget_usd)}으로 늘었으므로 지금 다시 만들 수 있습니다.
          <div className="small muted" style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>당시 오류: {f.message}</div>
        </div>
      ) : (
        <div className="notice bad" style={{ whiteSpace: "pre-wrap" }}>{f.message}{budgetCause && <div className="small">현재 저장된 예산은 {usd(wf.budget_usd)}입니다.</div>}</div>
      )}
      {!budgetCause && <div className="small muted">예산 때문이 아닌 검증 오류라서 예산을 늘리는 것만으로는 해소되지 않습니다. 계획을 다시 만들거나 직접 단계를 추가하세요.</div>}
      <div className="row wrap">
        {f.has_proposal && <button disabled={busy} onClick={() => onReplan(false)}>{busy ? "처리 중…" : "저장된 제안 다시 검증(AI 호출 없음)"}</button>}
        <button className={f.has_proposal ? "secondary" : undefined} disabled={busy} onClick={() => onReplan(true)}>{busy ? "처리 중…" : "현재 예산으로 AI가 계획 다시 생성"}</button>
        {budgetCause && wf.budget_info.editable && <button className="secondary" onClick={onBudget}>예산 변경</button>}
        <button className="secondary" onClick={onEdit}>직접 단계 추가</button>
      </div>
      <div className="small muted">다시 만들어도 워크플로 ID·예산 변경 이력·계획 생성 비용(누적)은 유지되며, 자동으로 실행되지 않습니다. 실행 전 검증과 승인 규칙은 그대로 적용됩니다.</div>
    </div>
  );
}

/** 단계를 깊이(선행 수)별 열로 배치하고, 선행 -> 후속 연결선을 SVG 로 그린다. 같은 열의 단계는 병렬, 선행이 둘 이상인 단계는 합류로 표시한다. */
function Dag({ steps, selected, onSelect }: { steps: WorkflowStepT[]; selected: string | null; onSelect: (k: string) => void }) {
  const box = useRef<HTMLDivElement>(null);
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const [lines, setLines] = useState<{ d: string; key: string; from: string; to: string }[]>([]);
  const levels = Math.max(...steps.map((s) => s.level)) + 1;
  const cols = Array.from({ length: levels }, (_, l) => steps.filter((s) => s.level === l));
  const title = (k: string) => steps.find((x) => x.key === k)?.title ?? k;

  const measure = () => {
    const b = box.current?.getBoundingClientRect();
    if (!b) return;
    const out: { d: string; key: string; from: string; to: string }[] = [];
    for (const s of steps) {
      for (const d of s.depends_on) {
        const from = refs.current[d]?.getBoundingClientRect();
        const to = refs.current[s.key]?.getBoundingClientRect();
        if (!from || !to) continue;
        const x1 = from.right - b.left, y1 = from.top + from.height / 2 - b.top, x2 = to.left - b.left, y2 = to.top + to.height / 2 - b.top;
        const mx = (x1 + x2) / 2;
        out.push({ key: `${d}-${s.key}`, from: d, to: s.key, d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2 - 6},${y2}` });
      }
    }
    setLines(out);
  };
  useLayoutEffect(() => {
    measure();
    const ro = new ResizeObserver(measure);
    if (box.current) ro.observe(box.current);
    window.addEventListener("resize", measure);
    return () => { ro.disconnect(); window.removeEventListener("resize", measure); };
  }, [steps]);  // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="dag-scroll">
      <div ref={box} className="dag" style={{ gridTemplateColumns: `repeat(${levels}, minmax(210px, 1fr))`, minWidth: levels * 254 }}>
        <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", overflow: "visible" }} aria-hidden>
          <defs>
            <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#8fa2c2" /></marker>
            <marker id="arrow-hl" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="#1677ff" /></marker>
          </defs>
          {lines.map((l) => { const hl = selected !== null && (l.from === selected || l.to === selected); return <path key={l.key} d={l.d} className={`dag-edge ${hl ? "hl" : ""}`} markerEnd={hl ? "url(#arrow-hl)" : "url(#arrow)"} />; })}
        </svg>
        {cols.map((col, i) => (
          <div key={i} className="dag-col">
            <div className="dag-label">{i === 0 ? "시작 단계" : `${i + 1}번째 층`}{col.length > 1 && <span className="muted"> · 병렬 {col.length}개</span>}</div>
            {col.map((s) => {
              const tone = STATUS[s.status]?.[1] ?? "muted";
              return (
                <button key={s.key} ref={(el) => { refs.current[s.key] = el; }} className={`dag-node t-${tone} ${selected === s.key ? "active" : ""}`} aria-pressed={selected === s.key} onClick={() => onSelect(s.key)}>
                  <div className="row between"><b className="t">{s.title}</b><StatusBadge status={s.status} /></div>
                  <div className="dag-meta"><span>👤 {s.worker_name}</span><span>{s.task_title}</span></div>
                  <div className="dag-meta"><span>{s.depends_on.length ? `← ${s.depends_on.map(title).join(", ")}` : "선행 없음"}</span><span>{usd(s.cost_usd)}</span></div>
                  <div className="dag-tags">
                    {s.requires_approval && <span className="dag-tag warn">승인 필요</span>}
                    {s.depends_on.length > 1 && <span className="dag-tag violet">합류 {s.depends_on.length}</span>}
                    {s.status === "awaiting_approval" && <span className="dag-tag warn">승인 대기 중</span>}
                    {!s.worker_enabled && <span className="dag-tag bad">직원 비활성</span>}
                  </div>
                  {s.status === "awaiting_approval" && <div className="small" style={{ color: "var(--warn)", marginTop: 4 }}>승인 전에는 다음 단계가 시작되지 않습니다</div>}
                  {s.error_kind && <div className="small" style={{ color: "var(--bad)", marginTop: 4 }}>{ERR[s.error_kind] ?? s.error_kind}</div>}
                </button>
              );
            })}
          </div>
        ))}
      </div>
      <div className="dag-legend"><span>→ 선행에서 후속으로 이어지며 선행 결과물이 후속 단계의 입력이 됩니다</span><span>같은 층의 단계는 병렬 실행</span><span>왼쪽 띠 색: 초록 완료 · 파랑 실행 중 · 노랑 대기 · 빨강 실패</span></div>
    </div>
  );
}
function StepPanel({ wf, step, nav, onOpenArtifact, onRetry }: { wf: WorkflowDetailT; step: WorkflowStepT; nav: Nav; onOpenArtifact: (id: number) => void; onRetry: () => void }) {
  const deps = step.depends_on.map((k) => wf.steps.find((s) => s.key === k)?.title ?? k);
  return (
    <div className="card stack">
      <div className="row between wrap"><h3>{step.title} <StatusBadge status={step.status} /></h3>
        <div className="row wrap">
          {(step.status === "failed" || step.status === "cancelled") && wf.status !== "cancelled" && wf.status !== "completed" && <button onClick={onRetry}>이 단계만 다시 실행</button>}
          {step.status === "awaiting_approval" && <button onClick={() => nav.go("approvals")}>승인하러 가기</button>}
          <button className="secondary" onClick={() => nav.go("workers")}>직원 화면에서 실행 이력</button>
        </div></div>
      {step.error && <div className={step.status === "failed" ? "notice bad" : "notice"}>{ERR[step.error_kind ?? ""] ?? step.error_kind}: {step.error}</div>}
      <dl className="kv">
        <dt>담당 직원</dt><dd>{step.worker_name}{!step.worker_enabled && <span className="badge plain bad" style={{ marginLeft: 6 }}>비활성</span>}</dd>
        <dt>업무</dt><dd>{step.task_title}{step.requires_approval && <span className="badge plain warn" style={{ marginLeft: 6 }}>승인 필요</span>}</dd>
        <dt>사용 모델</dt><dd>{step.model || "-"}</dd>
        <dt>선행 단계</dt><dd>{deps.length ? deps.join(", ") : "없음"}</dd>
        <dt>시도 / 비용</dt><dd>{step.attempts}회 · {usd(step.cost_usd)}{step.run ? ` · LLM ${step.run.llm_calls}회 · 실행 #${step.run.id}` : ""}</dd>
        <dt>시간</dt><dd>{fmtTime(step.started_at)} ~ {fmtTime(step.ended_at)}</dd>
        {step.reason && <><dt>선택 이유</dt><dd>{step.reason}</dd></>}
      </dl>
      {step.directive && <Collapse title="이 단계의 지시"><p style={{ whiteSpace: "pre-wrap" }}>{step.directive}</p></Collapse>}
      <div>
        <h4>입력 결과물 (선행 단계에서 자동 연결, 고정 해시 참조)</h4>
        {step.inputs.length === 0 ? <div className="muted small">없음</div> : <div className="row wrap">{step.inputs.map((i) => (
          <button key={i.artifact_id} className="secondary sm" onClick={() => onOpenArtifact(i.artifact_id)} title={`sha256 ${i.sha256}`}>#{i.artifact_id} v{i.version} · {i.filename} · {i.sha256.slice(0, 8)}</button>))}</div>}
        <h4>출력 결과물</h4>
        {step.artifact ? <div className="row wrap"><button className="secondary sm" onClick={() => onOpenArtifact(step.artifact!.id)}>#{step.artifact.id} · {step.artifact.title || step.artifact.filename}</button>
          <StatusBadge status={step.artifact.verified ? "completed" : "failed"} label={step.artifact.verified ? "검증됨" : "검증 실패"} />{step.status === "awaiting_approval" && <span className="small muted">승인 전에는 다른 단계의 입력으로 쓰이지 않습니다</span>}</div> : <div className="muted small">아직 없음</div>}
      </div>
    </div>
  );
}

function LineageTree({ node, depth = 0 }: { node: LineageNode; depth?: number }) {
  return (
    <div style={{ marginLeft: depth * 16 }}>
      <div className="small"><b>#{node.artifact_id}</b> {node.worker} · {node.task} <span className="muted">(실행 #{node.run_id}, {node.run_status}, {node.sha256.slice(0, 8)})</span></div>
      {node.inputs.map((i) => (i.upstream ? <LineageTree key={i.artifact_id} node={i.upstream} depth={depth + 1} /> : <div key={i.artifact_id} className="small muted" style={{ marginLeft: (depth + 1) * 16 }}>#{i.artifact_id} (이미 표시됨)</div>))}
    </div>
  );
}

function ArtifactModal({ id, onClose, onOpen }: { id: number; onClose: () => void; onOpen: (id: number) => void }) {
  const art = useApi<ArtifactDetailT>(`/artifacts/${id}`, 0);
  const lin = useApi<LineageNode>(`/artifacts/${id}/lineage`, 0);
  void onOpen;
  return (
    <Modal open size="wide" title={`결과물 #${id}`} onClose={onClose}>
      <Async q={art}>
        {(a) => (
          <div className="stack">
            <div className="row wrap small muted"><b>{a.filename}</b><span>v{a.version}</span><span>{a.size}B</span><span>sha256 {a.sha256.slice(0, 16)}…</span><StatusBadge status={a.verified ? "completed" : "failed"} label={a.verified ? "검증됨" : "미검증"} /></div>
            {a.content == null ? <div className="muted">내용을 읽을 수 없습니다.</div> : a.filename.endsWith(".md") ? <MarkdownPane source={a.content} /> : <pre>{a.content}</pre>}
            <Collapse title="입력 자료 계보(어떤 결과물을 바탕으로 만들어졌는가)" open>
              {lin.data ? <LineageTree node={lin.data} /> : <span className="muted small">불러오는 중…</span>}
              {lin.data && lin.data.inputs.length === 0 && <div className="small muted">선행 결과물 없이 만들어진 결과물입니다.</div>}
            </Collapse>
          </div>
        )}
      </Async>
    </Modal>
  );
}

interface EditStep { key: string; title: string; worker_id: number; task_id: number; depends_on: string[]; directive: string; reason: string; locked: boolean; status?: string }

function PlanEditor({ wf, maxBudget, onClose, onSaved }: { wf: WorkflowDetailT; maxBudget: number; onClose: () => void; onSaved: () => void }) {
  const [budget, setBudget] = useState(String(wf.budget_usd));
  const [steps, setSteps] = useState<EditStep[]>(wf.steps.map((s) => ({ key: s.key, title: s.title, worker_id: s.worker_id, task_id: s.task_id, depends_on: s.depends_on, directive: s.directive, reason: s.reason,
    locked: ["running", "awaiting_approval", "completed"].includes(s.status), status: s.status })));
  const [workers, setWorkers] = useState<WorkerDetailT[]>([]);
  const [error, setError] = useState<string | null>(null);
  const base = useRef(JSON.stringify({ b: String(wf.budget_usd), s: steps }));
  const dirty = JSON.stringify({ b: budget, s: steps }) !== base.current;
  useEffect(() => {
    api<WorkerRow[]>("/workers").then((ws) => Promise.all(ws.filter((w) => w.enabled).map((w) => api<WorkerDetailT>(`/workers/${w.id}`)))).then(setWorkers).catch((e: Error) => setError(e.message));
  }, []);
  // 편집 중인 계획 기준의 최소 예산(서버 _projection 과 같은 규칙): 사용액 + 대기 단계 상한 + 실행 중 단계의 남은 상한
  const capOf = (s: EditStep) => {
    const w = workers.find((x) => x.id === s.worker_id);
    const t = w?.tasks.find((x) => x.id === s.task_id);
    return w && t ? Math.min(w.max_cost_usd, t.max_cost_usd) : null;
  };
  const minBudget = workers.length === 0 ? wf.budget_info.min_budget_usd : wf.budget_info.spent_usd + steps.reduce((sum, s) => {
    if (s.status && s.status !== "pending" && s.status !== "running") return sum;
    const cap = capOf(s);
    if (cap === null) return sum;
    return sum + (s.status === "running" ? Math.max(cap - (wf.steps.find((x) => x.key === s.key)?.cost_usd ?? 0), 0) : cap);
  }, 0);
  const budgetErr = budgetError(budget, maxBudget, minBudget);
  const budgetChanged = budgetErr === null && Math.abs(Number(budget) - wf.budget_usd) > 1e-9;
  const upd = (i: number, patch: Partial<EditStep>) => setSteps((p) => p.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const add = () => {
    let n = steps.length + 1;
    while (steps.some((s) => s.key === `s${n}`)) n++;
    const w = workers[0];
    setSteps((p) => [...p, { key: `s${n}`, title: "새 단계", worker_id: w?.id ?? 0, task_id: w?.tasks.find((t) => t.status === "active")?.id ?? 0, depends_on: [], directive: "", reason: "", locked: false }]);
  };
  const save = async () => {
    await api(`/workflows/${wf.id}/plan`, { method: "PUT", json: { steps: steps.map(({ locked, status, ...s }) => s), ...(budgetChanged ? { budget_usd: Number(budget) } : {}) } });
    onSaved();
  };
  return (
    <CrudDialog mode="update" size="wide" title="실행 계획 수정" dirty={dirty} disabled={steps.length === 0 || budgetErr !== null} onClose={onClose} onSubmit={save}>
      <div className="stack">
        <div className="card flat stack tight">
          <Field label="총 예산(USD)" error={budgetErr ?? undefined} hint={`사용 ${usd(wf.budget_info.spent_usd)} + 남은 단계 상한 ${usd(wf.budget_info.required_usd)} (편집 중인 계획 기준 최소 ${usd(minBudget)}, 최대 ${fmtMax(maxBudget)}). 저장할 때 서버가 같은 규칙으로 다시 검증합니다.`}>
            <input type="number" min={0} max={maxBudget} step={0.05} value={budget} aria-invalid={budgetErr !== null} onChange={(e) => setBudget(e.target.value)} style={budgetErr ? { borderColor: "var(--bad)" } : undefined} />
          </Field>
        </div>
        <p className="small muted">저장하면 서버가 직원·업무 존재와 소유 관계, 순환 의존성, 예산을 다시 검증합니다. 실행 중이거나 끝난 단계는 바꿀 수 없습니다.</p>
        {error && <div className="notice bad">{error}</div>}
        {steps.map((s, i) => {
          const w = workers.find((x) => x.id === s.worker_id);
          return (
            <div key={s.key} className="card flat stack tight">
              <div className="row between wrap"><b>{s.key}</b>{s.locked ? <span className="badge plain warn">{s.status === "completed" ? "완료됨(수정 불가)" : "진행 중(수정 불가)"}</span> : <button type="button" className="ghost sm" onClick={() => setSteps((p) => p.filter((_, j) => j !== i).map((x) => ({ ...x, depends_on: x.depends_on.filter((d) => d !== s.key) })))}>단계 삭제</button>}</div>
              <Field label="제목"><input value={s.title} disabled={s.locked} onChange={(e) => upd(i, { title: e.target.value })} /></Field>
              <div className="grid g2">
                <Field label="담당 직원"><select value={s.worker_id} disabled={s.locked} onChange={(e) => { const nw = workers.find((x) => x.id === Number(e.target.value)); upd(i, { worker_id: Number(e.target.value), task_id: nw?.tasks.find((t) => t.status === "active")?.id ?? 0 }); }}>
                  {workers.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
                <Field label="업무"><select value={s.task_id} disabled={s.locked} onChange={(e) => upd(i, { task_id: Number(e.target.value) })}>
                  {(w?.tasks ?? []).map((t) => <option key={t.id} value={t.id}>{t.title}{t.requires_approval ? " (승인 필요)" : ""}</option>)}</select></Field>
              </div>
              <Field label="이 단계의 지시"><textarea rows={3} value={s.directive} disabled={s.locked} onChange={(e) => upd(i, { directive: e.target.value })} /></Field>
              <div><div className="small muted">선행 단계 (결과물이 이 단계의 입력으로 전달됨)</div>
                <div className="row wrap">{steps.filter((o) => o.key !== s.key).map((o) => <label key={o.key} className="check"><input type="checkbox" disabled={s.locked} checked={s.depends_on.includes(o.key)}
                  onChange={(e) => upd(i, { depends_on: e.target.checked ? [...s.depends_on, o.key] : s.depends_on.filter((d) => d !== o.key) })} />{o.key}</label>)}
                  {steps.length < 2 && <span className="small muted">다른 단계가 없습니다</span>}</div></div>
            </div>
          );
        })}
        <div><button type="button" className="secondary" onClick={add} disabled={workers.length === 0}>＋ 단계 추가</button></div>
      </div>
    </CrudDialog>
  );
}

function BudgetModal({ wf, maxBudget, onClose, onSaved }: { wf: WorkflowDetailT; maxBudget: number; onClose: () => void; onSaved: () => void }) {
  const info = wf.budget_info;
  const form = useCrudForm({ value: String(wf.budget_usd) }, (v) => ({ value: budgetError(v.value, maxBudget, info.min_budget_usd) ?? undefined }));
  const value = form.values.value;
  const err = budgetError(value, maxBudget, info.min_budget_usd);
  const unchanged = err === null && Math.abs(Number(value) - wf.budget_usd) < 1e-9;
  return (
    <CrudDialog mode="update" title="총예산 변경" submitLabel="변경" dirty={form.dirty} validate={form.check} disabled={unchanged} onClose={onClose}
      onSubmit={async () => { await api(`/workflows/${wf.id}`, { method: "PUT", json: { budget_usd: Number(value) } }); onSaved(); }}>
      <div className="stack">
        <dl className="kv">
          <dt>현재 예산</dt><dd>{usd(wf.budget_usd)}</dd>
          <dt>이미 사용</dt><dd>{usd(info.spent_usd)} <span className="muted small">(계획 생성 {usd(wf.planning_cost_usd)} 포함{info.removed_steps_usd > 0 ? `, 계획에서 삭제된 단계 ${usd(info.removed_steps_usd)} 포함` : ""})</span></dd>
          <dt>남은 단계 상한</dt><dd>{usd(info.required_usd)} <span className="muted small">(대기·실행 중인 단계가 앞으로 쓸 수 있는 최대 비용)</span></dd>
          <dt>설정 가능 범위</dt><dd>{usd(info.min_budget_usd)} ~ ${fmtMax(maxBudget)} (USD)</dd>
        </dl>
        <Field label="새 총예산(USD)" error={form.errorOf("value")} hint={(wf.status === "planned" ? "실행 전이므로 자유롭게 바꿀 수 있습니다." : "실행 기록·승인 상태·결과물 참조·비용 기록은 그대로 유지되고, 남은 단계에 즉시 적용됩니다.")}>
          <input type="number" min={0} max={maxBudget} step={0.05} value={value} aria-invalid={err !== null} onChange={(e) => form.set("value", e.target.value)} onBlur={() => form.touch("value")} />
        </Field>
        {wf.removed_steps.length > 0 && (
          <Collapse title="계획에서 삭제된 단계의 비용(누적에 포함)" aside={usd(info.removed_steps_usd)}>
            {wf.removed_steps.map((r) => (
              <div key={r.step_id} className="item small">
                <b>{r.title ?? `삭제된 단계 #${r.step_id}`}</b> <span className="muted">{r.key ? `(${r.key})` : ""} · {usd(r.cost_usd)} · 실행 {r.runs.map((x) => `#${x.run_id}`).join(", ")}</span>
              </div>
            ))}
            <div className="small muted">삭제된 단계의 실행 이력과 결과물 계보는 직원 화면의 실행 이력과 결과물 보기에 그대로 남아 있습니다.</div>
          </Collapse>
        )}
        <Collapse title="예산 변경 이력" aside={`${wf.budget_history.length}건`} open={wf.budget_history.length > 0}>
          {wf.budget_history.length === 0 ? <div className="muted small">변경 이력이 없습니다.</div> : wf.budget_history.map((h) => (
            <div key={h.id} className="item small">
              <div><b>{usd(h.old_usd)} → {usd(h.new_usd)}</b> <span className="badge plain">{h.new_usd > h.old_usd ? "증액" : "감액"}</span> <span className="muted">{h.source === "plan" ? "계획 수정과 함께" : "예산 변경"}</span></div>
              <div className="muted">{fmtTime(h.created_at)} · {STATUS_KO[h.status] ?? h.status} · 당시 사용 {usd(h.spent_usd)}, 남은 단계 상한 {usd(h.required_usd)}</div>
            </div>
          ))}
        </Collapse>
      </div>
    </CrudDialog>
  );
}
