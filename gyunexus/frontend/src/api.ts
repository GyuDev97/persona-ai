import { useCallback, useEffect, useRef, useState } from "react";

export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T> {
  const res = await fetch(`/api${path}`, {
    ...init,
    headers: init?.json !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: init?.json !== undefined ? JSON.stringify(init.json) : init?.body,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* JSON이 아닌 오류 응답 본문 */
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

/** 서버가 이벤트를 보낼 때마다 카운터를 올린다. 화면은 이 값이 바뀌면 다시 조회한다. */
export function useServerEvents(): number {
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const es = new EventSource("/api/events");
    let timer: number | undefined;
    const bump = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => setVersion((v) => v + 1), 250);
    };
    for (const t of ["log", "agent.status", "debate.started", "debate.message", "debate.updated", "debate.completed",
      "proactive.message", "approval.created", "approval.updated", "memory.updated", "topic.created"]) {
      es.addEventListener(t, bump);
    }
    return () => {
      es.close();
      window.clearTimeout(timer);
    };
  }, []);
  return version;
}

export function useApi<T>(path: string | null, version: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);
  const load = useCallback(() => {
    if (path === null) return;
    const mine = ++seq.current;
    api<T>(path)
      .then((d) => mine === seq.current && (setData(d), setError(null)))
      .catch((e: Error) => mine === seq.current && setError(e.message));
  }, [path]);
  useEffect(load, [load, version]);
  return { data, error, reload: load };
}

export interface Health {
  llm_configured: boolean;
  model: string;
  autonomous_enabled: boolean;
  debate_interval_minutes: number;
  daily_budget_usd: number;
  spent_today_usd: number;
  debate_running: boolean;
}
export interface Conversation { id: number; title: string; updated_at: string }
export interface RoutingTrace {
  intent: string;
  interpreted_by: string;
  reason: string;
  prior_state: { topic: string | null; slots: Record<string, unknown> } | null;
  changes: Record<string, { from: unknown; to: unknown }>;
  merged_state: { topic: string | null; slots: Record<string, unknown>; missing_fields: string[] } | null;
  tools_selected: { tool: string; reason: string; args: Record<string, unknown> }[];
  tools_skipped: { tool: string; reason: string }[];
  advice: string[];
}
export interface ChatTrace {
  routing?: RoutingTrace;
  steps: string[];
  sky_intent: boolean;
  llm?: { called: boolean; model?: string; tokens?: number; cost_usd?: number; latency_ms?: number; history_messages?: number; error?: string };
  memories: { id: number; kind: string; content: string }[];
  tools: { name: string; status: string; error?: string; error_kind?: string; attempts?: number; reason?: string;
    result?: Record<string, unknown> }[];
  missing_data: string[];
}
export interface Message {
  id: number; role: "user" | "assistant"; content: string; proactive: boolean;
  meta: { kind?: string; reason?: string; debate_id?: number; trace?: ChatTrace }; created_at: string;
}
export interface Memory { id: number; kind: string; content: string; importance: number; use_count: number; source: string }
export interface Agent {
  id: string; name: string; role: string; description: string; status: string;
  current_task: string | null; last_active_at: string | null;
}
export interface Debate {
  id: number; title: string; goal: string; trigger: string; status: string; participants: string[];
  max_rounds: number; rounds_done: number; stop_reason: string | null; tokens_used: number; cost_usd: number;
  importance: number; error: string | null; started_at: string; ended_at: string | null; delivered_at: string | null;
}
export interface Claim {
  text: string;
  status: "verified" | "unverified" | "interpretation" | "assumption" | "proposal" | "conflicted" | "rebuttal" | "endorsed" | "opinion";
  evidence_ids: number[];
  notes?: string[];
}
export interface DebateMessage { id: number; round: number; agent_id: string; content: string; claims: Claim[] }
export interface IdeaT {
  id: number; title: string; description: string; feasibility: string; risks: string[];
  next_steps: string[]; confidence: number; debate_id: number; debate_title?: string;
  status?: "accepted" | "needs_research" | "discarded" | null; rationale?: string | null;
}
export interface DebateDetail extends Debate {
  messages: DebateMessage[];
  ideas: IdeaT[];
  evidence: { id: number; tool: string; source: string; summary: string }[];
  result: {
    summary: string; decision: string; verified_facts: { text: string; evidence_ids: number[] }[];
    unverified_claims: string[]; open_questions: string[];
  } | null;
}
export interface Approval {
  id: number; tool: string; args: Record<string, unknown>; reason: string; requested_by: string;
  status: string; result: unknown; created_at: string; debate_id: number | null;
}
export interface Log { id: number; ts: string; source: string; agent_id: string | null; debate_id: number | null; level: string; event: string; detail: Record<string, unknown> }
export interface Topic { id: number; title: string; source: string; status: string; debate_id: number | null }
