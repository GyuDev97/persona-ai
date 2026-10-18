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
      "proactive.message", "proactive.suggestion", "proactive.reaction", "approval.created", "approval.updated", "memory.updated", "topic.created",
      "worker.updated", "worker.run", "workflow.updated"]) {
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
  meta: { kind?: string; reason?: string; debate_id?: number; run_id?: number; suggestion_id?: number; topic_key?: string; trace?: ChatTrace }; created_at: string; conversation_id?: number;
}
export interface Memory {
  id: number; kind: string; content: string; importance: number; use_count: number; source: string;
  created_at: string; last_seen_at: string; last_used_at: string | null;
}
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
  status?: "accepted" | "needs_research" | "discarded" | null; rationale?: string | null; evidence_ids?: number[] | null; created_at?: string;
}
export interface DebateDetail extends Debate {
  plan?: unknown; progress?: unknown;
  messages: DebateMessage[];
  ideas: IdeaT[];
  evidence: { id: number; tool: string; source: string; summary: string }[];
  result: {
    summary: string; decision: string; verified_facts: { text: string; evidence_ids: number[] }[];
    unverified_claims: string[]; open_questions: string[]; warnings?: string[];
  } | null;
}
export interface Approval {
  id: number; tool: string; args: Record<string, unknown>; reason: string; requested_by: string;
  status: string; result: unknown; created_at: string; decided_at?: string | null; debate_id: number | null;
}
export interface Log { id: number; ts: string; source: string; agent_id: string | null; debate_id: number | null; level: string; event: string; detail: Record<string, unknown> }
export interface ProactivePrefs {
  enabled: boolean; daily_max: number; quiet_hours: string; topics: Record<string, boolean>; topic_labels: Record<string, string>;
}
export interface SuggestionRow {
  id: number; type: string; topic_key: string; status: string; decision: string | null; decision_reason: string; score: number | null;
  score_detail: Record<string, unknown>; confidence: string; title: string; reason: string; needed_action: string;
  event: string; reaction: string | null; created_at: string; valid_until: string | null; delivered_at: string | null;
}
export interface ReminderRow { id: number; topic_key: string; due_at: string; status: string; attempts: number; note: string }
export interface WorkerRow {
  id: number; name: string; role: string; description: string; model: string; allowed_tools: string[];
  permission_level: "read_only" | "write_with_approval"; max_cost_usd: number; enabled: boolean;
  task_count: number; awaiting_approval: number; running: number; state: "idle" | "working" | "waiting_approval" | "disabled";
  last_run: { id: number; status: string; ended_at: string | null } | null;
}
export interface WorkerTaskRow {
  id: number; worker_id: number; title: string; instructions: string; completion_criteria: string[];
  checks: { min_chars?: number; required_sections?: string[]; required_keys?: string[]; max_age_hours?: number; min_items?: number };
  max_tool_calls: number; tool_rounds: number; report_kind: "generic" | "news"; mode: "manual" | "scheduled";
  interval_minutes: number | null; tools: string[]; max_seconds: number; max_cost_usd: number; output_type: "markdown" | "text" | "json";
  requires_approval: boolean; allow_agents: boolean; requires_materials: boolean; materials: { name: string; content: string }[];
  input_files: string[]; status: "active" | "paused"; next_run_at: string | null; last_run_at: string | null;
}
export interface WorkerDetailT extends WorkerRow { tasks: WorkerTaskRow[]; inputs: { name: string; size: number }[] }
export interface VerifyCheck { name: string; passed: boolean; detail: string }
export interface WorkerRunRow {
  id: number; task_id: number; worker_id: number; task_title: string | null; worker_name: string | null; trigger: string; status: string;
  cost_usd: number; tokens: number; llm_calls: number; error_kind: string | null; error: string | null; summary: string;
  approval_id: number | null; approval_status: string | null; created_at: string; started_at: string | null; ended_at: string | null;
  artifact: { id: number; filename: string; title: string; size: number; sha256: string; verified: boolean; rel_path: string } | null;
  steps?: { t: string; kind: string; ok: boolean; [k: string]: unknown }[];
  verification?: { passed: boolean; checks: VerifyCheck[]; warnings: string[]; attempt: number } | null;
  content?: string | null;
}
export interface WorkerOptions {
  models: string[]; output_types: string[]; permission_levels: string[]; min_interval_minutes: number;
  tools: { name: string; description: string; risk: string; available_read_only: boolean; available_with_write: boolean; unavailable_reason: string }[];
  templates: { id: string; label: string; worker: Partial<WorkerRow>; task: Partial<WorkerTaskRow> }[];
}
export interface Topic { id: number; title: string; source: string; status: string; debate_id: number | null }


