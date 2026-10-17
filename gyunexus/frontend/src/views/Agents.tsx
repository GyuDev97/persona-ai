import { useState } from "react";
import { api, useApi, type Agent, type Log, type Topic } from "../api";

const time = (iso: string | null) => (iso ? new Date(iso).toLocaleString("ko-KR", { hour12: false }) : "-");

export function Agents({ version }: { version: number }) {
  const agents = useApi<Agent[]>("/agents", version);
  const topics = useApi<Topic[]>("/topics", version);
  const logs = useApi<Log[]>("/logs?limit=12", version);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    try {
      await api("/debates/run", { method: "POST", json: { topic: title.trim() } });
      setTitle("");
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <div className="stack">
      <div className="cards">
        {agents.data?.map((a) => (
          <div key={a.id} className="card">
            <h3>
              <span className={`dot ${a.status === "thinking" ? "busy" : "ok"}`} /> {a.name}
            </h3>
            <div className="muted">{a.role}</div>
            <p>{a.description}</p>
            <div className="small">{a.status === "thinking" ? a.current_task : `대기 중 · 마지막 활동 ${time(a.last_active_at)}`}</div>
          </div>
        ))}
      </div>
      <div className="card">
        <h3>주제 직접 던지기</h3>
        <form className="row" onSubmit={(e) => (e.preventDefault(), title.trim().length >= 3 && submit())}>
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="에이전트들이 토론할 주제 (비워 두면 자동 발굴)" />
          <button disabled={title.trim().length < 3}>토론 시작</button>
        </form>
        {error && <div className="notice">{error}</div>}
      </div>
      <div className="two">
        <div className="card">
          <h3>주제 큐</h3>
          {topics.data?.slice(0, 10).map((t) => (
            <div key={t.id} className="line">
              <span className={`pill ${t.status}`}>{t.status}</span> <span className="muted">[{t.source}]</span> {t.title}
            </div>
          ))}
          {topics.data?.length === 0 && <p className="muted">아직 주제가 없습니다.</p>}
        </div>
        <div className="card">
          <h3>최근 활동</h3>
          {logs.data?.map((l) => (
            <div key={l.id} className="line small">
              <span className="muted">{time(l.ts)}</span> {l.agent_id ?? l.source} · {l.event}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function Logs({ version }: { version: number }) {
  const [agent, setAgent] = useState("");
  const logs = useApi<Log[]>(`/logs?limit=200${agent ? `&agent_id=${agent}` : ""}`, version);
  return (
    <div className="card">
      <div className="row">
        <h3>실행 로그</h3>
        <select value={agent} onChange={(e) => setAgent(e.target.value)}>
          <option value="">전체</option>
          {["research", "idea", "developer", "critic", "gyuvis"].map((a) => <option key={a}>{a}</option>)}
        </select>
      </div>
      <table>
        <tbody>
          {logs.data?.map((l) => (
            <tr key={l.id} className={l.level}>
              <td className="muted nowrap">{time(l.ts)}</td>
              <td>{l.agent_id ?? l.source}</td>
              <td>{l.event}{l.debate_id ? ` (#${l.debate_id})` : ""}</td>
              <td className="small muted">{JSON.stringify(l.detail).slice(0, 160)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
