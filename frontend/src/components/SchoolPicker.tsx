import { useEffect, useMemo, useRef, useState } from "react";
import { useMySchools } from "../lib/mySchools";
import type { School } from "../types";

const TIERS: { key: string; label: string }[] = [
  { key: "elementary", label: "Elementary" },
  { key: "middle", label: "Middle" },
  { key: "high", label: "High school" },
  { key: "alternative", label: "Alternative" },
  { key: "other", label: "Preschool & early childhood" },
];

/** One dropdown for "which schools' dates am I looking at": the visitor's
 * own schools listed first (pre-checked), then every other tracked school
 * as a multi-select underneath - so a parent can pull in a neighbor's
 * school or a district-wide view without touching their own picked list
 * on /start. District-wide items (closures, early dismissals, board
 * meetings) always show for any selection - the backend includes the
 * district of every selected school, and an empty selection shows all
 * schools - so there's deliberately no "district" checkbox to forget. */
export function SchoolPicker({ selected, onChange }: { selected: string[]; onChange: (slugs: string[]) => void }) {
  const { mySchools, allSchools, colorFor } = useMySchools();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onClick = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const mine = new Set(mySchools.map((s) => s.slug));
  const others = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return allSchools.filter((s) => !mine.has(s.slug) && (!needle || s.name.toLowerCase().includes(needle) || (s.short_name ?? "").toLowerCase().includes(needle)));
  }, [allSchools, q, mySchools]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (s: School) => onChange(selected.includes(s.slug) ? selected.filter((x) => x !== s.slug) : [...selected, s.slug]);
  const bySlug = new Map(allSchools.map((s) => [s.slug, s]));
  const chosen = selected.map((slug) => bySlug.get(slug)).filter((s): s is School => Boolean(s));
  const label =
    chosen.length === 0
      ? "All schools"
      : chosen.length <= 2
        ? chosen.map((s) => s.short_name || s.name).join(", ")
        : `${chosen[0].short_name || chosen[0].name} + ${chosen.length - 1} more`;

  const row = (s: School) => (
    <label className="pickerRow" key={s.id}>
      <input type="checkbox" checked={selected.includes(s.slug)} onChange={() => toggle(s)} />
      {s.logo_url ? <img className="pickerLogo" src={s.logo_url} alt="" /> : <span className="dot" style={{ ["--c" as string]: colorFor(s.id) }} />}
      <span className="pickerName">{s.short_name || s.name}</span>
    </label>
  );

  return (
    <div className="schoolPicker" ref={ref}>
      <button className="pickerTrigger" onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-haspopup="listbox">
        <span className="pickerTriggerLabel">
          <span className="eyebrow">Showing</span>
          {label}
        </span>
        <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className="pickerPanel" role="dialog" aria-label="Choose schools">
          <div className="pickerActions">
            <button className="ghost" onClick={() => onChange(mySchools.map((s) => s.slug))} disabled={mySchools.length === 0}>
              My schools
            </button>
            <button className="ghost" onClick={() => onChange([])}>
              All schools
            </button>
          </div>
          {mySchools.length > 0 && (
            <>
              <div className="tier">My schools</div>
              {mySchools.map(row)}
            </>
          )}
          <div className="tier" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
            Other schools
            <input className="pickerSearch" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {TIERS.map((t) => {
            const group = others.filter((s) => (s.school_type ?? "other") === t.key);
            if (group.length === 0) return null;
            return (
              <div key={t.key}>
                <div className="pickerTier">{t.label}</div>
                {group.map(row)}
              </div>
            );
          })}
          <p className="fine" style={{ textAlign: "left", margin: "8px 0 0" }}>
            District-wide dates (closures, early dismissals, board meetings) always show.
          </p>
        </div>
      )}
    </div>
  );
}
