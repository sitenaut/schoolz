import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { SeoHead } from "../../../components/SeoHead";
import { ClosureNote } from "../ClosureNote";
import { Field } from "../../../components/ui/Field";
import { useToast } from "../../../components/ui/Toast";
import { useAuth } from "../../../context/AuthContext";
import { usePrerenderReady } from "../../../lib/prerenderReady";
import {
  type AddressKind,
  type CostKind,
  type Hours,
  ITEM_LABELS,
  type MyListing,
  type ProgramPlace,
  type ProviderDate,
  type ProviderType,
  type Signup,
  type WaysToHelp,
  deleteDate,
  emptyHours,
  emptyPlace,
  emptySignup,
  emptyWaysToHelp,
  fetchDates,
  postDate,
  fetchMyListings,
  fetchProviderTypes,
  updateListing,
} from "../../../lib/providerPortal";
import { SignInPrompt } from "./ProviderPortalPage";
import { AddressFields, type AddressValue, DeliverySelect, HoursEditor, PlaceFields, SignupEditor, TypeSelect, WaysToHelpEditor } from "./ProviderFields";
import { LOCALE } from "../../../lib/i18n";

const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const tomorrow = () => {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};

const counties = (areas: string[]) => areas.map((a) => a.replace(/ County, NJ$/, "")).filter((a) => !a.includes(","));

/** What a changed column is called on screen. */
const FIELD_LABELS: Record<string, string> = {
  ...ITEM_LABELS,
  name: "Program name",
  organization_name: "Organization name",
  phone: "Phone",
  website: "Website",
  email: "Email",
  fees: "Cost",
  cost_kind: "Cost",
  taxonomy_codes: "Kind of help",
  taxonomy_names: "Kind of help",
  address_kind: "Address",
  address: "Address",
  city: "Address",
  postal_code: "Address",
  service_areas: "Counties you serve",
  private_address: "Address",
  latitude: "Address",
  longitude: "Address",
  alert: "Alert",
  description: "Description",
  languages: "Languages spoken",
  required_documents: "What to bring",
  eligibility_text: "Who can come",
  hours: "Hours",
  hours_text: "Hours",
  week_hours: "This week's hours",
  closure_starts_on: "Closure",
  closure_ends_on: "Closure",
  closure_note: "Closure",
  signup: "How people join",
  delivery: "In person or online",
  location_name: "Name of the place",
  ways_to_help: "How people can help you",
};

function Card({ title, children, hint }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="card provider-quick">
      <h3>{title}</h3>
      {hint && <p className="note">{hint}</p>}
      {children}
    </section>
  );
}

/** /localz/providers/listings/:id - quick updates, the portal's main screen.
 * For a verified member these publish at once; changes to who you are and
 * how to reach you wait for a reviewer while the old details stay up. */
export function ProviderListingPage() {
  const { serviceId } = useParams();
  const { user, loading } = useAuth();
  const { t } = useTranslation();
  usePrerenderReady(!loading);
  if (loading) return <p className="note">{t("Loading…")}</p>;
  if (!user) return <SignInPrompt next={`/localz/providers/listings/${serviceId ?? ""}`} />;
  return <QuickUpdates key={serviceId} serviceId={serviceId ?? ""} />;
}

