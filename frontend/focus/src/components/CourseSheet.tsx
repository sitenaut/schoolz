import { useRef, useState } from "react";
import {
  PALETTE_HEXES,
  courseColorProps,
  daysFromToday,
  defaultPaletteHex,
  displayCourseName,
  dueLabel,
  shortCourseName,
  sortMissingByRecency,
} from "../courses";
import type { CourseProgress, TodoItem } from "../types";
import { Capped } from "./Capped";
import { Sheet } from "./Sheet";

/** Where the future lives.
 *
 * The dashboard is deliberately blind past the next school day, so this
 * is the only place next week's essay exists. Putting it behind a tap on
 * a subject tile - a different tab, a different screen - is what gives
 * permission to ignore it tonight. Grouped by distance, nearest first. */
export function CourseSheet({
  course,
  items,
  todayIso,
  onClose,
  onOpenItem,
  onToggle,
  customColor,
  onSetColor,
  customName,
  onSetName,
}: {
  course: CourseProgress;
  items: TodoItem[];
  todayIso: string;
  onClose: () => void;
  onOpenItem: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
  customColor?: string;
  onSetColor: (hex: string | null) => void;
  customName?: string;
  onSetName: (name: string | null) => void;
}) {
  const [showDone, setShowDone] = useState(false);
  const [editingAppearance, setEditingAppearance] = useState(false);
  const displayName = displayCourseName(course.course_name, customName);

  // Same rule Focus's Needs Attention uses - most recently missed first -
  // scoped to just this class, per the request: "pretend you're filtering
  // [Focus] by that particular class".
  const missing = sortMissingByRecency(items.filter((i) => i.category === "missing"));
  const upcoming = items.filter((i) => i.category === "due" && i.due_date);
  const thisWeek = upcoming.filter((i) => daysFromToday(i.due_date!, todayIso) <= 7);
  const later = upcoming.filter((i) => daysFromToday(i.due_date!, todayIso) > 7);
  const undated = items.filter((i) => i.category === "no_due_date");
  const done = items.filter((i) => i.category === "done");

  return (
    <Sheet onClose={onClose} label={displayName}>
      <div className="sheet-title-row">
        <h2 className="sheet-title">{displayName}</h2>
        <button
          type="button"
          className="sheet-edit-toggle"
          aria-label={editingAppearance ? "Done editing name and color" : "Edit class name and color"}
          aria-pressed={editingAppearance}
          onClick={() => setEditingAppearance((v) => !v)}
        >
          <IconEdit />
        </button>
      </div>
      <p className="sheet-course">
        {course.teacher_name ? (
          course.teacher_emails.length > 0 ? (
            <a href={`mailto:${course.teacher_emails[0]}`}>{course.teacher_name}</a>
          ) : (
            course.teacher_name
          )
        ) : (
          "Teacher unknown"
        )}
        {course.grade_percent !== null && ` · ${Math.round(course.grade_percent)}%`}
      </p>

      {editingAppearance && (
        <>
          <NamePicker autoName={shortCourseName(course.course_name)} customName={customName} onSetName={onSetName} />
          <ColorPicker courseKey={course.course_key} customColor={customColor} onSetColor={onSetColor} />
        </>
      )}

      {/* Same pacing principle as the Focus tab: what's still due soon (still
          full credit, still worth acting on today) leads, and what's already
          missing - which can't get any less late by staring at it - follows,
          not the other way around. */}
      <ItemList label="This week" items={thisWeek} todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />
      <ItemList label="Missing" items={missing} tone="missed" todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />
      <ItemList label="Later" items={later} todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />
      <ItemList label="No due date" items={undated} todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />

      {missing.length + upcoming.length + undated.length === 0 && (
        <p className="sheet-empty">Nothing outstanding in this class.</p>
      )}

      {done.length > 0 && (
        <section className="finished">
          <button type="button" className="finished-toggle" onClick={() => setShowDone((s) => !s)}>
            {showDone ? "Hide" : "Show"} finished ({done.length})
          </button>
          {showDone && <ItemList label={null} items={done} todayIso={todayIso} onOpen={onOpenItem} onToggle={onToggle} />}
        </section>
      )}
    </Sheet>
  );
}

/** "She wanted to be able to customize the color of the class" - ten preset
 * swatches (the same fixed palette every tile draws its default from, so
 * picking one still reads as part of the same set) plus a native color
 * input for anything else. The native input is the point for "like a
 * color picker": it opens the OS's own picker on both iOS and Android,
 * no library needed. Persisted server-side, per account (lib/
 * coursePreferences.ts), keyed by course_key so it's the exact same
 * identity Focus's chips and this tile's own color already share. */
/** "Give the class a display name that's also editable" - propagates
 * everywhere the class is referenced, the same way the color override
 * does and for the same reason: both are keyed by course_key, and both
 * are resolved through one shared function (displayCourseName /
 * courseColorProps) rather than each screen applying its own override
 * separately, which is exactly how the color mismatch happened the first
 * time.
 *
 * Two real complaints from actually using this: showing the auto-derived
 * name AS the placeholder read as already-typed text that needed
 * deleting first, not an empty field - now plain instructional text, with
 * the default spelled out in a hint line instead. And on a phone,
 * focusing the input zooms the page in (iOS Safari does this to any text
 * input under 16px - see the CSS) and "tap elsewhere to save" isn't an
 * obvious next step while the view is zoomed. Explicit check/✕ buttons,
 * always in frame next to the field, are the way out - either one blurs
 * the input, which is what lets the browser un-zoom. */
