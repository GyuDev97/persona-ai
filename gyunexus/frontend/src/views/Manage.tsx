import { useState } from "react";
import { api, useApi, type Approval, type Memory } from "../api";

const KINDS = ["interest", "preference", "routine", "fact", "goal"];

export function Memories({ version }: { version: number }) {
  const mems = useApi<Memory[]>("/memories", version);
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("interest");
  const [error, setError] = useState<string | null>(null);

  const add = async () => {
    try {
      await api("/memories", { method: "POST", json: { kind, content: content.trim(), importance: 7 } });
      setContent("");
      setError(null);
      mems.reload();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  const del = async (id: number) => {
    await api(`/memories/${id}`, { method: "DELETE" });
    mems.reload();
  };

  return (
    <div className="stack">
      <div className="card">
        <h3>기억 추가</h3>
        <form className="row" onSubmit={(e) => (e.preventDefault(), content.trim() && add())}>
          <select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k}>{k}</option>)}</select>
          <input value={content} onChange={(e) => setContent(e.target.value)} placeholder="예: 사용자는 은하수 촬영을 즐긴다" />
          <button disabled={!content.trim()}>저장</button>
        </form>
        {error && <div className="notice">{error}</div>}
        <p className="small muted">대화 중에도 GYUVIS가 오래 유효한 정보를 자동으로 기억합니다.</p>
      </div>
      <div className="card">
        {mems.data?.map((m) => (
          <div key={m.id} className="line">
            <span className="pill">{m.kind}</span> {m.content}
            <span className="muted small"> · 중요도 {m.importance} · 사용 {m.use_count}회 · {m.source}</span>
            <button className="x" onClick={() => del(m.id)} title="삭제">×</button>
          </div>
        ))}
        {mems.data?.length === 0 && <p className="muted">저장된 기억이 없습니다.</p>}
      </div>
    </div>
  );
}

export function Approvals({ version }: { version: number }) {
  const list = useApi<Approval[]>("/approvals", version);
  const [error, setError] = useState<string | null>(null);
  const decide = async (id: number, action: "approve" | "reject") => {
    try {
      await api(`/approvals/${id}/${action}`, { method: "POST" });
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    list.reload();
  };
  return (
    <div className="stack">
      <p className="muted">파일 변경·외부 게시 같은 작업은 에이전트가 직접 실행하지 못하고 여기서 승인해야 실행됩니다.</p>
      {error && <div className="notice">{error}</div>}
      {list.data?.map((a) => (
        <div key={a.id} className="card">
          <h3>
            <span className={`pill ${a.status}`}>{a.status}</span> {a.tool}
          </h3>
          <div className="small muted">요청: {a.requested_by}{a.debate_id ? ` · 토론 #${a.debate_id}` : ""}</div>
          {a.reason && <p>{a.reason}</p>}
          <pre>{JSON.stringify(a.args, null, 2)}</pre>
          {a.result != null && <pre>{JSON.stringify(a.result, null, 2)}</pre>}
          {a.status === "pending" && (
            <div className="row">
              <button onClick={() => decide(a.id, "approve")}>승인하고 실행</button>
              <button className="ghost" onClick={() => decide(a.id, "reject")}>거절</button>
            </div>
          )}
        </div>
      ))}
      {list.data?.length === 0 && <p className="muted">대기 중인 승인 요청이 없습니다.</p>}
    </div>
  );
}