function QuickUpdates({ serviceId }: { serviceId: string }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [listing, setListing] = useState<MyListing | null | undefined>(undefined);
  const [types, setTypes] = useState<ProviderType[]>([]);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    fetchMyListings()
      .then((rows) => setListing(rows.find((r) => r.id === serviceId) ?? null))
      .catch(() => setListing(null));
  }, [serviceId]);
  useEffect(() => {
    load();
    fetchProviderTypes().then(setTypes).catch(() => setTypes([]));
  }, [load]);

  if (listing === undefined) return <p className="note">{t("Loading…")}</p>;
  if (listing === null)
    return (
      <p className="note">
        {t("This listing isn't one you manage.")} <Link to="/localz/providers/portal">{t("Your listings")}</Link>
      </p>
    );

  const send = async (body: Record<string, unknown>) => {
    setBusy(true);
    try {
      const res = await updateListing(listing.id, body);
      const labels = (fields: string[]) => [...new Set(fields.map((f) => t(FIELD_LABELS[f] ?? f)))].join(", ");
      if (res.applied.length) toast({ title: t("Published"), description: labels(res.applied), tone: "ok" });
      if (res.held.length) toast({ title: t("Sent for review"), description: t("The current details stay up until we've checked: {{fields}}", { fields: labels(res.held) }), tone: "info" });
      if (!res.applied.length && !res.held.length) toast({ title: t("Nothing changed"), tone: "info" });
      load();
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : t("Couldn't save - please try again."), tone: "bad" });
    } finally {
      setBusy(false);
    }
  };

  const closedToday = !!listing.closure && listing.closure.starts_on <= today() && listing.closure.ends_on >= today();

  return (
    <div className="provider-page">
      <SeoHead title={t("Your listing · Localz")} description={t("Update your Localz listing.")} path="/localz/providers/portal" />
      <Link className="localz-back-link" to="/localz/providers/portal">
        {t("Your listings")}
      </Link>
      <h2 className="localz-title">{listing.name}</h2>
      {listing.organization_name && listing.organization_name !== listing.name && <div className="localz-card-org">{listing.organization_name}</div>}
      <p>
        <Link to={`/localz/r/${listing.id}`}>{t("See the public listing")}</Link>
      </p>
      {!listing.verified && <p className="localz-alert">{t("Until we've confirmed it's you by phone, every change waits for review. We'll call the number on the listing.")}</p>}
      {listing.pending_changes.length > 0 && (
        <p className="note">
          {t("Waiting for review: {{fields}}", {
            fields: [...new Set(listing.pending_changes.flatMap((p) => p.fields).map((f) => t(FIELD_LABELS[f] ?? f)))].join(", "),
          })}
        </p>
      )}

      <div className="provider-quick-row">
        <button className={`btn ${closedToday ? "" : "btn-primary"}`} disabled={busy} onClick={() => send({ closed_today: !closedToday })}>
          {closedToday ? t("We're open again today") : t("Closed today")}
        </button>
      </div>
      {listing.closure && !closedToday && <ClosureNote closure={listing.closure} />}

      <ClosureCard listing={listing} busy={busy} send={send} />
      <AlertCard listing={listing} busy={busy} send={send} />
      <JoiningCard listing={listing} busy={busy} send={send} />
      <DatesCard listing={listing} />
      <WeekHoursCard listing={listing} busy={busy} send={send} />
      <DetailsCard listing={listing} busy={busy} send={send} />
      <HelpCard listing={listing} busy={busy} send={send} />
      <ReviewedCard listing={listing} types={types} busy={busy} send={send} />
    </div>
  );
}

type CardProps = { listing: MyListing; busy: boolean; send: (body: Record<string, unknown>) => Promise<void> };

function ClosureCard({ listing, busy, send }: CardProps) {
  const { t } = useTranslation();
  const [from, setFrom] = useState(listing.closure?.starts_on ?? today());
  const [to, setTo] = useState(listing.closure?.ends_on ?? today());
  const [note, setNote] = useState(listing.closure?.note ?? "");
  return (
    <Card title={t("Temporary closure")} hint={t("For a holiday, repairs or bad weather. It shows on your listing until the last day.")}>
      <div className="fgrid two">
        <Field label={t("First day closed")}>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
        </Field>
        <Field label={t("Last day closed")}>
          <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
        </Field>
      </div>
      <Field label={t("Note")} hint={t("Optional - for example \"Closed for the holiday\".")}>
        <input value={note} maxLength={300} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="provider-actions">
        <button className="btn btn-primary" disabled={busy || !from || !to} onClick={() => send({ closure: { starts_on: from, ends_on: to, note: note || null } })}>
          {t("Post closure")}
        </button>
        {listing.closure && (
          <button className="btn ghost" disabled={busy} onClick={() => send({ closure: null })}>
            {t("Remove closure")}
          </button>
        )}
      </div>
    </Card>
  );
}

function AlertCard({ listing, busy, send }: CardProps) {
  const { t } = useTranslation();
  const [alert, setAlert] = useState(listing.alert ?? "");
  return (
    <Card title={t("Service alert")} hint={t("A short note at the top of your listing, like \"Out of produce this week\".")}>
      <Field label={t("Alert")}>
        <input value={alert} maxLength={300} onChange={(e) => setAlert(e.target.value)} />
      </Field>
      <div className="provider-actions">
        <button className="btn btn-primary" disabled={busy || !alert.trim()} onClick={() => send({ alert: alert.trim() })}>
          {t("Post alert")}
        </button>
        {listing.alert && (
          <button
            className="btn ghost"
            disabled={busy}
            onClick={() => {
              setAlert("");
              void send({ alert: null });
            }}
          >
            {t("Remove alert")}
          </button>
        )}
      </div>
    </Card>
  );
}

