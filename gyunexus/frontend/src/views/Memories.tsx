import { useMemo, useState } from "react";
import { api, useApi, type Memory } from "../api";
import { CrudDialog } from "../components/crud/CrudDialog";
import { CrudList, type Column } from "../components/crud/CrudList";
import { DeleteConfirmDialog } from "../components/crud/DeleteConfirmDialog";
import { useCrudForm } from "../components/crud/useCrudForm";
import { Async, EmptyState, Field, FilterBar, SearchField, fmtAgo, fmtTime, PageHeader } from "../components/ui";

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

  // 기억 API 는 조회·추가·삭제만 지원한다(수정 API 없음). 그래서 행 메뉴에도 ‘삭제’만 둔다.
  const columns: Column<Memory>[] = [
    { key: "kind", header: "종류", render: (m) => <span className="badge plain info">{KIND_LABEL[m.kind] ?? m.kind}</span>, className: "nowrap" },
    { key: "content", header: "내용", render: (m) => <div>{m.content}<div className="small muted">{SOURCE_LABEL[m.source] ?? m.source} · 생성 {fmtTime(m.created_at)} · 마지막 확인 {fmtAgo(m.last_seen_at)}</div></div> },
    { key: "importance", header: "중요도", render: (m) => m.importance, className: "nowrap" },
    { key: "use", header: "사용", render: (m) => <span className="small muted">{m.use_count}회{m.last_used_at ? ` · 최근 ${fmtAgo(m.last_used_at)}` : ""}</span>, className: "nowrap" },
  ];

  return (
    <div className="page-inner">
      <PageHeader title="기억" desc="GYUVIS가 사용자에 대해 기억하는 내용입니다. 대화 중에도 오래 유효한 정보를 자동으로 저장합니다." actions={<button onClick={() => setAdding(true)}>＋ 기억 추가</button>} />
      <FilterBar>
        <SearchField value={q} onChange={setQ} placeholder="기억 내용 검색" label="기억 검색" />
        <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="종류 필터"><option value="">모든 종류</option>{KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}</select>
        <span className="muted small">{rows.length} / {mems.data?.length ?? 0}건</span>
      </FilterBar>
      <Async q={mems}>
        {() => (
          <div className="card pad0">
            <CrudList items={rows} rowKey={(m) => m.id} columns={columns} pageSize={20}
              actions={(m) => [{ label: "삭제", danger: true, onClick: () => setDel(m) }]}
              empty={<EmptyState title={mems.data?.length ? "검색 결과가 없습니다" : "저장된 기억이 없습니다"} desc={mems.data?.length ? undefined : "기억 추가 버튼으로 직접 입력하거나, 대화하면 자동으로 쌓입니다."} />} />
          </div>
        )}
      </Async>
      {adding && <AddModal onClose={() => setAdding(false)} onSaved={() => (setAdding(false), mems.reload())} />}
      <DeleteConfirmDialog open={!!del} title="기억을 삭제할까요?" itemName={<>‘{del?.content}’</>} action="삭제"
        impact={["GYUVIS가 이후 대화에서 이 내용을 사용하지 않습니다"]} recovery={{ reversible: false, note: "삭제한 기억은 되살릴 수 없습니다. 필요하면 ‘기억 추가’로 다시 입력해야 합니다." }}
        onCancel={() => setDel(null)} onConfirm={async () => { if (del) await api(`/memories/${del.id}`, { method: "DELETE" }); setDel(null); mems.reload(); }} />
    </div>
  );
}

function AddModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const form = useCrudForm({ kind: "interest", content: "", importance: 7 }, (v) => ({ content: v.content.trim() ? undefined : "기억할 내용을 입력하세요" }));
  const f = form.values;
  return (
    <CrudDialog mode="create" title="기억 추가" dirty={form.dirty} validate={form.check} onClose={onClose}
      onSubmit={async () => { await api("/memories", { method: "POST", json: { kind: f.kind, content: f.content.trim(), importance: f.importance } }); onSaved(); }}>
      <Field label="종류"><select value={f.kind} onChange={(e) => form.set("kind", e.target.value)}>{KINDS.map((k) => <option key={k} value={k}>{KIND_LABEL[k]} ({k})</option>)}</select></Field>
      <Field label="내용" required error={form.errorOf("content")} hint={`${f.content.length} / 500`}><textarea rows={3} maxLength={500} value={f.content} aria-invalid={!!form.errorOf("content")} onBlur={() => form.touch("content")} onChange={(e) => form.set("content", e.target.value)} placeholder="예: 사용자는 은하수 촬영을 즐긴다" /></Field>
      <Field label={`중요도 ${f.importance}`}><input type="range" min={1} max={10} value={f.importance} onChange={(e) => form.set("importance", Number(e.target.value))} /></Field>
    </CrudDialog>
  );
}