function NamePicker({
  autoName,
  customName,
  onSetName,
}: {
  autoName: string;
  customName?: string;
  onSetName: (name: string | null) => void;
}) {
  const [draft, setDraft] = useState(customName ?? "");
  const inputRef = useRef<HTMLInputElement>(null);

  // An empty field showing the auto name AS its placeholder read as
  // already-filled-in text that needed deleting first, not as "type
  // something here" - confirmed real, reported directly. Plain
  // instructional text instead; the default name still shows up as soon
  // as it's actually applied (the sheet title above updates live).
  const commit = () => {
    const trimmed = draft.trim();
    if (trimmed !== (customName ?? "")) onSetName(trimmed || null);
    inputRef.current?.blur();
  };

  const cancel = () => {
    setDraft(customName ?? "");
    inputRef.current?.blur();
  };

  return (
    <section className="sheet-row name-picker">
      <h3>Class name</h3>
      <div className="name-row">
        <input
          ref={inputRef}
          className="name-input"
          value={draft}
          placeholder="Enter a custom name"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") commit();
            if (e.key === "Escape") cancel();
          }}
          aria-label="Class display name"
        />
        {/* Always in frame next to the field itself, Jira-style, rather
            than relying on "tap away to save" - on a phone that's also
            "tap away" while the keyboard has the view zoomed in, with no
            obvious next step. Tapping either one blurs the input, which
            is what lets the browser un-zoom. */}
        <button type="button" className="name-commit" aria-label="Save name" onClick={commit}>
          <IconCheck />
        </button>
        <button type="button" className="name-cancel" aria-label="Cancel" onClick={cancel}>
          <IconX />
        </button>
      </div>
      <p className="name-hint">Leave blank to use the default: {autoName}</p>
    </section>
  );
}

function ColorPicker({
  courseKey,
  customColor,
  onSetColor,
}: {
  courseKey: string;
  customColor?: string;
  onSetColor: (hex: string | null) => void;
}) {
  const { className: defaultClassName } = courseColorProps(courseKey);
  // With no custom pick, the class still HAS a color - the deterministic
  // default - and the picker should show that as selected rather than
  // leaving every swatch looking unchosen.
  const activeHex = customColor ?? defaultPaletteHex(courseKey);
  return (
    <section className="sheet-row color-picker">
      <h3>Class color</h3>
      <div className="swatch-row">
        {PALETTE_HEXES.map((hex) => (
          <button
            key={hex}
            type="button"
            className={`swatch${activeHex === hex ? " swatch-selected" : ""}`}
            style={{ background: hex }}
            aria-label={`Use ${hex}`}
            aria-pressed={activeHex === hex}
            onClick={() => onSetColor(hex)}
          />
        ))}
        <label
          className={`swatch swatch-custom${customColor && !PALETTE_HEXES.includes(customColor) ? " swatch-selected" : ""}`}
          aria-label="Pick a custom color"
        >
          <input type="color" value={customColor ?? "#888888"} onChange={(e) => onSetColor(e.target.value)} />
          <span aria-hidden="true">+</span>
        </label>
      </div>
      {customColor && (
        <button type="button" className="ask-restart" onClick={() => onSetColor(null)}>
          Use the default color ({defaultClassName.replace("tile-", "")})
        </button>
      )}
    </section>
  );
}

function IconEdit() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3z" />
      <path d="M14 6l4 4" />
    </svg>
  );
}

function IconCheck() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}

function IconX() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 6l12 12M18 6L6 18" />
    </svg>
  );
}

function ItemList({
  label,
  items,
  tone,
  todayIso,
  onOpen,
  onToggle,
}: {
  label: string | null;
  items: TodoItem[];
  tone?: "missed";
  todayIso: string;
  onOpen: (item: TodoItem) => void;
  onToggle: (item: TodoItem, done: boolean) => void;
}) {
  if (items.length === 0) return null;
  return (
    <section className="sheet-section">
      {label && <h3 className={`group-heading${tone ? ` ${tone}` : ""}`}>{label}</h3>}
      <Capped items={items} cap={5} noun="tasks">
        {(visible) => (
          <ul className="sheet-list">
            {visible.map((item) => (
              <li key={item.id} className={`sheet-item${item.done ? " is-done" : ""}`}>
                <button type="button" className="sheet-item-open" onClick={() => onOpen(item)}>
                  <span className="sheet-item-title">{item.title}</span>
                  {item.due_date && <span className="due">{dueLabel(item.due_date, todayIso)}</span>}
                </button>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={item.done}
                    onChange={(e) => onToggle(item, e.target.checked)}
                    aria-label={`Mark ${item.title} done`}
                  />
                  <span className="box" aria-hidden="true" />
                </label>
              </li>
            ))}
          </ul>
        )}
      </Capped>
    </section>
  );
}
