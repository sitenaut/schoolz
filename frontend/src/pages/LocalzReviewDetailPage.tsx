import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { Field } from "../components/ui/Field";
import { Modal } from "../components/ui/Modal";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { can } from "../lib/permissions";
import {
  CHECKLIST,
  type LogEntry,
  type Member,
  REJECT_REASONS,
  type Review,
  addMember,
  approveRequest,
  editRequest,
  fetchMembers,
  fetchReview,
  fetchServiceLog,
  mergeRequest,
  rejectRequest,
  requestChanges,
  revertLog,
  saveChecklist,
  verifyMember,
} from "../lib/localzReview";
import {
  CORE_ITEMS,
  ITEM_LABELS,
  OPTIONAL_ITEMS,
  type Cost,
  type Hours,
  type ProviderType,
  STATUS_LABELS,
  type ServiceEntry,
  type Submission,
  type WhoCanCome,
  fetchProviderTypes,
  withDefaults,
} from "../lib/providerPortal";
import { CompletenessMeter, ListingForm, cleanSubmission } from "./localz/providers/ProviderFields";

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "-");
const ORIGINS: Record<string, string> = { self_serve: "Portal", inquiry: "Ask to be listed", admin_assisted: "Admin-assisted" };
const TONE = { ok: "ok", info: "info", warn: "warn" } as const;

const WEEK_NAMES: Record<number, string> = { 1: "1st", 2: "2nd", 3: "3rd", 4: "4th", 5: "5th", [-1]: "last" };

/** A schedule in a reviewer's shorthand (the public text comes from the server). */
function schedule(h: Hours): string {
  const parts =
    h.mode === "weekly"
      ? [Object.entries(h.weekly).map(([d, r]) => `${d} ${(r ?? []).map((x) => `${x.open}-${x.close}`).join(", ")}`).join("; ")]
      : h.mode === "monthly"
        ? [(h.monthly ?? []).map((m) => `${m.weeks.map((w) => WEEK_NAMES[w]).join("+")} ${m.day} ${m.open}-${m.close}`).join("; ")]
        : [h.mode ?? "-"];
  if (h.alternate_weeks_from) parts.push(`every other week from ${h.alternate_weeks_from}`);
  if (h.season) parts.push(`season ${h.season.start} to ${h.season.end}`);
  if (h.note) parts.push(h.note);
  return parts.filter(Boolean).join(" · ") || "-";
}

const whoLine = (w: WhoCanCome) => (w.open_to_anyone ? "Open to anyone" : JSON.stringify(w));
const costLine = (c: Cost) => [c.kind, c.amount].filter(Boolean).join(" ") || "-";

function programLine(x: ServiceEntry, label: (key: string | null) => string): string {
  const lines = [`${label(x.type)}: ${x.name || "-"} - ${x.description || "-"}`];
  if (x.hours) lines.push(`  Own hours: ${schedule(x.hours)}`);
  if (x.place) lines.push(`  Meets at: ${[x.place.place_name, x.place.address, x.place.city, x.place.postal_code].filter(Boolean).join(", ")}`);
  if (x.who) lines.push(`  Own who can come: ${whoLine(x.who)}`);
  if (x.cost) lines.push(`  Own cost: ${costLine(x.cost)}`);
  if (x.delivery) lines.push(`  Delivery: ${x.delivery}`);
  if (x.signup?.status) lines.push(`  Sign-up: ${[x.signup.status, x.signup.opens_on, x.signup.how].filter(Boolean).join(" · ")}`);
  return lines.join("\n");
}

