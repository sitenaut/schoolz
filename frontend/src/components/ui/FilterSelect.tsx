import { useEffect, useId, useMemo, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import { useTranslation } from "react-i18next";
import { IconCheck, IconSearch } from "../icons";

export type FilterOption = {
  value: string;
  label: string;
  /** Heading the option sits under (school type, state). */
  group?: string;
  /** Second line: what tells two same-named options apart (the town). */
  hint?: string;
  /** Right-aligned number, e.g. how many schools are picked in a town. */
  count?: number;
};

type Props = {
  value: string;
  onChange: (value: string) => void;
  options: FilterOption[];
  /** Shown on the button while nothing is selected. */
  placeholder: string;
  /** When set, a first row that clears the selection ("All schools"). */
  clearLabel?: string;
  filterPlaceholder?: string;
  ariaLabel?: string;
  disabled?: boolean;
  required?: boolean;
  className?: string;
};

/** Lists this short need no filter box - it would only raise the keyboard. */
const FILTER_FROM = 8;

/** Words AND across label, hint and group, so "cherry high" finds a school by
 * town and type. */
export function filterOptions(options: FilterOption[], q: string): FilterOption[] {
  const words = q.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return options;
  return options.filter((o) => {
    const hay = `${o.label} ${o.hint ?? ""} ${o.group ?? ""}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

/** A dropdown you can type into. Replaces a native `<select>` wherever the
 * list is schools, districts or towns, which grow with every onboarding. */
export function FilterSelect({ value, onChange, options, placeholder, clearLabel, filterPlaceholder, ariaLabel, disabled, required, className = "" }: Props) {
  const { t } = useTranslation();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const list = useRef<HTMLDivElement>(null);

  const showFilter = options.length > FILTER_FROM;
  const rows = useMemo(() => {
    const matched = filterOptions(options, q);
    return clearLabel && !q.trim() ? [{ value: "", label: clearLabel }, ...matched] : matched;
  }, [options, q, clearLabel]);
  const selected = options.find((o) => o.value === value);

  const close = (refocus = true) => {
    setOpen(false);
    setQ("");
    if (refocus) trigger.current?.focus();
  };

  const openList = () => {
    if (disabled) return;
    setActive(Math.max(0, rows.findIndex((o) => o.value === value)));
    setOpen(true);
  };

  useEffect(() => {
    if (!open) return;
    // On a phone, focusing the filter raises the keyboard over the list
    // someone may only want to scroll; they can tap the box to type.
    const touch = typeof window.matchMedia === "function" && window.matchMedia("(pointer: coarse)").matches;
    if (showFilter && !touch) input.current?.focus();
    else list.current?.focus();
    const outside = (e: MouseEvent | TouchEvent) => {
      if (!root.current?.contains(e.target as Node)) close(false);
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("touchstart", outside);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("touchstart", outside);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (open) list.current?.querySelector<HTMLElement>('[data-active="true"]')?.scrollIntoView?.({ block: "nearest" });
  }, [open, active]);

  const pick = (v: string) => {
    onChange(v);
    close();
  };

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!rows.length) return;
      const step = e.key === "ArrowDown" ? 1 : -1;
      setActive((a) => (a + step + rows.length) % rows.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (rows[active]) pick(rows[active].value);
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      close();
    } else if (e.key === "Tab") {
      close(false);
    }
  };

  let lastGroup: string | undefined;
  return (
    <div className={`fsel ${open ? "open" : ""} ${className}`} ref={root}>
      <button
        type="button"
        className="fsel-trigger"
        ref={trigger}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => (open ? close() : openList())}
        onKeyDown={(e) => {
          if (!open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
            e.preventDefault();
            openList();
          }
        }}
      >
        <span className={selected ? "fsel-value" : "fsel-value placeholder"}>{selected ? selected.label : clearLabel && !required ? clearLabel : placeholder}</span>
        <svg className="fsel-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>
      {/* Lets a surrounding <form> refuse to submit with nothing chosen, the
          way a native required <select> does. */}
      {required && <input className="fsel-required" tabIndex={-1} aria-hidden="true" required value={value} onChange={() => {}} onFocus={() => trigger.current?.focus()} />}
      {open && (
        // preventDefault: inside a <label> (Field), a click on an option would
        // otherwise be forwarded to the trigger and reopen the list.
        <div className="fsel-pop" onClick={(e) => e.preventDefault()}>
          {showFilter && (
            <div className="fsel-filter">
              <IconSearch />
              <input
                ref={input}
                role="combobox"
                aria-expanded="true"
                aria-controls={`${id}-list`}
                aria-activedescendant={rows[active] ? `${id}-${active}` : undefined}
                aria-label={filterPlaceholder ?? t("Type to filter…")}
                placeholder={filterPlaceholder ?? t("Type to filter…")}
                value={q}
                autoComplete="off"
                onChange={(e) => {
                  setQ(e.target.value);
                  setActive(0);
                }}
                onKeyDown={onKey}
              />
            </div>
          )}
          <div className="fsel-list" role="listbox" id={`${id}-list`} ref={list} tabIndex={-1} onKeyDown={onKey}>
            {rows.length === 0 && <div className="fsel-empty">{t("No matches")}</div>}
            {rows.map((o, i) => {
              const heading = o.group && o.group !== lastGroup ? o.group : null;
              lastGroup = o.group;
              return (
                <div key={o.value || "__clear"}>
                  {heading && <div className="fsel-group">{heading}</div>}
                  <div
                    id={`${id}-${i}`}
                    role="option"
                    aria-selected={o.value === value}
                    data-active={i === active}
                    className="fsel-opt"
                    onMouseEnter={() => setActive(i)}
                    onClick={() => pick(o.value)}
                  >
                    <span className="fsel-opt-text">
                      {o.label}
                      {o.hint && <small>{o.hint}</small>}
                    </span>
                    {o.count ? <span className="fsel-count">{o.count}</span> : null}
                    {o.value === value && <IconCheck className="fsel-check" />}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
