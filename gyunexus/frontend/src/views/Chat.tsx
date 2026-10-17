import { useEffect, useRef, useState } from "react";
import { api, useApi, type ChatTrace, type Conversation, type Message } from "../api";

const fmt = (topic: string | null, slots: Record<string, unknown>) =>
  [topic, ...Object.entries(slots).map(([k, v]) => `${k}=${String(v)}`)].filter(Boolean).join(", ");

/** 응답이 만들어진 과정(LLM 호출, 사용한 기억, 도구 호출, 조회하지 못한 데이터)을 보여준다. */
function TraceView({ trace }: { trace: ChatTrace }) {
  const llm = trace.llm;
  return (
    <details className="trace">
      <summary>처리 과정</summary>
      <div>LLM 호출: {llm?.called ? `예 (${llm.model}, ${llm.tokens} tokens, ${llm.latency_ms}ms, 이전 대화 ${llm.history_messages}건)` : "아니오"}</div>
      {trace.routing && (
        <>
          <div>
            해석된 의도: {trace.routing.intent} ({trace.routing.interpreted_by === "llm" ? "LLM 해석" : "규칙"}) — {trace.routing.reason}
          </div>
          <div>이전 상태: {trace.routing.prior_state ? fmt(trace.routing.prior_state.topic, trace.routing.prior_state.slots) : "없음"}</div>
          <div>
            변경된 조건:{" "}
            {Object.keys(trace.routing.changes).length === 0
              ? "없음"
              : Object.entries(trace.routing.changes).map(([k, v]) => `${k}: ${String(v.from ?? "-")} → ${String(v.to ?? "-")}`).join(", ")}
          </div>
          {trace.routing.merged_state && (
            <div>
              최종 조건: {fmt(trace.routing.merged_state.topic, trace.routing.merged_state.slots)}
              {trace.routing.merged_state.missing_fields.length > 0 && ` · 부족한 정보: ${trace.routing.merged_state.missing_fields.join(", ")}`}
            </div>
          )}
          {trace.routing.advice.map((a, i) => <div key={i} className="muted">· 참고: {a}</div>)}
        </>
      )}
      <div>도구 호출 {trace.tools.length === 0 && ": 없음"}</div>
      {trace.tools.map((t, i) => (
        <div key={i} className="muted">
          · {t.name} → {t.status}
          {t.error_kind ? ` [${t.error_kind}, ${t.attempts}회 시도]` : t.error ? ` (${t.error})` : ""}
          {t.reason && ` — ${t.reason}`}
          {t.result && ` — ${Object.entries(t.result).map(([k, v]) => `${k}=${String(v)}`).join(", ")}`}
        </div>
      ))}
      <div>사용한 기억 {trace.memories.length}건{trace.memories.map((m) => <div key={m.id} className="muted">· {m.content}</div>)}</div>
      {trace.missing_data.length > 0 && (
        <div>조회하지 못한 데이터{trace.missing_data.map((d, i) => <div key={i} className="muted">· {d}</div>)}</div>
      )}
    </details>
  );
}

interface Props {
  version: number;
  onOpenDebate: (id: number) => void;
  llmConfigured: boolean;
}

export default function Chat({ version, onOpenDebate, llmConfigured }: Props) {
  const convs = useApi<Conversation[]>("/conversations", version);
  const [convId, setConvId] = useState<number | null>(null);
  const [pendingText, setPendingText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
  const msgs = useApi<Message[]>(convId ? `/conversations/${convId}/messages` : null, version);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (convId === null && convs.data && convs.data.length > 0) setConvId(convs.data[0].id);
  }, [convs.data, convId]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
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

  const remove = async (id: number) => {
    await api(`/conversations/${id}`, { method: "DELETE" });
    if (id === convId) setConvId(null);
    convs.reload();
  };

  return (
    <div className="chat">
      <aside>
        <button onClick={() => setConvId(null)}>＋ 새 대화</button>
        {convs.data?.map((c) => (
          <div key={c.id} className={`conv ${c.id === convId ? "active" : ""}`} onClick={() => setConvId(c.id)}>
            <span>{c.title}</span>
            <button className="x" onClick={(e) => (e.stopPropagation(), remove(c.id))} title="삭제">×</button>
          </div>
        ))}
      </aside>
      <section>
        <div className="messages">
          {!convId && pendingText === null && <p className="muted center">GYUVIS에게 말을 걸어보세요.</p>}
          {msgs.data?.map((m) => (
            <div key={m.id} className={`msg ${m.role}`}>
              {m.proactive && (
                <div className="tag">
                  GYUVIS가 먼저 말을 걸었어요
                  {m.meta.debate_id && (
                    <button className="link" onClick={() => onOpenDebate(m.meta.debate_id!)}>토론 #{m.meta.debate_id} 보기</button>
                  )}
                </div>
              )}
              {m.content}
              {m.meta.trace && <TraceView trace={m.meta.trace} />}
            </div>
          ))}
          {pendingText !== null && (
            <>
              {!msgs.data?.some((m) => m.content === pendingText) && <div className="msg user">{pendingText}</div>}
              <div className="msg assistant muted">…</div>
            </>
          )}
          <div ref={bottom} />
        </div>
        {error && <div className="notice">{error}</div>}
        {!llmConfigured && <div className="notice">OPENAI_API_KEY가 설정되지 않아 대화할 수 없습니다. README를 참고하세요.</div>}
        <form onSubmit={(e) => (e.preventDefault(), send())}>
          <textarea
            value={text}
            placeholder="메시지를 입력하세요 (Enter 전송, Shift+Enter 줄바꿈)"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && (e.preventDefault(), send())}
            rows={2}
          />
          <button disabled={pendingText !== null || !text.trim()}>전송</button>
        </form>
      </section>
    </div>
  );
}
