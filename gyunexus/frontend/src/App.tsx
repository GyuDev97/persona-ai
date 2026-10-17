import { useEffect, useState } from "react";
import { api, useApi, useServerEvents, type Approval, type Health } from "./api";
import Chat from "./views/Chat";
import { Agents, Logs } from "./views/Agents";
import { DebateList, Ideas } from "./views/Debates";
import { Approvals, Memories } from "./views/Manage";

const TABS = ["대화", "에이전트", "토론", "아이디어", "기억", "승인", "로그"] as const;
type Tab = (typeof TABS)[number];

export default function App() {
  const version = useServerEvents();
  const [tab, setTab] = useState<Tab>("대화");
  const [focusDebate, setFocusDebate] = useState<number | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const health = useApi<Health>("/health", version);
  const approvals = useApi<Approval[]>("/approvals", version);
  const pending = approvals.data?.filter((a) => a.status === "pending").length ?? 0;
  const h = health.data;

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

  const run = async () => {
    try {
      await api("/debates/run", { method: "POST", json: {} });
      setNotice(null);
      health.reload();
    } catch (e) {
      setNotice((e as Error).message);
    }
  };
  const toggle = async () => {
    await api("/settings", { method: "PUT", json: { autonomous_enabled: !h?.autonomous_enabled } });
    health.reload();
  };
  const openDebate = (id: number) => {
    setFocusDebate(id);
    setTab("토론");
  };

  return (
    <div className="app">
      <header>
        <h1>GyuNexus</h1>
        <nav>
          {TABS.map((t) => (
            <button key={t} className={t === tab ? "active" : ""} onClick={() => setTab(t)}>
              {t}
              {t === "승인" && pending > 0 && <span className="badge">{pending}</span>}
            </button>
          ))}
        </nav>
        <div className="status">
          {h && (
            <>
              <span className={`dot ${h.llm_configured ? "ok" : "bad"}`} />
              <span>{h.llm_configured ? h.model : "API 키 없음"}</span>
              <span className="muted">
                오늘 ${h.spent_today_usd.toFixed(3)} / ${h.daily_budget_usd.toFixed(2)}
              </span>
              <button className="ghost" onClick={toggle} title={`${h.debate_interval_minutes}분마다`}>
                자율 토론 {h.autonomous_enabled ? "ON" : "OFF"}
              </button>
              <button onClick={run} disabled={!h.llm_configured || h.debate_running}>
                {h.debate_running ? "토론 중…" : "지금 토론"}
              </button>
            </>
          )}
        </div>
      </header>
      {notice && <div className="notice" onClick={() => setNotice(null)}>{notice}</div>}
      <main>
        {tab === "대화" && <Chat version={version} onOpenDebate={openDebate} llmConfigured={h?.llm_configured ?? true} />}
        {tab === "에이전트" && <Agents version={version} />}
        {tab === "토론" && <DebateList version={version} focus={focusDebate} />}
        {tab === "아이디어" && <Ideas version={version} onOpenDebate={openDebate} />}
        {tab === "기억" && <Memories version={version} />}
        {tab === "승인" && <Approvals version={version} />}
        {tab === "로그" && <Logs version={version} />}
      </main>
    </div>
  );
}
