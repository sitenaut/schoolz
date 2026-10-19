import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Badge } from "../components/ui/Badge";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { Field } from "../components/ui/Field";
import { PageHeader } from "../components/ui/PageHeader";
import { SectionCard } from "../components/ui/SectionCard";
import { useToast } from "../components/ui/Toast";
import { useAuth } from "../context/AuthContext";
import { can } from "../lib/permissions";
import {
  type AdminListing,
  type LogEntry,
  type Member,
  deleteListing,
  editLiveListing,
  fetchLiveListing,
  fetchMembers,
  fetchServiceLog,
  hideListing,
  revertLog,
  unhideListing,
} from "../lib/localzReview";
import { type ProviderType, fetchProviderTypes } from "../lib/providerPortal";
import { LogList } from "./LocalzReviewDetailPage";
import { AlertCard, ClosureCard, DetailsCard, HelpCard, JoiningCard, ReviewedCard, WeekHoursCard } from "./localz/providers/ProviderListingPage";

const SOURCES: Record<string, string> = { provider: "Submitted by a provider", nj211: "NJ 211 (claimed)", childcarenj: "ChildCareNJ (claimed)" };

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "-");

/** /admin/resources/listings/:id - a live listing a reviewer looks after:
 * the provider's own edit cards (every change publishes at once), hide it
 * off the site now, or delete one a provider submitted. */
