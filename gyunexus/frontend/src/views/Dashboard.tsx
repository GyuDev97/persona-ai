import { useEffect, useState } from "react";
import { useApi, type Agent, type Approval, type AutonomyCard, type AutonomyOverview, type Debate, type Health, type IdeaT, type Log, type SuggestionRow, type WorkerRow, type WorkerRunRow } from "../api";
import type { Nav, PageId } from "../App";
import { describeTrigger, KIND_NAME, ModeBadge, ORIGIN_NAME } from "../components/autonomy";
import { actorLabel, EmptyState, eventLabel, fmtAgo, Icon, PageHeader, SectionCard, StatCard, StatusBadge } from "../components/ui";

function Stat({ icon, label, num, sub, to, nav, tone }: { icon: string; label: string; num: number | string; sub: string; to: PageId; nav: Nav; tone?: "cyan" | "mint" | "violet" | "warn" | "bad" }) {
  return <StatCard icon={icon} tone={tone} label={label} value={num} sub={sub} onClick={() => nav.go(to)} />;
}

// 빠른 작업: 모두 기존 화면으로 이동하는 실제 동작만 둔다.
const QUICK: { icon: string; label: string; to: PageId }[] = [
  { icon: "chat", label: "GYUVIS와 대화", to: "chat" },
  { icon: "workflows", label: "새 워크플로", to: "workflows" },
  { icon: "debates", label: "토론 주제 던지기", to: "agents" },
  { icon: "approvals", label: "승인 확인", to: "approvals" },
];

function CardRow({ c, nav, extra }: { c: AutonomyCard; nav: Nav; extra?: string }) {
  return (
    <button className="sel-item" onClick={() => nav.go("workflows")}>
      <div className="row between"><span className="t">#{c.id} {c.title}</span><span className="row"><ModeBadge mode={c.mode} /><StatusBadge status={c.status} /></span></div>
      <div className="small muted">{ORIGIN_NAME[c.origin] ?? c.origin} · {c.done}/{c.total}단계{c.current[0] ? ` · 담당 ${c.current[0].worker}` : ""}{extra ? ` · ${extra}` : ""}</div>
      {c.attention[0] && <div className="small" style={{ color: "var(--warn)" }}>{c.attention[0]}</div>}
    </button>
  );
}

