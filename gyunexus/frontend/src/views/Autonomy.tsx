import { useEffect, useRef, useState } from "react";
import { api, useApi, type AutonomyConfig, type AutonomyRunRow, type ExecMode, type TriggerKind, type TriggerRow } from "../api";
import type { Nav } from "../App";
import { describeTrigger, KIND_NAME, ModeBadge, ModeSelect, MODE_DESC, SKIP_NAME, WEEKDAYS } from "../components/autonomy";
import { CrudDialog } from "../components/crud/CrudDialog";
import { CrudList } from "../components/crud/CrudList";
import { DeleteConfirmDialog } from "../components/crud/DeleteConfirmDialog";
import { useCrudForm } from "../components/crud/useCrudForm";
import { Async, ConfirmDialog, EmptyState, Field, fmtAgo, Icon, fmtTime, PageHeader, SectionCard, StatusBadge, Tabs } from "../components/ui";

type Tab = "triggers" | "settings" | "history";
const usd = (n: number) => `$${n.toFixed(4)}`;

export default function Autonomy({ version, nav }: { version: number; nav: Nav }) {
  const cfg = useApi<AutonomyConfig>("/autonomy/settings", version);
  const triggers = useApi<TriggerRow[]>("/autonomy/triggers", version);
  const runs = useApi<AutonomyRunRow[]>("/autonomy/runs?limit=60", version);
  const [tab, setTab] = useState<Tab>("triggers");
  const [editing, setEditing] = useState<TriggerRow | "new" | null>(null);
  const [deleting, setDeleting] = useState<TriggerRow | null>(null);
  const [offAsk, setOffAsk] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const c = cfg.data;

  const save = async (body: Record<string, unknown>) => {
    try {
      await api("/autonomy/settings", { method: "PUT", json: body });
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    cfg.reload();
  };
  const [firing, setFiring] = useState<TriggerRow | null>(null); // 확인 대화상자의 대상
  const inflight = useRef(false);
  const [busyId, setBusyId] = useState<number | null>(null); // 발동 요청이 진행 중인 트리거(중복 클릭 방지)
  const [result, setResult] = useState<{ tone: "ok" | "warn" | "bad"; text: string; workflowId?: number } | null>(null);
  const fire = async (t: TriggerRow) => {
    if (inflight.current) return; // state 는 같은 틱의 연속 클릭에서 갱신되지 않으므로 ref 로 막는다
    inflight.current = true;
    setBusyId(t.id);
    setFiring(null);
    try {
      const r = await api<{ status: string; code?: string; message?: string; error?: string; workflow_id?: number }>(`/autonomy/triggers/${t.id}/fire`, { method: "POST" });
      setResult(r.status === "started" ? { tone: "ok", text: `'${t.name}'을(를) 시작했습니다. 워크플로 #${r.workflow_id}가 진행 중입니다.`, workflowId: r.workflow_id }
        : r.status === "blocked" ? { tone: "warn", text: `'${t.name}': 계획은 만들었지만 자동 실행이 허용되지 않아 사용자 확인을 기다립니다. 워크플로 #${r.workflow_id}에서 사유를 확인하세요.`, workflowId: r.workflow_id }
        : r.status === "failed" ? { tone: "bad", text: `'${t.name}' 계획 생성에 실패했습니다: ${r.error ?? ""}`, workflowId: r.workflow_id }
        : r.status === "duplicate" ? { tone: "warn", text: `'${t.name}': 같은 발동이 이미 처리되어 실행하지 않았습니다.` }
        : { tone: "bad", text: `'${t.name}'은(는) 실행되지 않았습니다 — ${SKIP_NAME[r.code ?? ""] ?? r.status}${r.message ? `: ${r.message}` : ""}` });
    } catch (e) {
      setResult({ tone: "bad", text: `'${t.name}' 발동 요청에 실패했습니다: ${(e as Error).message}` });
    }
    inflight.current = false;
    setBusyId(null);
    triggers.reload(); runs.reload();
  };
  const toggle = async (t: TriggerRow) => {
    try { await api(`/autonomy/triggers/${t.id}`, { method: "PUT", json: { enabled: !t.enabled } }); setError(null); } catch (e) { setError((e as Error).message); }
    triggers.reload();
  };
  const spentPct = c ? Math.min(100, (c.spent_today_usd / Math.max(c.daily_cost_cap_usd, 0.0001)) * 100) : 0;

  return (
    <div className="page-inner">
      <PageHeader title="자율 운영" desc="예약·이벤트·능동 제안·선행 업무 완료를 조건으로 AI 직원 워크플로를 자동으로 시작합니다. 모든 시작은 기존 워크플로 엔진과 같은 권한·승인·비용 규칙을 따르고, 시작 사유가 기록됩니다."
        actions={c && (
          <button className={c.enabled ? "secondary" : undefined} aria-pressed={c.enabled} onClick={() => (c.enabled ? setOffAsk(true) : save({ enabled: true }))}>
            <span className={`badge plain ${c.enabled ? "ok" : ""}`} style={{ padding: "0 6px", marginRight: 6 }}>{c.enabled ? "ON" : "OFF"}</span>상시 자율 운영
          </button>
        )} />
      {error && <div className="notice bad" onClick={() => setError(null)}>{error}</div>}
      {notice && <div className="notice" onClick={() => setNotice(null)}>{notice}</div>}
      {result && (
        <div className={`notice ${result.tone === "ok" ? "" : result.tone}`} role="status" aria-live="polite">
          <div className="row between wrap"><span>{result.text}</span>
            <span className="row">{result.workflowId && <button className="secondary sm" onClick={() => nav.openWorkflow(result.workflowId!)}>워크플로 보기</button>}<button className="ghost sm" onClick={() => setResult(null)} aria-label="알림 닫기">✕</button></span></div>
        </div>
      )}
      {c && !c.enabled && <div className="notice">상시 자율 운영이 꺼져 있습니다. 트리거는 등록할 수 있지만 켜기 전에는 어떤 것도 자동으로 시작되지 않습니다. (직접 요청한 워크플로·대화로 맡긴 목표는 이 스위치와 무관하게 모드 설정을 따릅니다)</div>}
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "triggers", label: "트리거", count: triggers.data?.length }, { id: "settings", label: "허용 범위·한도" }, { id: "history", label: "실행 기록", count: runs.data?.length }]} />

      {tab === "triggers" && (
        <SectionCard title="트리거" aside={<button onClick={() => setEditing("new")}>＋ 트리거 추가</button>}
          desc="조건이 맞으면 목표를 워크플로로 만들어 실행합니다. 같은 일정·이벤트·제안은 한 번만 처리되며, 쿨다운·동시 실행·비용 한도에 걸리면 이유와 함께 건너뜁니다.">
          <CrudList items={triggers.data} error={triggers.error} onRetry={triggers.reload} rowKey={(t) => t.id}
            empty={<EmptyState icon="autonomy" title="등록된 트리거가 없습니다" desc="예: 매일 아침 9시에 최근 개발 기록을 조사해 정리하기" action={<button onClick={() => setEditing("new")}>＋ 트리거 추가</button>} />}
            columns={[
              { key: "name", header: "이름", render: (t) => <><b>{t.name}</b><div className="small muted clamp2">{t.goal}</div></> },
              { key: "when", header: "조건", render: (t) => <><span className="badge plain">{KIND_NAME[t.kind]}</span><div className="small">{describeTrigger(t)}</div></> },
              { key: "mode", header: "모드", render: (t) => <ModeBadge mode={t.exec_mode} /> },
              { key: "next", header: "다음 실행", render: (t) => (t.next_fire_at ? fmtTime(t.next_fire_at) : <span className="muted">조건 대기</span>) },
              { key: "cost", header: "오늘 비용", render: (t) => <span className="small">{usd(t.spent_today_usd)} / {usd(t.daily_cost_cap_usd)}</span> },
              { key: "run", header: "수동 실행", render: (t) => <button className="secondary sm" disabled={busyId !== null} onClick={() => setFiring(t)} aria-label={`${t.name} 지금 실행`}><Icon name="play" size={14} />{busyId === t.id ? "실행 중…" : "지금 실행"}</button> },
              { key: "state", header: "상태", render: (t) => <><StatusBadge status={t.enabled ? "active" : "disabled"} />{t.live_workflows > 0 && <div className="small muted">진행 중 {t.live_workflows}건</div>}{t.last_run && <div className="small muted">{t.last_run.status === "skipped" ? `건너뜀: ${SKIP_NAME[t.last_run.skip_reason ?? ""] ?? t.last_run.skip_reason}` : `최근 ${fmtAgo(t.last_run.created_at)}`}</div>}</> },
            ]}
            actions={(t) => [
              { label: "수정", onClick: () => setEditing(t) },
              { label: t.enabled ? "비활성화" : "활성화", onClick: () => toggle(t) },
              { label: "삭제", danger: true, onClick: () => setDeleting(t) },
            ]} />
        </SectionCard>
      )}

      {tab === "settings" && (
        <Async q={cfg}>{(s) => <SettingsForm cfg={s} spentPct={spentPct} onSave={save} />}</Async>
      )}

      {tab === "history" && (
        <SectionCard title="최근 자율 실행 기록" desc="시작한 것뿐 아니라 건너뛴 것과 그 이유, 계획만 만들고 멈춘 것도 남습니다.">
          <CrudList items={runs.data} error={runs.error} onRetry={runs.reload} rowKey={(r) => r.id} pageSize={15} empty={<EmptyState title="아직 기록이 없습니다" />}
            columns={[
              { key: "t", header: "시각", render: (r) => <span className="small">{fmtTime(r.created_at)}</span> },
              { key: "trig", header: "트리거", render: (r) => r.trigger_name ?? `#${r.trigger_id}` },
              { key: "st", header: "결과", render: (r) => <><StatusBadge status={r.status} />{r.skip_reason && <div className="small muted">{SKIP_NAME[r.skip_reason] ?? r.skip_reason}</div>}</> },
              { key: "why", header: "시작 사유 / 상세", render: (r) => <><div className="small">{r.reason}</div>{(r.detail.message || r.detail.error || r.detail.reason) && <div className="small muted">{r.detail.message ?? r.detail.error ?? r.detail.reason}</div>}</> },
              { key: "wf", header: "워크플로", render: (r) => (r.workflow_id ? <button className="link" onClick={() => nav.go("workflows")}>#{r.workflow_id} {r.workflow_title ?? ""}{r.workflow_status ? ` (${r.workflow_status})` : ""}</button> : <span className="muted">-</span>) },
            ]} />
        </SectionCard>
      )}

      {editing && <TriggerDialog cfg={c} current={editing === "new" ? null : editing} others={triggers.data ?? []} onClose={() => setEditing(null)} onSaved={() => (setEditing(null), triggers.reload())} />}
      <DeleteConfirmDialog open={!!deleting} title="트리거를 삭제할까요?" itemName={deleting?.name ?? ""} action="트리거 삭제"
        impact={["더 이상 자동으로 시작되지 않습니다", "이미 시작된 워크플로와 실행 기록은 그대로 남습니다", "이 트리거 완료 후 실행되도록 연결된 트리거가 있으면 삭제할 수 없습니다"]}
        recovery={{ reversible: false, note: "삭제한 트리거 설정은 되돌릴 수 없습니다. 잠시 멈추려면 '비활성화'를 쓰세요." }} onCancel={() => setDeleting(null)}
        onConfirm={async () => { const t = deleting!; setDeleting(null); try { await api(`/autonomy/triggers/${t.id}`, { method: "DELETE" }); setError(null); } catch (e) { setError((e as Error).message); } triggers.reload(); }} />
      <ConfirmDialog open={!!firing} title="트리거를 지금 실행할까요?" confirmLabel="지금 실행" onCancel={() => setFiring(null)} onConfirm={() => firing && void fire(firing)}
        message={firing && (
          <div className="stack tight">
            <dl className="kv">
              <dt>트리거</dt><dd>{firing.name}</dd>
              <dt>목표</dt><dd style={{ whiteSpace: "pre-wrap" }}>{firing.goal}</dd>
              <dt>실행 모드</dt><dd><ModeBadge mode={firing.exec_mode} /> <span className="small muted">{MODE_DESC[firing.exec_mode]}</span></dd>
              <dt>비용 한도</dt><dd>실행 1회 예산 {usd(firing.budget_usd)} · 트리거 일일 한도 {usd(firing.daily_cost_cap_usd)}(오늘 {usd(firing.spent_today_usd)} 사용){c && <> · 전체 일일 한도 {usd(c.daily_cost_cap_usd)}(오늘 {usd(c.spent_today_usd)} 사용)</>}</dd>
            </dl>
            <div className="small muted">예약 일정과 같은 검사(전체 ON/OFF, 쿨다운, 중복, 동시 실행, 비용 한도)를 거치며, 막히면 사유를 알려 드립니다. 다음 예약 일정은 바뀌지 않습니다.{c && !c.enabled && <b style={{ color: "var(--warn)" }}> 현재 상시 자율 운영이 꺼져 있어 실행되지 않습니다.</b>}</div>
          </div>
        )} />
      <ConfirmDialog open={offAsk} title="상시 자율 운영을 끌까요?" confirmLabel="끄기" danger
        message="새 자동 시작과 자동 재시도가 멈추고, 트리거가 시작해 진행 중인 워크플로는 일시정지됩니다(재개는 직접 합니다). 이미 끝난 결과와 기록은 그대로입니다."
        onCancel={() => setOffAsk(false)} onConfirm={() => { setOffAsk(false); void save({ enabled: false }); }} />
    </div>
  );
}

