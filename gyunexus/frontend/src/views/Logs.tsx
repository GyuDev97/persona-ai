import { useMemo, useState } from "react";
import { useApi, type Log } from "../api";
import { Async, Collapse, EmptyState, FilterBar, SearchField, actorLabel, eventLabel, fmtTime, PageHeader, SOURCE_LABEL, StatusBadge } from "../components/ui";

const GROUPS: Record<string, string> = { all: "전체", debate: "토론·에이전트", proactive: "능동 제안", worker: "AI 직원", tool: "도구·승인", chat: "대화·기억", system: "시스템" };
const groupOf = (l: Log) => {
  const e = l.event;
  if (e.startsWith("proactive")) return "proactive";
  if (e.startsWith("run.") || e.startsWith("worker.") || e.startsWith("task.")) return "worker";
  if (e.startsWith("tool") || e.startsWith("approval")) return "tool";
  if (e.startsWith("chat") || e.startsWith("memory") || e.startsWith("routing") || e.startsWith("intent")) return "chat";
  if (["startup", "settings.changed", "budget.exhausted"].includes(e)) return "system";
  return "debate";
};

export default function Logs({ version }: { version: number }) {
  const [actor, setActor] = useState("");
  const [group, setGroup] = useState("all");
  const [level, setLevel] = useState("");
  const [q, setQ] = useState("");
  const logs = useApi<Log[]>(`/logs?limit=300${actor ? `&agent_id=${actor}` : ""}`, version);
  const rows = useMemo(
    () => (logs.data ?? []).filter((l) => (group === "all" || groupOf(l) === group) && (!level || l.level === level) &&
      (!q.trim() || `${l.event} ${eventLabel(l.event)} ${JSON.stringify(l.detail)}`.toLowerCase().includes(q.trim().toLowerCase()))),
    [logs.data, group, level, q],
  );
  const errors = (logs.data ?? []).filter((l) => l.level === "error").length;

  return (
    <div className="page-inner">
      <PageHeader title="로그" desc={`최근 활동 기록입니다. 오류 ${errors}건.`} />
      <FilterBar>
        <select value={group} onChange={(e) => setGroup(e.target.value)} aria-label="이벤트 유형">{Object.entries(GROUPS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
        <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="수준"><option value="">모든 수준</option><option value="error">오류</option><option value="warn">경고</option><option value="info">정보</option></select>
        <select value={actor} onChange={(e) => setActor(e.target.value)} aria-label="주체"><option value="">모든 주체</option>{["research", "idea", "developer", "critic", "gyuvis"].map((a) => <option key={a} value={a}>{SOURCE_LABEL[a]}</option>)}</select>
        <SearchField value={q} onChange={setQ} placeholder="이벤트·상세 검색" label="로그 검색" />
        <span className="muted small" aria-live="polite">{rows.length}건</span>
      </FilterBar>
      <Async q={logs}>
        {() => (
          <div className="card" style={{ padding: 0 }}>
            {rows.length === 0 && <EmptyState title="조건에 맞는 로그가 없습니다" />}
            {rows.map((l) => (
              <div key={l.id} className={`log-row ${l.level}`}>
                <div className="row wrap">
                  <span className="log-time nowrap">{fmtTime(l.ts)}</span>
                  {l.level !== "info" && <StatusBadge status={l.level === "error" ? "error" : "warn"} />}
                  <b>{eventLabel(l.event)}</b>
                  <span className="muted small">{actorLabel(l.agent_id, l.source)}{l.debate_id ? ` · 토론 #${l.debate_id}` : ""}</span>
                  <code className="muted small" style={{ marginLeft: "auto", fontFamily: "var(--mono)" }}>{l.event}</code>
                </div>
                {Object.keys(l.detail ?? {}).length > 0 && <div style={{ marginTop: 4 }}><Collapse title={<span className="small muted">{JSON.stringify(l.detail).slice(0, 110)}</span>}><pre>{JSON.stringify(l.detail, null, 2)}</pre></Collapse></div>}
              </div>
            ))}
          </div>
        )}
      </Async>
    </div>
  );
}
