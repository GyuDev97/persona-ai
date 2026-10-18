import { useMemo, useState } from "react";
import { api, useApi, type Memory } from "../api";
import { Async, ConfirmDialog, EmptyState, Field, fmtAgo, fmtTime, Modal, PageHeader } from "../components/ui";

const KINDS = ["interest", "preference", "routine", "fact", "goal"];
const KIND_LABEL: Record<string, string> = { interest: "관심사", preference: "선호", routine: "루틴", fact: "사실", goal: "목표" };
const SOURCE_LABEL: Record<string, string> = { chat: "대화에서 추출", manual: "직접 추가", reaction: "제안 반응" };

export default function Memories({ version }: { version: number }) {
  const mems = useApi<Memory[]>("/memories", version);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const [adding, setAdding] = useState(false);
  const [del, setDel] = useState<Memory | null>(null);
  const rows = useMemo(() => (mems.data ?? []).filter((m) => (!kind || m.kind === kind) && (!q.trim() || m.content.toLowerCase().includes(q.trim().toLowerCase()))), [mems.data, q, kind]);

  return (
    <div className="page-inner">
      <PageHeader title="기억" desc="GYUVIS가 사용자에 대해 기억하는 내용입니다. 대화 중에도 오래 유효한 정보를 자동으로 저장합니다." actions={<button onClick={() => setAdding(true)}>＋ 기억 추가</button>} />
      <div className="row wrap">
        <input className="grow" style={{ maxWidth: 420 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="기억 내용 검색" aria-label="기억 검색" />
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="종류 필터"><option value="">모든 종류</option>{KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select>
        <span className="muted small">{rows.length} / {mems.data?.length ?? 0}건</span>
      </div>
      <Async q={mems}>
        {() => (
          <div className="card">
            {rows.length === 0 && <EmptyState title={mems.data?.length ? "검색 결과가 없습니다" : "저장된 기억이 없습니다"} desc={mems.data?.length ? undefined : "기억 추가 버튼으로 직접 입력하거나, 대화하면 자동으로 쌓입니다."} />}
            {rows.map((m) => (
              <div key={m.id} className="item">
                <div className="row between wrap">
                  <div className="row wrap"><span className="badge plain info">{KIND_LABEL[m.kind] ?? m.kind}</span><span className="badge plain" title="중요도">중요도 {m.importance}</span></div>
                  <button className="ghost sm" onClick={() => setDel(m)} aria-label="기억 삭제">삭제</button>
                </div>
                <div style={{ margin: "4px 0" }}>{m.content}</div>
                <div className="small muted">{SOURCE_LABEL[m.source] ?? m.source} · 생성 {fmtTime(m.created_at)} · 마지막 확인 {fmtAgo(m.last_seen_at)} · 사용 {m.use_count}회{m.last_used_at ? ` (최근 ${fmtAgo(m.last_used_at)})` : ""}</div>
              </div>
            ))}
          </div>
        )}
      </Async>
      {adding && <AddModal onClose={() => setAdding(false)} onSaved={() => (setAdding(false), mems.reload())} />}
      <ConfirmDialog open={!!del} danger title="기억을 삭제할까요?" message={<>‘{del?.content}’<div className="small muted">삭제하면 GYUVIS가 더 이상 이 내용을 사용하지 않습니다.</div></>} confirmLabel="삭제"
        onCancel={() => setDel(null)} onConfirm={async () => { if (del) await api(`/memories/${del.id}`, { method: "DELETE" }); setDel(null); mems.reload(); }} />
    </div>
  );
}

function AddModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [content, setContent] = useState("");
  const [kind, setKind] = useState("interest");
  const [importance, setImportance] = useState(7);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    try {
      await api("/memories", { method: "POST", json: { kind, content: content.trim(), importance } });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  return (
    <Modal open title="기억 추가" onClose={onClose} footer={<><button className="secondary" onClick={onClose}>취소</button><button disabled={!content.trim()} onClick={save}>저장</button></>}>
      <div className="stack">
        {error && <div className="notice bad">{error}</div>}
        <Field label="종류"><select value={kind} onChange={(e) => setKind(e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]} ({k})</option>)}</select></Field>
        <Field label="내용" required><textarea rows={3} maxLength={500} value={content} onChange={(e) => setContent(e.target.value)} placeholder="예: 사용자는 은하수 촬영을 즐긴다" /></Field>
        <Field label={`중요도 ${importance}`}><input type="range" min={1} max={10} value={importance} onChange={(e) => setImportance(Number(e.target.value))} /></Field>
      </div>
    </Modal>
  );
}
