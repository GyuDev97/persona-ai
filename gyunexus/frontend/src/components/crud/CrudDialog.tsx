import { useId, useState, type ReactNode } from "react";
import { ConfirmDialog, Modal } from "../ui";
import { FormError } from "./FormParts";

/**
 * 생성(create)·수정(update) 공통 대화상자. API 호출·검증 규칙은 모르고 호출한 쪽의 함수를 실행만 한다.
 * - onSubmit 이 예외를 던지면 메시지를 폼 위에 보여 주고 입력값은 그대로 둔다(상태는 호출한 쪽이 갖고 있다)
 * - 저장 중에는 버튼·닫기를 막아 중복 제출을 방지한다
 * - dirty 이면 닫기(취소·Esc·바깥 클릭) 전에 변경 사항 경고를 띄운다
 */
export interface CrudDialogProps {
  mode: "create" | "update";
  title: string;
  description?: ReactNode;
  size?: "narrow" | "wide";
  submitLabel?: string;
  busyLabel?: string;
  /** 저장 전 검증. false 를 돌려주면 제출하지 않는다(필드별 오류는 호출한 쪽이 표시). */
  validate?: () => boolean;
  /** 추가로 저장을 막는 조건(예: 필수값 비어 있음). */
  disabled?: boolean;
  dirty?: boolean;
  onSubmit: () => Promise<unknown> | unknown;
  onClose: () => void;
  children: ReactNode;
}

export function CrudDialog({ mode, title, description, size, submitLabel, busyLabel, validate, disabled, dirty, onSubmit, onClose, children }: CrudDialogProps) {
  const formId = useId();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [guard, setGuard] = useState(false);

  const attemptClose = () => {
    if (busy) return;
    if (dirty) setGuard(true);
    else onClose();
  };
  const submit = async () => {
    if (busy) return;
    if (validate && !validate()) {
      setError("입력값을 확인해 주세요. 표시된 항목을 고치면 저장할 수 있습니다.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSubmit();
    } catch (e) {
      setError((e as Error).message || "저장하지 못했습니다.");
      setBusy(false);
      return;
    }
    setBusy(false);
  };

  return (
    <>
      <Modal open title={title} size={size} onClose={guard ? () => {} : attemptClose}
        footer={
          <>
            {dirty && !busy && <span className="small muted grow">저장하지 않은 변경 사항이 있습니다</span>}
            <button type="button" className="secondary" onClick={attemptClose} disabled={busy}>취소</button>
            <button type="submit" form={formId} disabled={busy || disabled}>{busy ? (busyLabel ?? "저장 중…") : (submitLabel ?? (mode === "create" ? "등록" : "저장"))}</button>
          </>
        }>
        <form id={formId} className="stack" noValidate onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          {description && <p className="muted">{description}</p>}
          {error && <FormError>{error}</FormError>}
          {children}
        </form>
      </Modal>
      <ConfirmDialog open={guard} title="저장하지 않고 닫을까요?" message="입력한 변경 사항이 사라집니다." confirmLabel="닫기" danger
        onCancel={() => setGuard(false)} onConfirm={() => { setGuard(false); onClose(); }} />
    </>
  );
}