export interface WorkflowStepT {
  id: number; key: string; title: string; directive: string; worker_id: number; task_id: number; depends_on: string[]; reason: string;
  status: "pending" | "running" | "awaiting_approval" | "completed" | "failed" | "cancelled"; attempts: number; run_id: number | null; model: string; cost_usd: number;
  error_kind: string | null; error: string | null; inputs: { artifact_id: number; sha256: string; version: number; filename: string; from_run_id: number }[];
  output_artifact_id: number | null; level: number; worker_name: string | null; task_title: string | null; requires_approval: boolean; worker_enabled: boolean;
  run: { id: number; status: string; cost_usd: number; error_kind: string | null; approval_id: number | null; llm_calls: number } | null;
  artifact: { id: number; filename: string; title: string; verified: boolean; sha256: string; media_type: string } | null;
  started_at: string | null; ended_at: string | null;
}
export interface WorkflowRow {
  id: number; title: string; goal: string; status: "planned" | "running" | "paused" | "completed" | "failed" | "cancelled"; auto_run: boolean; budget_usd: number;
  planning_cost_usd: number; plan_notes: string; plan_version: number; error: string | null; created_at: string; started_at: string | null; ended_at: string | null;
  cost_usd: number; step_count?: number; done_count?: number; awaiting_approval?: number;
}
export interface WorkflowDetailT extends WorkflowRow {
  steps: WorkflowStepT[]; remaining_budget_usd: number; counts: Record<string, number>;
  budget_info: { spent_usd: number; required_usd: number; min_budget_usd: number; max_budget_usd: number; editable: boolean; removed_steps_usd: number };
  removed_steps: { step_id: number; key: string | null; title: string | null; cost_usd: number; runs: { run_id: number; status: string; cost_usd: number; artifact_id: number | null }[] }[];
  budget_history: BudgetChangeT[];
  plan_state: "ok" | "failed"; plan_error: string | null; plan_error_kind: "budget" | "invalid" | null;
  /** 계획 생성 자체가 실패해 단계가 없을 때만 있다(유효한 계획이 있으면 null). stale_budget: 실패 이후 예산이 늘어 메시지의 예산이 과거 값인 경우 */
  plan_failure: { message: string | null; kind: "budget" | "invalid" | null; budget_at_failure_usd: number | null; has_proposal: boolean; stale_budget: boolean; can_replan: boolean } | null;
  plan_attempts: PlanAttemptT[];
  /** 유효한 계획이 있을 때, 지금 저장된 예산으로 시작할 수 있는가 */
  start_check: { ok: boolean; error: string | null; kind: "budget" | "invalid" | null } | null;
}
export interface PlanAttemptT { id: number; kind: "initial" | "auto" | "revalidate" | "replan" | "manual"; source: "llm" | "proposal" | "user" | "legacy"; status: "succeeded" | "failed"; error: string | null; error_kind: string | null; budget_usd: number; cost_usd: number; step_count: number; created_at: string }
export interface BudgetChangeT { id: number; old_usd: number; new_usd: number; spent_usd: number; required_usd: number; status: string; source: "budget" | "plan"; created_at: string }
export interface WorkflowOptions { currency: string; default_budget_usd: number; max_budget_usd: number; max_steps: number }
export interface ArtifactDetailT {
  id: number; run_id: number; worker_id: number; filename: string; title: string; size: number; sha256: string; verified: boolean; media_type: string; content: string | null; version: number;
}
export interface LineageNode {
  artifact_id: number; filename: string; sha256: string; verified: boolean; run_id: number; run_status: string; worker: string; task: string; workflow_step_id: number | null;
  inputs: { artifact_id: number; sha256: string; version: number; upstream: LineageNode | null }[];
}