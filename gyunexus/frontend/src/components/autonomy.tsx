import type { ReactNode } from "react";
import type { AutonomyView, ExecMode, TriggerKind, TriggerRow } from "../api";
import { fmtTime } from "./ui";

/** 자율 실행 화면들이 함께 쓰는 이름·설명·작은 조각. 판정(권한·위험도·비용)은 모두 서버가 코드로 하고, 여기서는 표시만 한다. */

export const MODE_NAME: Record<ExecMode, string> = { manual: "수동", supervised: "감독 자동", autonomous: "자율" };
export const MODE_DESC: Record<ExecMode, string> = {
  manual: "계획만 만들고, 사용자가 확인한 뒤 직접 실행합니다(기존 방식).",
  supervised: "검증을 통과한 계획을 자동으로 시작합니다. 승인이 필요한 업무는 사용자 승인 전에 멈춥니다.",
  autonomous: "감독 자동에 더해, 읽기 전용 직원의 검증을 통과한 결과물은 자동 승인합니다. 쓰기·외부 작업은 항상 사용자 승인이 필요합니다.",
};
export const KIND_NAME: Record<TriggerKind, string> = { once: "한 번 예약", interval: "반복 간격", daily: "매일 정시", event: "이벤트", proactive: "능동 제안", chain: "선행 업무 완료" };
export const ORIGIN_NAME: Record<string, string> = { user: "직접 요청", chat: "GYUVIS 대화", schedule: "예약", event: "이벤트", proactive: "능동 제안", chain: "선행 업무 완료" };
export const SKIP_NAME: Record<string, string> = {
  disabled: "자율 운영 꺼짐", trigger_disabled: "트리거 비활성", cooldown: "쿨다운 중", already_running: "이미 진행 중", duplicate_goal: "같은 목표 진행 중",
  daily_limit: "하루 실행 횟수 도달", concurrency: "동시 실행 한도", daily_budget: "일일 비용 한도", trigger_budget: "트리거 비용 한도", loop_guard: "연쇄 반복 차단", missed: "예정 시각 경과",
};
export const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];

export function describeTrigger(t: Pick<TriggerRow, "kind" | "config">): string {
  const c = t.config as Record<string, unknown>;
  switch (t.kind) {
    case "interval": return `${String(c.minutes)}분마다`;
    case "daily": return `매일 ${String(c.time)}${Array.isArray(c.weekdays) && c.weekdays.length ? ` (${(c.weekdays as number[]).map((d) => WEEKDAYS[d]).join("·")})` : ""}`;
    case "once": return `${fmtTime(String(c.run_at))} 한 번`;
    case "event": return `이벤트 '${String(c.event)}'`;
    case "proactive": return c.topic_key === "*" ? "모든 능동 제안 전달 시" : `능동 제안(${String(c.topic_key)}) 전달 시`;
    case "chain": return c.after_trigger_id ? `트리거 #${String(c.after_trigger_id)} 완료 후` : `워크플로 #${String(c.after_workflow_id)} 완료 후`;
  }
}

export function ModeBadge({ mode }: { mode: ExecMode }) {
  return <span className={`badge plain ${mode === "autonomous" ? "warn" : mode === "supervised" ? "info" : ""}`} title={MODE_DESC[mode]}>{MODE_NAME[mode]}</span>;
}

export function ModeSelect({ value, onChange, max, disabled, label = "실행 모드" }: { value: ExecMode; onChange: (m: ExecMode) => void; max?: ExecMode; disabled?: boolean; label?: string }) {
  const order: ExecMode[] = ["manual", "supervised", "autonomous"];
  const limit = max ? order.indexOf(max) : 2;
  return (
    <select value={value} disabled={disabled} aria-label={label} onChange={(e) => onChange(e.target.value as ExecMode)}>
      {order.map((m, i) => <option key={m} value={m} disabled={i > limit}>{MODE_NAME[m]}{i > limit ? " (허용 범위 밖)" : ""}</option>)}
    </select>
  );
}

/** 워크플로 상세의 자동 실행 상태 카드: 시작 사유, 현재 담당 직원, 다음 단계, 사용자 확인이 필요한 이유. */
export function AutonomyPanel({ a, status, children }: { a: AutonomyView; status: string; children?: ReactNode }) {
  const live = status === "running";
  return (
    <div className="card stack tight" aria-label="자동 실행 상태">
      <div className="card-title"><h3>자동 실행 상태</h3><div className="row wrap"><ModeBadge mode={a.mode} />{a.auto_started && <span className="badge plain ok">자동 시작됨</span>}</div></div>
      <dl className="kv">
        <dt>시작 방식</dt><dd>{ORIGIN_NAME[a.origin] ?? a.origin}{a.trigger ? ` · 트리거 '${a.trigger.name}'` : ""}</dd>
        {a.trigger_reason && <><dt>시작 사유</dt><dd>{a.trigger_reason}</dd></>}
        <dt>현재 담당</dt>
        <dd>{a.current.length ? a.current.map((c) => <div key={c.key}>👤 {c.worker} — {c.title} <span className="muted small">({c.status === "awaiting_approval" ? "승인 대기" : "실행 중"})</span></div>) : <span className="muted">{live ? "다음 단계를 준비 중입니다" : "없음"}</span>}</dd>
        <dt>다음 단계</dt>
        <dd>{a.next.length ? a.next.map((n) => <div key={n.key}>{n.title} <span className="muted small">— {n.worker}{n.waiting_for.length ? ` · 선행 ${n.waiting_for.join(", ")} 대기` : " · 곧 시작"}</span></div>) : <span className="muted">없음</span>}</dd>
        {a.mode !== "manual" && <><dt>자동 재시도</dt><dd>{a.auto_retries}/{a.retry_limit}회 <span className="muted small">(일시적 실패만, 상한 도달 시 사용자 판단)</span></dd></>}
      </dl>
      {a.attention.length > 0 && (
        <div className="notice" role="status">
          <b>사용자 확인이 필요합니다</b>
          <ul style={{ margin: "4px 0 0", paddingLeft: 18 }}>{a.attention.map((t, i) => <li key={i}>{t}</li>)}</ul>
        </div>
      )}
      {a.mode !== "manual" && a.decision.reason && !a.attention.length && <div className="small muted">정책 판정: {a.decision.reason}</div>}
      {children}
    </div>
  );
}
