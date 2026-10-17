import { useEffect, useState } from "react";
import { useApi, type Claim, type Debate, type DebateDetail, type IdeaT } from "../api";

const NAMES: Record<string, string> = { research: "Research", idea: "Idea", developer: "Developer", critic: "Critic" };
const CLAIM_LABEL: Record<Claim["status"], string> = {
  verified: "검증됨", unverified: "미검증", interpretation: "해석", assumption: "추정", proposal: "제안", conflicted: "증거와 충돌",
  rebuttal: "반박", endorsed: "인정", opinion: "의견",
};
const IDEA_STATUS_LABEL: Record<string, string> = { accepted: "채택", needs_research: "추가 조사 필요", discarded: "폐기" };
const STOP_LABEL: Record<string, string> = {
  consensus: "합의", needs_research: "추가 조사 필요", stagnation: "정체", max_rounds: "최대 라운드", token_budget: "토큰 예산",
  daily_budget: "일일 예산", llm_errors: "LLM 오류",
};

export function DebateList({ version, focus }: { version: number; focus: number | null }) {
  const list = useApi<Debate[]>("/debates", version);
  const [selected, setSelected] = useState<number | null>(focus);
  useEffect(() => {
    setSelected(focus);
  }, [focus]);
  useEffect(() => {
    if (selected === null && list.data?.length) setSelected(list.data[0].id);
  }, [list.data, selected]);

  return (
    <div className="split">
      <aside>
        {list.data?.map((d) => (
          <div key={d.id} className={`conv ${d.id === selected ? "active" : ""}`} onClick={() => setSelected(d.id)}>
            <span>
              <span className={`pill ${d.status}`}>{d.status}</span> #{d.id} {d.title}
            </span>
          </div>
        ))}
        {list.data?.length === 0 && <p className="muted">아직 토론이 없습니다. “지금 토론”을 눌러보세요.</p>}
      </aside>
      <section>{selected !== null && <DebateView id={selected} version={version} />}</section>
    </div>
  );
}

function DebateView({ id, version }: { id: number; version: number }) {
  const { data: d } = useApi<DebateDetail>(`/debates/${id}`, version);
  if (!d || d.id !== id) return null;
  return (
    <div className="stack">
      <div className="card">
        <h2>#{d.id} {d.title}</h2>
        <div className="small muted">
          {d.trigger} · 참여 {d.participants.map((p) => NAMES[p]).join(", ")} · 라운드 {d.rounds_done}/{d.max_rounds}
          {d.stop_reason && ` · 종료: ${STOP_LABEL[d.stop_reason] ?? d.stop_reason}`} · {d.tokens_used} tokens · ${d.cost_usd.toFixed(4)}
        </div>
        <div className="small">목표: {d.goal}</div>
        {d.error && <div className="notice">{d.error}</div>}
      </div>
      {d.result && (
        <div className="card">
          <h3>결과 <span className="pill">{d.result.decision}</span> <span className="pill">중요도 {d.importance}</span></h3>
          <p>{d.result.summary}</p>
          {d.result.verified_facts.length > 0 && (
            <>
              <h4>검증된 사실</h4>
              <ul>{d.result.verified_facts.map((f, i) => <li key={i}>{f.text} <span className="muted">[{f.evidence_ids.map((e) => `E${e}`).join(", ")}]</span></li>)}</ul>
            </>
          )}
          {d.result.unverified_claims.length > 0 && (
            <>
              <h4>검증되지 않은 주장</h4>
              <ul>{d.result.unverified_claims.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </>
          )}
          {d.result.open_questions.length > 0 && (
            <>
              <h4>열린 질문</h4>
              <ul>{d.result.open_questions.map((c, i) => <li key={i}>{c}</li>)}</ul>
            </>
          )}
        </div>
      )}
      {d.ideas.length > 0 && <IdeaCards ideas={d.ideas} />}
      <div className="card">
        <h3>토론 기록</h3>
        {d.messages.map((m) => (
          <div key={m.id} className={`turn ${m.agent_id}`}>
            <div className="small muted">R{m.round} · {NAMES[m.agent_id] ?? m.agent_id}</div>
            <div>{m.content}</div>
            {m.claims.map((c, i) => (
              <div key={i} className="claim">
                <span className={`pill ${c.status}`}>{CLAIM_LABEL[c.status]}</span> {c.text}
                {c.evidence_ids.length > 0 && <span className="muted"> [{c.evidence_ids.map((e) => `E${e}`).join(", ")}]</span>}
              </div>
            ))}
          </div>
        ))}
        {d.status === "running" && <p className="muted">토론 진행 중…</p>}
      </div>
      {d.evidence.length > 0 && (
        <div className="card">
          <h3>증거</h3>
          {d.evidence.map((e) => (
            <div key={e.id} className="line small"><b>E{e.id}</b> {e.tool} <span className="muted">{e.source}</span><div className="muted">{e.summary.slice(0, 240)}</div></div>
          ))}
        </div>
      )}
    </div>
  );
}

function IdeaCards({ ideas, onOpenDebate }: { ideas: IdeaT[]; onOpenDebate?: (id: number) => void }) {
  return (
    <div className="cards">
      {ideas.map((i) => (
        <div key={i.id} className="card">
          <h3>
            {i.status && <span className={`pill ${i.status}`}>{IDEA_STATUS_LABEL[i.status]}</span>} {i.title}
          </h3>
          {i.rationale && <div className="small muted">판정 근거: {i.rationale}</div>}
          <div className="small muted">
            실현성 {i.feasibility} · 확신도 {Math.round(i.confidence * 100)}%
            {i.debate_title && onOpenDebate && (
              <> · <button className="link" onClick={() => onOpenDebate(i.debate_id)}>#{i.debate_id} {i.debate_title}</button></>
            )}
          </div>
          <p>{i.description}</p>
          {i.risks.length > 0 && <><h4>위험</h4><ul>{i.risks.map((r, k) => <li key={k}>{r}</li>)}</ul></>}
          {i.next_steps.length > 0 && <><h4>다음 단계</h4><ul>{i.next_steps.map((r, k) => <li key={k}>{r}</li>)}</ul></>}
        </div>
      ))}
    </div>
  );
}

export function Ideas({ version, onOpenDebate }: { version: number; onOpenDebate: (id: number) => void }) {
  const ideas = useApi<IdeaT[]>("/ideas", version);
  if (ideas.data?.length === 0) return <p className="muted">저장된 아이디어가 없습니다.</p>;
  return <IdeaCards ideas={ideas.data ?? []} onOpenDebate={onOpenDebate} />;
}
