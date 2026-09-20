import { useState } from "react";
import { displayCourseName } from "../courses";
import type { CourseNameOverrides } from "../lib/coursePreferences";
import type { HelpDraft, HelpKind, SuggestionState, TodoItem } from "../types";
import { Sheet } from "./Sheet";

export function TaskModal({
  item,
  suggestion,
  helpKinds,
  onSuggest,
  onAskTeacher,
  onSetException,
  onClose,
  onToggle,
  courseNames,
}: {
  item: TodoItem;
  suggestion: SuggestionState | null;
  helpKinds: HelpKind[];
  onSuggest: (item: TodoItem) => void;
  onAskTeacher: (item: TodoItem, kind: string) => Promise<HelpDraft | null>;
  onSetException: (item: TodoItem, acceptedUntil: string | null, note?: string) => Promise<boolean>;
  onClose: () => void;
  onToggle: (item: TodoItem, done: boolean) => void;
  courseNames: CourseNameOverrides;
}) {
  // Graded work's own points_possible is the more authoritative figure
  // when both exist (Genesis's real gradebook value); the detail-page
  // figure is what's available before anything is graded at all.
  const points = item.grade?.score_possible ?? item.points_possible;

  return (
    <Sheet onClose={onClose} label={item.title}>
      <h2 className="sheet-title">{item.title}</h2>

      {item.course_name && (
        <p className="sheet-course">{displayCourseName(item.course_name, courseNames[item.course_key])}</p>
      )}

      {/* First, before teacher or due date: not knowing how to begin is
          the thing that stalls an assignment, so the way in comes before
          the admin. Shown outright when already cached; otherwise it is
          one button, because the sheet must never do a model call on its
          own just from being opened. */}
      {!item.done && <Starter item={item} state={suggestion} onSuggest={onSuggest} />}

      {/* After "how do I start" and before the admin details, because it
          answers the harder question underneath it: not knowing what the
          thing even IS. Asking the teacher is the right first move and the
          reason it doesn't happen is that writing the email is itself the
          barrier - so this writes it. */}
      {!item.done && <AskTeacher item={item} kinds={helpKinds} onAskTeacher={onAskTeacher} />}

      {item.late_credit?.is_late && <LateNote credit={item.late_credit} />}

      {/* Shown for any late item, not only closed ones: a teacher can say
          "I'll still take it" long before a cutoff, and this is where that
          gets written down. It's the one thing on this screen that can
          bring work back from behind the marking-period filter. */}
      {!item.done && (item.late_credit?.is_late || item.category === "missing") && (
        <TeacherException item={item} onSetException={onSetException} />
      )}

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
    </Sheet>
  );
}

/** "I have no idea what this is about."
 *
 * The student never has to articulate *what* they don't understand - that's
 * often the whole problem, and asking someone to diagnose their own
 * confusion stacks a second blocker on the first. They pick which KIND of
 * stuck they are from a short menu and the backend writes the email, in
 * specific words a teacher can actually answer.
 *
 * The draft opens in their own mail app via mailto: - deliberately not sent
 * for them. Pressing send stays their decision, and schoolz never sees
 * whether or what they sent; only that an ask of this kind happened. The
 * pick-a-kind step is also the guard against this becoming a reflex: ten
 * seconds of thought is what makes the email specific rather than "I don't
 * get it" fired at every assignment. */
