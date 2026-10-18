import { useMemo, useState } from "react";
import { api, useApi, type Agent, type Log, type Topic } from "../api";
import { Async, Collapse, EmptyState, eventLabel, actorLabel, fmtAgo, MODE_LABEL, PageHeader, StatusBadge } from "../components/ui";

export default function Agents({ version }: { version: number }) {
  const agents = useApi<Agent[]>("/agents", version);
  const topics = useApi<Topic[]>("/topics", version);
  const logs = useApi<Log[]>("/logs?limit=200", version);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    try {
      await api("/debates/run", { method: "POST", json: { topic: title.trim() } });
      setTitle("");
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  // 에이전트의 가장 최근 로그가 오류면 ‘오류’, 실행 중이면 ‘실행 중’, 아니면 ‘대기’로 구분한다.
  const state = useMemo(() => {
    const out: Record<string, "idle" | "thinking" | "error"> = {};
    for (const a of agents.data ?? []) {
      const last = (logs.data ?? []).find((l) => l.agent_id === a.id);
      out[a.id] = a.status === "thinking" ? "thinking" : last && last.level === "error" ? "error" : "idle";
    }
    return out;
  }, [agents.data, logs.data]);
  const activity = (logs.data ?? []).filter((l) => l.source !== "tool" || l.level !== "info").slice(0, 14);

  return (
    <div className="page-inner">
      <PageHeader title="에이전트" desc="Research · Idea · Developer · Critic 의 현재 상태와 토론 주제 큐입니다." />
      <Async q={agents}>
        {(rows) => (
          <div className="grid g2">
            {rows.map((a) => {
              const s = state[a.id] ?? "idle";
              return (
                <div key={a.id} className="card">
                  <div className="row between"><h3>{a.name}</h3><StatusBadge status={s} /></div>
                  <div className="muted" style={{ margin: "2px 0 8px" }}>{a.role}</div>
                  <div className="small">
                    {s === "thinking" ? <span style={{ color: "var(--info)" }}>지금 실행 중: {a.current_task ?? "작업 중"}</span> : <span className="muted">대기 중 · 마지막 활동 {fmtAgo(a.last_active_at)}</span>}
                  </div>
                  {s === "error" && <div className="small" style={{ color: "var(--bad)" }}>최근 로그에 오류가 있습니다. 로그 화면에서 확인하세요.</div>}
                  <div style={{ marginTop: 8 }}><Collapse title="상세 설명"><p className="muted">{a.description}</p></Collapse></div>
                </div>
              );
            })}
          </div>
        )}
      </Async>
      <div className="card">
        <div className="card-title"><h3>주제 직접 던지기</h3></div>
        <form className="row wrap" onSubmit={(e) => (e.preventDefault(), title.trim().length >= 3 && submit())}>
          <input className="grow" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="에이전트들이 토론할 주제 (3자 이상)" aria-label="토론 주제" />
          <button disabled={title.trim().length < 3 || busy}>토론 시작</button>
        </form>
        <div className="small muted" style={{ marginTop: 6 }}>비워 두고 상단의 ‘지금 토론’을 누르면 주제를 자동으로 발굴합니다.</div>
        {error && <div className="notice bad" style={{ marginTop: 8 }}>{error}</div>}
      </div>
      <div className="grid g2">
        <div className="card">
          <div className="card-title"><h3>주제 큐</h3></div>
          {topics.data?.length === 0 && <EmptyState title="아직 주제가 없습니다" />}
          {topics.data?.slice(0, 10).map((t) => (
            <div key={t.id} className="item">
              <div className="row wrap"><StatusBadge status={t.status} /><span className="badge plain">{MODE_LABEL[t.source] ?? t.source}</span></div>
              <div style={{ marginTop: 2 }}>{t.title}</div>
            </div>
          ))}
        </div>
        <div className="card">
          <div className="card-title"><h3>최근 활동</h3></div>
          {activity.length === 0 && <EmptyState title="활동 기록이 없습니다" />}
          {activity.map((l) => (
            <div key={l.id} className="item small">
              <div className="row between"><b>{eventLabel(l.event)}</b><span className="muted">{fmtAgo(l.ts)}</span></div>
              <div className="muted">{actorLabel(l.agent_id, l.source)}{l.debate_id ? ` · 토론 #${l.debate_id}` : ""}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
