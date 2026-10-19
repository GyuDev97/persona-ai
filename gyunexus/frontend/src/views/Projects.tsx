import { useState } from "react";
import { api, useApi, type ExecProfile, type ProjectChangeRow, type ProjectRow } from "../api";
import type { Nav } from "../App";
import { CrudDialog } from "../components/crud/CrudDialog";
import { CrudList } from "../components/crud/CrudList";
import { DeleteConfirmDialog } from "../components/crud/DeleteConfirmDialog";
import { FormSection } from "../components/crud/FormParts";
import { useCrudForm } from "../components/crud/useCrudForm";
import { Collapse, EmptyState, Field, fmtTime, PageHeader, SectionCard, StatusBadge, Tabs } from "../components/ui";

type Tab = "projects" | "changes";
type ProfileForm = { name: string; kind: ExecProfile["kind"]; command: string; timeout: string; allow_args: boolean; flags: string };
type ProjectForm = { name: string; root_path: string; description: string; allow_read: boolean; allow_write: boolean; allow_exec: boolean; allow_git: boolean; enabled: boolean; profiles: ProfileForm[] };

const KIND: Record<string, string> = { test: "테스트", build: "빌드", lint: "린트", other: "기타" };
// 공백으로 나눈 단어 배열(셸 해석 없음). 공백이 든 인자는 지원하지 않는다: 서버가 셸을 쓰지 않고 이 배열 그대로 실행한다.
const toArgv = (s: string) => s.trim().split(/\s+/).filter(Boolean);
const toForm = (p?: ProjectRow): ProjectForm => ({
  name: p?.name ?? "", root_path: p?.root_path ?? "", description: p?.description ?? "", allow_read: p?.allow_read ?? true, allow_write: p?.allow_write ?? false, allow_exec: p?.allow_exec ?? false,
  allow_git: p?.allow_git ?? true, enabled: p?.enabled ?? true,
  profiles: (p?.exec_profiles ?? []).map((x) => ({ name: x.name, kind: x.kind, command: x.argv.join(" "), timeout: String(x.timeout_seconds), allow_args: x.allow_args, flags: x.allowed_flags.join(" ") })),
});

