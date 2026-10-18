import { useEffect, useRef, useState } from "react";
import { Icon } from "../ui";

export interface MenuAction { label: string; onClick: () => void; danger?: boolean; disabled?: boolean; hint?: string }

/** 행별 액션 메뉴(⋯). 바깥 클릭·Esc 로 닫히고 열리면 첫 항목에 포커스가 간다. */
export function CrudActions({ actions, label = "작업 메뉴" }: { actions: MenuAction[]; label?: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const items = () => Array.from(box.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]:not(:disabled)") ?? []);
    items()[0]?.focus();
    const down = (e: MouseEvent) => { if (!box.current?.contains(e.target as Node)) setOpen(false); };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setOpen(false); box.current?.querySelector<HTMLButtonElement>("[aria-haspopup]")?.focus(); return; }
      if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
      e.preventDefault();
      const list = items();
      const i = list.indexOf(document.activeElement as HTMLButtonElement);
      list[(i + (e.key === "ArrowDown" ? 1 : -1) + list.length) % list.length]?.focus();
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", down); document.removeEventListener("keydown", key); };
  }, [open]);
  if (actions.length === 0) return null;
  return (
    <div className="row-menu" ref={box}>
      <button type="button" className="ghost sm" aria-haspopup="menu" aria-expanded={open} aria-label={label} onClick={(e) => { e.stopPropagation(); setOpen(!open); }}><Icon name="more" size={16} /></button>
      {open && (
        <div className="menu-pop" role="menu">
          {actions.map((a) => (
            <button type="button" key={a.label} role="menuitem" className={`menu-item ${a.danger ? "danger" : ""}`} disabled={a.disabled} title={a.hint}
              onClick={(e) => { e.stopPropagation(); setOpen(false); a.onClick(); }}>{a.label}</button>
          ))}
        </div>
      )}
    </div>
  );
}