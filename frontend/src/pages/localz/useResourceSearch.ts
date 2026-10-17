import { useEffect, useState } from "react";
import { type ResourceSummary, fetchNearby, fetchResourcesByIds, searchResources } from "../../lib/localz";
import { type LocalzScope, boxAround, orderNearby } from "../../lib/localzWhere";

const PAGE_SIZE = 20;

type Result = { key: string; page: number; items: ResourceSummary[]; total: number; error: boolean };
type Ordered = { key: string; rows: { id: string; miles: number }[] } | { key: string; error: true };

/** POSTs a resource search and pages through it ("Show more" appends).
 * `enabled: false` (an empty home-page search) does nothing. Every result
 * remembers the query and page it answers, so a response for an older query
 * is never shown and "loading" is simply "no answer yet for this one".
 *
 * With `near` (a point the visitor set, and a radius), the list is closest
 * first: /nearby gives every match placed in a coarse box around the point,
 * measured and sorted here, and once those run out the pages continue with
 * what has no place to measure (hotlines, statewide programs, shelters). */
export function useResourceSearch({
  category,
  query,
  type,
  scope,
  enabled = true,
}: {
  category?: string;
  query?: string;
  type?: string;
  scope: Pick<LocalzScope, "county" | "near">;
  enabled?: boolean;
}) {
  const { county, near } = scope;
  const box = near ? boxAround(near.lat, near.lon, near.miles) : undefined;
  const key = JSON.stringify([category ?? "", query ?? "", county ?? "", type ?? "", near]);
  // The page belongs to the query it was asked for: a new query is page 1
  // on the same render, never "page 2 of the new query" first.
  const [paging, setPaging] = useState({ key, page: 1 });
  const page = paging.key === key ? paging.page : 1;
  const [result, setResult] = useState<Result | null>(null);
  const [ordered, setOrdered] = useState<Ordered | null>(null);
  const orderedNow = near ? (ordered?.key === key ? ordered : null) : null;

  useEffect(() => {
    if (!enabled || !near || !box) return;
    let cancelled = false;
    fetchNearby({ category: category || undefined, query: query || undefined, type: type || undefined, box })
      .then((points) => !cancelled && setOrdered({ key, rows: orderNearby(points, near.lat, near.lon, near.miles) }))
      .catch(() => !cancelled && setOrdered({ key, error: true }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled]);

  useEffect(() => {
    if (!enabled) return;
    if (near && !orderedNow) return; // measuring first
    let cancelled = false;
    const base = { category: category || undefined, query: query || undefined, county: county || undefined, type: type || undefined };
    let request: Promise<{ items: ResourceSummary[]; total: number }>;
    if (orderedNow && "error" in orderedNow) {
      request = Promise.reject(new Error("nearby failed"));
    } else if (orderedNow) {
      const rows = orderedNow.rows;
      const start = (page - 1) * PAGE_SIZE;
      const slice = rows.slice(start, start + PAGE_SIZE);
      const room = PAGE_SIZE - slice.length;
      const miles = new Map(slice.map((r) => [r.id, r.miles]));
      request = Promise.all([
        fetchResourcesByIds(slice.map((r) => r.id)),
        // Asked even on a full page, for the total.
        searchResources({ ...base, outside: box, offset: Math.max(0, start - rows.length), page_size: Math.max(1, room) }),
      ]).then(([placed, rest]) => ({
        items: [...placed.map((r) => ({ ...r, distance_miles: miles.get(r.id) })), ...(room > 0 ? rest.items : [])],
        total: rows.length + rest.total,
      }));
    } else {
      request = searchResources({ ...base, page, page_size: PAGE_SIZE });
    }
    request
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
  }, [key, page, enabled, orderedNow]);

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
