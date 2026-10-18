import { useEffect, type ReactNode } from "react";

/** 공통 UI 조각. 화면마다 따로 만들지 않도록 상태 표시·모달·탭·빈 상태 등을 한 곳에 둔다. */

export type Tone = "ok" | "info" | "warn" | "bad" | "muted";

// 서버 상태 코드 -> [사용자용 이름, 색]. 모든 화면이 같은 상태에 같은 이름·색을 쓴다.
export const STATUS: Record<string, [string, Tone]> = {
  idle: ["대기", "muted"], thinking: ["실행 중", "info"], running: ["실행 중", "info"], reviewing: ["검토 중", "info"], pending: ["대기", "warn"],
  queued: ["대기열", "muted"], completed: ["완료", "ok"], done: ["완료", "ok"], delivered: ["전달됨", "ok"], executed: ["실행됨", "ok"],
  failed: ["실패", "bad"], error: ["오류", "bad"], rejected: ["반려", "bad"], cancelled: ["취소", "muted"], dropped: ["폐기", "muted"], expired: ["만료", "muted"],
  held: ["보류", "warn"], candidate: ["후보", "info"], awaiting_approval: ["승인 대기", "warn"], needs_input: ["자료 필요", "warn"],
  active: ["활성", "ok"], paused: ["일시정지", "warn"], disabled: ["비활성", "muted"], working: ["작업 중", "info"], waiting_approval: ["승인 대기", "warn"],
  accepted: ["채택", "ok"], needs_research: ["추가 조사", "warn"], discarded: ["폐기", "muted"],
  planned: ["계획 확인 대기", "info"], fired: ["발송됨", "ok"], info: ["정보", "muted"], warn: ["경고", "warn"],
};
export const MODE_LABEL: Record<string, string> = { manual: "수동", schedule: "자율", event: "이벤트", scheduled: "정기", discovery: "자동 발굴" };

export function StatusBadge({ status, label, tone, pulse }: { status: string; label?: string; tone?: Tone; pulse?: boolean }) {
  const [text, t] = STATUS[status] ?? [status, "muted" as Tone];
  const live = pulse ?? ["thinking", "running", "reviewing", "working"].includes(status);
  return <span className={`badge ${tone ?? t} ${live ? "pulse" : ""}`}>{label ?? text}</span>;
}

export function PageHeader({ title, desc, actions }: { title: string; desc?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h2>{title}</h2>
        {desc && <p>{desc}</p>}
      </div>
      {actions && <div className="row wrap">{actions}</div>}
    </div>
  );
}

export function EmptyState({ title, desc, action }: { title: string; desc?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <b>{title}</b>
      {desc && <div>{desc}</div>}
      {action}
    </div>
  );
}
export const LoadingState = ({ label = "불러오는 중…" }: { label?: string }) => (
  <div className="empty" role="status"><div className="spinner" />{label}</div>
);
export const ErrorState = ({ message, onRetry }: { message: string; onRetry?: () => void }) => (
  <div className="empty" role="alert"><b>불러오지 못했습니다</b><div className="muted">{message}</div>{onRetry && <button className="secondary" onClick={onRetry}>다시 시도</button>}</div>
);
/** data/error/reload 를 받아 로딩·오류·내용을 고른다. */
export function Async<T>({ q, children }: { q: { data: T | null; error: string | null; reload: () => void }; children: (d: T) => ReactNode }) {
  if (q.data !== null) return <>{children(q.data)}</>;
  return q.error ? <ErrorState message={q.error} onRetry={q.reload} /> : <LoadingState />;
}

