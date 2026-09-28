import { useMemo, useState, type ReactNode } from "react";

export type Column<T> = {
  id: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  /** Value used for sorting; omit to make the column unsortable. */
  sortValue?: (row: T) => string | number | null | undefined;
  align?: "left" | "right";
  width?: string;
  /** Skip the mobile "label:" prefix (for cells that are self-explanatory). */
  noLabel?: boolean;
};

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  getRowId: (row: T) => string;
  loading?: boolean;
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  rowActions?: (row: T) => ReactNode;
  defaultSort?: { id: string; dir: "asc" | "desc" };
  /** Server-side sorting: the parent owns the sort and the row order; the
   * table only draws the arrows and reports clicks. Columns need a
   * `sortValue` (any) to be clickable. */
  sort?: { id: string; dir: "asc" | "desc" };
  onSortChange?: (sort: { id: string; dir: "asc" | "desc" }) => void;
};

/** Small client-side table: sortable headers, row click, trailing actions,
 * and a CSS-driven card layout under 720px (see ui.css .dt). Deliberately
 * not a full TanStack table - the jobs list is ~100 rows, filtering happens
 * above it, and pagination would just hide things. */
export function DataTable<T>({ columns, rows, getRowId, loading, empty, onRowClick, rowActions, defaultSort, sort: controlledSort, onSortChange }: Props<T>) {
  const [localSort, setLocalSort] = useState(defaultSort ?? null);
  const controlled = onSortChange !== undefined;
  const sort = controlled ? (controlledSort ?? null) : localSort;

  const sorted = useMemo(() => {
    if (controlled || !sort) return rows;
    const col = columns.find((c) => c.id === sort.id);
    if (!col?.sortValue) return rows;
    const dir = sort.dir === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => {
      const av = col.sortValue!(a);
      const bv = col.sortValue!(b);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
    });
  }, [rows, sort, columns, controlled]);

  const toggleSort = (id: string) => {
    const next = sort?.id === id ? { id, dir: sort.dir === "asc" ? ("desc" as const) : ("asc" as const) } : { id, dir: "asc" as const };
    if (controlled) onSortChange!(next);
    else setLocalSort(next);
  };

  return (
    <div className="dt-wrap">
      <table className="dt">
        <thead>
          <tr>
            {columns.map((c) => (
              <th
                key={c.id}
                className={`${c.sortValue ? "sortable" : ""} ${c.align === "right" ? "num" : ""}`}
                style={c.width ? { width: c.width } : undefined}
                onClick={c.sortValue ? () => toggleSort(c.id) : undefined}
                aria-sort={sort?.id === c.id ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
              >
                {c.header}
                {sort?.id === c.id && <span className="sort">{sort.dir === "asc" ? "▲" : "▼"}</span>}
              </th>
            ))}
            {rowActions && <th className="num" aria-label="Actions" />}
          </tr>
        </thead>
        <tbody>
          {loading && rows.length === 0 ? (
            <tr>
              <td className="dt-empty no-label" colSpan={columns.length + (rowActions ? 1 : 0)}>
                Loading…
              </td>
            </tr>
          ) : sorted.length === 0 ? (
            <tr>
              <td className="dt-empty no-label" colSpan={columns.length + (rowActions ? 1 : 0)}>
                {empty ?? "Nothing here."}
              </td>
            </tr>
          ) : (
            sorted.map((row) => (
              <tr key={getRowId(row)} className={onRowClick ? "clickable" : ""} onClick={onRowClick ? () => onRowClick(row) : undefined}>
                {columns.map((c) => (
                  <td
                    key={c.id}
                    className={`${c.align === "right" ? "num" : ""} ${c.noLabel ? "no-label" : ""}`}
                    data-label={typeof c.header === "string" ? c.header : c.id}
                  >
                    {c.cell(row)}
                  </td>
                ))}
                {rowActions && (
                  <td className="actions no-label" onClick={(e) => e.stopPropagation()}>
                    <span className="row-actions">{rowActions(row)}</span>
                  </td>
                )}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
