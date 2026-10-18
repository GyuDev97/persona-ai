import { useState, type ReactNode } from "react";
import { Icon, Modal } from "../ui";
import { FormError } from "./FormParts";

/**
 * 삭제·비활성화·취소처럼 되돌리기 어려운 동작의 공통 확인 창.
 * 영향 범위(impact)·복구 가능 여부(recovery)는 호출한 쪽이 ‘실제 데이터나 API 문서로 확인한 것만’ 넘긴다.
 * 넘기지 않으면 표시하지 않는다(모르는 영향을 단정하지 않기 위해).
 */
export interface DeleteConfirmProps {
  open: boolean;
  title: string;
  /** 대상 이름 */
  itemName: ReactNode;
  /** 수행할 작업(예: 비활성화) */
  action: string;
  confirmLabel?: string;
  impact?: ReactNode[];
  /** 복구 가능 여부와 설명. 확인되지 않았으면 undefined. */
  recovery?: { reversible: boolean; note: string };
  warning?: ReactNode;
  /** 값이 있으면 실행할 수 없는 대상이다. 이유를 보여 주고 확인 버튼을 막는다. */
  blockedReason?: string;
  onConfirm: () => Promise<unknown> | unknown;
  onCancel: () => void;
}

export function DeleteConfirmDialog({ open, title, itemName, action, confirmLabel, impact, recovery, warning, blockedReason, onConfirm, onCancel }: DeleteConfirmProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const confirm = async () => {
    if (busy || blockedReason) return;
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (e) {
      setError((e as Error).message || "처리하지 못했습니다.");
    }
    setBusy(false);
  };
  const close = () => { if (!busy) { setError(null); onCancel(); } };
  return (
    <Modal open={open} title={title} size="narrow" onClose={close}
      footer={<><button className="secondary" onClick={close} disabled={busy}>취소</button><button className="danger solid" onClick={confirm} disabled={busy || !!blockedReason}>{busy ? "처리 중…" : (confirmLabel ?? action)}</button></>}>
      <div className="stack">
        <div className="delete-hero"><span className="delete-ico"><Icon name="warning" size={26} /></span>
          <div><b>{itemName}</b><div className="muted small">수행할 작업: {action}</div></div></div>
        {error && <FormError>{error}</FormError>}
        {blockedReason && <div className="notice bad">{blockedReason}</div>}
        {warning && <div className="notice">{warning}</div>}
        {impact && impact.length > 0 && <div className="impact-box"><b>영향을 받는 항목</b><ul>{impact.map((x, i) => <li key={i}>{x}</li>)}</ul></div>}
        {recovery && <div className={`recover-box ${recovery.reversible ? "ok" : "bad"}`}><b>{recovery.reversible ? "복구 가능" : "복구 불가"}</b> <span>{recovery.note}</span></div>}
      </div>
    </Modal>
  );
}