function JoiningCard({ listing, busy, send }: CardProps) {
  const { t } = useTranslation();
  const [signup, setSignup] = useState<Signup>(listing.signup ?? emptySignup());
  const [delivery, setDelivery] = useState(listing.delivery);
  return (
    <Card title={t("How people join")} hint={t("Open sign-ups, start a waiting list, or close them until a date.")}>
      <SignupEditor idPrefix="listing" value={signup} onChange={setSignup} />
      <DeliverySelect value={delivery} onChange={setDelivery} />
      <button
        className="btn btn-primary"
        disabled={busy}
        onClick={() => send({ signup: signup.status ? { ...signup, opens_on: signup.status === "closed" ? signup.opens_on : null } : null, delivery })}
      >
        {t("Save")}
      </button>
    </Card>
  );
}

const when = (d: ProviderDate) => {
  const start = new Date(d.start_time);
  // Always New Jersey time: it's where the event is, whatever the phone says.
  const day = start.toLocaleDateString(LOCALE, { weekday: "short", month: "short", day: "numeric", timeZone: "America/New_York" });
  const time = (x: Date) => x.toLocaleTimeString(LOCALE, { hour: "numeric", minute: "2-digit", timeZone: "America/New_York" });
  return `${day}, ${time(start)}${d.end_time ? `–${time(new Date(d.end_time))}` : ""}`;
};

