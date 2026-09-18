import { useEffect } from "react";
import { shortCourseName } from "../courses";
import type { SuggestionState, TodoItem } from "../types";

export function TaskModal({
  item,
  suggestion,
  onSuggest,
  onClose,
  onToggle,
}: {
  item: TodoItem;
  suggestion: SuggestionState | null;
  onSuggest: (item: TodoItem) => void;
  onClose: () => void;
  onToggle: (item: TodoItem, done: boolean) => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const points = item.grade?.score_possible ?? null;

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={item.title} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-grab" aria-hidden="true" />
        <h2 className="sheet-title">{item.title}</h2>

        {item.course_name && <p className="sheet-course">{shortCourseName(item.course_name)}</p>}

        {/* First, before teacher or due date: not knowing how to begin is
            the thing that stalls an assignment, so the way in comes before
            the admin. Shown outright when already cached; otherwise it is
            one button, because the sheet must never do a model call on its
            own just from being opened. */}
        {!item.done && <Starter item={item} state={suggestion} onSuggest={onSuggest} />}

        {item.teacher_name && (
          <section className="sheet-row">
            <h3>Teacher</h3>
            <p>
              {item.teacher_emails.length > 0 ? (
                <a href={`mailto:${item.teacher_emails[0]}`}>{item.teacher_name}</a>
              ) : (
                item.teacher_name
              )}
            </p>
          </section>
        )}

        {item.due_raw && (
          <section className="sheet-row">
            <h3>Due</h3>
            <p>{item.due_raw}</p>
          </section>
        )}

        {item.link && (
          <section className="sheet-row">
            <h3>Attachments</h3>
            <p>
              <a
                href={item.link.startsWith("http") ? item.link : `https://classroom.google.com${item.link}`}
                target="_blank"
                rel="noreferrer"
              >
                Open in Classroom
              </a>
            </p>
          </section>
        )}

        {points !== null && (
          <section className="sheet-row">
            <h3>Point value</h3>
            <p>{points} pts</p>
          </section>
        )}

        {/* Classroom's own status is shown as reported, never rewritten -
            a person's mark in schoolz beats it in both directions, and
            hiding the disagreement would make that confusing. */}
        {item.classroom_status && (
          <section className="sheet-row">
            <h3>Classroom says</h3>
            <p>{item.classroom_status}</p>
          </section>
        )}

        <button type="button" className={`primary${item.done ? " undo" : ""}`} onClick={() => onToggle(item, !item.done)}>
          {item.done ? "Mark as not done" : "Mark as done"}
        </button>
        {item.done && item.marked_by && <p className="sheet-note">Marked by {item.marked_by}</p>}
      </div>
    </div>
  );
}

function Starter({
  item,
  state,
  onSuggest,
}: {
  item: TodoItem;
  state: SuggestionState | null;
  onSuggest: (item: TodoItem) => void;
}) {
  if (!state) {
    return (
      <section className="starter">
        <button type="button" className="starter-ask" onClick={() => onSuggest(item)}>
          How do I start?
        </button>
      </section>
    );
  }
  if (state.loading) {
    return (
      <section className="starter">
        <p className="starter-status">Thinking…</p>
      </section>
    );
  }
  if (state.error) {
    return (
      <section className="starter">
        <p className="starter-status">{state.error}</p>
        <button type="button" className="starter-ask" onClick={() => onSuggest(item)}>
          Try again
        </button>
      </section>
    );
  }
  if (state.declined || !state.text) {
    return (
      <section className="starter">
        <h3>How to start</h3>
        <p className="starter-status">
          The title doesn't say enough to suggest a way in — open it in Classroom, or ask the teacher what they're
          looking for.
        </p>
      </section>
    );
  }
  // The model is told to answer as "- " bullets, first one under five
  // minutes. Rendered as a real list so each step is one scannable line.
  const steps = state.text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => l.replace(/^[-*•]\s*/, ""));
  return (
    <section className="starter">
      <h3>How to start</h3>
      <ol className="starter-steps">
        {steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </section>
  );
}
