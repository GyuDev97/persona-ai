import { useEffect, useMemo, useState } from "react";
import { useApi, type Debate, type IdeaT } from "../api";
import type { Nav } from "../App";
import { Async, EmptyState, fmtTime, MasterDetail, PageHeader, StatusBadge } from "../components/ui";

type Filter = "all" | "accepted" | "needs_research" | "discarded";
const FILTERS: { id: Filter; label: string }[] = [{ id: "all", label: "전체" }, { id: "accepted", label: "채택" }, { id: "needs_research", label: "추가 조사" }, { id: "discarded", label: "폐기" }];
const FEAS: Record<string, string> = { high: "높음", medium: "보통", low: "낮음" };

export default function Ideas({ version, nav }: { version: number; nav: Nav }) {
  // 폐기 항목까지 받아 두고 상태 필터·검색은 화면에서 처리한다(기존 API 그대로 사용)
  const ideas = useApi<IdeaT[]>("/ideas?status=all", version);
  const debates = useApi<Debate[]>("/debates", version);
  const [filter, setFilter] = useState<Filter>("all");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const importance = useMemo(() => new Map((debates.data ?? []).map((d) => [d.id, d.importance])), [debates.data]);
  const status = (i: IdeaT) => i.status ?? "needs_research"; // 이전 버전 데이터(null)는 추가 조사로 본다
  const ORDER: Record<string, number> = { accepted: 0, needs_research: 1, discarded: 2 };
  const rows = useMemo(() => (ideas.data ?? []).slice().sort((a, b) => ORDER[status(a)] - ORDER[status(b)] || b.id - a.id).filter((i) => (filter === "all" || status(i) === filter) && (!q.trim() || `${i.title} ${i.description} ${i.debate_title ?? ""}`.toLowerCase().includes(q.trim().toLowerCase()))), [ideas.data, filter, q]);
  const count = (f: Filter) => (ideas.data ?? []).filter((i) => f === "all" || status(i) === f).length;
  useEffect(() => {
    if (sel === null && rows.length && window.matchMedia("(min-width: 901px)").matches) setSel(rows[0].id);
  }, [rows, sel]);
  const current = (ideas.data ?? []).find((i) => i.id === sel) ?? null;

  return (
    <div className="page-inner fill">
      <PageHeader title="아이디어" desc="토론에서 나온 아이디어입니다. 채택·추가 조사·폐기 상태와 판단 근거를 확인합니다." />
      <Async q={ideas}>
        {(all) => all.length === 0 ? <div className="card"><EmptyState title="저장된 아이디어가 없습니다" desc="토론이 끝나면 아이디어가 여기에 쌓입니다." /></div> : (
          <MasterDetail hasDetail={current !== null}
            list={
              <>
                <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="제목·내용·토론 검색" aria-label="아이디어 검색" />
                <div className="row wrap">{FILTERS.map((f) => <button key={f.id} className={`sm ${filter === f.id ? "" : "secondary"}`} onClick={() => setFilter(f.id)}>{f.label} {count(f.id)}</button>)}</div>
                {rows.length === 0 && <div className="muted small" style={{ padding: 8 }}>조건에 맞는 아이디어가 없습니다.</div>}
                {rows.map((i) => (
                  <button key={i.id} className={`sel-item ${i.id === sel ? "active" : ""}`} onClick={() => setSel(i.id)}>
                    <div className="row between"><StatusBadge status={status(i)} />{importance.has(i.debate_id) && <span className="small muted">중요도 {importance.get(i.debate_id)}</span>}</div>
                    <div className="t" style={{ margin: "4px 0 2px" }}>{i.title}</div>
                    <div className="small muted" style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>{i.description}</div>
                    <div className="small muted">토론 #{i.debate_id}</div>
                  </button>
                ))}
              </>
            }
            detail={current && (
              <div className="stack">
                <div className="card">
                  <div className="row wrap"><button className="ghost back-btn" onClick={() => setSel(null)}>← 목록</button><StatusBadge status={status(current)} /><h2 className="grow">{current.title}</h2></div>
                  <p style={{ marginTop: 10, whiteSpace: "pre-wrap" }}>{current.description}</p>
                </div>
                <div className="grid g2">
                  <div className="card"><div className="card-title"><h3>판단 근거</h3></div>{current.rationale ? <p style={{ whiteSpace: "pre-wrap" }}>{current.rationale}</p> : <div className="muted">저장된 판단 근거가 없습니다.</div>}</div>
                  <div className="card"><div className="card-title"><h3>검증 상태</h3></div>
                    <dl className="kv"><dt>상태</dt><dd><StatusBadge status={status(current)} /></dd><dt>확신도</dt><dd>{Math.round(current.confidence * 100)}%</dd><dt>실현성</dt><dd>{FEAS[current.feasibility] ?? current.feasibility}</dd>
                      <dt>연결된 근거</dt><dd>{current.evidence_ids?.length ? current.evidence_ids.map((e) => `E${e}`).join(", ") : <span className="muted">없음 (증거가 연결되지 않은 일반 의견)</span>}</dd>
                      {importance.has(current.debate_id) && <><dt>토론 중요도</dt><dd>{importance.get(current.debate_id)}</dd></>}</dl></div>
                </div>
                <div className="grid g2">
                  <div className="card"><div className="card-title"><h3>위험 요소</h3></div>{current.risks.length ? <ul>{current.risks.map((r, k) => <li key={k}>{r}</li>)}</ul> : <div className="muted">기록된 위험이 없습니다.</div>}</div>
                  <div className="card"><div className="card-title"><h3>다음 단계</h3></div>{current.next_steps.length ? <ul>{current.next_steps.map((r, k) => <li key={k}>{r}</li>)}</ul> : <div className="muted">기록된 다음 단계가 없습니다.</div>}</div>
                </div>
                <div className="card"><div className="card-title"><h3>출처 및 관련 토론</h3></div>
                  <div className="row wrap"><button className="secondary wrap-btn" onClick={() => nav.openDebate(current.debate_id)}>토론 #{current.debate_id} {current.debate_title ?? ""}</button>{current.created_at && <span className="muted small">생성 {fmtTime(current.created_at)}</span>}</div></div>
              </div>
            )} />
        )}
      </Async>
    </div>
  );
}