/** "Post a date": a one-time event on the listing and the /local calendar. */
function DatesCard({ listing }: { listing: MyListing }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [dates, setDates] = useState<ProviderDate[] | null>(null);
  const [title, setTitle] = useState("");
  const [on, setOn] = useState(tomorrow());
  const [start, setStart] = useState("10:00");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState("");
  const [place, setPlace] = useState<ProgramPlace | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(() => {
    fetchDates(listing.id).then(setDates).catch(() => setDates([]));
  }, [listing.id]);
  useEffect(load, [load]);
  if (listing.address_kind === "confidential") return null;

  const post = async () => {
    setBusy(true);
    try {
      await postDate(listing.id, { title: title.trim(), on, start, end: end || null, note: note.trim() || null, place: place?.address ? place : null });
      toast({ title: t("Posted"), description: title.trim(), tone: "ok" });
      setTitle("");
      setNote("");
      load();
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : t("Couldn't save - please try again."), tone: "bad" });
    } finally {
      setBusy(false);
    }
  };
  const remove = async (d: ProviderDate) => {
    try {
      await deleteDate(listing.id, d.id);
      load();
    } catch (err) {
      toast({ title: err instanceof Error ? err.message : t("Couldn't save - please try again."), tone: "bad" });
    }
  };

  return (
    <Card title={t("Post a date")} hint={t("A one-time event, like a free screening day or a community meeting. It shows on your listing and on the local events calendar.")}>
      {!listing.verified ? (
        <p className="note">{t("Once we've confirmed it's you by phone, you can post dates.")}</p>
      ) : (
        <>
          <Field label={t("What's happening")}>
            <input value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />
          </Field>
          <div className="fgrid two">
            <Field label={t("Date")}>
              <input type="date" value={on} min={today()} onChange={(e) => setOn(e.target.value)} />
            </Field>
            <Field label={t("Starts")}>
              <input type="time" value={start} onChange={(e) => setStart(e.target.value)} />
            </Field>
            <Field label={t("Ends")} hint={t("Optional")}>
              <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} />
            </Field>
          </div>
          <Field label={t("Note")} hint={t("Optional - what to bring, who it's for.")}>
            <input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} />
          </Field>
          <label className={`check ${place ? "on" : ""}`}>
            <input type="checkbox" checked={!!place} onChange={(e) => setPlace(e.target.checked ? emptyPlace() : null)} />
            <span>{t("It's somewhere else")}</span>
          </label>
          {place && <PlaceFields value={place} onChange={setPlace} />}
          <button className="btn btn-primary" disabled={busy || title.trim().length < 3 || !on || !start} onClick={post}>
            {t("Post date")}
          </button>
        </>
      )}
      {dates && dates.length > 0 && (
        <ul className="provider-dates">
          {dates.map((d) => (
            <li key={d.id}>
              <span>
                <strong>{d.title}</strong> · {when(d)}
                {d.venue_name ? ` · ${d.venue_name}` : ""}
              </span>
              <button type="button" className="btn ghost" onClick={() => remove(d)}>
                {t("Remove")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function HelpCard({ listing, busy, send }: CardProps) {
  const { t } = useTranslation();
  const [ways, setWays] = useState<WaysToHelp>(listing.ways_to_help ?? emptyWaysToHelp());
  const clean = (w: WaysToHelp) => ({
    ...w,
    volunteer_roles: w.volunteer_roles.map((x) => x.trim()).filter(Boolean),
    donations: w.donations.map((x) => x.trim()).filter(Boolean),
    wishlist_url: (w.wishlist_url ?? "").trim() || null,
  });
  return (
    <Card title={t("How people can help you")} hint={t("Volunteers and things to donate show at once; a new wish-list link is checked first.")}>
      <WaysToHelpEditor value={ways} onChange={setWays} />
      <button className="btn btn-primary" disabled={busy} onClick={() => send({ ways_to_help: clean(ways) })}>
        {t("Save")}
      </button>
    </Card>
  );
}

function WeekHoursCard({ listing, busy, send }: CardProps) {
  const { t } = useTranslation();
  const [hours, setHours] = useState<Hours>(listing.week_hours?.hours ?? listing.hours ?? emptyHours());
  const [regular, setRegular] = useState<Hours>(listing.hours ?? emptyHours());
  return (
    <>
      <Card title={t("This week's hours")} hint={t("Different hours this week only. Next week your regular hours come back on their own.")}>
        {listing.week_hours?.text && <p>{t("Posted: {{hours}}", { hours: listing.week_hours.text })}</p>}
        <HoursEditor idPrefix="week" value={hours} onChange={setHours} />
        <div className="provider-actions">
          <button className="btn btn-primary" disabled={busy || !hours.mode} onClick={() => send({ week_hours: hours })}>
            {t("Post this week's hours")}
          </button>
          {listing.week_hours && (
            <button className="btn ghost" disabled={busy} onClick={() => send({ week_hours: null })}>
              {t("Back to regular hours")}
            </button>
          )}
        </div>
      </Card>
      <Card title={t("Regular hours")}>
        {listing.hours_text && <p className="note">{listing.hours_text}</p>}
        <HoursEditor idPrefix="regular" value={regular} onChange={setRegular} />
        <button className="btn btn-primary" disabled={busy || !regular.mode} onClick={() => send({ hours: regular })}>
          {t("Save regular hours")}
        </button>
      </Card>
    </>
  );
}

function DetailsCard({ listing, busy, send }: CardProps) {
  const { t } = useTranslation();
  const [description, setDescription] = useState(listing.description ?? "");
  const [languages, setLanguages] = useState(listing.languages.join(", "));
  const [documents, setDocuments] = useState(listing.required_documents.join("\n"));
  const [eligibility, setEligibility] = useState(listing.eligibility_text ?? "");
  const list = (v: string) =>
    v
      .split(/\n|,/)
      .map((x) => x.trim())
      .filter(Boolean);
  return (
    <Card title={t("About your program")}>
      <Field label={t("Description")}>
        <textarea rows={2} maxLength={500} value={description} onChange={(e) => setDescription(e.target.value)} />
      </Field>
      <Field label={t("Who can come")}>
        <input value={eligibility} maxLength={500} onChange={(e) => setEligibility(e.target.value)} />
      </Field>
      <Field label={t("Languages spoken")} hint={t("Separate with commas.")}>
        <input value={languages} onChange={(e) => setLanguages(e.target.value)} />
      </Field>
      <Field label={t("What to bring")} hint={t("One per line, for example \"Photo ID\".")}>
        <textarea rows={2} value={documents} onChange={(e) => setDocuments(e.target.value)} />
      </Field>
      <button
        className="btn btn-primary"
        disabled={busy}
        onClick={() => send({ description, eligibility_note: eligibility, languages: list(languages), documents: list(documents) })}
      >
        {t("Save")}
      </button>
    </Card>
  );
}

function ReviewedCard({ listing, types, busy, send }: CardProps & { types: ProviderType[] }) {
  const { t } = useTranslation();
  const [name, setName] = useState(listing.name);
  const [org, setOrg] = useState(listing.organization_name ?? "");
  const [phone, setPhone] = useState(listing.phone ?? "");
  const [website, setWebsite] = useState(listing.website ?? "");
  const [email, setEmail] = useState(listing.email ?? "");
  const [costKind, setCostKind] = useState<CostKind | "">(listing.cost_kind ?? "");
  const [amount, setAmount] = useState(listing.fees && listing.cost_kind !== "free" ? listing.fees.replace(/^(Fee|Sliding scale):?\s*/, "") : "");
  const [kinds, setKinds] = useState<string[]>(listing.types.length ? listing.types : [""]);
  const [address, setAddress] = useState<AddressValue>({
    kind: listing.address_kind,
    address: listing.address,
    city: listing.city,
    postal_code: listing.postal_code,
    counties: counties(listing.service_areas),
  });
  const [privateAddress, setPrivateAddress] = useState("");
  const [placeName, setPlaceName] = useState(listing.location_name ?? "");

  const submit = () => {
    const body: Record<string, unknown> = {};
    if (name.trim() !== listing.name) body.name = name;
    if (org.trim() !== (listing.organization_name ?? "")) body.organization_name = org;
    if (phone.trim() !== (listing.phone ?? "")) body.phone = phone;
    if (website.trim() !== (listing.website ?? "")) body.website = website || null;
    if (email.trim() !== (listing.email ?? "")) body.email = email || null;
    if (costKind && (costKind !== listing.cost_kind || costKind !== "free")) body.cost = { kind: costKind, amount: amount || null };
    const picked = kinds.filter(Boolean);
    if (picked.length && picked.join() !== listing.types.join()) body.types = picked;
    const addressChanged =
      address.kind !== listing.address_kind ||
      (address.address ?? "") !== (listing.address ?? "") ||
      (address.city ?? "") !== (listing.city ?? "") ||
      (address.postal_code ?? "") !== (listing.postal_code ?? "") ||
      address.counties.join() !== counties(listing.service_areas).join() ||
      (address.kind === "public" && placeName.trim() !== (listing.location_name ?? "")) ||
      !!privateAddress.trim();
    if (address.kind && addressChanged)
      body.address = {
        ...address,
        kind: address.kind as AddressKind,
        private_address: privateAddress.trim() || null,
        ...(address.kind === "public" ? { place_name: placeName.trim() || null } : {}),
      };
    void send(body).then(() => setPrivateAddress(""));
  };

  return (
    <Card title={t("Details we check first")} hint={t("Changes here go live after a reviewer checks them. Your current details stay up until then.")}>
      <div className="fgrid two">
        <Field label={t("Program name")}>
          <input value={name} maxLength={200} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label={t("Organization name")}>
          <input value={org} maxLength={200} onChange={(e) => setOrg(e.target.value)} />
        </Field>
        <Field label={t("Phone")}>
          <input type="tel" value={phone} maxLength={40} onChange={(e) => setPhone(e.target.value)} />
        </Field>
        <Field label={t("Website")}>
          <input type="url" value={website} maxLength={300} onChange={(e) => setWebsite(e.target.value)} />
        </Field>
        <Field label={t("Public email")}>
          <input type="email" value={email} maxLength={255} onChange={(e) => setEmail(e.target.value)} />
        </Field>
        <Field label={t("Cost")}>
          <select value={costKind} onChange={(e) => setCostKind(e.target.value as CostKind)}>
            <option value="" disabled>
              {t("Pick one")}
            </option>
            <option value="free">{t("Free")}</option>
            <option value="sliding">{t("Sliding scale")}</option>
            <option value="fee">{t("There's a fee")}</option>
          </select>
        </Field>
        {costKind && costKind !== "free" && (
          <Field label={t("How much?")}>
            <input value={amount} maxLength={100} onChange={(e) => setAmount(e.target.value)} />
          </Field>
        )}
      </div>
      {kinds.map((k, i) => (
        <TypeSelect key={i} types={types} label={t("Kind of help")} value={k || null} onChange={(v) => setKinds(kinds.map((x, j) => (j === i ? v : x)))} />
      ))}
      {kinds.length < 5 && (
        <button type="button" className="btn ghost" onClick={() => setKinds([...kinds, ""])}>
          {t("Add another kind of help")}
        </button>
      )}
      <h4>{t("Address")}</h4>
      <AddressFields
        idPrefix="listing"
        value={address}
        onChange={setAddress}
        privateAddress={privateAddress}
        onPrivateAddress={setPrivateAddress}
        hasPrivateAddress={listing.address_kind !== null && listing.address_kind !== "public"}
      />
      {address.kind === "public" && (
        <Field label={t("Name of the place")} hint={t("Optional - for example \"Church hall, lower level\".")}>
          <input value={placeName} maxLength={200} onChange={(e) => setPlaceName(e.target.value)} />
        </Field>
      )}
      <button className="btn btn-primary" disabled={busy} onClick={submit}>
        {t("Send for review")}
      </button>
    </Card>
  );
}
