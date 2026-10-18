import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BOT_CHECK_ENABLED, BotCheck } from "../../../components/BotCheck";
import { SeoHead } from "../../../components/SeoHead";
import { Field } from "../../../components/ui/Field";
import { useToast } from "../../../components/ui/Toast";
import { useAuth } from "../../../context/AuthContext";
import { usePrerenderReady } from "../../../lib/prerenderReady";
import {
  ITEM_LABELS,
  type ListingBrief,
  type OnboardingRequest,
  type ProviderType,
  STATUS_LABELS,
  type Submission,
  completeness,
  emptySubmission,
  fetchMyRequest,
  fetchProviderTypes,
  matchListings,
  saveRequest,
  startRequest,
  submitRequest,
  withDefaults,
} from "../../../lib/providerPortal";
import { SignInPrompt, StatusMessage } from "./ProviderPortalPage";
import { CompletenessMeter, ListingForm, cleanSubmission } from "./ProviderFields";

/** /localz/providers/requests/:id ("new" starts one) - the listing form with
 * its completeness meter. Editable as a draft or when a reviewer asked for
 * changes; otherwise it shows where the request stands. */
export function ProviderRequestPage() {
  const { requestId } = useParams();
  const { user, loading } = useAuth();
  const { t } = useTranslation();
  usePrerenderReady(!loading);
  if (loading) return <p className="note">{t("Loading…")}</p>;
  if (!user) return <SignInPrompt next={`/localz/providers/requests/${requestId ?? "new"}`} />;
  return <RequestEditor key={requestId} requestId={requestId === "new" ? null : (requestId ?? null)} />;
}