function Summary({ s, types }: { s: Submission; types: ProviderType[] }) {
  const label = (key: string | null) => types.find((t) => t.key === key)?.label ?? key ?? "-";
  const rows: [string, string][] = [
    ["Organization", s.organization_name || "-"],
    ["Programs", s.services.map((x) => programLine(x, label)).join("\n") || "-"],
    ["Address", s.address_kind === "public" ? [s.address, s.city, s.postal_code].filter(Boolean).join(", ") || "-" : s.address_kind ?? "-"],
    ["Counties served", s.service_area_counties.join(", ") || "-"],
    ["Hours", schedule(s.hours)],
    ["Phone", s.phone || "-"],
    ["Who can come", whoLine(s.who)],
    ["Cost", costLine(s.cost)],
    ["Website", s.website || "-"],
    ["Email", s.email || "-"],
    [
      "Ways to help",
      s.ways_to_help
        ? [
            s.ways_to_help.volunteer_roles.length ? `Volunteers: ${s.ways_to_help.volunteer_roles.join("; ")}` : "",
            s.ways_to_help.volunteer_how ?? "",
            s.ways_to_help.donations.length ? `Donations: ${s.ways_to_help.donations.join("; ")}` : "",
            s.ways_to_help.wishlist_url ? `Wish list: ${s.ways_to_help.wishlist_url}` : "",
          ]
            .filter(Boolean)
            .join("\n") || "-"
        : "-",
    ],
    ["What they provide (inquiry)", s.what_you_provide || "-"],
    ["Town (inquiry)", s.town || "-"],
  ];
  return (
    <dl className="kv">
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <dt>{k}</dt>
          <dd style={{ whiteSpace: "pre-wrap" }}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

function LogList({ entries, onRevert, manage }: { entries: LogEntry[]; onRevert?: (e: LogEntry) => void; manage: boolean }) {
  if (!entries.length) return <p className="note">Nothing yet.</p>;
  return (
    <ul className="provider-log">
      {entries.map((e) => (
        <li key={e.id}>
          <strong>{e.action}</strong> · {e.actor_email ?? e.actor_kind} · {when(e.created_at)}
          {e.note && <span className="note"> · {e.note}</span>}
          {Object.keys(e.after).length > 0 && <span className="note"> · {Object.keys(e.after).join(", ")}</span>}
          {e.reverted_at && <Badge dot={false}>Reverted</Badge>}
          {manage && e.revertible && onRevert && (
            <button className="btn ghost" onClick={() => onRevert(e)}>
              Revert
            </button>
          )}
        </li>
      ))}
    </ul>
  );
}

/** /admin/resources/onboarding/:id - one request: what they sent, the
 * automatic checks, likely duplicates, the checklist and the decision. */
export function LocalzReviewDetailPage() {
  const { requestId = "" } = useParams();
  const { user } = useAuth();
  const toast = useToast();
  const manage = can(user, "resources.manage");
  const [review, setReview] = useState<Review | null>(null);
  const [types, setTypes] = useState<ProviderType[]>([]);
  const [checklist, setChecklist] = useState<Record<string, boolean>>({});
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Submission | null>(null);
  const [editPrivate, setEditPrivate] = useState("");
  const [changesOpen, setChangesOpen] = useState(false);
  const [changeFields, setChangeFields] = useState<string[]>([]);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [reason, setReason] = useState("could_not_verify");
  const [mergeTarget, setMergeTarget] = useState("");
  const [serviceLogs, setServiceLogs] = useState<Record<string, LogEntry[]>>({});
  const [members, setMembers] = useState<Record<string, Member[]>>({});
  const [memberEmail, setMemberEmail] = useState("");

  const loadServices = useCallback((ids: string[]) => {
    ids.forEach((id) => {
      fetchServiceLog(id).then((l) => setServiceLogs((m) => ({ ...m, [id]: l })));
      fetchMembers(id).then((l) => setMembers((m) => ({ ...m, [id]: l })));
    });
  }, []);

  const apply = useCallback(
    (r: Review) => {
      setReview(r);
      setChecklist(r.checklist);
      loadServices(r.service_ids);
    },
    [loadServices],
  );

  useEffect(() => {
    fetchReview(requestId).then(apply).catch(() => setReview(null));
    fetchProviderTypes().then(setTypes).catch(() => setTypes([]));
  }, [requestId, apply]);

  const run = async (fn: () => Promise<Review>, done: string) => {
    setBusy(true);
    try {
      apply(await fn());
      toast({ title: done, tone: "ok" });
      return true;
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : "Failed", tone: "bad" });
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (!review) return <p className="note">Loading…</p>;
  const open = review.status === "submitted" || review.status === "in_review";
  const allTicked = CHECKLIST.every((c) => checklist[c.key]);
  // A claim of a listing whose source published an email can skip the call:
  // the provider confirms with a code sent there (their edits wait until then).
  const approveReady = CHECKLIST.every((c) => checklist[c.key] || (c.key === "connected" && !!review.verify_by_email));
  const sub = withDefaults(review.submission);

  const revert = async (e: LogEntry) => {
    try {
      await revertLog(e.id);
      toast({ title: "Reverted", tone: "ok" });
      if (e.service_id) loadServices([e.service_id]);
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : "Failed", tone: "bad" });
    }
  };

  return (
    <div>
      <PageHeader
        back={{ to: "/admin/resources/onboarding", label: "Localz listings" }}
        title={sub.organization_name || "(no name)"}
        subtitle={`${STATUS_LABELS[review.status]} · ${ORIGINS[review.origin] ?? review.origin} · submitted ${when(review.submitted_at)}`}
      />

      {review.flags.length > 0 && (
        <SectionCard title="Automatic checks" description="Prompts to look closer, not verdicts.">
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {review.flags.map((f, i) => (
              <span key={i}>
                <Badge tone={TONE[f.level]} dot={false}>
                  {f.code.replace(/_/g, " ")}
                </Badge>{" "}
                {f.message}
              </span>
            ))}
          </div>
        </SectionCard>
      )}

      <SectionCard title="Who sent it" description="Contact details are for verification only and are never published.">
        <dl className="kv">
          <dt>Contact</dt>
          <dd>{review.contact_name || "-"}</dd>
          <dt>Contact phone</dt>
          <dd>{review.contact_phone || "-"}</dd>
          <dt>Contact email</dt>
          <dd>{review.contact_email || "-"}</dd>
          <dt>Account</dt>
          <dd>{review.account_email || "(no account)"}</dd>
          {review.claimed_service && (
            <>
              <dt>Claiming</dt>
              <dd>
                <Link to={`/localz/r/${review.claimed_service.id}`}>{review.claimed_service.name}</Link> ({review.claimed_service.source})
              </dd>
            </>
          )}
          {review.private_address && (
            <>
              <dt>{sub.address_kind === "confidential" ? "Confidential address" : "Mailing address"}</dt>
              <dd>
                {review.private_address} <span className="note">(never published - verify only)</span>
              </dd>
            </>
          )}
        </dl>
      </SectionCard>

      <SectionCard title="The listing" actions={manage && open && !editing ? <button className="btn" onClick={() => setEditing(sub)}>Edit before approving</button> : undefined}>
        <CompletenessMeter c={review.completeness} />
        {editing ? (
          <>
            <ListingForm value={editing} onChange={setEditing} types={types} privateAddress={editPrivate} onPrivateAddress={setEditPrivate} hasPrivateAddress={review.has_private_address} />
            <div style={{ display: "flex", gap: 8 }}>
              <button
                className="btn btn-primary"
                disabled={busy}
                onClick={async () => {
                  if (await run(() => editRequest(review.id, cleanSubmission(editing), editPrivate.trim() || undefined), "Saved (logged as your edit)")) {
                    setEditing(null);
                    setEditPrivate("");
                  }
                }}
              >
                Save edit
              </button>
              <button className="btn" onClick={() => setEditing(null)}>
                Cancel
              </button>
            </div>
          </>
        ) : (
          <Summary s={sub} types={types} />
        )}
      </SectionCard>

      <SectionCard title="Likely duplicates" description="Same or similar name, phone or street, across every source including NJ 211.">
        {review.duplicates.length === 0 ? (
          <p className="note">None found.</p>
        ) : (
          <ul className="provider-log">
            {review.duplicates.map((d) => (
              <li key={d.id}>
                <Link to={`/localz/r/${d.id}`}>{d.name}</Link> · {d.organization_name ?? "-"} · {d.city ?? (d.location_confidential ? "confidential" : "-")} · {d.phone ?? "-"} · {d.source}{" "}
                <span className="note">({d.reasons.join(", ")})</span>{" "}
                {manage && open && (
                  <button className="btn ghost" onClick={() => setMergeTarget(d.id)}>
                    Merge into this
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      {open && (
        <SectionCard title="Reviewer checklist" description="Every item ticked before Approve. Your answers are recorded with the decision.">
          <div className="checks">
            {CHECKLIST.map((c) => (
              <label key={c.key} className={`check ${checklist[c.key] ? "on" : ""}`}>
                <input type="checkbox" disabled={!manage} checked={!!checklist[c.key]} onChange={(e) => setChecklist({ ...checklist, [c.key]: e.target.checked })} />
                <span>
                  <strong>{c.label}</strong>
                  <span className="note" style={{ display: "block" }}>
                    {c.hint}
                  </span>
                </span>
              </label>
            ))}
          </div>
          {review.verify_by_email && !checklist.connected && (
            <p className="note">
              No call needed: NJ 211 lists {review.verify_by_email} for this listing. After approval they can confirm with a code sent there; until
              then every change they make waits for review.
            </p>
          )}
          {manage && (
            <>
              <Field label="Note" hint="Optional for Approve, required for Request changes. The provider sees it.">
                <textarea rows={2} value={note} maxLength={2000} onChange={(e) => setNote(e.target.value)} />
              </Field>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="btn" disabled={busy} onClick={() => run(() => saveChecklist(review.id, checklist), "Checklist saved")}>
                  Save checklist
                </button>
                <button className="btn btn-primary" disabled={busy || !approveReady} onClick={() => run(() => approveRequest(review.id, checklist, note), "Approved - it's live")}>
                  Approve
                </button>
                <button className="btn" disabled={busy} onClick={() => setChangesOpen(true)}>
                  Request changes
                </button>
                <button className="btn danger" disabled={busy} onClick={() => setRejectOpen(true)}>
                  Reject
                </button>
              </div>
              <p className="note">No email or text is sent in this version: the provider sees the decision in their portal, so call them if it matters.</p>
            </>
          )}
        </SectionCard>
      )}

      {review.decision_note && !open && (
        <SectionCard title="Decision">
          <p>
            {review.reject_reason ? `${REJECT_REASONS.find((r) => r.key === review.reject_reason)?.label ?? review.reject_reason}: ` : ""}
            {review.decision_note}
          </p>
        </SectionCard>
      )}

      {review.service_ids.map((sid) => (
        <SectionCard key={sid} title="Live listing" description="Its history, with one-step revert, and who can update it." actions={<Link to={`/localz/r/${sid}`}>Public page</Link>}>
          <LogList entries={serviceLogs[sid] ?? []} manage={manage} onRevert={revert} />
          <h4>Members</h4>
          <ul className="provider-log">
            {(members[sid] ?? []).map((m) => (
              <li key={m.id}>
                {m.email ?? "(deleted account)"} · {m.role} · {m.verified_at ? `verified ${when(m.verified_at)}` : "not verified"}{" "}
                {manage && !m.verified_at && (
                  <button className="btn ghost" onClick={() => verifyMember(m.id).then(() => loadServices([sid]))}>
                    I called and confirmed
                  </button>
                )}
              </li>
            ))}
          </ul>
          {manage && (
            <div style={{ display: "flex", gap: 8, alignItems: "flex-end" }}>
              <Field label="Add someone by account email" hint="They start unverified: their changes wait for review until you've called.">
                <input type="email" value={memberEmail} onChange={(e) => setMemberEmail(e.target.value)} />
              </Field>
              <button
                className="btn"
                disabled={!memberEmail.trim()}
                onClick={() =>
                  addMember(sid, memberEmail.trim(), "editor")
                    .then(() => {
                      setMemberEmail("");
                      loadServices([sid]);
                    })
                    .catch((err) => toast({ title: err instanceof Error ? err.message : "Failed", tone: "bad" }))
                }
              >
                Add
              </button>
            </div>
          )}
        </SectionCard>
      ))}

      <SectionCard title="Request history">
        <LogList entries={review.log} manage={false} />
      </SectionCard>

      <Modal
        open={changesOpen}
        onClose={() => setChangesOpen(false)}
        title="Request changes"
        footer={
          <>
            <button className="btn" onClick={() => setChangesOpen(false)}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              disabled={busy || !note.trim()}
              onClick={async () => {
                if (await run(() => requestChanges(review.id, note, changeFields), "Sent back to the provider")) setChangesOpen(false);
              }}
            >
              Send back
            </button>
          </>
        }
      >
        <Field label="What needs changing" hint="Required. The provider sees this note.">
          <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
        <p className="note">Fields to highlight in their form:</p>
        <div className="chips provider-chips">
          {[...CORE_ITEMS, ...OPTIONAL_ITEMS].map((k) => (
            <button
              key={k}
              type="button"
              className="chip"
              aria-pressed={changeFields.includes(k)}
              onClick={() => setChangeFields(changeFields.includes(k) ? changeFields.filter((x) => x !== k) : [...changeFields, k])}
            >
              {ITEM_LABELS[k]}
            </button>
          ))}
        </div>
      </Modal>

      <Modal
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        title="Reject this request"
        footer={
          <>
            <button className="btn" onClick={() => setRejectOpen(false)}>
              Cancel
            </button>
            <button
              className="btn danger"
              disabled={busy}
              onClick={async () => {
                if (await run(() => rejectRequest(review.id, reason, note), "Rejected")) setRejectOpen(false);
              }}
            >
              Reject
            </button>
          </>
        }
      >
        <Field label="Reason">
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            {REJECT_REASONS.map((r) => (
              <option key={r.key} value={r.key}>
                {r.label}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Note" hint="Optional. The provider sees it - keep it polite.">
          <textarea rows={3} value={note} onChange={(e) => setNote(e.target.value)} />
        </Field>
      </Modal>

      <Modal
        open={!!mergeTarget}
        onClose={() => setMergeTarget("")}
        title="Merge into the existing listing"
        footer={
          <>
            <button className="btn" onClick={() => setMergeTarget("")}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              disabled={busy || !allTicked}
              onClick={async () => {
                if (await run(() => mergeRequest(review.id, checklist, mergeTarget, note), "Merged - the existing listing now carries their details")) setMergeTarget("");
              }}
            >
              Merge
            </button>
          </>
        }
      >
        <p>The provider's details replace the existing listing's (logged, and revertible), and they get to maintain it. No second listing is created.</p>
        {!allTicked && <p className="note">Tick every checklist item first.</p>}
      </Modal>
    </div>
  );
}
