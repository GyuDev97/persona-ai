import { useCallback, useEffect, useState } from "react";
import { api, useApi, useServerEvents, type Approval, type Health } from "./api";
import { ConfirmDialog } from "./components/ui";
import Dashboard from "./views/Dashboard";
import Chat from "./views/Chat";
import Agents from "./views/Agents";
import Workers from "./views/Workers";
import Debates from "./views/Debates";
import Ideas from "./views/Ideas";
import Memories from "./views/Memories";
import Proactive from "./views/Proactive";
import Approvals from "./views/Approvals";
import Logs from "./views/Logs";

export const PAGES = [
  { id: "dashboard", label: "대시보드", ico: "◈" },
  { id: "chat", label: "대화", ico: "✉" },
  { id: "agents", label: "에이전트", ico: "◎" },
  { id: "workers", label: "직원", ico: "☰" },
  { id: "debates", label: "토론", ico: "❖" },
  { id: "ideas", label: "아이디어", ico: "✦" },
  { id: "memories", label: "기억", ico: "▣" },
  { id: "proactive", label: "능동 제안", ico: "➤" },
  { id: "approvals", label: "승인", ico: "✔" },
  { id: "logs", label: "로그", ico: "≣" },
] as const;
export type PageId = (typeof PAGES)[number]["id"];
const RUN_BUTTON_PAGES: PageId[] = ["dashboard", "agents", "debates"]; // ‘지금 토론’은 관련 있는 화면에서만 노출한다

const readHash = (): PageId => {
  const h = window.location.hash.replace(/^#\/?/, "");
  return (PAGES.find((p) => p.id === h)?.id ?? "dashboard") as PageId;
};

export interface Nav {
  go: (page: PageId) => void;
  openDebate: (id: number) => void;
  focusDebate: number | null;
}

export default function App() {
  const version = useServerEvents();
  const [page, setPage] = useState<PageId>(readHash);
  const [menu, setMenu] = useState(false);
  const [focusDebate, setFocusDebate] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmAuto, setConfirmAuto] = useState(false);
  const health = useApi<Health>("/health", version);
  const approvals = useApi<Approval[]>("/approvals", version);
  const pending = approvals.data?.filter((a) => a.status === "pending").length ?? 0;
  const h = health.data;

  useEffect(() => {
    const on = () => setPage(readHash());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  useEffect(() => {
    const beat = () => document.visibilityState === "visible" && api("/context/activity", { method: "POST" }).catch(() => {});
    beat();
    const t = window.setInterval(beat, 60_000);
    document.addEventListener("visibilitychange", beat);
    return () => {
      window.clearInterval(t);
      document.removeEventListener("visibilitychange", beat);
    };
  }, []);

  const go = useCallback((p: PageId) => {
    window.location.hash = `/${p}`;
    setPage(p);
    setMenu(false);
  }, []);
  const nav: Nav = { go, focusDebate, openDebate: (id) => (setFocusDebate(id), go("debates")) };

  const run = async () => {
    try {
      await api("/debates/run", { method: "POST", json: {} });
      setNotice(null);
      health.reload();
    } catch (e) {
      setNotice((e as Error).message);
    }
  };
  const toggleAuto = async () => {
    await api("/settings", { method: "PUT", json: { autonomous_enabled: !h?.autonomous_enabled } });
    setConfirmAuto(false);
    health.reload();
  };
  const spentPct = h ? Math.min(100, (h.spent_today_usd / Math.max(h.daily_budget_usd, 0.0001)) * 100) : 0;

  return (
    <div className="shell">
      <header className="topbar">
        <button className="menu-btn" onClick={() => setMenu(!menu)} aria-label="메뉴">☰</button>
        <div className="logo"><i /><span className="logo-text">GyuNexus</span></div>
        <div className="top-info">
          {h && (
            <>
              <span className="chip model" title="현재 LLM 모델"><span className={`badge plain ${h.llm_configured ? "ok" : "bad"}`}>{h.llm_configured ? h.model : "API 키 없음"}</span></span>
              <span className="chip" title="오늘 자율 작업 비용 / 일일 예산">
                <span className="muted opt">오늘</span> ${h.spent_today_usd.toFixed(3)} / ${h.daily_budget_usd.toFixed(2)}
                <span className="budget"><i style={{ width: `${spentPct}%` }} /></span>
              </span>
              <button className="secondary sm" onClick={() => (h.autonomous_enabled ? setConfirmAuto(true) : toggleAuto())} title={`${h.debate_interval_minutes}분마다 자율 토론`}>
                자율<span className="opt"> 토론</span> {h.autonomous_enabled ? "ON" : "OFF"}
              </button>
              {RUN_BUTTON_PAGES.includes(page) && (
                <button onClick={run} disabled={!h.llm_configured || h.debate_running}>{h.debate_running ? "토론 중…" : <><span className="opt">지금 </span>토론</>}</button>
              )}
            </>
          )}
        </div>
      </header>
      <div className="body">
        <div className={`scrim ${menu ? "open" : ""}`} onClick={() => setMenu(false)} />
        <nav className={`sidebar ${menu ? "open" : ""}`} aria-label="주 메뉴">
          {PAGES.map((p) => (
            <button key={p.id} className={`nav-item ${page === p.id ? "active" : ""}`} aria-current={page === p.id ? "page" : undefined} onClick={() => go(p.id)}>
              <span className="ico">{p.ico}</span>{p.label}
              {p.id === "approvals" && pending > 0 && <span className="count">{pending}</span>}
            </button>
          ))}
        </nav>
        <main className="page">
          {notice && <div className="notice bad" onClick={() => setNotice(null)} style={{ marginBottom: 12 }}>{notice}</div>}
          {page === "dashboard" && <Dashboard version={version} nav={nav} health={h} />}
          {page === "chat" && <Chat version={version} nav={nav} llmConfigured={h?.llm_configured ?? true} />}
          {page === "agents" && <Agents version={version} />}
          {page === "workers" && <Workers version={version} nav={nav} />}
          {page === "debates" && <Debates version={version} nav={nav} />}
          {page === "ideas" && <Ideas version={version} nav={nav} />}
          {page === "memories" && <Memories version={version} />}
          {page === "proactive" && <Proactive version={version} />}
          {page === "approvals" && <Approvals version={version} />}
          {page === "logs" && <Logs version={version} />}
        </main>
      </div>
      <ConfirmDialog open={confirmAuto} title="자율 토론을 끌까요?" message="끄면 정해진 주기의 자동 토론이 멈춥니다. 수동 토론과 AI 직원의 정기 업무는 영향을 받지 않습니다." confirmLabel="끄기" onConfirm={toggleAuto} onCancel={() => setConfirmAuto(false)} />
    </div>
  );
}

