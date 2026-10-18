import { useEffect, useRef, type ButtonHTMLAttributes, type ReactNode } from "react";

/** 공통 UI 조각. 화면마다 따로 만들지 않도록 상태 표시·모달·탭·빈 상태 등을 한 곳에 둔다. */

/** 선 아이콘(24x24, currentColor). 메뉴·카드·빈 상태가 같은 세트를 쓴다. */
const ICON_PATHS: Record<string, string> = {
  dashboard: "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
  chat: "M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z",
  agents: "M12 8V4M8 4h8M6 8h12a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zM9 13v1M15 13v1M9 18h6",
  workers: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM22 21v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
  workflows: "M5 4a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM5 16a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM19 10a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM7 6h4a4 4 0 0 1 4 4v0M7 18h4a4 4 0 0 0 4-4v0",
  debates: "M17 9V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8l3-3h3M21 21l-3-3h-7a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2z",
  ideas: "M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7c.6.5 1 1.2 1 2V17h6v-.3c0-.8.4-1.5 1-2A7 7 0 0 0 12 2z",
  memories: "M4 4h12a4 4 0 0 1 4 4v12H8a4 4 0 0 1-4-4zM8 9h8M8 13h6",
  proactive: "M22 2 11 13M22 2l-7 20-4-9-9-4z",
  approvals: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4",
  logs: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  autonomy: "M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  menu: "M4 6h16M4 12h16M4 18h16",
  panel: "M3 4h18v16H3zM9 4v16",
  inbox: "M22 12h-6l-2 3h-4l-2-3H2M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  check: "M5 12l5 5L20 7",
  plus: "M12 5v14M5 12h14",
  spark: "M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z",
  play: "M6 4l14 8-14 8z",
  warning: "M12 3 2 20h20zM12 10v5M12 18h.01",
  more: "M5 12h.01M12 12h.01M19 12h.01",
};
export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false"><path d={ICON_PATHS[name] ?? ICON_PATHS.spark} /></svg>;
}
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
  starting: ["시작 중", "info"], started: ["진행 중", "info"], blocked: ["사용자 확인 필요", "warn"], skipped: ["건너뜀", "muted"],
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

