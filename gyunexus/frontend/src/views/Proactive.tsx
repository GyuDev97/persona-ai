import { useEffect, useState } from "react";
import { api, useApi, type ProactivePrefs, type ReminderRow, type SuggestionRow } from "../api";
import { Async, Collapse, EmptyState, fmtTime, PageHeader, StatusBadge, Tabs } from "../components/ui";

const REACTION: Record<string, string> = { interested: "관심", details: "자세히 물음", declined: "거절", snoozed: "나중에", muted: "알림 중지", chat: "일반 대화" };
const DECISION: Record<string, string> = { deliver: "전달", hold: "보류", drop: "폐기", llm_judge: "LLM 판단", llm_declined: "LLM이 보류" };
const EVENT: Record<string, string> = { dashboard_opened: "대시보드 접속", scheduled: "정시 점검", manual: "수동 점검", idea_created: "새 아이디어", reminder_due: "재알림 시점",
  worker_approval_needed: "직원 승인 필요", worker_completed: "직원 업무 완료", worker_failed: "직원 업무 실패", worker_needs_input: "직원 자료 필요" };
const TYPE: Record<string, string> = { sky_observation: "은하수 출사", idea: "토론 아이디어", worker_result: "AI 직원 결과" };
type Tab = "settings" | "history" | "reminders";

export default function Proactive({ version }: { version: number }) {
  const prefs = useApi<ProactivePrefs>("/proactive/settings", version);
  const list = useApi<SuggestionRow[]>("/proactive/suggestions?limit=60", version);
  const reminders = useApi<ReminderRow[]>("/proactive/reminders", version);
  const [tab, setTab] = useState<Tab>("history");
  const [quiet, setQuiet] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  useEffect(() => setQuiet(prefs.data?.quiet_hours ?? ""), [prefs.data?.quiet_hours]);

  const update = async (body: Record<string, unknown>) => {
    try {
      await api("/proactive/settings", { method: "PUT", json: body });
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    prefs.reload();
  };
  const p = prefs.data;
  const pendingRem = (reminders.data ?? []).filter((r) => r.status === "pending").length;
  const rows = (list.data ?? []).filter((s) => !status || s.status === status);

  return (
    <div className="page-inner">
      <PageHeader title="능동 제안" desc="GYUVIS가 먼저 말을 걸지 판단한 기록과 설정입니다. 전달하지 않은 후보도 점수와 이유가 남습니다." />
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "history", label: "제안 이력", count: list.data?.length }, { id: "reminders", label: "재알림", count: pendingRem }, { id: "settings", label: "설정" }]} />

      {tab === "settings" && (
        <div className="card stack" style={{ maxWidth: 720 }}>
          {error && <div className="notice bad">{error}</div>}
          <Async q={prefs}>
            {(pr) => (
              <>
                <label className="check"><input type="checkbox" checked={pr.enabled} onChange={(e) => update({ enabled: e.target.checked })} /><span>GYUVIS가 먼저 말 걸기<div className="small muted">끄면 어떤 제안도 보내지 않습니다.</div></span></label>
                <div className="grid g2">
                  <label className="field"><span>하루 최대 제안 횟수</span><input type="number" min={0} max={20} value={pr.daily_max} onChange={(e) => update({ daily_max: Number(e.target.value) })} /></label>
                  <form className="field" onSubmit={(e) => (e.preventDefault(), update({ quiet_hours: quiet.trim() }))}>
                    <span>조용히 할 시간대 (예: 23:00-07:00, 비우면 사용 안 함)</span>
                    <div className="row"><input className="grow" value={quiet} onChange={(e) => setQuiet(e.target.value)} /><button>저장</button></div>
                  </form>
                </div>
                <div>
                  <h4>주제별 허용</h4>
                  <div className="stack tight">
                    {Object.entries(pr.topic_labels).map(([k, label]) => <label key={k} className="check"><input type="checkbox" checked={pr.topics[k]} onChange={(e) => update({ topics: { [k]: e.target.checked } })} />{label}</label>)}
                  </div>
                </div>
              </>
            )}
          </Async>
        </div>
      )}

      {tab === "reminders" && (
        <div className="card">
          {reminders.data?.length === 0 && <EmptyState title="등록된 재알림이 없습니다" desc="제안에 ‘다음 주 금요일에 다시 알려줘’처럼 답하면 등록됩니다." />}
          {reminders.data?.map((r) => (
            <div key={r.id} className="item row between wrap">
              <div><div className="row wrap"><StatusBadge status={r.status} /><b>{fmtTime(r.due_at)}</b><span className="muted">{p?.topic_labels[r.topic_key] ?? r.topic_key}</span></div>
                <div className="small muted">{r.note}{r.attempts > 0 ? ` · 조회 실패로 ${r.attempts}회 미룸` : ""}</div></div>
              {r.status === "pending" && <button className="danger sm" onClick={() => api(`/proactive/reminders/${r.id}/cancel`, { method: "POST" }).then(reminders.reload)}>취소</button>}
            </div>
          ))}
        </div>
      )}

      {tab === "history" && (
        <>
          <div className="row"><select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="상태 필터"><option value="">모든 상태</option>
            {["delivered", "held", "dropped", "expired", "candidate"].map((s) => <option key={s} value={s}>{({ delivered: "전달됨", held: "보류", dropped: "폐기", expired: "만료", candidate: "후보" } as Record<string, string>)[s]}</option>)}</select></div>
          <Async q={list}>
            {() => (
              <div className="card">
                {rows.length === 0 && <EmptyState title="제안 기록이 없습니다" />}
                {rows.map((s) => (
                  <div key={s.id} className="item">
                    <div className="row between wrap">
                      <div className="row wrap"><StatusBadge status={s.status} /><b>#{s.id} {s.title}</b></div>
                      <span className="small muted">{fmtTime(s.created_at)}</span>
                    </div>
                    <div className="row wrap small muted" style={{ margin: "3px 0" }}>
                      <span>{TYPE[s.type] ?? s.type}</span><span>· {EVENT[s.event] ?? s.event}</span><span>· 점수 {s.score ?? "-"}</span><span>· 신뢰 {s.confidence}</span>
                      {s.decision && <span>· 판단 {DECISION[s.decision] ?? s.decision}</span>}{s.reaction && <span>· 사용자 반응 {REACTION[s.reaction] ?? s.reaction}</span>}
                    </div>
                    <div className="small">{s.decision_reason}</div>
                    <div style={{ marginTop: 4 }}><Collapse title={<span className="small muted">점수 구성·근거 보기</span>}>
                      <pre>{JSON.stringify({ reason: s.reason, needed_action: s.needed_action, valid_until: s.valid_until, score_detail: s.score_detail }, null, 2)}</pre></Collapse></div>
                  </div>
                ))}
              </div>
            )}
          </Async>
        </>
      )}
    </div>
  );
}
