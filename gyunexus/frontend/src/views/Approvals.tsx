import { useEffect, useState } from "react";
import { api, useApi, type Approval, type WorkflowDetailT, type WorkflowRow } from "../api";
import type { Nav } from "../App";
import { MarkdownPane } from "../components/Markdown";
import { Async, Collapse, ConfirmDialog, EmptyState, fmtTime, PageHeader, StatusBadge, Tabs } from "../components/ui";

const TOOL_LABEL: Record<string, string> = { "worker.finalize": "AI 직원 결과물 확정", "notes.write": "노트 파일 저장" };
type Tab = "pending" | "done";

/** 승인 대기 중인 워크플로 단계(실행 id 기준)와 그 후속 단계. 승인 후 이어질 단계를 보여 주기 위해 기존 조회 API 만 쓴다. */
interface FlowLink { wfId: number; wfTitle: string; stepTitle: string; next: string[] }

export default function Approvals({ version, nav }: { version: number; nav: Nav }) {
  const [flows, setFlows] = useState<Record<number, FlowLink>>({});
  const list = useApi<Approval[]>("/approvals", version);
  const [tab, setTab] = useState<Tab>("pending");
  const [error, setError] = useState<string | null>(null);
  const [ask, setAsk] = useState<{ a: Approval; action: "approve" | "reject" } | null>(null);

  const decide = async () => {
    if (!ask) return;
    const { a, action } = ask;
    setAsk(null);
    try {
      await api(`/approvals/${a.id}/${action}`, { method: "POST" });
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
    list.reload();
  };
  const wfs = useApi<WorkflowRow[]>("/workflows", version);
  useEffect(() => {
    const targets = (wfs.data ?? []).filter((w) => (w.awaiting_approval ?? 0) > 0);
    if (targets.length === 0) { setFlows({}); return; }
    let live = true;
    Promise.all(targets.map((w) => api<WorkflowDetailT>(`/workflows/${w.id}`).catch(() => null))).then((ds) => {
      if (!live) return;
      const out: Record<number, FlowLink> = {};
      for (const wf of ds) {
        if (!wf) continue;
        for (const s of wf.steps) {
          if (s.status === "awaiting_approval" && s.run) out[s.run.id] = { wfId: wf.id, wfTitle: wf.title || wf.goal, stepTitle: s.title, next: wf.steps.filter((x) => x.depends_on.includes(s.key)).map((x) => x.title) };
        }
      }
      setFlows(out);
    });
    return () => { live = false; };
  }, [wfs.data]);
  const all = list.data ?? [];
  const pending = all.filter((a) => a.status === "pending");
  const done = all.filter((a) => a.status !== "pending");
  const rows = tab === "pending" ? pending : done;

  return (
    <div className="page-inner">
      <PageHeader title="승인" desc="파일 변경·결과물 확정처럼 영향이 있는 작업은 에이전트나 직원이 직접 실행하지 못하고 여기서 승인해야 실행됩니다." />
      {error && <div className="notice bad">{error}</div>}
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "pending", label: "승인 대기", count: pending.length }, { id: "done", label: "처리됨", count: done.length }]} />
      <Async q={list}>
        {() => (
          <div className="stack">
            {rows.length === 0 && <div className="card"><EmptyState icon="approvals" title={tab === "pending" ? "대기 중인 승인 요청이 없습니다" : "처리된 요청이 없습니다"} /></div>}
            {rows.map((a) => {
              const args = a.args as Record<string, unknown>;
              const impact = typeof args.impact === "string" ? args.impact : a.tool === "notes.write" ? "data/notes 폴더에 마크다운 파일이 만들어지거나 같은 이름의 파일이 덮어써집니다." : "승인하면 이 작업이 실행됩니다.";
              const preview = typeof args.preview === "string" ? args.preview : typeof args.content === "string" ? args.content : null;
              const target = (args.artifact ?? args.filename ?? args.task) as string | undefined;
              const flow = typeof args.run_id === "number" ? flows[args.run_id] : undefined;
              return (
                <div key={a.id} className="card">
                  <div className="row between wrap">
                    <div className="row wrap"><h3>{TOOL_LABEL[a.tool] ?? a.tool}</h3><StatusBadge status={a.status} /></div>
                    <span className="small muted">요청 {fmtTime(a.created_at)}{a.decided_at ? ` · 처리 ${fmtTime(a.decided_at)}` : ""}</span>
                  </div>
                  <dl className="kv" style={{ marginTop: 8 }}>
                    <dt>요청자</dt><dd>{a.requested_by}{a.debate_id ? ` · 토론 #${a.debate_id}` : ""}</dd>
                    {target && <><dt>대상</dt><dd>{target}</dd></>}
                    {a.reason && <><dt>이유</dt><dd>{a.reason}</dd></>}
                    <dt>예상 영향</dt><dd style={{ color: "var(--warn)" }}>{impact}</dd>
                    {flow && a.status === "pending" && <><dt>승인 후</dt><dd>워크플로 #{flow.wfId} 「{flow.wfTitle}」의 단계 「{flow.stepTitle}」이(가) 완료되고{flow.next.length ? <>, 후속 단계 {flow.next.map((n) => `「${n}」`).join(", ")}이(가) 이어서 실행됩니다.</> : " 이어질 단계가 있으면 자동으로 실행됩니다."}</dd></>}
                  </dl>
                  {preview && <Collapse title="결과물 미리보기" open={a.status === "pending"}>{a.tool === "worker.finalize" && /\.md$/.test(String(args.artifact ?? "")) ? <MarkdownPane source={preview} maxHeight={320} /> : <pre>{preview}</pre>}</Collapse>}
                  <div style={{ marginTop: 8 }}><Collapse title="인자 전체 (JSON)"><pre>{JSON.stringify(a.args, null, 2)}</pre></Collapse></div>
                  {a.result != null && <div style={{ marginTop: 8 }}><Collapse title="실행 결과"><pre>{JSON.stringify(a.result, null, 2)}</pre></Collapse></div>}
                  {a.status === "pending" && (
                    <div className="row" style={{ marginTop: 12 }}>
                      <button onClick={() => setAsk({ a, action: "approve" })}>승인하고 실행</button>
                      <button className="danger" onClick={() => setAsk({ a, action: "reject" })}>반려</button>
                      {flow && <button className="secondary" onClick={() => nav.go("workflows")}>워크플로로 이동</button>}
                      {!flow && typeof args.run_id === "number" && <button className="secondary" onClick={() => nav.go("workers")}>직원 실행 이력</button>}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Async>
      <ConfirmDialog open={!!ask} danger={ask?.action === "reject"} confirmLabel={ask?.action === "approve" ? "승인하고 실행" : "반려"}
        title={ask?.action === "approve" ? "이 요청을 승인할까요?" : "이 요청을 반려할까요?"}
        message={ask && <><b>{TOOL_LABEL[ask.a.tool] ?? ask.a.tool}</b><div className="small muted" style={{ marginTop: 6 }}>{ask.action === "approve" ? "승인하면 요청된 작업이 바로 실행됩니다." : "반려하면 작업은 실행되지 않습니다."}</div></>}
        onCancel={() => setAsk(null)} onConfirm={decide} />
    </div>
  );
}