export function EmptyState({ title, desc, action, icon = "inbox" }: { title: string; desc?: ReactNode; action?: ReactNode; icon?: string }) {
  return (
    <div className="empty">
      <span className="empty-ico"><Icon name={icon} size={26} /></span>
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

/** 요약 카드. onClick 이 있으면 버튼으로, 없으면 일반 카드로 그린다. tone 은 아이콘 배경색. */
export function StatCard({ icon, label, value, sub, tone, onClick }: { icon: string; label: string; value: ReactNode; sub?: ReactNode; tone?: "cyan" | "mint" | "violet" | "warn" | "bad"; onClick?: () => void }) {
  const body = (
    <>
      <span className={`stat-ico ${tone ?? ""}`}><Icon name={icon} size={22} /></span>
      <span className="grow"><span className="lbl">{label}</span><span className="num" style={{ display: "block" }}>{value}</span>{sub && <span className="sub" style={{ display: "block" }}>{sub}</span>}</span>
    </>
  );
  return onClick ? <button className="stat-card" onClick={onClick}>{body}</button> : <div className="stat-card">{body}</div>;
}

/** 제목·부가 영역·설명을 가진 흰 카드. 화면마다 card-title 을 직접 만들지 않도록 둔다. */
export function SectionCard({ title, aside, desc, children, flush, className }: { title?: ReactNode; aside?: ReactNode; desc?: ReactNode; children: ReactNode; flush?: boolean; className?: string }) {
  return (
    <section className={`card ${flush ? "pad0" : ""} ${className ?? ""}`}>
      {(title || aside) && <div className="card-title" style={flush ? { padding: "14px 18px 0" } : undefined}><h3>{title}</h3>{aside && <div className="row">{aside}</div>}</div>}
      {desc && <div className="card-desc">{desc}</div>}
      {children}
    </section>
  );
}

/** 실제 상태에 연결된 검색 입력. 값·변경 핸들러는 호출한 화면이 소유한다. */
export function SearchField({ value, onChange, placeholder, label }: { value: string; onChange: (v: string) => void; placeholder: string; label: string }) {
  return (
    <div className="search"><Icon name="search" size={16} /><input type="search" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} aria-label={label} /></div>
  );
}

/** 검색·필터 한 줄. 화면 폭이 좁으면 줄바꿈된다. */
export const FilterBar = ({ children }: { children: ReactNode }) => <div className="toolbar" role="search">{children}</div>;

/** 알약형 상태 필터(선택 상태는 색과 aria-pressed 로 함께 표시). */
export function FilterPills<T extends string>({ options, value, onChange, label }: { options: { id: T; label: string; count?: number }[]; value: T; onChange: (v: T) => void; label: string }) {
  return (
    <div className="pills" role="group" aria-label={label}>
      {options.map((o) => <button key={o.id} className={`pill ${o.id === value ? "on" : ""}`} aria-pressed={o.id === value} onClick={() => onChange(o.id)}>{o.label}{o.count !== undefined && <span className="n"> {o.count}</span>}</button>)}
    </div>
  );
}

/** 아이콘이 있는 실행 버튼. variant 는 기존 버튼 클래스(secondary/ghost/danger)와 같다. */
export function ActionButton({ icon, variant, children, ...rest }: { icon?: string; variant?: "secondary" | "ghost" | "danger"; children: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button {...rest} className={`${variant ?? ""} ${rest.className ?? ""}`.trim()}>{icon && <Icon name={icon} size={15} />}{children}</button>;
}

/** Markdown 표시는 안전 렌더러(Markdown.tsx)를 그대로 쓴다. */
export { MarkdownPane as MarkdownViewer } from "./Markdown";
export function Modal({ open, title, onClose, children, footer, size }: { open: boolean; title: string; onClose: () => void; children: ReactNode; footer?: ReactNode; size?: "narrow" | "wide" }) {
  const box = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose; // 최신 onClose 를 쓰기 위한 참조(열려 있는 동안 부모 상태가 바뀔 수 있다)
  useEffect(() => {
    if (!open) return;
    const back = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(box.current?.querySelectorAll<HTMLElement>('input:not(:disabled), textarea:not(:disabled), select:not(:disabled), button:not(:disabled), [href], [tabindex]:not([tabindex="-1"])') ?? []).filter((e) => e.offsetParent !== null);
    // 열릴 때 본문의 첫 입력(없으면 첫 버튼)에 포커스를 두고, 닫히면 열기 전 위치로 돌려 준다.
    (box.current?.querySelector<HTMLElement>(".modal-body input:not(:disabled), .modal-body textarea:not(:disabled), .modal-body select:not(:disabled)") ?? focusables().find((e) => !e.matches(".modal-head button")))?.focus();
    const h = (e: KeyboardEvent) => {
      const all = document.querySelectorAll(".modal");
      if (all[all.length - 1] !== box.current) return; // 가장 위에 열린 대화상자만 키를 처리한다
      if (e.key === "Escape") closeRef.current();
      if (e.key === "Tab") {
        const f = focusables();
        if (f.length === 0) return;
        if (!box.current?.contains(document.activeElement)) { e.preventDefault(); f[0].focus(); }
        else if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    };
    window.addEventListener("keydown", h);
    return () => { window.removeEventListener("keydown", h); back?.focus?.(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
  if (!open) return null;
  return (
    <div className="modal-back" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={box} className={`modal ${size ?? ""}`} role="dialog" aria-modal="true" aria-label={title}>
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

/** 입력 한 칸. error 가 있으면 빨간 테두리와 메시지를 함께 보여 준다(색만으로 구분하지 않는다). */
export function Field({ label, required, children, hint, error }: { label: string; required?: boolean; children: ReactNode; hint?: ReactNode; error?: string }) {
  return (
    <label className={`field ${error ? "invalid" : ""}`}>
      <span>{label}{required && <span className="req" aria-hidden="true"> *</span>}{required && <span className="sr-only"> (필수)</span>}</span>
      {children}
      {error ? <span className="field-err" role="alert">⚠ {error}</span> : hint && <span className="small">{hint}</span>}
    </label>
  );
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
  "autonomy.config_changed": "자율 운영 설정 변경", "autonomy.trigger_created": "트리거 등록", "autonomy.trigger_updated": "트리거 수정", "autonomy.trigger_deleted": "트리거 삭제",
  "autonomy.goal_submitted": "자율 목표 접수", "autonomy.auto_started": "워크플로 자동 시작", "autonomy.blocked": "자동 실행 차단(사용자 확인 필요)",
  "autonomy.auto_approved": "결과물 자동 승인(정책)", "autonomy.fire_started": "트리거 발동: 시작", "autonomy.fire_blocked": "트리거 발동: 사용자 확인 필요",
  "autonomy.fire_failed": "트리거 발동: 실패", "autonomy.skipped": "트리거 건너뜀", "autonomy.duplicate_slot": "중복 발동 차단", "autonomy.retry": "실패 자동 재시도",
  "autonomy.paused": "자율 운영 꺼져 일시정지", "autonomy.mode_changed": "실행 모드 변경", "autonomy.chat_delegated": "대화로 맡긴 목표", "autonomy.chat_notified": "대화로 진행 알림",
  "autonomy.event": "이벤트 수신", "autonomy.recovered": "중단된 발동 정리", "autonomy.auto_approve_error": "자동 승인 오류",
};
export const eventLabel = (e: string) => EVENT_LABEL[e] ?? e;
export const SOURCE_LABEL: Record<string, string> = { research: "Research", idea: "Idea", developer: "Developer", critic: "Critic", gyuvis: "GYUVIS", system: "시스템", scheduler: "스케줄러", tool: "도구", policy: "정책", worker: "AI 직원", autonomy: "자율 운영", workflow: "워크플로" };
export const actorLabel = (a: string | null, source: string) => SOURCE_LABEL[a ?? ""] ?? (a?.startsWith("worker:") ? "AI 직원" : SOURCE_LABEL[source] ?? a ?? source);
