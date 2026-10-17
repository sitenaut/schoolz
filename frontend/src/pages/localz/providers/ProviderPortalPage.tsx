import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SeoHead } from "../../../components/SeoHead";
import { ClosureNote } from "../ClosureNote";
import { ConfirmDialog } from "../../../components/ui/ConfirmDialog";
import { useAuth } from "../../../context/AuthContext";
import { usePrerenderReady } from "../../../lib/prerenderReady";
import {
  type MyListing,
  type OnboardingRequest,
  STATUS_LABELS,
  fetchMyListings,
  fetchMyRequests,
  withdrawRequest,
} from "../../../lib/providerPortal";

export function SignInPrompt({ next }: { next: string }) {
  const { t } = useTranslation();
  return (
    <div className="card provider-signin">
      <p>{t("Sign in to list your program or update your listing.")}</p>
      <Link className="btn btn-primary" to={`/login?next=${encodeURIComponent(next)}`}>
        {t("Sign in or create an account")}
      </Link>
    </div>
  );
}

export function StatusMessage({ r }: { r: OnboardingRequest }) {
  const { t } = useTranslation();
  switch (r.status) {
    case "draft":
      return <p className="note">{t("Not sent yet. Finish it and send it for review.")}</p>;
    case "submitted":
    case "in_review":
      return <p className="note">{t("Submitted — we usually review within 3 business days. We'll call the number you listed to confirm it's you.")}</p>;
    case "changes_requested":
      return (
        <div className="localz-alert provider-decision" role="note">
          <span>
            <strong>{t("We asked for a few changes:")}</strong> {r.decision_note}
          </span>
        </div>
      );
    case "approved":
      return <p className="note">{t("Approved - your listing is live.")}</p>;
    case "rejected":
      return (
        <p className="note">
          {t("We couldn't approve this listing.")} {r.decision_note} <Link to="/contact">{t("Questions? Contact us.")}</Link>
        </p>
      );
    default:
      return <p className="note">{t("Withdrawn.")}</p>;
  }
}

const WITHDRAWABLE = ["draft", "submitted", "in_review", "changes_requested"];

/** /localz/providers/portal - the provider's home: approved listings first
 * (their quick updates are what they come back for), then requests. */
export function ProviderPortalPage() {
  const { t } = useTranslation();
  const { user, loading } = useAuth();
  const [listings, setListings] = useState<MyListing[] | null>(null);
  const [requests, setRequests] = useState<OnboardingRequest[] | null>(null);
  const [error, setError] = useState(false);
  const [withdrawing, setWithdrawing] = useState<OnboardingRequest | null>(null);
  const [busy, setBusy] = useState(false);
  usePrerenderReady(!loading);

  const load = useCallback(() => {
    Promise.all([fetchMyListings(), fetchMyRequests()])
      .then(([l, r]) => {
        setListings(l);
        setRequests(r);
      })
      .catch(() => setError(true));
  }, []);
  useEffect(() => {
    if (user) load();
  }, [user, load]);

  if (loading) return <p className="note">{t("Loading…")}</p>;
  if (!user) return <SignInPrompt next="/localz/providers/portal" />;

  const withdraw = async () => {
    if (!withdrawing) return;
    setBusy(true);
    try {
      await withdrawRequest(withdrawing.id);
      setWithdrawing(null);
      load();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="provider-page">
      <SeoHead title={t("Your listings · Localz")} description={t("Update your Localz listing.")} path="/localz/providers/portal" />
      <div className="localz-nav-row">
        <h2 className="localz-title">{t("Your listings")}</h2>
        <Link className="btn btn-primary" to="/localz/providers/requests/new">
          {t("Start a new listing")}
        </Link>
      </div>
      {error && <p className="note">{t("Couldn't load this just now. Try again in a moment.")}</p>}
      {listings === null || requests === null ? (
        !error && <p className="note">{t("Loading…")}</p>
      ) : (
        <>
          {listings.length === 0 && requests.length === 0 && (
            <p className="note">
              {t("Nothing here yet.")} <Link to="/localz/providers">{t("How listing works")}</Link>
            </p>
          )}
          {listings.map((l) => (
            <article key={l.id} className="localz-card">
              <Link className="localz-card-title" to={`/localz/providers/listings/${l.id}`}>
                {l.name}
              </Link>
              {l.organization_name && l.organization_name !== l.name && <div className="localz-card-org">{l.organization_name}</div>}
              {l.closure && <ClosureNote closure={l.closure} />}
              {!l.verified && <p className="note">{t("Until we've confirmed it's you by phone, your changes wait for review.")}</p>}
              {l.pending_changes.length > 0 && <p className="note">{t("Some changes are waiting for review.")}</p>}
              <div className="localz-card-actions">
                <Link className="btn btn-primary" to={`/localz/providers/listings/${l.id}`}>
                  {t("Quick updates")}
                </Link>
                <Link className="btn ghost" to={`/localz/r/${l.id}`}>
                  {t("See the public listing")}
                </Link>
              </div>
            </article>
          ))}

          {requests.length > 0 && <h3 className="provider-subhead">{t("Your requests")}</h3>}
          {requests.map((r) => (
            <article key={r.id} className="localz-card">
              <div className="localz-card-title">{r.submission.organization_name || t("Untitled listing")}</div>
              <span className="tag localz-tag">{t(STATUS_LABELS[r.status])}</span>
              <StatusMessage r={r} />
              <div className="localz-card-actions">
                {(r.status === "draft" || r.status === "changes_requested") && (
                  <Link className="btn btn-primary" to={`/localz/providers/requests/${r.id}`}>
                    {r.status === "draft" ? t("Continue") : t("Make changes")}
                  </Link>
                )}
                {(r.status === "submitted" || r.status === "in_review") && (
                  <Link className="btn" to={`/localz/providers/requests/${r.id}`}>
                    {t("View")}
                  </Link>
                )}
                {WITHDRAWABLE.includes(r.status) && (
                  <button className="btn ghost" onClick={() => setWithdrawing(r)}>
                    {t("Withdraw")}
                  </button>
                )}
              </div>
            </article>
          ))}
        </>
      )}
      <ConfirmDialog
        open={!!withdrawing}
        title={t("Withdraw this request?")}
        description={t("It won't be reviewed. You can start a new one any time.")}
        confirmLabel={t("Withdraw")}
        cancelLabel={t("Keep it")}
        busy={busy}
        onConfirm={withdraw}
        onCancel={() => setWithdrawing(null)}
      />
    </div>
  );
}
