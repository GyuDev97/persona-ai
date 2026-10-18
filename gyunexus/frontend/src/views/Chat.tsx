import { useEffect, useRef, useState } from "react";
import { api, useApi, type ChatTrace, type Conversation, type Message } from "../api";
import type { Nav } from "../App";
import { DeleteConfirmDialog } from "../components/crud/DeleteConfirmDialog";
import { EmptyState, fmtAgo, Icon, PageHeader } from "../components/ui";

const fmt = (topic: string | null, slots: Record<string, unknown>) =>
  [topic, ...Object.entries(slots).map(([k, v]) => `${k}=${String(v)}`)].filter(Boolean).join(", ");

/** 응답이 만들어진 과정(LLM 호출, 사용한 기억, 도구 호출, 조회하지 못한 데이터). 기본은 접혀 있다. */
function TraceView({ trace }: { trace: ChatTrace }) {
  const llm = trace.llm;
  return (
    <details className="trace">
      <summary>처리 과정</summary>
      <div>LLM 호출: {llm?.called ? `예 (${llm.model}, ${llm.tokens} tokens, ${llm.latency_ms}ms, 이전 대화 ${llm.history_messages}건)` : "아니오"}</div>
      {trace.routing && (
        <>
          <div>해석된 의도: {trace.routing.intent} ({trace.routing.interpreted_by === "llm" ? "LLM 해석" : "규칙"}) — {trace.routing.reason}</div>
          <div>이전 상태: {trace.routing.prior_state ? fmt(trace.routing.prior_state.topic, trace.routing.prior_state.slots) : "없음"}</div>
          <div>변경된 조건: {Object.keys(trace.routing.changes).length === 0 ? "없음" : Object.entries(trace.routing.changes).map(([k, v]) => `${k}: ${String(v.from ?? "-")} → ${String(v.to ?? "-")}`).join(", ")}</div>
          {trace.routing.merged_state && (
            <div>최종 조건: {fmt(trace.routing.merged_state.topic, trace.routing.merged_state.slots)}{trace.routing.merged_state.missing_fields.length > 0 && ` · 부족한 정보: ${trace.routing.merged_state.missing_fields.join(", ")}`}</div>
          )}
          {trace.routing.advice.map((a, i) => <div key={i}>· 참고: {a}</div>)}
        </>
      )}
      <div>도구 호출 {trace.tools.length === 0 && ": 없음"}</div>
      {trace.tools.map((t, i) => (
        <div key={i}>· {t.name} → {t.status}{t.error_kind ? ` [${t.error_kind}, ${t.attempts}회 시도]` : t.error ? ` (${t.error})` : ""}{t.reason && ` — ${t.reason}`}{t.result && ` — ${Object.entries(t.result).map(([k, v]) => `${k}=${String(v)}`).join(", ")}`}</div>
      ))}
      <div>사용한 기억 {trace.memories.length}건{trace.memories.map((m) => <div key={m.id}>· {m.content}</div>)}</div>
      {trace.missing_data.length > 0 && <div>조회하지 못한 데이터{trace.missing_data.map((d, i) => <div key={i}>· {d}</div>)}</div>}
    </details>
  );
}

const PRO_LABEL: Record<string, string> = { worker_result: "AI 직원 업무 알림", suggestion: "GYUVIS 능동 제안", idea: "토론 아이디어 제안" };