function AskTeacher({
  item,
  kinds,
  onAskTeacher,
}: {
  item: TodoItem;
  kinds: HelpKind[];
  onAskTeacher: (item: TodoItem, kind: string) => Promise<HelpDraft | null>;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [draft, setDraft] = useState<HelpDraft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const asked = item.asked_kinds.length > 0;

  if (kinds.length === 0) return null;

  const pick = async (kind: string) => {
    setBusy(kind);
    setError(null);
    const result = await onAskTeacher(item, kind);
    setBusy(null);
    if (!result) {
      setError("Couldn't put that together just now. Try again in a moment.");
      return;
    }
    setDraft(result);
  };

  if (draft) {
    const mailto = `mailto:${draft.teacher_email ?? ""}?subject=${encodeURIComponent(
      draft.subject,
    )}&body=${encodeURIComponent(draft.body)}`;
    return (
      <section className="ask">
        <h3>Ready to send</h3>
        <p className="ask-preview">{draft.body}</p>
        {draft.teacher_email ? (
          <a className="ask-send" href={mailto}>
            Open this in email
          </a>
        ) : (
          // No resolved address is not a dead end - the words are the hard
          // part, and they can still be copied into a message by hand.
          <p className="ask-note">
            No email on file for {item.teacher_name ?? "this teacher"} — copy the text above into a message, or ask
            them in class.
          </p>
        )}
        <button type="button" className="ask-restart" onClick={() => setDraft(null)}>
          Pick something else
        </button>
      </section>
    );
  }

  if (!open) {
    return (
      <section className="ask">
        <button type="button" className="ask-open" onClick={() => setOpen(true)}>
          I don't know what this is about
        </button>
        {asked && <p className="ask-note">You asked about this one already.</p>}
      </section>
    );
  }

  return (
    <section className="ask">
      <h3>What's the trouble?</h3>
      <ul className="ask-kinds">
        {kinds.map((k) => (
          <li key={k.kind}>
            <button type="button" className="ask-kind" disabled={busy !== null} onClick={() => pick(k.kind)}>
              {busy === k.kind ? "Writing…" : k.label}
            </button>
          </li>
        ))}
      </ul>
      {error && <p className="ask-note">{error}</p>}
      <button type="button" className="ask-restart" disabled={busy !== null} onClick={() => setOpen(false)}>
        Cancel
      </button>
    </section>
  );
}

/** "A teacher said they'd still take it."
 *
 * Confirmed to happen with more than one teacher, usually as "get it to me
 * before the marking period ends". Without somewhere to record it, the app
 * keeps applying a rule the teacher has personally waived - and since
 * past-cutoff work is hidden from the dashboard, it would be hiding exactly
 * the assignment someone just got permission to finish. Recording it here
 * overrides the class policy and the marking-period filter both. */
function TeacherException({
  item,
  onSetException,
}: {
  item: TodoItem;
  onSetException: (item: TodoItem, acceptedUntil: string | null, note?: string) => Promise<boolean>;
}) {
  const [open, setOpen] = useState(false);
  const [until, setUntil] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const existing = item.late_exception;

  if (existing) {
    return (
      <section className="sheet-row">
        <h3>Teacher exception</h3>
        <p>
          {existing.accepted_until === "marking_period_end"
            ? "Accepted until the end of the marking period."
            : `Accepted until ${existing.accepted_until}.`}
          {existing.granted_note ? ` “${existing.granted_note}”` : ""}
        </p>
        <button type="button" className="ask-restart" onClick={() => void onSetException(item, null)}>
          Remove this
        </button>
      </section>
    );
  }

  if (!open) {
    return (
      <section className="sheet-row">
        <h3>Teacher exception</h3>
        <button type="button" className="ask-restart" onClick={() => setOpen(true)}>
          A teacher said they'd still take this
        </button>
      </section>
    );
  }

  const save = async (acceptedUntil: string) => {
    setBusy(true);
    const ok = await onSetException(item, acceptedUntil, note.trim() || undefined);
    setBusy(false);
    if (ok) setOpen(false);
  };

  return (
    <section className="sheet-row">
      <h3>Teacher exception</h3>
      <p className="policy-hint">When did they say they'd take it by?</p>
      <div className="exception-actions">
        <button
          type="button"
          className="policy-save"
          disabled={busy}
          onClick={() => void save("marking_period_end")}
        >
          End of marking period
        </button>
        <input
          type="date"
          className="exception-date"
          value={until}
          onChange={(e) => setUntil(e.target.value)}
          aria-label="Accepted until"
        />
        {until && (
          <button type="button" className="policy-save" disabled={busy} onClick={() => void save(until)}>
            Save
          </button>
        )}
      </div>
      <input
        className="exception-note"
        placeholder="What they said (optional)"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <button type="button" className="ask-restart" onClick={() => setOpen(false)}>
        Cancel
      </button>
    </section>
  );
}

/** What's still earnable, stated plainly and only in the sheet - never on
 * the card. A number like "worth 65%" is forward-looking and useful once
 * you've chosen to look at an item; on the dashboard it would just be a
 * running score of how far behind you are. */
function LateNote({ credit }: { credit: NonNullable<TodoItem["late_credit"]> }) {
  if (!credit.accepted) {
    return (
      <section className="sheet-row">
        <h3>Late work</h3>
        <p>
          Past the cutoff for this class{credit.closes_on ? ` (${credit.closes_on})` : ""}.
          {credit.extension_by_request ? " This teacher will consider an extension if you ask." : ""}
        </p>
      </section>
    );
  }
  const closing =
    credit.days_left === null
      ? null
      : credit.days_left === 0
        ? "Today is the last day it's accepted."
        : `Accepted for ${credit.days_left} more day${credit.days_left === 1 ? "" : "s"}.`;
  return (
    <section className="sheet-row">
      <h3>Late work</h3>
      <p>
        {credit.by_exception
          ? credit.credit_pct === 100
            ? "Your teacher said they'd still take this, for full credit."
            : `Your teacher said they'd still take this, worth up to ${credit.credit_pct}%.`
          : credit.credit_pct === 100
            ? "Still worth full credit in this class."
            : `Still worth up to ${credit.credit_pct}% in this class.`}
        {closing ? ` ${closing}` : ""}
      </p>
    </section>
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
  // Collapsing is purely a local display toggle - the suggestion itself is
  // already cached (server-side, shared by the whole class section, plus
  // this component's own `state` prop) so hiding it never re-triggers a
  // model call, and reopening is instant.
  const [collapsed, setCollapsed] = useState(false);

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

  if (collapsed) {
    return (
      <section className="starter starter-collapsed">
        <button type="button" className="starter-toggle" onClick={() => setCollapsed(false)}>
          How to start <span aria-hidden="true">▾</span>
        </button>
      </section>
    );
  }

  const collapseButton = (
    <button type="button" className="starter-toggle" onClick={() => setCollapsed(true)} aria-label="Collapse">
      <span aria-hidden="true">▴</span>
    </button>
  );

  if (state.error) {
    return (
      <section className="starter">
        <div className="starter-head">
          <h3>How to start</h3>
          {collapseButton}
        </div>
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
        <div className="starter-head">
          <h3>How to start</h3>
          {collapseButton}
        </div>
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
      <div className="starter-head">
        <h3>How to start</h3>
        {collapseButton}
      </div>
      <ol className="starter-steps">
        {steps.map((step, i) => (
          <li key={i}>{step}</li>
        ))}
      </ol>
    </section>
  );
}