export default function Projects({ version }: { version: number; nav: Nav }) {
  const list = useApi<ProjectRow[]>("/projects", version);
  const changes = useApi<ProjectChangeRow[]>("/projects/changes?limit=60", version);
  const [tab, setTab] = useState<Tab>("projects");
  const [editing, setEditing] = useState<ProjectRow | "new" | null>(null);
  const [deleting, setDeleting] = useState<ProjectRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const names = new Map((list.data ?? []).map((p) => [p.id, p.name]));
  const toggle = async (p: ProjectRow) => {
    try { await api(`/projects/${p.id}`, { method: "PUT", json: { enabled: !p.enabled } }); setError(null); } catch (e) { setError((e as Error).message); }
    list.reload();
  };

  return (
    <div className="page-inner">
      <PageHeader title="프로젝트" desc="AI 개발 직원이 접근할 수 있는 로컬 프로젝트입니다. 여기서 허용한 범위 안에서만 직원에게 읽기·수정·실행 권한을 줄 수 있고, 직원은 그 범위 안에서 승인 없이 개발 작업을 진행합니다."
        actions={<button onClick={() => setEditing("new")}>＋ 프로젝트 등록</button>} />
      {error && <div className="notice bad" onClick={() => setError(null)}>{error}</div>}
      <Tabs value={tab} onChange={setTab} tabs={[{ id: "projects", label: "프로젝트", count: list.data?.length }, { id: "changes", label: "변경 기록", count: changes.data?.length }]} />

      {tab === "projects" && (
        <SectionCard>
          <CrudList items={list.data} error={list.error} onRetry={list.reload} rowKey={(p) => p.id}
            empty={<EmptyState icon="projects" title="등록된 프로젝트가 없습니다" desc="프로젝트 폴더를 등록한 뒤, 직원 화면에서 '개발자' 권한 직원에게 접근 범위를 지정하세요." action={<button onClick={() => setEditing("new")}>＋ 프로젝트 등록</button>} />}
            columns={[
              { key: "name", header: "프로젝트", render: (p) => <><b>{p.name}</b><div className="small muted clamp2">{p.description || "설명 없음"}</div><div className="small muted" style={{ wordBreak: "break-all" }}>{p.root_path}</div></> },
              { key: "perm", header: "허용 범위", render: (p) => <div className="row wrap">{[["읽기", p.allow_read], ["수정", p.allow_write], ["실행", p.allow_exec], ["Git 조회", p.allow_git]].map(([l, on]) => <span key={String(l)} className={`badge plain ${on ? "ok" : ""}`}>{String(l)}{on ? "" : " ✕"}</span>)}</div> },
              { key: "prof", header: "실행 프로파일", render: (p) => (p.exec_profiles.length ? <div className="small">{p.exec_profiles.map((x) => <div key={x.name}><b>{x.name}</b> <span className="muted">({KIND[x.kind]}, {x.timeout_seconds}초)</span></div>)}</div> : <span className="muted small">없음</span>) },
              { key: "use", header: "사용", render: (p) => <span className="small">직원 {p.worker_count}명<br />변경 기록 {p.change_count}건</span> },
              { key: "state", header: "상태", render: (p) => <StatusBadge status={p.enabled ? "active" : "disabled"} /> },
            ]}
            actions={(p) => [
              { label: "수정", onClick: () => setEditing(p) },
              { label: p.enabled ? "비활성화" : "활성화", onClick: () => void toggle(p) },
              { label: "삭제", danger: true, onClick: () => setDeleting(p), disabled: p.change_count > 0, hint: p.change_count > 0 ? "변경 기록이 있어 삭제할 수 없습니다(이력 보존). 비활성화하세요" : undefined },
            ]} />
        </SectionCard>
      )}

      {tab === "changes" && (
        <SectionCard title="직원이 적용한 파일 변경" desc="변경 전후 해시와 diff 가 실행 기록과 함께 남습니다. 변경은 프로젝트 파일에 이미 적용된 상태입니다.">
          <CrudList items={changes.data} error={changes.error} onRetry={changes.reload} rowKey={(c) => c.id} pageSize={15} empty={<EmptyState title="아직 변경 기록이 없습니다" />}
            columns={[
              { key: "t", header: "시각", render: (c) => <span className="small">{fmtTime(c.created_at)}</span> },
              { key: "p", header: "프로젝트", render: (c) => names.get(c.project_id) ?? `#${c.project_id}` },
              { key: "f", header: "파일", render: (c) => <><code>{c.path}</code><div className="small muted">{c.action === "create" ? "새 파일" : "수정"} · {c.tool} · <span className="ok">+{c.added_lines}</span> <span style={{ color: "var(--bad)" }}>-{c.removed_lines}</span></div></> },
              { key: "r", header: "실행", render: (c) => (c.run_id ? `#${c.run_id}` : "-") },
              { key: "d", header: "diff", render: (c) => <Collapse title={<span className="small">보기</span>}><pre style={{ maxHeight: 280, overflow: "auto" }}>{c.diff || "(diff 없음)"}</pre><div className="small muted">sha256 {c.before_sha256 ? c.before_sha256.slice(0, 10) : "(신규)"} → {c.after_sha256.slice(0, 10)}</div></Collapse> },
            ]} />
        </SectionCard>
      )}

      {editing && <ProjectDialog current={editing === "new" ? null : editing} onClose={() => setEditing(null)} onSaved={() => (setEditing(null), list.reload())} />}
      <DeleteConfirmDialog open={!!deleting} title="프로젝트 등록을 삭제할까요?" itemName={deleting?.name ?? ""} action="등록 삭제"
        impact={["이 프로젝트에 부여된 직원 권한이 모두 사라집니다", "프로젝트 폴더와 파일은 삭제되지 않습니다(등록 정보만 삭제)"]}
        recovery={{ reversible: true, note: "같은 경로를 다시 등록하고 직원 권한을 다시 부여하면 됩니다." }} onCancel={() => setDeleting(null)}
        onConfirm={async () => { const p = deleting!; setDeleting(null); try { await api(`/projects/${p.id}`, { method: "DELETE" }); setError(null); } catch (e) { setError((e as Error).message); } list.reload(); }} />
    </div>
  );
}

