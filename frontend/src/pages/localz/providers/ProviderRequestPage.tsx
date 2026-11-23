import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BOT_CHECK_ENABLED, BotCheck } from "../../../components/BotCheck";
import { SeoHead } from "../../../components/SeoHead";
import { Field } from "../../../components/ui/Field";
import { PhoneInput } from "../../../components/ui/PhoneInput";
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
  emptyUpkeep,
  fetchMyRequest,
  fetchProviderTypes,
  matchListings,
  saveRequest,
  startRequest,
  submitRequest,
  upkeepMissing,
  withDefaults,
} from "../../../lib/providerPortal";
import { SignInPrompt, StatusMessage } from "./ProviderPortalPage";
import { CompletenessMeter, ListingForm, UpkeepEditor, cleanSubmission } from "./ProviderFields";

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
  // Listings we already carry that they ticked as theirs, and whether they
  // also have a program to add that we don't list.
  const [claims, setClaims] = useState<ListingBrief[]>([]);
  const [addMore, setAddMore] = useState(false);
  const [matches, setMatches] = useState<ListingBrief[] | null>(null);
  const [searching, setSearching] = useState(false);
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
        setClaims(r.claimed_services ?? []);
        setAddMore((r.submission.services ?? []).length > 0);
      })
      .catch(() => setLoadFailed(true));
  }, [requestId]);

  const hasPrivate = !!privateAddress.trim() || !!req?.has_private_address;
  // Ticked their listings and has nothing to add: no form to fill in.
  const claimOnly = claims.length > 0 && !addMore;
  // A new request opens on one question - "what are you called?" - and the
  // long form waits until we've looked: most agencies are listed already.
  const [skipped, setSkipped] = useState(false);
  const looked = !!req || !!claim || matches !== null || claims.length > 0 || skipped;
  // The long form: for a program to add beside ticked listings, or for an
  // organization we don't list (nothing found, or none of it theirs).
  const found = (matches ?? []).length > 0;
  const showForm = claims.length > 0 ? addMore : !!req || !!claim || skipped || (matches !== null && !found);
  const canSend = claims.length > 0 || showForm;
  const sending = useMemo<Submission>(
    () => ({ ...sub, claims: claims.map((c) => c.id), services: claimOnly ? [] : sub.services }),
    [sub, claims, claimOnly],
  );
  const meter = useMemo(() => completeness(sending, hasPrivate), [sending, hasPrivate]);
  const editable = !req || req.status === "draft" || req.status === "changes_requested";
  const needsSource = upkeepMissing(sub);
  const needsBot = !req && BOT_CHECK_ENABLED;

  if (loadFailed) return <p className="note">{t("Couldn't load this just now. Try again in a moment.")}</p>;
  if (requestId && !req) return <p className="note">{t("Loading…")}</p>;

  const body = () => ({
    submission: cleanSubmission(sending),
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
    setSearching(true);
    try {
      setMatches(await matchListings(name));
    } catch {
      setMatches([]);
    } finally {
      setSearching(false);
    }
  };

  const ticked = (id: string) => claims.some((c) => c.id === id);
  const tick = (m: ListingBrief, on: boolean) => setClaims((all) => (on ? [...all.filter((c) => c.id !== m.id), m] : all.filter((c) => c.id !== m.id)));
  const wantMore = (yes: boolean) => {
    setAddMore(yes);
    // The form needs one blank program to fill in.
    if (yes && sub.services.length === 0) setSub({ ...sub, services: emptySubmission().services });
  };
  // Ticked ones stay on screen when a new search no longer finds them.
  const choices = [...claims.filter((c) => !(matches ?? []).some((m) => m.id === c.id)), ...(matches ?? [])];
  const unticked = choices.filter((m) => !ticked(m.id));

  const organizationExtra = claim ? (
    // A request from before listings could be ticked several at a time.
    !req || req.status === "draft" ? (
      <div className="provider-claim">
        <p>
          {t("You're claiming this listing:")} <strong>{claim.name}</strong>
          {claim.organization_name ? ` · ${claim.organization_name}` : ""}
        </p>
        <button type="button" className="btn ghost" onClick={() => setClaim(null)}>
          {t("This isn't us")}
        </button>
      </div>
    ) : null
  ) : (
    <div className="provider-find">
      <button
        type="button"
        className={`btn${choices.length === 0 ? " btn-primary" : ""}`}
        onClick={findMatches}
        disabled={searching || (sub.organization_name ?? "").trim().length < 2}
      >
        {searching ? t("Looking…") : choices.length > 0 ? t("Search again") : t("Find our listings")}
      </button>
      {!looked && (
        <>
          <p className="note">{t("We may list you already. Type your organization's name and we'll look - you won't have to retype what we have.")}</p>
          <button type="button" className="btn ghost" onClick={() => setSkipped(true)}>
            {t("We're new here - skip this")}
          </button>
        </>
      )}
      {matches && choices.length === 0 && <p className="note">{t("No listing with that name yet. Fill in the form below and we'll make one.")}</p>}
      {choices.length > 0 && (
        <fieldset className="provider-matches">
          <legend>{t("We already list these. Tick every one that's yours.")}</legend>
          {choices.map((m) => (
            <label key={m.id} className={`provider-match${ticked(m.id) ? " is-ticked" : ""}`}>
              <input type="checkbox" checked={ticked(m.id)} onChange={(e) => tick(m, e.target.checked)} />
              <span className="provider-match-text">
                <strong>{m.name}</strong>
                <span className="note">{[m.organization_name, [m.address, m.city].filter(Boolean).join(", "), m.phone].filter(Boolean).join(" · ")}</span>
              </span>
              <a className="provider-match-view" href={`/localz/r/${m.id}`} target="_blank" rel="noreferrer">
                {t("See it")}
              </a>
            </label>
          ))}
          {unticked.length > 1 && (
            <button type="button" className="btn ghost" onClick={() => setClaims(choices)}>
              {t("They're all ours - tick all {{count}}", { count: choices.length })}
            </button>
          )}
          <p className="note">{t("Not seeing one of yours? Search again with a shorter name, or add it below.")}</p>
          {claims.length === 0 && !showForm && (
            <button type="button" className="btn ghost" onClick={() => setSkipped(true)}>
              {t("None of these are ours")}
            </button>
          )}
        </fieldset>
      )}
      {claims.length > 0 && (
        <div className="provider-claim">
          <p>
            <strong>{t("{{count}} ticked.", { count: claims.length })}</strong>{" "}
            {t("Nothing to retype: once we confirm it's you, you can correct each one - hours, phone, anything that's out of date.")}
          </p>
          <fieldset className="provider-more">
            <legend>{t("Do you run a program that isn't on this list?")}</legend>
            <label>
              <input type="radio" name="provider-more" checked={!addMore} onChange={() => wantMore(false)} /> {t("No, that's all of them")}
            </label>
            <label>
              <input type="radio" name="provider-more" checked={addMore} onChange={() => wantMore(true)} /> {t("Yes, I'll add it now")}
            </label>
            <p className="note">{t("You can add more any time.")}</p>
          </fieldset>
        </div>
      )}
    </div>
  );

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
          {showForm && (
            <div className="provider-meter-sticky">
              <CompletenessMeter c={meter} />
            </div>
          )}
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
            organizationOnly={!showForm}
          />
          {canSend && (
          <>
          <UpkeepEditor value={sub.upkeep ?? emptyUpkeep()} onChange={(upkeep) => setSub({ ...sub, upkeep })} />
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
                <PhoneInput value={contactPhone} onChange={setContactPhone} />
              </Field>
            </div>
          </section>
          {needsBot && <BotCheck onToken={setBotToken} resetKey={botRound} />}
          <div className="provider-actions">
            <button className="btn" onClick={() => void save()} disabled={busy || (needsBot && !botToken)}>
              {t("Save draft")}
            </button>
            <button className="btn btn-primary" onClick={send} disabled={busy || meter.missing_core.length > 0 || needsSource || (needsBot && !botToken)}>
              {req?.status === "changes_requested" ? t("Send again for review") : t("Send for review")}
            </button>
          </div>
          {meter.missing_core.length > 0 ? (
            <p className="note">{t("Still needed: {{items}}", { items: meter.missing_core.map((k) => t(ITEM_LABELS[k] ?? k)).join(", ") })}</p>
          ) : needsSource ? (
            <p className="note">{t("Still needed: {{items}}", { items: sub.upkeep?.mode === "website" ? t("Pages we should read") : t("Where is your feed, or its instructions?") })}</p>
          ) : needsBot && !botToken ? (
            <p className="note">{t("Last step: tick the box above to show you're a person.")}</p>
          ) : null}
          <p className="note">{t("Nothing is public until we approve it.")}</p>
          </>
          )}
        </>
      ) : (
        <p>
          <Link to="/localz/providers/portal">{t("Back to your listings")}</Link>
        </p>
      )}
    </div>
  );
}