/** 자율 업무 현황: 실행 중 / 다음 예약 / 완료 / 사용자 확인 필요. 모두 /api/autonomy/overview 의 서버 값이다. */
function AutonomyBoard({ ov, nav }: { ov: AutonomyOverview | null; nav: Nav }) {
  if (!ov) return null;
  return (
    <div className="grid g2" aria-label="자율 업무 현황">
      <SectionCard title={<>실행 중인 자율 업무 <span className="muted small">{ov.running.length}건</span></>} aside={<button className="link" onClick={() => nav.go("autonomy")}>자율 운영 <span className={`badge plain ${ov.config.enabled ? "ok" : ""}`}>{ov.config.enabled ? "ON" : "OFF"}</span></button>}>
        {ov.running.length === 0 ? <EmptyState icon="autonomy" title="실행 중인 자율 업무가 없습니다" desc="감독 자동·자율 모드로 시작했거나 트리거가 시작한 워크플로가 여기에 표시됩니다." /> : ov.running.map((c) => <CardRow key={c.id} c={c} nav={nav} />)}
      </SectionCard>
      <SectionCard title={<>사용자 확인이 필요한 업무 <span className="muted small">{ov.needs_attention.length}건</span></>}>
        {ov.needs_attention.length === 0 ? <EmptyState icon="check" title="확인할 업무가 없습니다" desc="승인 대기·자동 실행 차단·실패한 업무가 생기면 사유와 함께 표시됩니다." /> : ov.needs_attention.map((c) => <CardRow key={c.id} c={c} nav={nav} />)}
      </SectionCard>
      <SectionCard title="다음 예약 업무" aside={<button className="link" onClick={() => nav.go("autonomy")}>트리거 관리</button>}>
        {ov.upcoming.length === 0 && ov.event_triggers.length === 0 ? <EmptyState icon="clock" title="예약된 업무가 없습니다" /> : (
          <>
            {ov.upcoming.map((u) => <div key={u.id} className="item row between wrap"><span><b>{u.name}</b> <span className="muted small">{KIND_NAME[u.kind]}</span></span><span className="small muted nowrap">{new Date(u.next_fire_at).toLocaleString("ko-KR", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span></div>)}
            {ov.event_triggers.map((u) => <div key={u.id} className="item row between wrap"><span><b>{u.name}</b></span><span className="small muted">{describeTrigger(u)}</span></div>)}
            {!ov.config.enabled && <div className="small muted">상시 자율 운영이 꺼져 있어 예약은 실행되지 않습니다.</div>}
          </>
        )}
      </SectionCard>
      <SectionCard title="완료된 자율 업무">
        {ov.completed.length === 0 ? <EmptyState title="아직 완료된 업무가 없습니다" /> : ov.completed.map((c) => <CardRow key={c.id} c={c} nav={nav} extra={c.ended_at ? `완료 ${fmtAgo(c.ended_at)}` : undefined} />)}
      </SectionCard>
    </div>
  );
}

/** 실제로 조회되는 API 값만 조합해 보여 준다(없는 통계는 만들지 않는다). */
export default function Dashboard({ version, nav, health }: { version: number; nav: Nav; health: Health | null }) {
  const agents = useApi<Agent[]>("/agents", version);
  const workers = useApi<WorkerRow[]>("/workers", version);
  const ideas = useApi<IdeaT[]>("/ideas?status=all", version);
  const approvals = useApi<Approval[]>("/approvals", version);
  const logs = useApi<Log[]>("/logs?limit=60", version);
  const runs = useApi<WorkerRunRow[]>("/workers/runs?limit=30", version);
  const debates = useApi<Debate[]>("/debates", version);
  const sugg = useApi<SuggestionRow[]>("/proactive/suggestions?limit=30", version);
  const auto = useApi<AutonomyOverview>("/autonomy/overview", version);
  const [now, setNow] = useState(new Date());
  useEffect(() => { const t = window.setInterval(() => setNow(new Date()), 30_000); return () => window.clearInterval(t); }, []);

  const ag = agents.data ?? [];
  const busyAgents = ag.filter((a) => a.status === "thinking");
  const ws = workers.data ?? [];
  const id = ideas.data ?? [];
  const st = (i: IdeaT) => i.status ?? "needs_research";
  const pending = (approvals.data ?? []).filter((a) => a.status === "pending");
  const activeRuns = (runs.data ?? []).filter((r) => ["pending", "running", "reviewing"].includes(r.status));
  const runningDebates = (debates.data ?? []).filter((d) => d.status === "running");
  const proactive = (sugg.data ?? []).filter((s) => s.status === "delivered").slice(0, 5);
  const activity = (logs.data ?? []).filter((l) => !(l.source === "tool" && l.level === "info") && l.event !== "chat.trace").slice(0, 10);
  const inProgress = busyAgents.length + activeRuns.length + runningDebates.length;

  return (
    <div className="page-inner">
      <PageHeader title="안녕하세요" desc={health?.llm_configured === false ? "OPENAI_API_KEY가 설정되지 않았습니다. README를 참고하세요." : "오늘의 GyuNexus 현황입니다."}
        actions={<div className="muted" style={{ textAlign: "right" }}>{now.toLocaleDateString("ko-KR", { year: "numeric", month: "long", day: "numeric", weekday: "short" })}<div style={{ fontSize: 22, color: "var(--text)", fontWeight: 700 }}>{now.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", hour12: false })}</div></div>} />
      <div className="grid g4">
        <Stat nav={nav} to="agents" icon="agents" label="에이전트" num={`${ag.length}명`} sub={`실행 중 ${busyAgents.length} · 대기 ${ag.length - busyAgents.length}`} />
        <Stat nav={nav} to="workers" icon="workers" tone="mint" label="AI 직원" num={`${ws.filter((w) => w.enabled).length}명`} sub={`작업 중 ${ws.filter((w) => w.state === "working").length} · 승인 대기 ${ws.reduce((s, w) => s + w.awaiting_approval, 0)}`} />
        <Stat nav={nav} to="ideas" icon="ideas" tone="violet" label="아이디어" num={`${id.length}건`} sub={`채택 ${id.filter((i) => st(i) === "accepted").length} · 추가 조사 ${id.filter((i) => st(i) === "needs_research").length} · 폐기 ${id.filter((i) => st(i) === "discarded").length}`} />
        <Stat nav={nav} to="approvals" icon="approvals" tone={pending.length ? "warn" : "cyan"} label="승인 대기" num={`${pending.length}건`} sub={pending.length ? "검토가 필요합니다" : "대기 중인 요청 없음"} />
      </div>

      <div className="row wrap" aria-label="빠른 작업">
        <span className="small muted">빠른 작업</span>
        {QUICK.map((q) => <button key={q.to + q.label} className="secondary sm" onClick={() => nav.go(q.to)}><Icon name={q.icon} size={14} />{q.label}</button>)}
      </div>

      <AutonomyBoard ov={auto.data} nav={nav} />

      <div className="grid g2">
        <SectionCard title={<>진행 중인 업무 <span className="muted small">{inProgress}건</span></>}>
          {inProgress === 0 && <EmptyState icon="check" title="진행 중인 업무가 없습니다" desc="토론·AI 직원 실행·에이전트 작업이 시작되면 여기에 표시됩니다." />}
          {runningDebates.map((d) => <button key={`d${d.id}`} className="sel-item" onClick={() => nav.openDebate(d.id)}><div className="row between"><span className="t">토론 #{d.id} {d.title}</span><StatusBadge status="running" /></div></button>)}
          {activeRuns.map((r) => <button key={`r${r.id}`} className="sel-item" onClick={() => nav.go("workers")}><div className="row between"><span className="t">{r.worker_name} · {r.task_title}</span><StatusBadge status={r.status} /></div></button>)}
          {busyAgents.map((a) => <button key={a.id} className="sel-item" onClick={() => nav.go("agents")}><div className="row between"><span className="t">{a.name}: {a.current_task ?? "작업 중"}</span><StatusBadge status="thinking" /></div></button>)}
        </SectionCard>
        <SectionCard title="GYUVIS의 능동 제안" aside={<button className="link" onClick={() => nav.go("proactive")}>전체 보기</button>}>
          {proactive.length === 0 && <EmptyState icon="spark" title="전달된 제안이 없습니다" desc="조건이 맞을 때만 먼저 말을 겁니다." />}
          {proactive.map((s) => (
            <div key={s.id} className="item">
              <div className="row between wrap"><b>{s.title}</b><span className="small muted nowrap">{fmtAgo(s.delivered_at)}</span></div>
              <div className="small muted clamp2">{s.reason}</div>
            </div>
          ))}
        </SectionCard>
      </div>

      <div className="grid g2">
        {pending.length > 0 && (
          <SectionCard title="승인이 필요한 요청" aside={<button className="link" onClick={() => nav.go("approvals")}>승인 화면</button>}>
            {pending.slice(0, 5).map((a) => <div key={a.id} className="item row between"><span>{a.reason || a.tool}</span><span className="small muted nowrap">{fmtAgo(a.created_at)}</span></div>)}
          </SectionCard>
        )}
        <SectionCard className={pending.length === 0 ? "span-all" : ""} title="최근 활동" aside={<button className="link" onClick={() => nav.go("logs")}>로그</button>}>
          {activity.length === 0 && <EmptyState title="활동 기록이 없습니다" />}
          {activity.map((l) => (
            <div key={l.id} className="item row between wrap">
              <span>{l.level !== "info" && <StatusBadge status={l.level === "error" ? "error" : "warn"} />} <b>{eventLabel(l.event)}</b> <span className="muted small">· {actorLabel(l.agent_id, l.source)}</span></span>
              <span className="small muted nowrap">{fmtAgo(l.ts)}</span>
            </div>
          ))}
        </SectionCard>
      </div>    </div>
  );
}