function SettingsForm({ cfg, spentPct, onSave }: { cfg: AutonomyConfig; spentPct: number; onSave: (b: Record<string, unknown>) => Promise<void> }) {
  const [conc, setConc] = useState(String(cfg.max_concurrent));
  const [cap, setCap] = useState(String(cfg.daily_cost_cap_usd));
  useEffect(() => { setConc(String(cfg.max_concurrent)); setCap(String(cfg.daily_cost_cap_usd)); }, [cfg.max_concurrent, cfg.daily_cost_cap_usd]);
  const capOk = Number(cap) > 0 && Number(cap) <= 50;
  const concOk = Number.isInteger(Number(conc)) && Number(conc) >= 1 && Number(conc) <= 10;
  return (
    <div className="grid g2">
      <SectionCard title="자동 실행 허용 범위" desc="요청·트리거가 고를 수 있는 가장 높은 모드입니다. 이보다 높은 모드는 선택할 수 없고, 트리거는 이 범위로 낮춰서 실행됩니다.">
        <div className="stack">
          <Field label="허용하는 최대 모드" hint={MODE_DESC[cfg.max_mode]}>
            <ModeSelect value={cfg.max_mode} max="autonomous" onChange={(m: ExecMode) => m !== "manual" && onSave({ max_mode: m })} label="허용하는 최대 모드" />
          </Field>
          <label className="check"><input type="checkbox" checked={cfg.auto_approve} onChange={(e) => onSave({ auto_approve: e.target.checked })} /><span>정책을 통과한 결과물 자동 승인 허용<div className="small muted">자율 모드에서만 적용됩니다. 읽기 전용 직원의 검증 통과 결과물만 대상이며, 외부 발행·메시지 전송·파일 삭제·중요 데이터 수정·권한 변경, 쓰기 권한 직원, 검증 경고(자료 부족 등)는 항상 사용자 승인이 필요합니다. 자동 승인 기록은 승인 화면에 &apos;자동&apos;으로 구분됩니다.</div></span></label>
        </div>
      </SectionCard>
      <SectionCard title="비용·동시 실행 한도" desc="트리거가 시작한 워크플로에 적용됩니다. 워크플로별 예산과 직원·업무별 한도는 그대로 따로 적용됩니다.">
        <form className="stack" onSubmit={(e) => { e.preventDefault(); if (capOk && concOk) void onSave({ max_concurrent: Number(conc), daily_cost_cap_usd: Number(cap) }); }}>
          <Field label="하루 비용 한도(USD)" error={capOk ? undefined : "0 초과 50 이하로 입력하세요"} hint={`오늘 사용 ${usd(cfg.spent_today_usd)} (시작 전에 실행 예산을 미리 더해 한도를 넘지 않게 막습니다)`}>
            <input type="number" min={0} max={50} step={0.1} value={cap} onChange={(e) => setCap(e.target.value)} aria-invalid={!capOk} />
          </Field>
          <div className={`meter ${spentPct > 90 ? "bad" : spentPct > 70 ? "warn" : ""}`} role="img" aria-label={`일일 한도 ${Math.round(spentPct)}% 사용`}><i style={{ width: `${spentPct}%` }} /></div>
          <Field label="동시 실행 한도(건)" error={concOk ? undefined : "1~10 사이 정수"}><input type="number" min={1} max={10} value={conc} onChange={(e) => setConc(e.target.value)} aria-invalid={!concOk} /></Field>
          <div><button disabled={!capOk || !concOk}>저장</button></div>
        </form>
      </SectionCard>
      <SectionCard className="span-all" title="항상 지키는 안전 규칙">
        <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
          <li>읽기 전용 직원 + 읽기 도구만 쓰는 계획만 자동 시작합니다. 하나라도 아니면 계획만 만들고 사용자 확인을 기다립니다.</li>
          <li>일시적 실패(LLM 오류·시간 초과·서버 재시작)만 트리거별 상한까지 자동 재시도합니다. 검증 실패·반려·예산 초과·자료 부족은 재시도하지 않고 사용자에게 알립니다.</li>
          <li>선행 업무 완료 연쇄는 깊이 {cfg.max_chain_depth}단계까지, 같은 트리거·같은 목표의 중복 시작과 순환 연결은 막습니다.</li>
          <li>서버가 재시작돼도 일정과 처리한 발동 기록이 유지되어 같은 발동을 다시 실행하지 않습니다. 놓친 일정은 한 번만 따라잡습니다.</li>
        </ul>
      </SectionCard>
    </div>
  );
}

