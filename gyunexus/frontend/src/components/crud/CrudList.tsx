import { useEffect, useState, type ReactNode } from "react";
import { ErrorState, LoadingState } from "../ui";
import { CrudActions, type MenuAction } from "./CrudActions";

/**
 * 공통 목록. 표(table)와 카드(cards) 중 화면이 고른다. 로딩·오류·빈 상태·페이지 나누기·행 액션 메뉴를 담당하고
 * 데이터를 어떻게 가져오는지, 행이 무슨 뜻인지는 모른다.
 */
export interface Column<T> { key: string; header: string; render: (row: T) => ReactNode; className?: string }

interface Props<T> {
  items: T[] | null;
  rowKey: (row: T) => string | number;
  empty: ReactNode;
  error?: string | null;
  onRetry?: () => void;
  actions?: (row: T) => MenuAction[];
  pageSize?: number;
  /** 표 보기 */
  columns?: Column<T>[];
  /** 카드 보기: 선택 가능한 한 줄의 내용을 그린다 */
  renderCard?: (row: T, selected: boolean) => ReactNode;
  selectedKey?: string | number | null;
  onSelect?: (row: T) => void;
}

export function CrudList<T>({ items, rowKey, empty, error, onRetry, actions, pageSize, columns, renderCard, selectedKey, onSelect }: Props<T>) {
  const [page, setPage] = useState(0);
  const total = items?.length ?? 0;
  const pages = pageSize ? Math.max(1, Math.ceil(total / pageSize)) : 1;
  useEffect(() => { if (page >= pages) setPage(pages - 1); }, [page, pages]);
  if (items === null) return error ? <ErrorState message={error} onRetry={onRetry} /> : <LoadingState />;
  if (items.length === 0) return <>{empty}</>;
  const shown = pageSize ? items.slice(page * pageSize, (page + 1) * pageSize) : items;

  return (
    <div>
      {columns ? (
        <div className="table-wrap">
          <table className="crud-table">
            <thead><tr>{columns.map((c) => <th key={c.key} className={c.className}>{c.header}</th>)}{actions && <th className="act-col"><span className="sr-only">작업</span></th>}</tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={rowKey(r)}>
                  {columns.map((c) => <td key={c.key} className={c.className}>{c.render(r)}</td>)}
                  {actions && <td className="act-col"><CrudActions actions={actions(r)} /></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="crud-cards">
          {shown.map((r) => {
            const sel = selectedKey !== undefined && selectedKey === rowKey(r);
            return (
              <div key={rowKey(r)} className={`crud-card ${sel ? "active" : ""}`}>
                <button type="button" className="crud-card-main" aria-current={sel ? "true" : undefined} onClick={() => onSelect?.(r)}>{renderCard?.(r, sel)}</button>
                {actions && <CrudActions actions={actions(r)} />}
              </div>
            );
          })}
        </div>
      )}
      {pageSize && pages > 1 && (
        <nav className="pager" aria-label="페이지 이동">
          <button type="button" className="secondary sm" disabled={page === 0} onClick={() => setPage(page - 1)}>이전</button>
          <span className="small muted" aria-live="polite">{page + 1} / {pages} · 전체 {total}건</span>
          <button type="button" className="secondary sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>다음</button>
        </nav>
      )}
    </div>
  );
}