function RequestEditor({ requestId }: { requestId: string | null }) {
  const { t } = useTranslation();
  const toast = useToast();
  const navigate = useNavigate();
  const [types, setTypes] = useState<ProviderType[]>([]);
  const [req, setReq] = useState<OnboardingRequest | null>(null);
  const [sub, setSub] = useState<Submission>(emptySubmission());
  const [privateAddress, setPrivateAddress] = useState("");
  const [contactName, setContactName] = useState("");
  const [contactPhone, setContactPhone] = useState("");
  const [claim, setClaim] = useState<ListingBrief | null>(null);
  const [matches, setMatches] = useState<ListingBrief[] | null>(null);
  const [botToken, setBotToken] = useState<string | null>(null);
  const [botRound, setBotRound] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    fetchProviderTypes().then(setTypes).catch(() => setLoadFailed(true));
  }, []);
  useEffect(() => {
    if (!requestId) return;
    fetchMyRequest(requestId)
      .then((r) => {
        setReq(r);
        setSub(withDefaults(r.submission));
        setContactName(r.contact_name ?? "");
        setContactPhone(r.contact_phone ?? "");
        setClaim(r.claimed_service);
      })
      .catch(() => setLoadFailed(true));
  }, [requestId]);

  const hasPrivate = !!privateAddress.trim() || !!req?.has_private_address;
  const meter = useMemo(() => completeness(sub, hasPrivate), [sub, hasPrivate]);
  const editable = !req || req.status === "draft" || req.status === "changes_requested";
  const needsBot = !req && BOT_CHECK_ENABLED;

  if (loadFailed) return <p className="note">{t("Couldn't load this just now. Try again in a moment.")}</p>;
  if (requestId && !req) return <p className="note">{t("Loading…")}</p>;

  const body = () => ({
    submission: cleanSubmission(sub),
    // Sent only when typed: a saved one is never sent back to the browser.
    private_address: privateAddress.trim() ? privateAddress.trim() : undefined,
    contact_name: contactName.trim() || null,
    contact_phone: contactPhone.trim() || null,
    claimed_service_id: claim?.id ?? null,
    bot_token: botToken,
  });

  const save = async (thenOpen = true): Promise<OnboardingRequest | null> => {
    setBusy(true);
    setError(null);
    try {
      const saved = req ? await saveRequest(req.id, body()) : await startRequest(body());
      setReq(saved);
      setPrivateAddress("");
      if (!req && thenOpen) navigate(`/localz/providers/requests/${saved.id}`, { replace: true });
      return saved;
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't save - please try again."));
      if (!req) {
        setBotToken(null);
        setBotRound((n) => n + 1);
      }
      return null;
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    const saved = await save(false);
    if (!saved) return;
    setBusy(true);
    try {
      const sent = await submitRequest(saved.id);
      setReq(sent);
      // A new request gets its own URL only now: navigating first remounts the
      // page, which would read it back as a draft before the submit lands.
      if (!req) navigate(`/localz/providers/requests/${sent.id}`, { replace: true });
      toast({ title: t("Sent for review"), tone: "ok" });
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Couldn't send - please try again."));
    } finally {
      setBusy(false);
    }
  };

  const findMatches = async () => {
    const name = (sub.organization_name ?? "").trim();
    if (name.length < 2) return;
    try {
      setMatches(await matchListings(name));
    } catch {
      setMatches([]);
    }
  };

  const organizationExtra =
    !req || req.status === "draft" ? (
      claim ? (
        <div className="provider-claim">
          <p>
            {t("You're claiming this listing:")} <strong>{claim.name}</strong>
            {claim.organization_name ? ` · ${claim.organization_name}` : ""}
          </p>
          <button type="button" className="btn ghost" onClick={() => setClaim(null)}>
            {t("This isn't us")}
          </button>
        </div>
      ) : (
        <div>
          <button type="button" className="btn" onClick={findMatches} disabled={(sub.organization_name ?? "").trim().length < 2}>
            {t("Check if we already list you")}
          </button>
          {matches && matches.length === 0 && <p className="note">{t("No listing with that name yet - we'll make a new one.")}</p>}
          {matches && matches.length > 0 && (
            <div className="provider-matches">
              <p className="note">{t("Is this you? Claim it so there's one listing, kept up to date by you.")}</p>
              {matches.map((m) => (
                <div key={m.id} className="provider-match">
                  <span>
                    <strong>{m.name}</strong>
                    {m.organization_name ? ` · ${m.organization_name}` : ""}
                    {m.city ? ` · ${m.city}` : ""}
                  </span>
                  <button type="button" className="btn" onClick={() => setClaim(m)}>
                    {t("Yes, this is us")}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )
    ) : null;

  return (
    <div className="provider-page">
      <SeoHead title={t("Your listing · Localz")} description={t("Update your Localz listing.")} path="/localz/providers/portal" />
      <Link className="localz-back-link" to="/localz/providers/portal">
        {t("Your listings")}
      </Link>
      <h2 className="localz-title">{req?.submission.organization_name || t("New listing")}</h2>
      {req && (
        <>
          <span className="tag localz-tag">{t(STATUS_LABELS[req.status])}</span>
          <StatusMessage r={req} />
        </>
      )}

      {editable ? (
        <>
          <div className="provider-meter-sticky">
            <CompletenessMeter c={meter} />
          </div>
          {error && <div className="form-error">{error}</div>}
          <ListingForm
            value={sub}
            onChange={setSub}
            types={types}
            privateAddress={privateAddress}
            onPrivateAddress={setPrivateAddress}
            hasPrivateAddress={!!req?.has_private_address}
            fieldsToFix={req?.fields_to_fix ?? []}
            organizationExtra={organizationExtra}
          />
          <section className="provider-section">
            <h3>{t("Who we should call")}</h3>
            <p className="note">
              {t("Only for us to confirm the listing - never shown publicly. We'll also call the program's own number to make sure it's you.")}
            </p>
            <div className="fgrid two">
              <Field label={t("Your name")}>
                <input value={contactName} maxLength={200} autoComplete="name" onChange={(e) => setContactName(e.target.value)} />
              </Field>
              <Field label={t("Best number for you")} hint={t("Optional")}>
                <input type="tel" value={contactPhone} maxLength={40} onChange={(e) => setContactPhone(e.target.value)} />
              </Field>
            </div>
          </section>
          {needsBot && <BotCheck onToken={setBotToken} resetKey={botRound} />}
          <div className="provider-actions">
            <button className="btn" onClick={() => void save()} disabled={busy || (needsBot && !botToken)}>
              {t("Save draft")}
            </button>
            <button className="btn btn-primary" onClick={send} disabled={busy || meter.missing_core.length > 0 || (needsBot && !botToken)}>
              {req?.status === "changes_requested" ? t("Send again for review") : t("Send for review")}
            </button>
          </div>
          {meter.missing_core.length > 0 ? (
            <p className="note">{t("Still needed: {{items}}", { items: meter.missing_core.map((k) => t(ITEM_LABELS[k] ?? k)).join(", ") })}</p>
          ) : needsBot && !botToken ? (
            <p className="note">{t("Last step: tick the box above to show you're a person.")}</p>
          ) : null}
          <p className="note">{t("Nothing is public until we approve it.")}</p>
        </>
      ) : (
        <p>
          <Link to="/localz/providers/portal">{t("Back to your listings")}</Link>
        </p>
      )}
    </div>
  );
}