const toLocalInput = (iso: unknown) => {
  if (typeof iso !== "string") return "";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  const p = (n: number) => String(n).padStart(2, "0");
  return Number.isNaN(d.getTime()) ? "" : `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
};

function TriggerDialog({ cfg, current, others, onClose, onSaved }: { cfg: AutonomyConfig | null; current: TriggerRow | null; others: TriggerRow[]; onClose: () => void; onSaved: () => void }) {
  const c = (current?.config ?? {}) as Record<string, unknown>;
  const minInterval = cfg?.min_interval_minutes ?? 5;
  const form = useCrudForm({
    name: current?.name ?? "", kind: (current?.kind ?? "daily") as TriggerKind, goal: current?.goal ?? "", mode: (current?.exec_mode ?? "supervised") as ExecMode,
    budget: String(current?.budget_usd ?? 0.3), cooldown: String(current?.cooldown_minutes ?? 60), maxRuns: String(current?.max_runs_per_day ?? 6),
    cap: String(current?.daily_cost_cap_usd ?? 0.5), retries: String(current?.max_retries ?? 1), enabled: current?.enabled ?? true,
    minutes: String(c.minutes ?? 60), time: String(c.time ?? "09:00"), weekdays: (c.weekdays as number[] | undefined) ?? [], runAt: toLocalInput(c.run_at),
    event: String(c.event ?? ""), topic: String(c.topic_key ?? "*"), after: String(c.after_trigger_id ?? ""),
  }, (v) => {
    const int = (s: string, lo: number, hi: number) => s.trim() !== "" && Number.isInteger(Number(s)) && Number(s) >= lo && Number(s) <= hi;
    const e: Partial<Record<keyof typeof v, string>> = {};
    if (!v.name.trim()) e.name = "이름을 입력하세요";
    if (v.goal.trim().length < 3) e.goal = "목표를 3자 이상 입력하세요";
    if (!(Number(v.budget) > 0 && Number(v.budget) <= 5)) e.budget = "0 초과 5 이하(USD)";
    else if (Number(v.budget) > Number(v.cap)) e.budget = "일일 비용 한도보다 클 수 없습니다";
    if (!(Number(v.cap) > 0 && Number(v.cap) <= 50)) e.cap = "0 초과 50 이하(USD)";
    if (!int(v.cooldown, 0, 10080)) e.cooldown = "0~10080 정수(분)";
    if (!int(v.maxRuns, 1, 100)) e.maxRuns = "1~100 정수";
    if (!int(v.retries, 0, 5)) e.retries = "0~5 정수";
    if (v.kind === "interval" && !int(v.minutes, minInterval, 10080)) e.minutes = `${minInterval}~10080 정수(분)`;
    if (v.kind === "daily" && !/^([01]\d|2[0-3]):[0-5]\d$/.test(v.time)) e.time = "HH:MM 형식";
    if (v.kind === "once" && !v.runAt) e.runAt = "실행 시각을 선택하세요";
    if (v.kind === "event" && !/^[a-z][a-z0-9_.:-]{1,39}$/.test(v.event)) e.event = "영문 소문자로 시작하는 2~40자(영문·숫자·._:-)";
    if (v.kind === "chain" && !v.after) e.after = "선행 트리거를 선택하세요";
    return e;
  });
  const f = form.values;
  const config = (): Record<string, unknown> => {
    switch (f.kind) {
      case "interval": return { minutes: Number(f.minutes) };
      case "daily": return { time: f.time, weekdays: f.weekdays };
      case "once": return { run_at: f.runAt };
      case "event": return { event: f.event };
      case "proactive": return { topic_key: f.topic };
      case "chain": return { after_trigger_id: Number(f.after) };
    }
  };
  const submit = async () => {
    const body = { name: f.name, goal: f.goal, exec_mode: f.mode, budget_usd: Number(f.budget), cooldown_minutes: Number(f.cooldown), max_runs_per_day: Number(f.maxRuns),
      daily_cost_cap_usd: Number(f.cap), max_retries: Number(f.retries), enabled: f.enabled, config: config(), ...(current ? {} : { kind: f.kind }) };
    if (current) await api(`/autonomy/triggers/${current.id}`, { method: "PUT", json: body });
    else await api("/autonomy/triggers", { method: "POST", json: body });
    onSaved();
  };
  const text = (k: "name" | "goal" | "budget" | "cooldown" | "maxRuns" | "cap" | "retries") => ({ value: f[k], "aria-invalid": !!form.errorOf(k), onBlur: () => form.touch(k), onChange: (ev: { target: { value: string } }) => form.set(k, ev.target.value) });
  const chainable = others.filter((o) => o.id !== current?.id);
  return (
    <CrudDialog mode={current ? "update" : "create"} size="wide" title={current ? "트리거 수정" : "트리거 추가"} dirty={form.dirty} validate={form.check} onClose={onClose} onSubmit={submit}>
      <div className="grid g2">
        <Field label="이름" required error={form.errorOf("name")}><input {...text("name")} /></Field>
        <Field label="조건 종류" hint={current ? "종류는 만든 뒤 바꿀 수 없습니다" : undefined}>
          <select value={f.kind} disabled={!!current} onChange={(e) => form.set("kind", e.target.value as TriggerKind)}>{(Object.keys(KIND_NAME) as TriggerKind[]).map((k) => <option key={k} value={k}>{KIND_NAME[k]}</option>)}</select>
        </Field>
      </div>
      <Field label="목표" required error={form.errorOf("goal")} hint="기존 직원·업무 카탈로그로 플래너가 계획을 만듭니다. 특정 직원 이름을 적을 필요는 없습니다."><textarea rows={3} {...text("goal")} /></Field>

      {f.kind === "interval" && <Field label="반복 간격(분)" error={form.errorOf("minutes")}><input type="number" min={minInterval} value={f.minutes} onChange={(e) => form.set("minutes", e.target.value)} onBlur={() => form.touch("minutes")} /></Field>}
      {f.kind === "daily" && (
        <div className="grid g2">
          <Field label="시각(서버 시간대)" error={form.errorOf("time")}><input type="time" value={f.time} onChange={(e) => form.set("time", e.target.value)} onBlur={() => form.touch("time")} /></Field>
          <Field label="요일(비우면 매일)"><div className="row wrap">{WEEKDAYS.map((d, i) => <label key={d} className="check"><input type="checkbox" checked={f.weekdays.includes(i)} onChange={(e) => form.set("weekdays", e.target.checked ? [...f.weekdays, i].sort() : f.weekdays.filter((x) => x !== i))} />{d}</label>)}</div></Field>
        </div>
      )}
      {f.kind === "once" && <Field label="실행 시각" error={form.errorOf("runAt")} hint="지난 시각으로 등록할 수 없고, 서버가 꺼져 있다가 한참 뒤 켜지면 실행하지 않고 '예정 시각 경과'로 기록합니다."><input type="datetime-local" value={f.runAt} onChange={(e) => form.set("runAt", e.target.value)} onBlur={() => form.touch("runAt")} /></Field>}
      {f.kind === "event" && (
        <Field label="이벤트 이름" error={form.errorOf("event")} hint={<>기본 제공: {Object.entries(cfg?.builtin_events ?? {}).map(([k, v]) => `${k}(${v})`).join(", ")}. 그 밖의 이름은 외부에서 POST /api/autonomy/events 로 알릴 때 쓰는 이름입니다.</>}>
          <input value={f.event} placeholder="dashboard_opened" onChange={(e) => form.set("event", e.target.value)} onBlur={() => form.touch("event")} />
        </Field>
      )}
      {f.kind === "proactive" && (
        <Field label="능동 제안 주제" hint="GYUVIS가 해당 주제의 제안을 실제로 사용자에게 전달했을 때만 발동합니다(보류·폐기된 제안은 발동하지 않음).">
          <select value={f.topic} onChange={(e) => form.set("topic", e.target.value)}><option value="*">모든 주제</option><option value="sky">은하수·출사</option><option value="idea">GyuNexus 아이디어</option></select>
        </Field>
      )}
      {f.kind === "chain" && (
        <Field label="선행 트리거(이 트리거의 워크플로가 완료되면 실행)" error={form.errorOf("after")} hint="순환 연결과 자기 자신은 서버가 거부합니다.">
          <select value={f.after} onChange={(e) => form.set("after", e.target.value)} onBlur={() => form.touch("after")}><option value="">선택하세요</option>{chainable.map((o) => <option key={o.id} value={o.id}>#{o.id} {o.name}</option>)}</select>
        </Field>
      )}

      <div className="card flat stack tight">
        <div className="grid g2">
          <Field label="실행 모드" hint={MODE_DESC[f.mode]}><ModeSelect value={f.mode} onChange={(m) => form.set("mode", m)} max="autonomous" /></Field>
          <Field label="실행 1회 예산(USD)" error={form.errorOf("budget")}><input type="number" min={0} max={5} step={0.05} {...text("budget")} /></Field>
        </div>
        {cfg && f.mode !== "manual" && ["supervised", "autonomous"].indexOf(f.mode) > ["supervised", "autonomous"].indexOf(cfg.max_mode) && <div className="small" style={{ color: "var(--warn)" }}>현재 허용 범위({cfg.max_mode})를 넘는 모드입니다. 실행할 때는 허용 범위로 낮춰서 시작합니다.</div>}
        <div className="grid g2">
          <Field label="쿨다운(분)" error={form.errorOf("cooldown")} hint="직전 시작 후 이 시간 안에는 다시 시작하지 않습니다"><input type="number" min={0} {...text("cooldown")} /></Field>
          <Field label="하루 최대 실행 횟수" error={form.errorOf("maxRuns")}><input type="number" min={1} {...text("maxRuns")} /></Field>
          <Field label="트리거 일일 비용 한도(USD)" error={form.errorOf("cap")}><input type="number" min={0} step={0.1} {...text("cap")} /></Field>
          <Field label="실패 자동 재시도 상한(회)" error={form.errorOf("retries")} hint="일시적 실패만 대상입니다"><input type="number" min={0} max={5} {...text("retries")} /></Field>
        </div>
        <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => form.set("enabled", e.target.checked)} />이 트리거 활성화 <span className="muted small">(전체 스위치가 꺼져 있으면 활성이어도 실행되지 않습니다)</span></label>
      </div>
    </CrudDialog>
  );
}