export default function Chat({ version, nav, llmConfigured }: { version: number; nav: Nav; llmConfigured: boolean }) {
  const convs = useApi<Conversation[]>("/conversations", version);
  const [convId, setConvId] = useState<number | null>(null);
  const [pendingText, setPendingText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [mobileList, setMobileList] = useState(false);
  const [del, setDel] = useState<Conversation | null>(null);
  const msgs = useApi<Message[]>(convId ? `/conversations/${convId}/messages` : null, version);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (convId === null && convs.data && convs.data.length > 0) setConvId(convs.data[0].id);
  }, [convs.data, convId]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs.data, pendingText]);

  const send = async () => {
    const message = text.trim();
    if (!message || pendingText !== null) return;
    setText("");
    setError(null);
    setPendingText(message);
    try {
      const res = await api<{ conversation_id: number }>("/chat", { method: "POST", json: { message, conversation_id: convId } });
      setConvId(res.conversation_id);
      convs.reload();
      msgs.reload();
    } catch (e) {
      setError((e as Error).message);
      setText(message);
    } finally {
      setPendingText(null);
    }
  };
  const remove = async () => {
    if (!del) return;
    await api(`/conversations/${del.id}`, { method: "DELETE" });
    if (del.id === convId) setConvId(null);
    setDel(null);
    convs.reload();
  };
  const current = convs.data?.find((c) => c.id === convId);

  return (
    <div className="page-inner fill">
      <PageHeader title="대화" desc="GYUVIS와 대화합니다. 먼저 말을 거는 능동 제안도 여기에 표시됩니다." />
      <div className={`chat-wrap ${mobileList ? "" : "has-detail"}`}>
        <aside className="side card stack tight" style={{ padding: 10, overflowY: "auto" }}>
          <button onClick={() => (setConvId(null), setMobileList(false))}><Icon name="plus" size={15} />새 대화</button>
          {convs.data?.length === 0 && <div className="muted small" style={{ padding: 8 }}>아직 대화가 없습니다.</div>}
          {convs.data?.map((c) => (
            <div key={c.id} className="conv-row">
              <button className={`sel-item ${c.id === convId ? "active" : ""}`} onClick={() => (setConvId(c.id), setMobileList(false))}>
                <div className="t">{c.title}</div><div className="small muted">{fmtAgo(c.updated_at)}</div>
              </button>
              <button className="ghost sm del" onClick={() => setDel(c)} aria-label={`${c.title} 삭제`}>✕</button>
            </div>
          ))}
        </aside>
        <section className="chat-main">
          <div className="chat-head">
            <button className="ghost back-btn" onClick={() => setMobileList(true)}>← 대화 목록</button><span className="av" aria-hidden="true">G</span>
            <b className="grow" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{current?.title ?? "새 대화"}</b>
          </div>
          <div className="messages">
            {!convId && pendingText === null && <EmptyState title="GYUVIS에게 말을 걸어보세요" desc="날씨·천문 조회, 기억 활용, 직원 결과 확인 등을 물어볼 수 있습니다." />}
            {msgs.data?.map((m) => (
              <div key={m.id} className={`msg-row ${m.role}`}>
              {m.role !== "user" && <span className={`av ${m.proactive && m.meta.kind === "worker_result" ? "work" : m.proactive ? "sug" : ""}`} aria-hidden="true">{m.proactive && m.meta.kind === "worker_result" ? "AI" : "G"}</span>}
              <div className={`msg ${m.role} ${m.proactive ? `proactive ${m.meta.kind ?? ""}` : ""}`}>
                {m.proactive && (
                  <div className="tag">{m.meta.kind === "worker_result" ? "AI 직원" : "✦"} {PRO_LABEL[m.meta.kind ?? ""] ?? "GYUVIS가 먼저 말을 걸었어요"}</div>
                )}
                {m.content}
                {m.proactive && (m.meta.debate_id || m.meta.run_id || m.meta.suggestion_id) && (
                  <div className="links">
                    {m.meta.debate_id && <button className="link" onClick={() => nav.openDebate(m.meta.debate_id!)}>토론 #{m.meta.debate_id} 보기</button>}
                    {m.meta.run_id && <button className="link" onClick={() => nav.go("workers")}>직원 결과 보기 (실행 #{m.meta.run_id})</button>}
                    {m.meta.suggestion_id && <button className="link" onClick={() => nav.go("proactive")}>판단 기록</button>}
                  </div>
                )}
                {m.meta.trace && <TraceView trace={m.meta.trace} />}
              </div>
              </div>
            ))}
            {pendingText !== null && (
              <>
                {!msgs.data?.some((m) => m.content === pendingText) && <div className="msg-row user"><div className="msg user">{pendingText}</div></div>}
                <div className="msg-row"><span className="av" aria-hidden="true">G</span><div className="msg assistant muted" role="status" aria-label="응답 작성 중">…</div></div>
              </>
            )}
            <div ref={bottom} />
          </div>
          {error && <div className="notice bad" style={{ margin: "0 12px 8px" }}>{error}</div>}
          {!llmConfigured && <div className="notice" style={{ margin: "0 12px 8px" }}>OPENAI_API_KEY가 설정되지 않아 대화할 수 없습니다. README를 참고하세요.</div>}
          <form className="composer" onSubmit={(e) => (e.preventDefault(), send())}>
            <textarea value={text} placeholder="메시지를 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)" onChange={(e) => setText(e.target.value)} aria-label="메시지 입력"
              onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && (e.preventDefault(), send())} rows={2} />
            <button disabled={pendingText !== null || !text.trim()}>전송</button>
          </form>
        </section>
      </div>
      <DeleteConfirmDialog open={!!del} title="대화를 삭제할까요?" itemName={del?.title ?? ""} action="삭제" impact={["이 대화의 메시지가 모두 삭제됩니다"]} recovery={{ reversible: false, note: "삭제한 대화와 메시지는 되돌릴 수 없습니다." }} onCancel={() => setDel(null)} onConfirm={remove} />
    </div>
  );
}
