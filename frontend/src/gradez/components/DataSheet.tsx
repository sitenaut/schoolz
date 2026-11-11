import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import type { LastUpdate } from "../../lib/family";
import { apiFetch, apiGet } from "../api";
import { agoWords, genesisKey, plural, scoreText, whenLabel } from "../format";
import { freshness } from "../lib/freshness";
import type { Audit, ImportResult, SyncStatus } from "../types";
import { IconChevronRight, IconCircleCheck, IconClose, IconFlag, IconImport, IconReread } from "./icons";
import { Sheet } from "./Sheet";

type Outcome = { ok: boolean; lines: string[] };

function resultLines(r: ImportResult): string[] {
  const read = `Read ${plural(r.captures_processed, "page")}: ${plural(r.work_items_upserted, "assignment update")}, ${plural(r.grade_entries_upserted, "grade update")}, ${plural(r.schedule_blocks_upserted, "schedule block")}.`;
  return [read, ...r.identity_mismatches];
}

/** Is this complete and current? The one place that answers it: when each
 * system last arrived, whether Classroom and Genesis agree, and the three
 * things to try when something looks wrong.
 *
 * Nothing here loads until the sheet is opened: the comparison reads every
 * assignment and grade the child has, and most visits never ask for it. */
export function DataSheet({
  studentId,
  firstName,
  isStudent,
  sync,
  now,
  onClose,
  onChanged,
}: {
  studentId: string;
  firstName: string;
  /** A child's own login can re-read, but not import a file or write to schoolz. */
  isStudent: boolean;
  sync: SyncStatus | null;
  now: number;
  onClose: () => void;
  /** After an import or a re-read, every tab's data is out of date. */
  onChanged: () => void;
}) {
  // undefined while loading, null when it couldn't be loaded.
  const [audit, setAudit] = useState<Audit | null | undefined>(undefined);
  const [auditVersion, setAuditVersion] = useState(0);
  const [update, setUpdate] = useState<LastUpdate | null>(null);
  const [showDiffer, setShowDiffer] = useState(false);
  const [busy, setBusy] = useState<"reread" | "import" | null>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [reporting, setReporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    void apiGet<Audit>(`/students/${studentId}/bucket3/audit`).then((a) => {
      if (!cancelled) setAudit(a);
    });
    return () => {
      cancelled = true;
    };
  }, [studentId, auditVersion]);

  // The last update's log belongs to the parent whose computer sent it.
  useEffect(() => {
    if (isStudent) return;
    let cancelled = false;
    void apiGet<LastUpdate>("/capture-devices/last-update").then((u) => {
      if (!cancelled) setUpdate(u);
    });
    return () => {
      cancelled = true;
    };
  }, [isStudent]);

  const finish = async (res: Response | null, failed: string) => {
    const body = res ? await res.json().catch(() => null) : null;
    if (!res?.ok || !body) {
      setOutcome({ ok: false, lines: [typeof body?.detail === "string" ? body.detail : failed] });
      return;
    }
    setOutcome({ ok: true, lines: resultLines(body as ImportResult) });
    setAuditVersion((v) => v + 1);
    onChanged();
  };

  const reread = async () => {
    setOutcome(null);
    setBusy("reread");
    const res = await apiFetch(`/students/${studentId}/bucket3/reprocess`, { method: "POST" }).catch(() => null);
    await finish(res, "Couldn't re-read the imported pages. Try again in a minute.");
    setBusy(null);
  };

  const importFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setOutcome(null);
    setBusy("import");
    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      setOutcome({ ok: false, lines: ["That doesn't look like a file saved by Backpack Capture. Use Export capture in the extension, then pick that file."] });
      setBusy(null);
      return;
    }
    const res = await apiFetch(`/students/${studentId}/bucket3/import`, { method: "POST", body: JSON.stringify(parsed) }).catch(() => null);
    await finish(res, "Couldn't import that file. Try again in a minute.");
    setBusy(null);
  };

  const fresh = freshness(sync, now);
  const sentOnce = fresh !== null && fresh.kind !== "never";
  const trouble = sentOnce && (fresh.kind === "stale" || fresh.needsLogin);
  const headline = !fresh
    ? "Couldn't check how current this is"
    : fresh.kind === "never"
      ? "Backpack Capture hasn't sent any schoolwork yet"
      : `Backpack Capture last sent schoolwork ${agoWords(fresh.ago)}`;
  const problems = update?.summary?.outcome === "trouble" ? update.summary.problems.filter((p) => !p.student_id || p.student_id === studentId) : [];

  const oneSystem = sync !== null && (!sync.classroom_seen_at || !sync.genesis_seen_at);
  const differ = audit ? audit.counts.classroom_only + audit.counts.genesis_only : 0;
  const clock = new Date(now);

  return (
    <Sheet onClose={onClose} label="About this data">
      <div className="gz-sheet-title-row">
        <h2 className="gz-sheet-heading">About this data</h2>
        <button type="button" className="gz-icon-btn" aria-label="Close" onClick={onClose}>
          <IconClose />
        </button>
      </div>
      <p className="gz-sheet-intro">Is this complete and current? Check here before acting on a missing assignment or a grade.</p>

      <section className={`gz-card gz-data-status${trouble ? " gz-is-warn" : ""}`}>
        <div className="gz-data-headline">
          {sentOnce && !trouble && <IconCircleCheck size={22} />}
          <h3>{headline}</h3>
        </div>
        {sentOnce && fresh.needsLogin && (
          <p className="gz-note">
            Google asked to sign in again, so Classroom can't be read. Sign in to Classroom in Chrome on the computer Backpack Capture runs on.
          </p>
        )}
        {sentOnce && fresh.kind === "stale" && !fresh.needsLogin && (
          <p className="gz-note">That is more than a day ago, so newer assignments and grades may be missing.</p>
        )}
        {fresh?.kind === "never" && <p className="gz-note">Nothing shows here until a parent's computer sends {firstName}'s pages.</p>}
        {sync && (
          <dl className="gz-data-rows">
            <div>
              <dt>Google Classroom</dt>
              <dd>{whenLabel(sync.classroom_seen_at, clock)}</dd>
            </div>
            <div>
              <dt>Genesis gradebook</dt>
              <dd>{whenLabel(sync.genesis_seen_at, clock)}</dd>
            </div>
          </dl>
        )}
        {problems.length > 0 && (
          <>
            <p className="gz-note">The last update ran into trouble:</p>
            <ul className="gz-data-problems">
              {problems.map((p) => (
                <li key={p.text}>{p.text}</li>
              ))}
            </ul>
          </>
        )}
      </section>

      <section className="gz-card gz-list gz-agree">
        <h3>Do Classroom and Genesis agree?</h3>
        {audit === undefined && <p className="gz-note">Checking…</p>}
        {audit === null && <p className="gz-note">Couldn't compare them just now.</p>}
        {audit && oneSystem && <p className="gz-note">Only one of the two has arrived so far, so there is nothing to compare yet.</p>}
        {audit && !oneSystem && (
          <>
            <AgreeRow count={audit.counts.matched} tone="ok" title="In both" note="Nothing to do." />
            <AgreeRow
              count={audit.counts.classroom_only}
              tone={audit.counts.classroom_only ? "warn" : "ok"}
              title="Only in Classroom"
              note="Posted, but not in the gradebook yet. Usually not graded yet."
            />
            <AgreeRow
              count={audit.counts.genesis_only}
              tone={audit.counts.genesis_only ? "warn" : "ok"}
              title="Only in Genesis"
              note="In the gradebook with no Classroom post. Usually paper work or a test."
            />
            {differ > 0 && (
              <button type="button" className="gz-link-btn gz-agree-more" aria-expanded={showDiffer} onClick={() => setShowDiffer((s) => !s)}>
                {showDiffer ? "Hide them" : `See the ${differ} that differ`}
                {!showDiffer && <IconChevronRight />}
              </button>
            )}
            {showDiffer && <Differences audit={audit} />}
          </>
        )}
      </section>

      <h3 className="gz-sheet-section">Something look wrong?</h3>
      <div className="gz-card gz-list">
        <ActionRow
          icon={<IconReread />}
          title={busy === "reread" ? "Re-reading…" : "Re-read imported pages"}
          note="Rebuilds every list from the pages already sent. Use it when something looks out of date."
          disabled={busy !== null}
          onClick={() => void reread()}
        />
        {!isStudent && (
          <ActionRow
            icon={<IconImport />}
            title={busy === "import" ? "Importing…" : "Import a capture file"}
            note="Parents only. Adds a file saved by Backpack Capture."
            disabled={busy !== null}
            onClick={() => fileRef.current?.click()}
          />
        )}
        {!isStudent && (
          <ActionRow
            icon={<IconFlag />}
            title="Report a problem"
            note="Sends schoolz a message with the last update's log. It names no child."
            expanded={reporting}
            onClick={() => setReporting((r) => !r)}
          />
        )}
      </div>
      {/* style, not the hidden attribute: the main app's `input { display: block }` beats [hidden]. */}
      <input ref={fileRef} type="file" accept="application/json" onChange={(e) => void importFile(e)} style={{ display: "none" }} />
      {outcome && (
        <div className={outcome.ok ? "gz-data-result" : "gz-banner-error"} role="status">
          {outcome.lines.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      )}
      {reporting && !isStudent && <ReportProblem update={update} onDone={() => setReporting(false)} />}
    </Sheet>
  );
}

function AgreeRow({ count, tone, title, note }: { count: number; tone: "ok" | "warn"; title: string; note: string }) {
  return (
    <div className="gz-agree-row">
      <span className={`gz-agree-count gz-is-${tone}`}>{count}</span>
      <span className="gz-row-main">
        <span className="gz-row-title">{title}</span>
        <span className="gz-row-sub">{note}</span>
      </span>
    </div>
  );
}

/** The assignments only one system lists, by name. Matched on the title
 * alone, which is why a difference is a question for the teacher and not
 * proof that work is missing. */
function Differences({ audit }: { audit: Audit }) {
  return (
    <div className="gz-differ">
      <p className="gz-note">
        Matched by assignment title. Teachers don't always keep both up to date, so a difference doesn't have to mean work is missing.
        {audit.current_marking_period && " Only in Classroom counts this marking period."}
      </p>
      {audit.classroom_only.length > 0 && (
        <>
          <h4>Only in Classroom</h4>
          <ul>
            {audit.classroom_only.map((it) => (
              <li key={it.external_uid}>
                <span className="gz-row-title gz-is-light">{it.title}</span>
                <span className="gz-row-sub">{[it.course_name, it.due_raw && `due ${it.due_raw}`].filter(Boolean).join(" · ")}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {audit.genesis_only.length > 0 && (
        <>
          <h4>Only in Genesis</h4>
          <ul>
            {audit.genesis_only.map((e) => (
              <li key={e.external_uid}>
                <span className="gz-row-title gz-is-light">{e.title}</span>
                <span className="gz-row-sub">{[e.course_name ?? genesisKey(e), scoreText(e)].filter(Boolean).join(" · ")}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function ActionRow({
  icon,
  title,
  note,
  disabled,
  expanded,
  onClick,
}: {
  icon: ReactNode;
  title: string;
  note: string;
  disabled?: boolean;
  expanded?: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className="gz-action-row" disabled={disabled} aria-expanded={expanded} onClick={onClick}>
      <span className="gz-action-icon">{icon}</span>
      <span className="gz-row-main">
        <span className="gz-row-title">{title}</span>
        <span className="gz-row-sub">{note}</span>
      </span>
    </button>
  );
}

/** A message to the schoolz team, tied to the last update's log when there
 * is one. The log lists which pages were opened and where it stopped, never
 * what was on them. */
function ReportProblem({ update, onDone }: { update: LastUpdate | null; onDone: () => void }) {
  const [note, setNote] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState<{ reference: string | null } | null>(update?.reported_at ? { reference: update.reference } : null);

  const send = async () => {
    setSending(true);
    setError(null);
    const res = await apiFetch("/capture-devices/report", {
      method: "POST",
      body: JSON.stringify({ note: note.trim() || null, diagnostic_id: update?.id ?? null }),
    }).catch(() => null);
    setSending(false);
    if (!res?.ok) {
      setError(res?.status === 429 ? "That's several reports in the last hour. Try again later." : "Couldn't send that. Try again in a minute.");
      return;
    }
    const body = (await res.json().catch(() => ({}))) as { reference?: string | null };
    setSent({ reference: body.reference ?? null });
  };

  if (sent) {
    return (
      <div className="gz-data-result" role="status">
        <p>
          Reported to the schoolz team{sent.reference ? `, reference ${sent.reference}` : ""}. They'll reply by email.
        </p>
      </div>
    );
  }

  return (
    <div className="gz-card gz-report">
      <label htmlFor="gz-report-note">What went wrong? (optional)</label>
      <textarea
        id="gz-report-note"
        className="gz-textarea"
        rows={3}
        maxLength={2000}
        placeholder="For example: it kept asking me to sign in"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <p className="gz-note">
        {update
          ? "The schoolz team also gets the last update's log: which pages it opened and where it stopped, never what was on them."
          : "The schoolz team gets your message and your account's email address."}
      </p>
      {error && <p className="gz-banner-error">{error}</p>}
      <div className="gz-report-actions">
        <button type="button" className="gz-btn gz-btn-primary" disabled={sending} onClick={() => void send()}>
          {sending ? "Sending…" : "Send to schoolz"}
        </button>
        <button type="button" className="gz-text-btn" onClick={onDone}>
          Cancel
        </button>
      </div>
    </div>
  );
}
