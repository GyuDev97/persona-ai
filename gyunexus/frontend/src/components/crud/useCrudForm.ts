import { useCallback, useMemo, useRef, useState } from "react";

/**
 * 생성·수정 폼이 함께 쓰는 값 관리. 도메인 지식은 없고 ‘초기값·검증 함수’만 받는다.
 * - dirty: 초기값과 달라졌는가(저장하지 않고 닫을 때 경고에 사용)
 * - errorOf: 저장을 시도했거나 해당 필드를 벗어난(blur) 뒤에만 오류를 보여 준다
 */
export function useCrudForm<T extends object>(initial: T, validate?: (v: T) => Partial<Record<keyof T, string>>) {
  const base = useRef(JSON.stringify(initial));
  const [values, setValues] = useState<T>(initial);
  const [touched, setTouched] = useState<Partial<Record<keyof T, boolean>>>({});
  const [submitted, setSubmitted] = useState(false);

  const set = useCallback(<K extends keyof T>(k: K, v: T[K]) => setValues((p) => ({ ...p, [k]: v })), []);
  const patch = useCallback((p: Partial<T>) => setValues((prev) => ({ ...prev, ...p })), []);
  const touch = useCallback((k: keyof T) => setTouched((p) => ({ ...p, [k]: true })), []);
  const errors = useMemo(() => (validate ? validate(values) : {}) as Partial<Record<keyof T, string>>, [validate, values]);
  const errorOf = (k: keyof T) => (submitted || touched[k] ? errors[k] : undefined);
  const dirty = JSON.stringify(values) !== base.current;
  /** 저장 직전에 호출한다. 오류가 있으면 모든 필드 오류를 열고 false 를 돌려준다. */
  const check = () => {
    setSubmitted(true);
    return Object.values(errors).every((m) => !m);
  };
  return { values, set, patch, touch, errors, errorOf, dirty, check, valid: Object.values(errors).every((m) => !m), errorCount: Object.values(errors).filter(Boolean).length };
}