function ProjectDialog({ current, onClose, onSaved }: { current: ProjectRow | null; onClose: () => void; onSaved: () => void }) {
  const form = useCrudForm<ProjectForm>(toForm(current ?? undefined), (v) => ({
    name: v.name.trim() ? undefined : "프로젝트 이름을 입력하세요",
    root_path: v.root_path.trim() ? undefined : "프로젝트 폴더의 절대 경로를 입력하세요",
    profiles: v.profiles.some((p) => !/^[a-z][a-z0-9_-]{0,29}$/.test(p.name) || toArgv(p.command).length === 0 || !(Number(p.timeout) >= 1)) ? "프로파일 이름(소문자·숫자·-_), 명령, 제한 시간(초)을 확인하세요" : undefined,
  }));
  const f = form.values;
  const upd = (i: number, patch: Partial<ProfileForm>) => form.set("profiles", f.profiles.map((p, j) => (j === i ? { ...p, ...patch } : p)));
  const save = async () => {
    const body = {
      name: f.name.trim(), root_path: f.root_path.trim(), description: f.description, allow_read: f.allow_read, allow_write: f.allow_read && f.allow_write, allow_exec: f.allow_read && f.allow_exec,
      allow_git: f.allow_read && f.allow_git, enabled: f.enabled,
      exec_profiles: f.profiles.map((p) => ({ name: p.name, kind: p.kind, argv: toArgv(p.command), timeout_seconds: Number(p.timeout), allow_args: p.allow_args, allowed_flags: toArgv(p.flags) })),
    };
    await api(current ? `/projects/${current.id}` : "/projects", { method: current ? "PUT" : "POST", json: body });
    onSaved();
  };
  return (
    <CrudDialog mode={current ? "update" : "create"} size="wide" title={current ? "프로젝트 수정" : "프로젝트 등록"} dirty={form.dirty} validate={form.check} onClose={onClose} onSubmit={save}
      description="경로는 서버가 실제 위치(심볼릭 링크 해석 후)로 확인합니다. 등록한 폴더 밖의 파일에는 어떤 직원도 접근할 수 없습니다.">
      <FormSection title="기본 정보">
        <div className="grid g2">
          <Field label="프로젝트 이름" required error={form.errorOf("name")}><input value={f.name} maxLength={80} onBlur={() => form.touch("name")} onChange={(e) => form.set("name", e.target.value)} placeholder="예: GyuNexus" /></Field>
          <Field label="로컬 경로(절대 경로)" required error={form.errorOf("root_path")} hint="예: D:\work\myapp 또는 /home/me/myapp"><input value={f.root_path} onBlur={() => form.touch("root_path")} onChange={(e) => form.set("root_path", e.target.value)} /></Field>
        </div>
        <Field label="설명"><textarea rows={2} value={f.description} onChange={(e) => form.set("description", e.target.value)} placeholder="이 프로젝트가 무엇인지(직원이 업무 맥락으로 봅니다)" /></Field>
      </FormSection>
      <FormSection title="허용 범위" desc="직원에게 줄 수 있는 권한의 상한입니다. 직원별로는 이 안에서 다시 고릅니다.">
        <label className="check"><input type="checkbox" checked={f.allow_read} onChange={(e) => form.set("allow_read", e.target.checked)} /><span>읽기 허용<div className="small muted">파일 탐색·읽기·검색. .env·키 파일 등 민감 파일과 node_modules·.git 은 항상 제외됩니다.</div></span></label>
        <label className="check"><input type="checkbox" checked={f.allow_write} disabled={!f.allow_read} onChange={(e) => form.set("allow_write", e.target.checked)} /><span>파일 수정 허용<div className="small muted">새 파일 생성과 기존 파일 수정(변경 전후와 diff 가 기록됩니다). 삭제 기능은 없습니다.</div></span></label>
        <label className="check"><input type="checkbox" checked={f.allow_exec} disabled={!f.allow_read} onChange={(e) => form.set("allow_exec", e.target.checked)} /><span>테스트·빌드 실행 허용<div className="small muted">아래 등록한 실행 프로파일만 실행할 수 있습니다. 주의: 테스트·빌드는 프로젝트의 코드를 실제로 실행하며 샌드박스가 아닙니다. 신뢰하는 프로젝트에만 허용하세요.</div></span></label>
        <label className="check"><input type="checkbox" checked={f.allow_git} disabled={!f.allow_read} onChange={(e) => form.set("allow_git", e.target.checked)} /><span>Git 조회 허용<div className="small muted">status·diff·log 조회만 가능합니다. commit·push·reset 은 제공되지 않습니다.</div></span></label>
        <label className="check"><input type="checkbox" checked={f.enabled} onChange={(e) => form.set("enabled", e.target.checked)} />활성화</label>
      </FormSection>
      <FormSection title="실행 프로파일" desc="직원은 임의 명령을 실행할 수 없고, 여기 등록한 이름만 고를 수 있습니다. 명령은 셸 없이 단어 배열로 실행됩니다.">
        {form.errorOf("profiles") && <div className="notice bad">{form.errorOf("profiles")}</div>}
        {f.profiles.map((p, i) => (
          <div key={i} className="card flat stack tight">
            <div className="grid g2">
              <Field label="이름"><input value={p.name} placeholder="test" onChange={(e) => upd(i, { name: e.target.value })} /></Field>
              <Field label="종류"><select value={p.kind} onChange={(e) => upd(i, { kind: e.target.value as ProfileForm["kind"] })}>{Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></Field>
            </div>
            <Field label="명령 (공백으로 구분)" hint="예: python -m pytest -q  /  npm run build  (셸 문법·파이프·따옴표는 사용할 수 없습니다)"><input value={p.command} onChange={(e) => upd(i, { command: e.target.value })} placeholder="python -m pytest -q" /></Field>
            <div className="grid g2">
              <Field label="제한 시간(초)"><input type="number" min={1} value={p.timeout} onChange={(e) => upd(i, { timeout: e.target.value })} /></Field>
              <Field label="AI 가 덧붙일 수 있는 옵션 (공백 구분, 선택)"><input value={p.flags} disabled={!p.allow_args} onChange={(e) => upd(i, { flags: e.target.value })} placeholder="-x -k" /></Field>
            </div>
            <div className="row between"><label className="check"><input type="checkbox" checked={p.allow_args} onChange={(e) => upd(i, { allow_args: e.target.checked })} />AI 가 추가 인자(테스트 파일 경로 등)를 덧붙이는 것 허용</label>
              <button type="button" className="ghost sm" onClick={() => form.set("profiles", f.profiles.filter((_, j) => j !== i))}>프로파일 삭제</button></div>
          </div>
        ))}
        <div><button type="button" className="secondary" onClick={() => form.set("profiles", [...f.profiles, { name: "", kind: "test", command: "", timeout: "120", allow_args: false, flags: "" }])}>＋ 프로파일 추가</button></div>
      </FormSection>
    </CrudDialog>
  );
}
