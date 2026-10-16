import { useEffect, useState } from "react";
import { type ResourceSummary, searchResources } from "../../lib/localz";

const PAGE_SIZE = 20;

type Result = { key: string; page: number; items: ResourceSummary[]; total: number; error: boolean };

/** POSTs a resource search and pages through it ("Show more" appends).
 * `enabled: false` (an empty home-page search) does nothing. Every result
 * remembers the query and page it answers, so a response for an older query
 * is never shown and "loading" is simply "no answer yet for this one". */
export function useResourceSearch({ category, query, county, type, enabled = true }: { category?: string; query?: string; county?: string; type?: string; enabled?: boolean }) {
  const key = JSON.stringify([category ?? "", query ?? "", county ?? "", type ?? ""]);
  // The page belongs to the query it was asked for: a new query is page 1
  // on the same render, never "page 2 of the new query" first.
  const [paging, setPaging] = useState({ key, page: 1 });
  const page = paging.key === key ? paging.page : 1;
  const [result, setResult] = useState<Result | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    searchResources({ category: category || undefined, query: query || undefined, county: county || undefined, type: type || undefined, page, page_size: PAGE_SIZE })
      .then((d) => {
        if (cancelled) return;
        setResult((prev) => ({
          key,
          page,
          items: page > 1 && prev?.key === key ? [...prev.items, ...d.items] : d.items,
          total: d.total,
          error: false,
        }));
      })
      .catch(() => {
        if (cancelled) return;
        setResult((prev) => (prev?.key === key ? { ...prev, page, error: true } : { key, page, items: [], total: 0, error: true }));
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, page, enabled]);

  const current = enabled && result?.key === key ? result : null;
  const items = current?.items ?? [];
  const total = current?.total ?? 0;
  return {
    items,
    total,
    loading: enabled && (current === null || current.page !== page),
    error: !!current?.error && current.page === page,
    hasMore: items.length < total,
    loadMore: () => setPaging({ key, page: page + 1 }),
  };
}
