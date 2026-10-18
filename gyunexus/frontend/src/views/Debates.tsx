import { useEffect, useState } from "react";
import { useApi, type Claim, type Debate, type DebateDetail } from "../api";
import type { Nav } from "../App";
import { Async, Collapse, EmptyState, fmtTime, MasterDetail, MODE_LABEL, PageHeader, StatusBadge } from "../components/ui";

export const AGENT_NAMES: Record<string, string> = { research: "Research", idea: "Idea", developer: "Developer", critic: "Critic" };
const CLAIM_LABEL: Record<Claim["status"], string> = {
  verified: "검증됨", unverified: "미검증", interpretation: "해석", assumption: "추정", proposal: "제안", conflicted: "증거와 충돌", rebuttal: "반박", endorsed: "인정", opinion: "의견",
};
const CLAIM_TONE: Record<string, string> = { verified: "ok", endorsed: "ok", conflicted: "bad", rebuttal: "bad", unverified: "warn", assumption: "warn" };
const STOP_LABEL: Record<string, string> = {
  consensus: "합의", needs_research: "추가 조사 필요", stagnation: "정체", max_rounds: "최대 라운드", token_budget: "토큰 예산", daily_budget: "일일 예산", llm_errors: "LLM 오류",
};
const DECISION: Record<string, string> = { adopt: "채택 권고", revise: "수정 후 재검토", reject: "채택하지 않음", defer: "보류" };

export default function Debates({ version, nav }: { version: number; nav: Nav }) {
  const list = useApi<Debate[]>("/debates", version);
  const [selected, setSelected] = useState<number | null>(nav.focusDebate);
  useEffect(() => setSelected(nav.focusDebate), [nav.focusDebate]);
  useEffect(() => {
    if (selected === null && list.data?.length && window.matchMedia("(min-width: 901px)").matches) setSelected(list.data[0].id);
  }, [list.data, selected]);

  return (
    <div className="page-inner fill">
      <PageHeader title="토론" desc="에이전트들의 토론 목록입니다. 선택하면 결론부터 근거와 발언 기록까지 볼 수 있습니다." />
      <Async q={list}>
        {(rows) => rows.length === 0 ? <div className="card"><EmptyState title="아직 토론이 없습니다" desc="상단의 ‘지금 토론’을 누르거나 에이전트 화면에서 주제를 직접 던져 보세요." /></div> : (
          <MasterDetail hasDetail={selected !== null}
            list={rows.map((d) => (
              <button key={d.id} className={`sel-item ${d.id === selected ? "active" : ""}`} onClick={() => setSelected(d.id)}>
                <div className="t">#{d.id} {d.title}</div>
                <div className="row wrap" style={{ margin: "4px 0" }}><StatusBadge status={d.status} /><span className="badge plain">{MODE_LABEL[d.trigger] ?? d.trigger}</span></div>
                <div className="small muted">{d.participants.map((p) => AGENT_NAMES[p] ?? p).join(" · ")}</div>
                <div className="small muted">{fmtTime(d.started_at)} · {d.tokens_used.toLocaleString()} tokens · ${d.cost_usd.toFixed(4)}</div>
              </button>
            ))}
            detail={selected !== null ? <DebateView id={selected} version={version} nav={nav} onBack={() => setSelected(null)} /> : null} />
        )}
      </Async>
    </div>
  );
}

function Refs({ ids }: { ids: number[] }) {
  return ids.length ? <span className="muted small"> [{ids.map((e) => `E${e}`).join(", ")}]</span> : null;
}

