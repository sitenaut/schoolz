import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { Field } from "../components/ui/Field";
import { Modal } from "../components/ui/Modal";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { Switch } from "../components/ui/Switch";
import { useToast } from "../components/ui/Toast";
import { IconAlert, IconCheck, IconEdit, IconPlus, IconRefresh, IconTrash, IconX } from "../components/icons";
import { apiFetch } from "../api";
import { useAuth } from "../context/AuthContext";
import { fmtDateTime } from "../lib/format";
import { can } from "../lib/permissions";
import { formatWhen, joinLocal, splitLocal, type DateParts } from "./submissions/localDates";
import {
  addItem,
  deleteItem,
  deleteSubmission,
  downloadSubmissionFile,
  getReview,
  loadTargets,
  publishItems,
  readUpload,
  unpublishItem,
  updateItem,
  updateSubmission,
  type SubmissionAttempt,
  type SubmissionItem,
  type SubmissionReview,
  type TargetOption,
} from "./submissions/submissionsApi";

type Draft = {
  id: string | null;
  title: string;
  description: string;
  category: string;
  scope: "school" | "district" | "local";
  venueName: string;
  venueAddress: string;
  localCategories: string[];
  tentative: boolean;
  published: boolean;
} & DateParts;

const BLANK: Draft = {
  id: null, title: "", description: "", category: "event", scope: "school", venueName: "", venueAddress: "", localCategories: [], tentative: false, published: false,
  date: "", time: "", endDate: "", endTime: "",
};

function statusTone(status: string): "warn" | "ok" | "bad" | "muted" {
  if (status === "pending") return "warn";
  if (status === "approved") return "ok";
  if (status === "rejected") return "bad";
  return "muted";
}

const CATEGORY_LABELS: Record<string, string> = { pta: "PTA", org_club: "Club", merch_ad: "Merchandise" };
const isLive = (i: SubmissionItem) => Boolean(i.content_item_id || i.local_event_id);
const labelize = (key: string) => CATEGORY_LABELS[key] ?? key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

/** One page for the whole job: see the upload, have it read, correct what
 * was read, and choose what goes on the calendar. Nothing is public until
 * Publish, and only the ticked items. */