export function Modal({ open, title, onClose, children, footer, size }: { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; size?: "narrow" | "wide" }) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${size ?? ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h3>{title}</h3><button className="ghost" onClick={onClose} aria-label="닫기">✕</button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function ConfirmDialog({ open, title, message, confirmLabel = "확인", danger, onConfirm, onCancel }: {
  open: boolean; title: string; message: ReactNode; confirmLabel?: string; danger?: boolean; onConfirm: () => void; onCancel: () => void;
}) {
  return (
    <Modal open={open} title={title} onClose={onCancel} size="narrow"
      footer={<><button className="secondary" onClick={onCancel}>취소</button><button className={danger ? "danger solid" : ""} onClick={onConfirm}>{confirmLabel}</button></>}>
      <div>{message}</div>
    </Modal>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string; count?: number }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={t.id === value} className={`tab ${t.id === value ? "active" : ""}`} onClick={() => onChange(t.id)}>
          {t.label}{t.count !== undefined && <span className="n">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Collapse({ title, aside, open, children }: { title: ReactNode; aside?: ReactNode; open?: boolean; children: ReactNode }) {
  return (
    <details className="collapse" open={open}>
      <summary><span className="grow">{title}</span>{aside && <span className="muted small">{aside}</span>}</summary>
      <div className="collapse-body">{children}</div>
    </details>
  );
}

/** 목록(왼쪽) + 상세(오른쪽). 좁은 화면에서는 선택하면 상세만 보이고 ‘← 목록’으로 돌아온다. */
export function MasterDetail({ list, detail, hasDetail }: { list: ReactNode; detail: ReactNode; hasDetail: boolean }) {
  return (
    <div className={`md ${hasDetail ? "has-detail" : ""}`}>
      <div className="list card">{list}</div>
      <div className="detail">{detail}</div>
    </div>
  );
}

export function Field({ label, required, children, hint }: { label: string; required?: boolean; children: ReactNode; hint?: string }) {
  return <label className="field"><span>{label}{required && <span className="req"> *</span>}</span>{children}{hint && <span className="small">{hint}</span>}</label>;
}

export const toDate = (iso: string) => new Date(iso + (iso.endsWith("Z") ? "" : "Z"));
export const fmtTime = (iso: string | null | undefined) => (iso ? toDate(iso).toLocaleString("ko-KR", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "-");
export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "기록 없음";
  const s = Math.max(0, (Date.now() - toDate(iso).getTime()) / 1000);
  if (s < 60) return "방금 전";
  if (s < 3600) return `${Math.floor(s / 60)}분 전`;
  if (s < 86400) return `${Math.floor(s / 3600)}시간 전`;
  return `${Math.floor(s / 86400)}일 전`;
}

// 로그 이벤트 코드 -> 사용자용 이름(없으면 코드를 그대로 보여 준다)
export const EVENT_LABEL: Record<string, string> = {
  startup: "서버 시작", "settings.changed": "설정 변경", "budget.exhausted": "일일 예산 소진", "debate.due": "토론 시각 도래", "debate.plan": "참여 에이전트 선정",
  "debate.started": "토론 시작", "debate.completed": "토론 완료", "debate.failed": "토론 실패", "debate.delivered": "토론 결과 전달", "topic.queued": "주제 등록",
  "topic.focus": "주제 선택", "topic.semantic_duplicate": "유사 주제 건너뜀", "topic.dedupe_failed": "주제 중복 검사 실패", "topic.discovery_exhausted": "새 주제를 찾지 못함",
  "turn.failed": "발언 생성 실패", "critic.rejected": "Critic 반박 기각", "critic.retry": "Critic 재작성", "consensus.ignored": "합의 무시", "synthesis.skipped": "종합 건너뜀",
  "plan.llm_failed": "계획 LLM 실패", "preserved.dropped": "보존 항목 제외", "delivery.fallback": "전달 문구 대체",
  "tool.ok": "도구 실행", "tool.error": "도구 오류", "tool.denied": "도구 거부", "tool.request_ignored": "도구 요청 무시", "approval.requested": "승인 요청",
  "approval.approved": "승인함", "approval.rejected": "반려함", "memory.created": "기억 저장", "memory.extract_failed": "기억 추출 실패",
  "chat.trace": "대화 처리", "chat.failed": "대화 실패", "routing.failed": "라우팅 실패", "intent.failed": "의도 해석 실패",
  "proactive.suggested": "능동 제안 전달", "proactive.skipped": "능동 제안 건너뜀", "proactive.declined": "LLM이 제안 보류", "proactive.failed": "능동 제안 실패",
  "proactive.reaction": "제안 반응 처리", "proactive.settings_changed": "능동 제안 설정 변경",
  "worker.created": "직원 등록", "worker.updated": "직원 수정", "task.created": "업무 등록", "run.started": "업무 실행 시작", "run.completed": "업무 완료",
  "run.failed": "업무 실패", "run.awaiting_approval": "결과물 승인 대기", "run.rejected": "결과물 반려", "run.cancelled": "업무 취소", "run.recovered": "중단된 실행 정리",
  "run.skipped": "정기 실행 건너뜀", "run.needs_input": "자료 필요",
};
export const eventLabel = (e: string) => EVENT_LABEL[e] ?? e;
export const SOURCE_LABEL: Record<string, string> = { research: "Research", idea: "Idea", developer: "Developer", critic: "Critic", gyuvis: "GYUVIS", system: "시스템", scheduler: "스케줄러", tool: "도구", policy: "정책", worker: "AI 직원" };
export const actorLabel = (a: string | null, source: string) => SOURCE_LABEL[a ?? ""] ?? (a?.startsWith("worker:") ? "AI 직원" : SOURCE_LABEL[source] ?? a ?? source);