function DebateView({ id, version, nav, onBack }: { id: number; version: number; nav: Nav; onBack: () => void }) {
  const q = useApi<DebateDetail>(`/debates/${id}`, version);
  const d = q.data;
  if (!d || d.id !== id) return <Async q={q}>{() => null}</Async>;
  const r = d.result;
  const warnings = r?.warnings ?? [];
  const ideas = d.ideas;
  return (
    <div className="stack">
      <div className="card">
        <div className="row wrap"><button className="ghost back-btn" onClick={onBack}>← 목록</button><h2 className="grow">#{d.id} {d.title}</h2><StatusBadge status={d.status} /></div>
        <div className="row wrap small muted" style={{ marginTop: 6 }}>
          <span>{MODE_LABEL[d.trigger] ?? d.trigger}</span><span>· 참여 {d.participants.map((p) => AGENT_NAMES[p] ?? p).join(", ")}</span><span>· 라운드 {d.rounds_done}/{d.max_rounds}</span>
          {d.stop_reason && <span>· 종료: {STOP_LABEL[d.stop_reason] ?? d.stop_reason}</span>}<span>· {fmtTime(d.started_at)}</span>
        </div>
        {d.goal && <div className="small" style={{ marginTop: 6 }}>목표: {d.goal}</div>}
        {d.error && <div className="notice bad" style={{ marginTop: 8 }}>{d.error}</div>}
      </div>

      {/* 1. 최종 결론 */}
      <div className="card conclusion">
        <div className="card-title"><h3>최종 결론</h3>{r && <div className="row"><span className="badge plain info">{DECISION[r.decision] ?? r.decision}</span><span className="badge plain">중요도 {d.importance}</span></div>}</div>
        {r ? <p style={{ whiteSpace: "pre-wrap" }}>{r.summary}</p> : <div className="muted">{d.status === "running" ? "토론 진행 중입니다. 결론은 종합 단계가 끝나면 표시됩니다." : "저장된 결론이 없습니다."}</div>}
        {r && r.open_questions.length > 0 && <><h4>열린 질문</h4><ul>{r.open_questions.map((c, i) => <li key={i}>{c}</li>)}</ul></>}
      </div>

      {/* 2. 주요 아이디어 */}
      {ideas.length > 0 && (
        <div className="card">
          <div className="card-title"><h3>주요 아이디어</h3><button className="link" onClick={() => nav.go("ideas")}>아이디어 화면</button></div>
          {ideas.map((i) => (
            <div key={i.id} className="item">
              <div className="row wrap"><StatusBadge status={i.status ?? "needs_research"} /><b>{i.title}</b></div>
              <div className="muted small">{i.description}</div>
              {i.rationale && <div className="small muted">판정 근거: {i.rationale}</div>}
            </div>
          ))}
        </div>
      )}

      {/* 3. 검증된 사실 / 불확실한 주장 */}
      {r && (r.verified_facts.length > 0 || r.unverified_claims.length > 0) && (
        <div className="grid g2">
          <div className="card"><div className="card-title"><h3>검증된 사실</h3><span className="badge plain ok">{r.verified_facts.length}</span></div>
            {r.verified_facts.length === 0 ? <div className="muted small">없음</div> : <ul>{r.verified_facts.map((f, i) => <li key={i}>{f.text}<Refs ids={f.evidence_ids} /></li>)}</ul>}</div>
          <div className="card"><div className="card-title"><h3>불확실한 주장</h3><span className="badge plain warn">{r.unverified_claims.length}</span></div>
            {r.unverified_claims.length === 0 ? <div className="muted small">없음</div> : <ul>{r.unverified_claims.map((c, i) => <li key={i}>{c}</li>)}</ul>}</div>
        </div>
      )}

      {/* 4. 근거와 경고 */}
      {(warnings.length > 0 || d.evidence.length > 0) && (
        <div className="card">
          <div className="card-title"><h3>근거와 경고</h3></div>
          {warnings.map((w, i) => <div key={i} className="notice" style={{ marginBottom: 6 }}>{w}</div>)}
          {d.evidence.map((e) => (
            <div key={e.id} className="item small"><b>E{e.id}</b> {e.tool} <span className="muted">{e.source}</span><div className="muted">{e.summary.slice(0, 300)}</div></div>
          ))}
        </div>
      )}

      {/* 5. 에이전트별 발언 기록 */}
      <Collapse title="에이전트 발언 기록" aside={`${d.messages.length}건`}>
        {d.messages.map((m) => (
          <div key={m.id} className={`turn ${m.agent_id}`}>
            <div className="small muted">R{m.round} · {AGENT_NAMES[m.agent_id] ?? m.agent_id}</div>
            <div style={{ whiteSpace: "pre-wrap" }}>{m.content}</div>
            {m.claims.map((c, i) => <div key={i} className="claim"><span className={`badge plain ${CLAIM_TONE[c.status] ?? ""}`}>{CLAIM_LABEL[c.status]}</span> {c.text}<Refs ids={c.evidence_ids} /></div>)}
          </div>
        ))}
        {d.messages.length === 0 && <div className="muted">발언 기록이 없습니다.</div>}
        {d.status === "running" && <p className="muted">토론 진행 중…</p>}
      </Collapse>

      {/* 6. 실행 추적 및 사용량 (저장된 원문 전체) */}
      <Collapse title="실행 추적 및 사용량" aside={`${d.tokens_used.toLocaleString()} tokens · $${d.cost_usd.toFixed(4)}`}>
        <dl className="kv"><dt>시작</dt><dd>{fmtTime(d.started_at)}</dd><dt>종료</dt><dd>{fmtTime(d.ended_at)}</dd><dt>토큰</dt><dd>{d.tokens_used.toLocaleString()}</dd><dt>비용</dt><dd>${d.cost_usd.toFixed(5)}</dd><dt>사용자 전달</dt><dd>{fmtTime(d.delivered_at)}</dd></dl>
        <h4>에이전트 선정·진행 기록 (원문)</h4>
        <pre>{JSON.stringify({ plan: d.plan, progress: d.progress }, null, 2)}</pre>
        <h4>저장된 토론 전체 데이터 (원문)</h4>
        <pre>{JSON.stringify({ ...d, messages: undefined }, null, 2)}</pre>
      </Collapse>
    </div>
  );
}
