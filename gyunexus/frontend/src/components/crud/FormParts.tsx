import type { ReactNode } from "react";

/** 폼 안의 구역. 항목이 많은 폼을 ‘기본 정보 / 실행 설정’처럼 나눌 때 쓴다(단순한 폼은 쓰지 않는다). */
export function FormSection({ title, desc, children, tone }: { title: string; desc?: ReactNode; children: ReactNode; tone?: "danger" }) {
  return (
    <section className={`form-section ${tone === "danger" ? "danger" : ""}`}>
      <header><h4>{title}</h4>{desc && <p>{desc}</p>}</header>
      <div className="stack">{children}</div>
    </section>
  );
}

/** 저장 실패·검증 요약 같은 폼 수준 오류. */
export const FormError = ({ children }: { children: ReactNode }) => <div className="notice bad" role="alert">{children}</div>;