export function LocalzListingAdminPage() {
  const { serviceId = "" } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const manage = can(user, "resources.manage");
  const [listing, setListing] = useState<AdminListing | null | undefined>(undefined);
  const [log, setLog] = useState<LogEntry[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [types, setTypes] = useState<ProviderType[]>([]);
  const [busy, setBusy] = useState(false);
  const [hideOpen, setHideOpen] = useState(false);
  const [hideNote, setHideNote] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);
  // Remounts the edit cards after a save or revert, so their fields show what's live.
  const [version, setVersion] = useState(0);

  const load = useCallback(() => {
    fetchLiveListing(serviceId)
      .then((l) => {
        setListing(l);
        setVersion((v) => v + 1);
      })
      .catch(() => setListing(null));
    fetchServiceLog(serviceId).then(setLog).catch(() => setLog([]));
    fetchMembers(serviceId).then(setMembers).catch(() => setMembers([]));
  }, [serviceId]);
  useEffect(() => {
    load();
    fetchProviderTypes().then(setTypes).catch(() => setTypes([]));
  }, [load]);

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    try {
      await fn();
      toast({ title: done, tone: "ok" });
      load();
      return true;
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : "Failed", tone: "bad" });
      return false;
    } finally {
      setBusy(false);
    }
  };

  if (listing === undefined) return <p className="note">Loading…</p>;
  if (listing === null)
    return (
      <p className="note">
        Listing not found. <Link to="/admin/resources/onboarding?tab=listings">Live listings</Link>
      </p>
    );

  const hidden = listing.status === "hidden";
  const send = async (body: Record<string, unknown>) => {
    await run(async () => {
      const res = await editLiveListing(listing.id, body);
      if (!res.applied.length) throw new Error("Nothing changed");
    }, "Published");
  };
  const last = listing.last_assured_on ? new Date(`${listing.last_assured_on}T12:00:00`).toLocaleDateString() : "never";

  return (
    <div>
      <PageHeader
        back={{ to: "/admin/resources/onboarding?tab=listings", label: "Live listings" }}
        title={listing.name}
        subtitle={[listing.organization_name !== listing.name ? listing.organization_name : null, SOURCES[listing.source] ?? listing.source, `last confirmed ${last}`]
          .filter(Boolean)
          .join(" · ")}
        actions={
          manage && (
            <>
              {hidden ? (
                <button className="btn btn-primary" disabled={busy} onClick={() => run(() => unhideListing(listing.id), "Back on the site")}>
                  Put back on the site
                </button>
              ) : (
                <button className="btn danger" disabled={busy} onClick={() => setHideOpen(true)}>
                  Hide now
                </button>
              )}
              {listing.can_delete && (
                <button className="btn danger" disabled={busy} onClick={() => setDeleteOpen(true)}>
                  Delete
                </button>
              )}
            </>
          )
        }
      />

      {hidden ? (
        <p className="localz-alert">
          <Badge tone="bad" dot={false}>
            Hidden
          </Badge>{" "}
          Off the site since {when(listing.hidden_at)}
          {listing.hidden_note ? ` - ${listing.hidden_note}` : ""}. Its provider can't change it until you put it back.
        </p>
      ) : listing.status !== "active" ? (
        <p className="note">
          <Badge tone="warn" dot={false}>
            {listing.status}
          </Badge>{" "}
          Not on the site: its source stopped listing it.
        </p>
      ) : (
        <p>
          <Link to={`/localz/r/${listing.id}`}>See the public listing</Link>
        </p>
      )}
      {listing.pending_changes.length > 0 && (
        <p className="note">
          Held edits waiting: {listing.pending_changes.flatMap((p) => p.fields).join(", ")} -{" "}
          <Link to="/admin/resources/onboarding?tab=changes">review them</Link>
        </p>
      )}

      <SectionCard title="Who manages it">
        {members.length ? (
          <ul className="provider-log">
            {members.map((m) => (
              <li key={m.id}>
                {m.email ?? "(deleted account)"} · {m.role} · {m.verified_at ? `verified ${when(m.verified_at)}` : "not verified"}
              </li>
            ))}
          </ul>
        ) : (
          <p className="note">No provider account.</p>
        )}
      </SectionCard>

      {manage && (
        <div key={version}>
          <p className="note">Your changes publish at once and are logged below, where each one can be reverted.</p>
          <ReviewedCard listing={listing} types={types} busy={busy} send={send} immediate />
          <DetailsCard listing={listing} busy={busy} send={send} />
          <AlertCard listing={listing} busy={busy} send={send} />
          <ClosureCard listing={listing} busy={busy} send={send} />
          <WeekHoursCard listing={listing} busy={busy} send={send} />
          <JoiningCard listing={listing} busy={busy} send={send} />
          <HelpCard listing={listing} busy={busy} send={send} />
        </div>
      )}

      <SectionCard title="History">
        <LogList entries={log} manage={manage} onRevert={(e) => run(() => revertLog(e.id), "Reverted")} />
      </SectionCard>

      <ConfirmDialog
        open={hideOpen}
        title="Hide this listing now"
        description="It comes off search, its page and the local events calendar at once, and its provider can't change it until you put it back."
        confirmLabel="Hide"
        danger
        busy={busy}
        disabled={!hideNote.trim()}
        onCancel={() => setHideOpen(false)}
        onConfirm={async () => {
          if (await run(() => hideListing(listing.id, hideNote.trim()), "Hidden")) {
            setHideOpen(false);
            setHideNote("");
          }
        }}
      >
        <Field label="Why" hint={'For the history - for example "Closed for good" or "Account taken over".'}>
          <input value={hideNote} maxLength={2000} onChange={(e) => setHideNote(e.target.value)} />
        </Field>
      </ConfirmDialog>

      <ConfirmDialog
        open={deleteOpen}
        title="Delete this listing for good"
        description="Its posted dates, held edits and provider access go with it, and it can't be undone. Hiding is reversible."
        confirmLabel="Delete"
        danger
        busy={busy}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={async () => {
          setBusy(true);
          try {
            await deleteListing(listing.id);
            toast({ title: "Deleted", tone: "ok" });
            navigate("/admin/resources/onboarding?tab=listings");
          } catch (err) {
            toast({ title: err instanceof Error ? err.message : "Failed", tone: "bad" });
            setBusy(false);
          }
        }}
      />
    </div>
  );
}