export function SubmissionReviewPage() {
  const { submissionId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { user } = useAuth();
  const canEdit = can(user, "submissions.manage");

  const [review, setReview] = useState<SubmissionReview | null>(null);
  const [missing, setMissing] = useState(false);
  const [schools, setSchools] = useState<TargetOption[]>([]);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [zoomed, setZoomed] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<Draft | null>(null);
  const [notes, setNotes] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  // Items whose tick has already been defaulted, so re-loading the review
  // after an edit never overrides a choice the reviewer made.
  const defaulted = useRef<Set<string>>(new Set());

  const fail = useCallback(
    (title: string, e: unknown) => toast({ title, description: e instanceof Error ? e.message : undefined, tone: "bad" }),
    [toast]
  );

  const accept = useCallback((next: SubmissionReview) => {
    setReview(next);
    setSelected((cur) => {
      const out = new Set<string>();
      for (const item of next.items) {
        if (isLive(item)) continue;
        if (defaulted.current.has(item.id)) {
          if (cur.has(item.id) && item.start_local) out.add(item.id);
        } else {
          defaulted.current.add(item.id);
          if (!item.flags.some((f) => f.hold)) out.add(item.id);
        }
      }
      return out;
    });
  }, []);

  useEffect(() => {
    getReview(submissionId)
      .then((r) => {
        accept(r);
        setNotes(r.submission.admin_notes ?? "");
      })
      .catch(() => setMissing(true));
    loadTargets()
      .then((t) => setSchools(t.schools))
      .catch(() => undefined);
  }, [submissionId, accept]);

  const submission = review?.submission;
  const isImage = submission?.kind === "file" && Boolean(submission.file_content_type?.startsWith("image/"));

  useEffect(() => {
    if (!isImage) return;
    let url = "";
    apiFetch(`/submissions/${submissionId}/file`)
      .then((r) => (r.ok ? r.blob() : null))
      .then((blob) => {
        if (blob) {
          url = URL.createObjectURL(blob);
          setImageUrl(url);
        }
      })
      .catch(() => undefined);
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [submissionId, isImage]);

  const groups = useMemo(() => {
    const items = review?.items ?? [];
    return {
      live: items.filter(isLive),
      dated: items.filter((i) => !isLive(i) && i.start_local),
      undated: items.filter((i) => !isLive(i) && !i.start_local),
    };
  }, [review]);

  const run = async (key: string, title: string, action: () => Promise<SubmissionReview>, done?: string) => {
    setBusy(key);
    try {
      const next = await action();
      accept(next);
      if (done) toast({ title: done, tone: "ok" });
      return next;
    } catch (e) {
      fail(title, e);
      return null;
    } finally {
      setBusy(null);
    }
  };

  const patchSubmission = async (patch: Parameters<typeof updateSubmission>[1], done?: string) => {
    setBusy("submission");
    try {
      await updateSubmission(submissionId, patch);
      accept(await getReview(submissionId));
      if (done) toast({ title: done, tone: "ok" });
    } catch (e) {
      fail("Could not update", e);
    } finally {
      setBusy(null);
    }
  };

  const openEdit = (item: SubmissionItem) =>
    setEditing({
      id: item.id,
      title: item.title,
      description: item.description ?? "",
      category: item.category,
      scope: item.scope,
      venueName: item.venue_name ?? "",
      venueAddress: item.venue_address ?? "",
      localCategories: item.local_categories,
      tentative: item.tentative,
      published: isLive(item),
      ...splitLocal(item.start_local, item.end_local),
    });

  const saveEdit = async () => {
    if (!editing) return;
    const input = {
      title: editing.title.trim(),
      description: editing.description,
      category: editing.category,
      scope: editing.scope,
      venue_name: editing.venueName,
      venue_address: editing.venueAddress,
      local_categories: editing.localCategories,
      tentative: editing.tentative,
      ...joinLocal(editing),
    };
    const known = new Set(review?.items.map((i) => i.id));
    const next = editing.id
      ? await run("edit", "Could not save this item", () => updateItem(submissionId, editing.id!, input))
      : await run("edit", "Could not add this item", () => addItem(submissionId, input));
    if (!next) return;
    // Correcting an item is a decision to use it: once nothing holds it
    // back, tick it rather than making the reviewer find it again.
    const saved = next.items.find((i) => (editing.id ? i.id === editing.id : !known.has(i.id)));
    if (saved && !isLive(saved) && saved.start_local && !saved.flags.some((f) => f.hold)) {
      setSelected((cur) => new Set(cur).add(saved.id));
    }
    setEditing(null);
  };

  const toggle = (id: string) =>
    setSelected((cur) => {
      const out = new Set(cur);
      if (out.has(id)) out.delete(id);
      else out.add(id);
      return out;
    });

  const publish = async () => {
    const ids = groups.dated.filter((i) => selected.has(i.id)).map((i) => i.id);
    await run("publish", "Could not publish", () => publishItems(submissionId, ids), `Published ${ids.length} to the calendar`);
  };

  const remove = async () => {
    setBusy("delete");
    try {
      await deleteSubmission(submissionId);
      navigate("/admin/submissions");
    } catch (e) {
      fail("Could not delete", e);
      setBusy(null);
    }
  };

  if (missing) {
    return (
      <div className="page">
        <PageHeader upperTitle="Admin" title="Submission not found" back={{ to: "/admin/submissions", label: "Submissions" }} />
      </div>
    );
  }
  if (!review || !submission) return <div className="page" aria-busy="true" />;

  const hasFile = submission.kind === "file";
  const chosen = groups.dated.filter((i) => selected.has(i.id));
  const publishCount = chosen.length;
  // Only items for a school or district calendar need a school; local events stand alone.
  const needsSchool = !submission.school_id && chosen.some((i) => i.scope !== "local");

  const itemRow = (item: SubmissionItem) => {
    const live = isLive(item);
    const local = item.scope === "local";
    // Replacing retires a school calendar item; a local event can only be skipped.
    const listed = local ? undefined : item.flags.find((f) => f.code === "already_listed");
    return (
      <li key={item.id} className={`sr-item ${live ? "live" : ""}`}>
        {!live && item.start_local && canEdit && (
          <input
            type="checkbox"
            className="sr-tick"
            checked={selected.has(item.id)}
            onChange={() => toggle(item.id)}
            aria-label={`Publish ${item.title}`}
          />
        )}
        <div className="sr-item-main">
          <div className="sr-item-title">
            {item.title}
            {live && <Badge tone="ok">Live</Badge>}
            {item.scope === "district" && <Badge tone="info" dot={false}>District</Badge>}
            {local && <Badge tone="info" dot={false}>Local</Badge>}
          </div>
          <div className="sr-item-when">
            {formatWhen(item.start_local, item.end_local)} · {local ? [item.venue_name || "No venue", ...item.local_categories.map(labelize)].join(" · ") : labelize(item.category)}
          </div>
          {!live && canEdit && (
            <select
              className="sr-dest"
              value={item.scope}
              disabled={busy !== null}
              aria-label={`Where ${item.title} goes`}
              onChange={(e) =>
                run("scope", "Could not move this item", () => updateItem(submissionId, item.id, { scope: e.target.value as SubmissionItem["scope"] }))
              }
            >
              <option value="school">This school's calendar</option>
              <option value="district">The whole district's calendar</option>
              <option value="local">Local events</option>
            </select>
          )}
          {item.description && <div className="note">{item.description}</div>}
          {item.flags
            .filter((f) => f.code !== "no_date")
            .map((f) => (
              <div key={f.code} className={`sr-flag ${f.hold ? "hold" : ""}`}>
                <IconAlert /> <span>{f.text}</span>
              </div>
            ))}
          {listed && canEdit && (
            <button
              type="button"
              className="btn sm"
              disabled={busy !== null}
              onClick={() =>
                run("replace", "Could not update this item", () =>
                  updateItem(submissionId, item.id, {
                    replaces_item_id: item.replaces_item_id === listed.item_id ? "" : listed.item_id ?? "",
                  })
                )
              }
            >
              {item.replaces_item_id === listed.item_id ? "Keep both instead" : "Replace that one with this"}
            </button>
          )}
          {item.source_excerpt && <div className="sr-excerpt">“{item.source_excerpt}”</div>}
        </div>
        {canEdit && (
          <div className="sr-item-actions">
            <button className="btn icon" title="Edit" onClick={() => openEdit(item)}>
              <IconEdit />
            </button>
            {live ? (
              <button
                className="btn sm"
                disabled={busy !== null}
                onClick={() =>
                  run("unpublish", "Could not unpublish", () => unpublishItem(submissionId, item.id), local ? "Taken off Local" : "Taken off the calendar")
                }
              >
                Unpublish
              </button>
            ) : (
              <button
                className="btn icon danger"
                title="Remove"
                disabled={busy !== null}
                onClick={() => run("remove", "Could not remove this item", () => deleteItem(submissionId, item.id))}
              >
                <IconTrash />
              </button>
            )}
          </div>
        )}
      </li>
    );
  };

  return (
    <div className="page sr-page">
      <PageHeader
        upperTitle="Admin"
        back={{ to: "/admin/submissions", label: "Submissions" }}
        title={hasFile ? submission.file_name : "Link submission"}
        subtitle={
          <>
            <Badge tone={statusTone(submission.status)}>{submission.status}</Badge>{" "}
            {submission.submitter_name || submission.submitter_email || submission.source?.user_email || "Anonymous"} · {fmtDateTime(submission.created_at)}
          </>
        }
        actions={
          canEdit && (
            <button className="btn icon danger" title="Delete submission" onClick={() => setConfirmDelete(true)}>
              <IconTrash />
            </button>
          )
        }
      />

      <div className="sr-cols">
        <div className="sr-source">
          <SectionCard title="What was sent">
            {hasFile ? (
              imageUrl ? (
                <button type="button" className="sr-image" onClick={() => setZoomed(true)} title="Tap to zoom">
                  <img src={imageUrl} alt="The uploaded page" />
                </button>
              ) : (
                <button
                  type="button"
                  className="linklike"
                  onClick={() => downloadSubmissionFile(submission.id, submission.file_name).catch((e) => fail("Could not open this file", e))}
                >
                  Open {submission.file_name} ({Math.round((submission.file_size ?? 0) / 1024)} KB)
                </button>
              )
            ) : (
              <a href={submission.url ?? undefined} target="_blank" rel="noreferrer">
                {submission.url}
              </a>
            )}
            {submission.description && (
              <div className="sr-sender-note">
                <span className="lbl">Sender's note</span>
                {submission.description}
              </div>
            )}
          </SectionCard>

          <SubmissionOrigin source={submission.source ?? null} />

          <SectionCard title="Filing">
            <Field label="School" hint="School and district items land on this school's page and calendar. Local events don't need one.">
              <select
                value={submission.school_id ?? ""}
                disabled={!canEdit || busy !== null}
                onChange={(e) => e.target.value && patchSubmission({ school_id: e.target.value })}
              >
                <option value="">Pick a school…</option>
                {schools.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Admin notes">
              <textarea
                value={notes}
                readOnly={!canEdit}
                onChange={(e) => setNotes(e.target.value)}
                onBlur={() => notes !== (submission.admin_notes ?? "") && patchSubmission({ admin_notes: notes }, "Notes saved")}
                rows={2}
              />
            </Field>
          </SectionCard>
        </div>

        <div className="sr-items">
          <SectionCard
            title="Calendar items"
            description={
              submission.extracted_at
                ? `Read ${fmtDateTime(submission.extracted_at)}. Check each one against the page.`
                : "Nothing is public until you publish."
            }
            actions={
              canEdit && (
                <>
                  {hasFile && (
                    <button
                      className={`btn ${submission.extracted_at ? "" : "btn-primary"} ${busy === "read" ? "spin" : ""}`}
                      disabled={busy !== null}
                      onClick={() => run("read", "Could not read this upload", () => readUpload(submissionId))}
                    >
                      <IconRefresh /> {busy === "read" ? "Reading…" : submission.extracted_at ? "Read again" : "Read this upload"}
                    </button>
                  )}
                  <button className="btn" disabled={busy !== null} onClick={() => setEditing({ ...BLANK })}>
                    <IconPlus /> Add
                  </button>
                </>
              )
            }
          >
            {review.note_flags.map((text) => (
              <div key={text} className="sr-flag hold">
                <IconAlert /> <span>{text}</span>
              </div>
            ))}
            {review.items.length === 0 && (
              <div className="empty">
                {hasFile ? "Read the upload to get a first pass, or add items by hand." : "Add the items this link is about by hand."}
              </div>
            )}
            {groups.live.length > 0 && (
              <>
                <div className="sr-group">On the calendar</div>
                <ul className="sr-list">{groups.live.map(itemRow)}</ul>
              </>
            )}
            {groups.dated.length > 0 && (
              <>
                <div className="sr-group">Ready to publish</div>
                <ul className="sr-list">{groups.dated.map(itemRow)}</ul>
              </>
            )}
            {groups.undated.length > 0 && (
              <details className="sr-undated">
                <summary>Mentioned with no date ({groups.undated.length})</summary>
                <ul className="sr-list">{groups.undated.map(itemRow)}</ul>
              </details>
            )}
          </SectionCard>
        </div>
      </div>

      {canEdit && (
        <div className="sr-bar">
          <button
            className="btn solid-danger"
            disabled={busy !== null || submission.status === "rejected"}
            onClick={() => patchSubmission({ status: "rejected" }, "Marked rejected")}
          >
            <IconX /> Reject
          </button>
          <button className="btn btn-primary" disabled={busy !== null || publishCount === 0 || needsSchool} onClick={publish}>
            <IconCheck /> {needsSchool ? "Pick a school to publish" : `Publish ${publishCount} item${publishCount === 1 ? "" : "s"}`}
          </button>
        </div>
      )}

      {zoomed && imageUrl && (
        <div className="sr-zoom" role="dialog" aria-label="Uploaded page" onClick={() => setZoomed(false)}>
          <img src={imageUrl} alt="The uploaded page, full size" />
          <button className="btn sr-zoom-close" onClick={() => setZoomed(false)}>
            <IconX /> Close
          </button>
        </div>
      )}

      <Modal
        open={Boolean(editing)}
        onClose={() => setEditing(null)}
        title={editing?.id ? "Edit item" : "Add item"}
        subtitle={editing?.published ? "This item is live - saving changes what the public sees." : undefined}
        footer={
          <>
            <button className="btn" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={busy !== null || !editing?.title.trim()} onClick={saveEdit}>
              Save
            </button>
          </>
        }
      >
        {editing && (
          <>
            <Field label="Title">
              <input value={editing.title} onChange={(e) => setEditing({ ...editing, title: e.target.value })} />
            </Field>
            <div className="sr-form-row">
              <Field label="Date">
                <input type="date" value={editing.date} onChange={(e) => setEditing({ ...editing, date: e.target.value })} />
              </Field>
              <Field label="Starts">
                <input type="time" value={editing.time} onChange={(e) => setEditing({ ...editing, time: e.target.value })} />
              </Field>
              <Field label="Ends">
                <input type="time" value={editing.endTime} onChange={(e) => setEditing({ ...editing, endTime: e.target.value })} />
              </Field>
            </div>
            <Field label="Last day" hint="Only for something that runs more than one day.">
              <input type="date" value={editing.endDate} onChange={(e) => setEditing({ ...editing, endDate: e.target.value })} />
            </Field>
            <div className="sr-form-row">
              {editing.scope !== "local" && (
                <Field label="Kind">
                  <select value={editing.category} onChange={(e) => setEditing({ ...editing, category: e.target.value })}>
                    {review.categories.map((c) => (
                      <option key={c} value={c}>
                        {labelize(c)}
                      </option>
                    ))}
                  </select>
                </Field>
              )}
              <Field
                label="Goes on"
                hint={editing.published ? "Unpublish it to move it somewhere else." : undefined}
              >
                <select
                  value={editing.scope}
                  disabled={editing.published}
                  onChange={(e) => setEditing({ ...editing, scope: e.target.value as Draft["scope"] })}
                >
                  <option value="school">This school's calendar</option>
                  <option value="district">The whole district's calendar</option>
                  <option value="local">Local events (not a school)</option>
                </select>
              </Field>
            </div>
            {editing.scope === "local" && (
              <Field label="Tags" hint="Added to whatever is picked up from the title and details.">
                <div className="sr-tags">
                  {review.local_categories.map((c) => {
                    const on = editing.localCategories.includes(c);
                    return (
                      <button
                        key={c}
                        type="button"
                        className={`btn sm ${on ? "btn-primary" : ""}`}
                        aria-pressed={on}
                        onClick={() =>
                          setEditing({
                            ...editing,
                            localCategories: on ? editing.localCategories.filter((x) => x !== c) : [...editing.localCategories, c],
                          })
                        }
                      >
                        {labelize(c)}
                      </button>
                    );
                  })}
                </div>
              </Field>
            )}
            {editing.scope === "local" && (
              <div className="sr-form-row">
                <Field label="Venue">
                  <input value={editing.venueName} onChange={(e) => setEditing({ ...editing, venueName: e.target.value })} />
                </Field>
                <Field label="Address">
                  <input value={editing.venueAddress} onChange={(e) => setEditing({ ...editing, venueAddress: e.target.value })} />
                </Field>
              </div>
            )}
            <Field label="Details">
              <textarea
                value={editing.description}
                onChange={(e) => setEditing({ ...editing, description: e.target.value })}
                rows={3}
                placeholder="Where, and what a parent needs to know"
              />
            </Field>
            <div className="sr-switch">
              <Switch
                checked={editing.tentative}
                onChange={(next) => setEditing({ ...editing, tentative: next })}
                label="Tentative"
              />
              <span>Tentative - shown as “(tentative)” on the calendar</span>
            </div>
          </>
        )}
      </Modal>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this submission?"
        description="This removes it and its file permanently. Items already published from it stay on the calendar."
        danger
        busy={busy === "delete"}
        onConfirm={remove}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

/** Where a submission came from, as recorded when it arrived. The same
 * record stays in the upload log after the submission is deleted. */
function SubmissionOrigin({ source }: { source: SubmissionAttempt | null }) {
  if (!source) {
    return (
      <SectionCard title="Sent from">
        <p className="note">Nothing was recorded - this arrived before uploads were tracked.</p>
      </SectionCard>
    );
  }
  const check = source.bot_check;
  const botCheck = !check ? "Not required (link)" : check.skipped === "staff" ? "Not needed (added by a signed-in admin)" : check.skipped ? "Skipped (no key configured)" : check.success ? "Passed" : "Failed";
  const rows: [string, ReactNode][] = [
    ["IP address", source.ip ? <code>{source.ip}</code> : "unknown"],
    ["Forwarded for", source.forwarded_for && source.forwarded_for !== source.ip ? <code>{source.forwarded_for}</code> : null],
    ["Signed in as", source.user_email],
    ["Browser", source.user_agent],
    ["Language", source.accept_language],
    ["Sent from page", source.referer || source.origin],
    ["Edge region", source.edge_region],
    ["Bot check", botCheck],
    ["File type", source.file_detected_type && `${source.file_detected_type}${source.file_declared_type && source.file_declared_type !== source.file_detected_type ? ` (sent as ${source.file_declared_type})` : ""}`],
    ["SHA-256", source.file_sha256 ? <code>{source.file_sha256}</code> : null],
    ["Received", fmtDateTime(source.created_at)],
  ];
  return (
    <SectionCard title="Sent from" description="Recorded when it arrived. Kept in the upload log even if this submission is deleted.">
      <dl className="sr-origin">
        {rows
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <div key={label} style={{ display: "contents" }}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
      </dl>
    </SectionCard>
  );
}
