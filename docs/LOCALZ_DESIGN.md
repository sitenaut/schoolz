# Localz — community resources for families in need (design)

Partly built: NJ 211 and ChildCareNJ sources, public search, and the
on-device eligibility check; the rest is design. Localz is a second "view" alongside
Gradez (`frontend/focus/`): a lightweight app that helps people in South
Jersey find food, housing, utility, health and family help without asking in
public and without fighting state websites. Resources are ingested and kept
fresh by scheduled jobs, the same way `/local` events are
(`backend/local_events/`, `docs/LOCAL_EVENTS_SOURCES.md`).

## Principles (these are rules, not styling)

1. **Nothing is required.** Search and chat work with no account and no
   questions answered. The eligibility check and the saved profile are
   offered, never gated.
2. **The server learns as little as it can.** The anonymous eligibility
   check runs in the browser; the server never receives the answers. A saved
   profile is encrypted, keyed to one person, and readable by no admin
   screen.
3. **Unknown is not "no".** A resource whose eligibility we couldn't
   structure is shown as "check requirements", never hidden by a filter.
   Same rule as `late_credit()` returning `None`.
4. **Nothing on screen, in a URL, in an email subject or in browser history
   should reveal a stigmatised need** to someone looking over a shoulder, a
   shared device, or a shared inbox.
5. **Neutral language.** "Save on groceries", "Help with bills",
   "Somewhere safe to stay", never "Emergency assistance for the needy".
6. **Translation from day one** (es/zh/ko/hi, `services/i18n.py`). This
   audience needs it most.

## The journey this is designed around

> I just lost my job. I need food for my kids this week, and I want to start
> getting help with the electric bill before it's a shutoff.

1. They open `schoolz.sitenaut.com/localz/` (or `localz.sitenaut.com`, which
   redirects there; see "Routing").
2. The landing page has three things at most: a search box ("What do you
   need help with?"), three to six large category tiles, and two buttons:
   **What am I eligible for?** and **Ask privately** (the chatbot). A strip
   at the top reads "Need help right now? 211 · 988" and stays there.
3. They tap **What am I eligible for?** About 6 short screens, every one
   skippable (see "Eligibility check"). Answers stay in the browser.
4. Results: **Food today** (pantries open in the next 48 hours near their
   town, sorted by distance and hours) first, then **Programs to apply for**
   (SNAP, WIC, school meals, Summer EBT), then **Bills** (LIHEAP, USF,
   NJ SHARES, PAGE), each with a plain "Likely eligible / May be eligible /
   Check requirements" badge and a one-line reason ("Your household of 4
   is under the income limit of $X/month").
5. Each program card has **How to apply** in steps, **What to bring**
   (documents), hours, phone, and "Last confirmed <date> by <source>".
6. A quiet prompt offers **Save this for later**: on this device only (no
   account), or to an account, which also turns on alerts. The consent
   screen comes before anything is stored.

## Routing and the shell

- **Built as routes in the main app** (`frontend/src/pages/localz/`,
  `/localz`, `/localz/:category`, `/localz/r/:id`, plus `/local` as its
  Events tab), not a separate Vite app like Focus as first planned: Localz
  needs the main app's translations and `/es/` routing, chatbot, auth,
  theme and crawler prerendering, which a second app would have to
  rebuild. `LocalzLayout` adds the Help Now strip and Quick exit (button or
  Esc); `AppShell` swaps the brand and nav when `isLocalzPath()`. **No GA**:
  `initAnalytics` doesn't load gtag when the first page is Localz, and
  AppShell sends no GA hits from Localz pages. RUM collapses
  `/localz/r/<id>` to `/localz/r/:id`. Revisit a separate bundle only if
  page weight on old phones becomes the problem.
- **`localz.sitenaut.com` is a 301 to `schoolz.sitenaut.com/localz/`**, a
  memorable door, not a second origin. Revisit only if Localz needs its own
  brand/domain, and then plan the auth hand-off deliberately.
- **Unlike `/focus/`, `/localz/` is public and should be indexable**: people
  search "food pantry near me". The prerender/crawler branch must cover it,
  with per-category landing pages ("Food help in Cherry Hill").
- **Schoolz nav:** the "Local" item becomes **Localz** and links to
  `/localz/` with a plain `<a>` (same reason as Gradez).
- **Localz nav:** Schoolz (→ `/`, Today) · Events · Food · Housing & Bills ·
  Health · Kids & Family · Money & Work. **Help Now** (211, 988, NJ domestic
  violence hotline, child abuse hotline) is a persistent strip, not a tab.
  Legal help, immigrant services, transportation, seniors/disability and
  veterans start as sub-sections and get promoted if usage justifies it.
- **Events** reuses `GET /local-events` with a new `help` category family
  (food distributions, mobile pantries, free tax prep days, Code Blue
  activations, coat drives). Phase 1 can simply link to `/local?category=help`.
- **Quick exit** button on every page (Esc key too): `location.replace` to a
  neutral site so Back doesn't return. **Document titles stay generic**
  ("Localz", not "Domestic violence help").

## Data model (HSDS-aligned)

The sources that matter most already speak, or nearly speak, the Open
Referral **Human Services Data Specification (HSDS 3.0)**. NJ 211's public
search (Connect 211's platform) serves records with `serviceAtLocationId`,
Inform USA taxonomy codes (e.g. `PH-0700 Benefits Screening`), a GeoJSON
`serviceArea` polygon, `eligibilities`, `requiredDocuments`, `fees`,
`applicationProcess`, `languages`, `hours`, and `lastAssuredOn`. So model
on HSDS rather than inventing a shape, and every adapter maps into it.

**Built so far (migration 0102):** `resource_organizations` and
`resource_services`. `resource_services` flattens HSDS's service ×
location × service-at-location into one row per NJ 211 service-at-location
(their search returns exactly that unit), with `service_areas`,
`taxonomy_codes`, derived `categories` and `missing_core`. Split it into the
fuller shape below when a second source or the provider portal needs a
service at several locations. Pipeline: `backend/resources/`
(`nj211.py` adapter, `refresh.py`, `categories.py`); job
`resources.refresh`; public API `routers/resources.py`
(`GET /resources/categories`, `POST /resources/search`,
`GET /resources/{id}`).

Planned tables (Alembic, additive):

| Table | Purpose |
|---|---|
| `resource_organizations` | HSDS organization: name, alternate names, description, url. |
| `resource_services` | HSDS service: name, description, application process, fees, required documents (json list), languages, `eligibility_text` (verbatim), `category_keys`, `taxonomy_codes`, `status` (active/inactive/seasonal), `last_assured_on`. |
| `resource_locations` | Address, lat/lon (reuse `geocoded_places`), accessibility notes. |
| `resource_service_at_location` | The searchable unit: service × location, hours (structured + text), phone. Service-area-only services (a hotline, a statewide program) have no location and a `service_area` (county list or polygon). |
| `resource_eligibility` | **Structured** criteria per service, one row per criterion (below). |
| `resource_provenance` | Per record: `source`, `source_record_id`, `first_seen_at`, `last_seen_at`, `content_hash`, raw payload (jsonb). Several sources can back one service. |
| `program_rules` | Versioned thresholds for the big programs (SNAP, WIC, NJ FamilyCare tiers, LIHEAP/USF, school meals): `program`, `effective_from/to`, `table` (jsonb, household size → monthly limit, or % FPL), `source_url`, `verified_by`, `verified_at`. |
| `poverty_guidelines` | HHS FPL by year and household size, effective dates. |
| `resource_category_map` | Inform USA taxonomy code prefix → Localz category/sub-category. Data, admin-editable. |

### Eligibility criteria shape

`resource_eligibility(service_id, criterion, operator, value, confidence,
source: "structured"|"extracted"|"admin")`. Criteria vocabulary (closed,
in code like `permissions.py`, so the UI and matcher agree):

- `income_max_fpl_pct` (e.g. 185), or `income_rule` → a `program_rules` row
- `county_in`, `nj_resident`
- `household_has_child_under` (age), `household_has_pregnancy`
- `age_min` / `age_max` (of the person served)
- `household_has_member_60_plus`, `has_disability`, `veteran_or_military_family`
- `recent_job_loss`, `housing_situation_in` (renting, behind on rent,
  shutoff notice, no stable place, staying with others)
- `serves_population` (women, men, LGBTQ+ youth, survivors, …): a
  *service's* audience, matched against an optional self-description (below)
- `immigration_status_not_required` (true when a program is open to
  everyone, e.g. NJ FamilyCare's Cover All Kids, food pantries, 211)
- `insurance_status_in` (uninsured, NJ FamilyCare, …)

Matcher result per service: **likely** (every criterion known and met),
**maybe** (no known criterion failed, some unknown), **not a match** (a
known criterion failed). Not-a-match is collapsed under "Other programs
that might still help", never deleted; thresholds near the line (within
~10%) count as maybe, because the inputs are rough.

Free-text `eligibility_text` is turned into criteria by a Claude extraction
pass (same pattern as `content_extractor.py`: a tool schema, `item.get(...)`
everywhere). Anything extracted lands with `source="extracted"` and a
confidence; low-confidence rows go to an admin review queue. The verbatim
text is always shown on the card, so a wrong extraction is visible.

## Ingestion

A new package `backend/resources/`, deliberately parallel to
`backend/local_events/`: `sources/` adapters, `normalizer.py`,
`deduper.py`, `pipeline.py`, `prune.py`, one scheduled job
`resources.refresh` with params JSON, and **Test fetch** in the admin UI.
Rendering via the shared Playwright droplet like events. Same tripwires
apply and must be written into this package's notes from the start:
`prune.SOURCE_KEYS` lists every `*_sources` key; removing a source deletes
its records (here, mark inactive instead, since a vanished food pantry is
worth a human look); zero results is a WARNING, not success.

### Source types, by data shape

| Shape | Examples | Adapter | Notes |
|---|---|---|---|
| **NJ 211 search site** | `search.nj211.org` | `nj211_sources` (see "NJ 211 adapter") | **Best source by far** (~6,300 curated programs, Inform USA accredited). Scraped politely until there's usage to show them; then approach NJ 211 for a formal feed through the 211 National Data Platform, and swap this adapter for `hsds_sources`. If they say no, stop. |
| **HSDS feed / API** | NJ 211 via the NDP later; any HSDS publisher | `hsds_sources` | Same HSDS mapping as the NJ 211 adapter, so switching is a source change, not a model change. |
| **Licensed directory** | findhelp | `hsds_sources` / CSV | Paid; offers API, CSV and widgets. Fallback if 211 says no. |
| **Federal datasets** | HRSA health center sites (CSV), SAMHSA FindTreatment locator, USDA summer meal sites | `csv_sources`, `json_api_sources` | Public, structured, stable. Map to HSDS. |
| **Child care providers** | ChildCareNJ.gov (state-regulated centers and registered family child care, with Grow NJ Kids ratings) | `childcarenj_sources` | **NJ 211 doesn't list individual daycares**, only the help around them (CCR&R subsidy/referral agencies, Early Head Start). See "ChildCareNJ adapter". data.nj.gov's "Licensed Child Care Centers" (`cru5-4rmm`) is from 2019: not usable. |
| **Food pantry locators** | Food Bank of South Jersey's zip locator, Plentiful directory | `listing_page_sources` / per-platform adapter | Hours change weekly; refresh daily. Check each platform's terms; prefer asking FBSJ for an export. |
| **Static government pages** | DCF Family Success Centers list, county Boards of Social Services, county Code Blue pages, DCA program pages | `page_extract_sources` (render → Claude extraction to HSDS) | Low volume, high value. Store the page hash; only re-extract on change. |
| **Program rules** | SNAP/WIC/NJ FamilyCare income charts, LIHEAP/USF season dates, HHS poverty guidelines | `program_rule_watch` | **Never auto-applied.** The job hashes each source page; a change opens an admin review item ("NJ FamilyCare chart changed") and the admin enters the new table. Wrong thresholds tell people they don't qualify. |
| **Time-bound help** | Mobile pantries, food distributions, VITA tax days, Code Blue activations, toy/coat drives | existing `local_events` pipeline | Events, not resources; tagged `help`, optionally linked to a `resource_service_id`. |

### NJ 211 adapter

Investigated directly against the live site.

- **Permission check.** `robots.txt` allows `/` for all agents except
  named SEO bots, disallows `/api/` and `/admin/`, and sets
  `Crawl-delay: 10`. The search site's legal pages are a privacy policy and
  an accessibility statement only; nj211.org's policy restricts
  "photographs, artwork, and ad designs", not directory content. No
  explicit "no". **Rules this adapter keeps:** never request `/api/`;
  one request at a time, 10 s apart; an honest User-Agent naming schoolz
  with a contact URL (so they can say no to us directly); stop on any 403/429
  and raise a WARNING rather than retrying harder. Re-check robots.txt at
  the start of every run and abort if `/search` becomes disallowed.
- **Platform.** Connect 211's Next.js app. Everything is server-rendered
  into the React Server Components payload (`self.__next_f.push([1,"…"])`
  chunks); plain httpx works, no browser needed. Decode each chunk with
  `json.loads` (it's a JSON string literal; `unicode_escape` mangles UTF-8),
  then `raw_decode` the `"results":[…]` array that precedes
  `"totalResults"`. Normalise `\xa0` to spaces.
- **List pages:** `/search?query=<taxonomy code>&query_type=taxonomy`
  `&location=<label>&coords=<lon>,<lat>&page=<n>`. 25 per page,
  `totalResults` and `currentPage` in the payload. **Taxonomy codes match
  as prefixes**: `query=B` returns every Basic Needs service (BD, BH, BV,
  BM…). **Location means "serves this place", not a radius**: food pantries
  near Cherry Hill were 47 at `distance=10` and 49 at `distance=50`, and 4
  in Cape May. So crawl by *place* (one point per county or large town in
  the area), not by radius.
- **List fields:** `id` (service-at-location UUID), `serviceName`,
  `name`, `locationName`, `description` (HTML), `phone`, `website`,
  `address`, `location` (GeoJSON point), `taxonomies[{code,name}]`,
  `eligibility`, `applicationProcess`, `hours`.
- **Detail page** `/search/<id>` adds what eligibility and freshness
  need: `eligibilities`, `requiredDocuments`, `fees`, `languages`,
  `interpretationServices`, `accessibility`, `transportation`,
  `serviceAreaName` (a newline list of counties, enough without the
  polygon), `serviceArea` (GeoJSON polygon), `lastAssuredOn`,
  `phoneNumbers[]`, `organizationName/Description/Url`, `categories`,
  `alert`/`alertDate`, `originalId`. It also has `contacts`, which can name
  staff: store nothing from it except a role-level phone/email, and never
  display individuals' names.
- **Scope: all 21 counties**, one place per county (its seat), each with a
  `county` that's stored on every service its search lists
  (`listed_in_counties`). That places a service before its detail page is
  fetched, and a service listed for 10+ counties reads as statewide. County
  search ranks services that name the county, then ones listed for only a
  few counties, then statewide, then unplaced.
- **Volume and schedule.** A Cherry Hill crawl of every branch was 99 pages
  and 1,674 services (350 requests with 250 details, no refusals). All 21
  places are ~1,100 list pages, about 3 h at the crawl delay, once every
  `list_every_days`; the starting place rotates daily so an interrupted
  crawl doesn't always miss the same counties. Details are capped per run
  (`max_details_per_run`, 300), so the ~6,000-record statewide backfill
  takes a few weeks of nights. Steady state: a detail fetch only for new
  ids, ids whose listing changed, and a rolling 30-day re-check.
- **Ids that vanish** from every list crawl for two consecutive runs are
  marked inactive, not deleted.
- Runs as its own scheduled job (like the Mt Laurel Y), so its long,
  throttled run never holds the other sources behind it.

### ChildCareNJ adapter

**Built:** `resources/childcarenj.py`, `refresh.refresh_childcarenj`, job
`resources.childcarenj` (weekly, migration 0105). Investigated directly
against the live site.

- **Endpoint:** the search page's own JSON call,
  `GET https://www.childcarenj.gov/Services/GetProviders.aspx`. **It needs
  every parameter the page sends** (`zipcode`, `county`, `programName`,
  `camp/center/home/preschool`, `rating`, `programTypes`, `subsidised`,
  `mccynplus`, `sortKey`, `sortDirection`, `pageSize`, `currentPage`);
  with any missing it 302s to its error page. Returns
  `{"Facilities": [...], "ResultCount": n}`. `pageSize=500`; the biggest
  counties take two pages (26 requests for all 21).
- **Access:** Cloudflare 403s datacenter networks: prod on Fly is refused,
  a home connection gets 200 JSON with our honest `schoolz-localz`
  User-Agent. So the job goes direct first and, on a 403/429, sends the
  rest of the run through `/fetch-raw` on each scraper in turn (ours, the
  droplet, the Pi; `scraper_client.fetch_raw_text_from_any`), which send
  the scrapers' browser User-Agent - the owner's call. Only when every
  route is refused does the run stop. `via_scraper: true` in the job's
  params skips the direct try. The reCAPTCHA on the page is
  commented out in its own JS. There's no robots.txt (the site serves its
  "Uh Oh!" error page).
- **Volume:** 6,214 providers statewide (Oct 2026). `ResultCount` runs a
  few above what's returned (Camden 397 counted, 395 sent; no `Hidden`
  rows) - recorded as `short_counts`, not an error.
- **Types:** centers `PH-1250.1400` Child Care Centers and camps
  `PL-6400.1500-820` Summer Camps (both codes NJ 211 uses); family child
  care, which NJ 211 doesn't list, takes the parent `PH-1250` rather than a
  guessed leaf code. The Type filter matches a code exactly.
- **No coordinates** in the data, so the 20-mile radius needs these
  geocoded (town level for family child care).
- Bump `NORMALIZE_VERSION` when `fields()` changes: unchanged records are
  skipped by hash, so a normalization fix otherwise never reaches them.
- **Fields:** `UniqueProgramID`, `ProgramName`, address parts, city, zip,
  county, phone, email, website, `ProgramLicensedCapacityTotal`,
  `AgesLicensedToServe`, `ProgramFacilityType`, `LicenseType`,
  `LicenseNumber`, `QualityRating`, `LanguagesSpokenByStaff`,
  `YearlySchedule`, **opening/closing time per weekday** (structured hours,
  so the required-core rule is met), tuition per age group
  (hourly/daily/weekly/monthly), `ParticipationInLocalStateOrFederalPrograms`,
  `MealOptions`, `TrainingAndExperienceToSupportSpecialNeeds`,
  `TransportationOptions`, `SpecialSchedules` (evening, overnight,
  weekends, drop-in, emergency, rotating shifts), `DiscountsAvailable`
  (incl. sliding scale), `AdditionalDepositsAndFees`, `MCCYNPlusInd`,
  `Hidden`.
- **Codes** are decoded by a lookup object embedded in the `/Search` page
  (`programTypes`, `LicenseTypes`, `rating`, `language`, `ageGroup`,
  `FederalPrograms`, `SpecialNeeds`, `SpecialSchedules`, `Discounts`, …).
  Copy it into the adapter as a constant and re-check it monthly (a code
  that isn't in the table is a WARNING, not a silent blank). Key ones:
  facility type 1 = licensed center, 2 = registered family child care,
  3 = group care; participation 3 = **accepts state child care assistance
  (CCAP)**, the filter that matters most for Localz (335 of 394 in Camden);
  1 = Head Start; 2 = state preschool.
- **Family child care is someone's home.** The state leaves the street
  address blank for every type-2 provider (all 128 in Camden), and their
  email is often a personal address. Treat these like the portal's
  confidential addresses: show name, town, phone, hours, ages and whether
  they accept CCAP; never the email, never a map pin closer than town
  level.
- Child care maps to the eligibility vocabulary through ages served and
  CCAP; special schedules (overnight, weekends, rotating shifts) are worth
  their own filter for parents who work shifts.

### Freshness and trust

- Every card shows **"Last confirmed <date> by <source>"**. Records past
  12 months unverified show a warning; past 18 months they drop out of
  eligibility results (still searchable).
- **Dedup** across sources on normalized org name + address + phone; the
  higher-trust source wins per field (211 > government page > pantry
  directory > extraction).
- **A changed phone number or URL on an existing record goes to review**
  before it's published (see "Content poisoning").
- A **"Something wrong?"** link on every card feeds the existing
  `community_submissions` review queue.

## Provider portal

Pantries, shelters, clinics and other programs can add and maintain their
own listings at `/localz/providers` ("List your program"). The scrapers
give breadth; the portal gives accuracy on what changes weekly (hours,
closures, what's in stock), which no scraped source keeps current.

### Required core (a listing can't be submitted without it)

| Field | Rule |
|---|---|
| **Organization name** | Required. Matched against existing records ("Is this you?") before a new one is created. |
| **Program/service name** and **what you provide** | At least one service, each with a category picked from the Localz list (mapped to an Inform USA code; free text alone isn't accepted) and a one-line description. |
| **Address** | Required, geocoded and confirmed on a map. Three kinds: **public** (shown); **confidential** (collected and verified, **never published, never sent to the chatbot or search index**: domestic violence shelters, safe houses, youth shelters; the public listing shows a phone/hotline and "Location shared after you call"); **service area only** (mobile pantries, home delivery, hotlines: counties/towns served, plus a mailing address for verification). |
| **Hours** | Structured weekly schedule (day + open/close, several ranges per day), or one explicit choice: 24/7, by appointment, call for hours. "Call for hours" also requires a phone. Seasonal dates optional. Free text is a note *on top of* the schedule, never instead of it. |
| **Phone** | Required: one public number people can call. |
| **Who can come** | Required, but with a one-tap "Open to anyone" option. Otherwise structured choices from the eligibility vocabulary (counties/towns, ages, income, families with children, …) plus a text note. |
| **Cost** | Required: free / sliding scale / fee (with amount). |

Strongly prompted but optional: what to bring (documents), languages
spoken, accessibility, website, email, walk-in vs. appointment, how to
apply. A completeness meter shows what's missing.

**The same rule applies to scraped data.** A record missing a core field
(NJ 211 records sometimes have no hours or only "call") is stored and
searchable but marked incomplete: it isn't shown as "Likely eligible", and
it goes on an outreach list ("invite this provider to claim their
listing").

### Accounts, claiming and verification

- A provider signs in with an ordinary schoolz account (Supabase on
  prod), then creates or **claims** an organization.
  `provider_memberships(user_id, organization_id, role: owner|editor,
  verified_at, verified_by)`; an owner can invite editors (volunteers
  rotate).
- **Verification before anything publishes**, in increasing strength:
  the account's email domain matches the organization's website domain;
  a code sent to the organization's listed phone (SMS or voice) or email
  as already known from NJ 211; or an admin calls the listed number. A
  church pantry with a Gmail address and no website gets the phone call.
- **Claiming a scraped record** links the membership to the existing
  `resource_services` row. From then on, provider-entered fields win over
  scraped ones (`resource_provenance` records which source set each field).
  If NJ 211 later changes a field the provider set, that's flagged for
  review, not silently applied either way.
- New reviewer permissions in `permissions.py`: `resources.view` /
  `resources.manage` (the review queue, verification, merges), held by the
  **Localz reviewer** role. Granting a provider membership is
  `resources.manage`, not super admin.

### Onboarding approval (admins approve every new resource)

No new organization, and no claim of an existing one, goes live without an
admin approving it. Verification proves the person controls the contact
details; approval is a human deciding the resource is real, legitimate and
belongs in Localz.

**Ways a resource asks to be onboarded**, all landing in the same queue:
- **Self-serve:** the provider fills in the portal form and submits.
- **"Ask to be listed"** on `/localz/providers` and the Contact page: a
  short no-account form (organization, contact person, phone, email,
  what you provide, town). It creates a `submitted` request with
  `origin="inquiry"`; an admin either invites the provider to finish it in
  the portal or completes it with them by phone.
- **Admin-assisted:** when a pantry emails or calls, an admin starts the
  request on their behalf (`origin="admin_assisted"`), fills what they
  know, and sends an invite link so the provider can review, complete and
  own the listing. The request still goes through the same approval, by a
  second admin where there's more than one.

**States** (`resource_onboarding_requests.status`):
`draft` → `submitted` → `in_review` → `approved` | `changes_requested` |
`rejected`, plus `withdrawn` by the provider. `changes_requested` returns
to `submitted` when the provider resubmits. Only `approved` creates or
links the `resource_services` rows and the `provider_memberships` row;
before that the submission lives only in the request (a draft, never
public, same as `CommunitySubmissionItem`).

**Review queue** at `/admin/resources/onboarding` (permission
`resources.manage`; viewing `resources.view`), oldest first, with a badge
in `AdminLayout`. Each request shows the submission, the completeness of
the required core, likely duplicates (name/address/phone match against
existing records, including NJ 211), the verification result, and
automated flags: domain mismatch, a phone that matches a different
organization, link shorteners or payment links, a fee on a category that's
normally free, an address outside the service area.

**Reviewer checklist** (each item ticked and recorded before Approve is
enabled):
1. The organization exists: website, NJ 211 listing, IRS nonprofit lookup,
   a church/municipal listing, or a call.
2. The submitter is connected to it (verification passed, or the admin
   confirmed by calling the listed number).
3. Required core is complete and plausible (hours make sense, address
   geocodes to the right place, categories fit the description).
4. Not a duplicate; if it is, **merge** into the existing record instead
   of creating a new one.
5. Confidential-address listings: the address is marked confidential and
   the public view shows no location.

**Admin actions:** Approve · Request changes (a required note, emailed to
the provider, with the fields to fix highlighted in their form) · Reject
(a reason from a short list plus a note; the provider is told politely
and can contact us) · Merge into an existing record · Edit before
approving (logged as the admin's change). Every decision is written to
`resource_change_log` with the reviewer and the checklist answers.

**Provider side:** the portal shows where the request stands ("Submitted
— we usually review within 3 business days"), emails on every decision,
and lets them edit while it's `changes_requested`. While waiting they can
still see and edit their draft; nothing is public.

**Targets:** a request waiting more than 3 business days shows in the
admin overview and pages through the same Grafana path as other
operational alerts. Reviews are counted in the analytics table
(submitted / approved / rejected per week) so the backlog is visible.

### What publishes immediately vs. what waits for review

Mirrors the content-poisoning guard: people in need are targeted by
scammers, and a hijacked provider account is the easiest way in.

- **Immediately (verified providers):** hours, temporary closures
  ("closed today", "closed for the holiday"), service alerts ("out of
  produce this week"), description, languages, documents, eligibility
  note.
- **Held for review** (same admin queue, as a change request rather than
  an onboarding request): organization name, address, phone, website,
  email, cost changing from free to a fee, adding a category, and every
  change from an unverified account. New organizations always go through
  onboarding approval above. The old
  value stays live until approved.
- Every change is kept in `resource_change_log` (who, when, before, after)
  so a bad edit can be reverted in one step.

### Keeping it fresh

- **"Is this still right?"** emails every 90 days with a one-click
  "Yes, still accurate" (sets `last_assured_on`) and an edit link. No
  answer for 180 days → "Not recently confirmed" on the listing; 365 →
  dropped from eligibility results until confirmed.
- **Quick updates** are the main screen of the portal, not buried in a
  form: "Closed today", "Change this week's hours", "Post a distribution"
  (creates a `help` `LocalEvent` tied to the service: mobile pantries,
  turkey giveaways, coat drives).

### Portal safeguards

- `BotCheck` and per-account/per-IP limits on create, like
  `community_submissions`.
- Staff names and personal contact details are collected only for
  verification and never shown publicly. A listing's public contact is a
  role ("Pantry coordinator"), not a person.
- Confidential addresses are encrypted at rest (`EncryptedText`) and
  excluded from every public schema, the chatbot's tools, exports, and
  the search tallies. A test asserts no public endpoint returns one.
- Links are checked against the organization's known domain; shorteners
  and payment links are refused.

## Eligibility check (anonymous)

### What's built (v1): "What am I eligible for?"

A simpler first cut of the flow below, shipped as one sheet rather than
seven screens, because it works as a filter on the lists people are already
browsing:

- **Criteria** live in `resource_eligibility` (migration 0104), one row per
  *distinct* eligibility sentence keyed on its normalized text
  (`resources/eligibility.py:text_key`), not per service and not the
  per-criterion table sketched above: ~1,500 sentences cover ~2,200
  listings, and "Open to the public" is one row. Stock phrases are
  recognized in code; the rest are read by Haiku in batches of 25 at the end
  of each `resources.refresh` run (`max_eligibility_per_run`, scheduler
  Anthropic key). Bump `VERSION` to re-read everything after a prompt change.
  Vocabulary: ages of the person served, ages of a child for family
  programs, `requires` (veteran/military, disability, pregnancy or new baby,
  uninsured, job loss, families with children, low income, homeless),
  `focus` (women, men, LGBTQ+, survivors), `either` (any one group is
  enough), `asks_immigration_status`, and `other` (a referral, a diagnosis).
- **The API** returns each listing's criteria on search and detail
  (`eligibility`, null until read). Answers never go to the server.
- **The sheet** (`pages/localz/FitButton.tsx`, matching in
  `lib/localzFit.ts`): household ages as bands, five "does this apply"
  chips, "services that focus on…", "programs that don't ask about
  immigration status first", and "Remember on this device" (off = session
  storage, which Quick exit clears). **No income question yet**: listings
  rarely state a number, so asking would collect a sensitive answer that
  improves nothing until `program_rules` exist.
- **Labels**: *For you* (a check mark; everything it asks is something you
  said), *Open to everyone*, *Check if you qualify* (income, a referral, or
  anything we can't tell), and for a mismatch no pill at all - just "For:
  ages 60 and up", sorted under "Other programs that might still help".
  Never red, never "not eligible". Focus only ever adds a match. With
  `either`, the right age alone only reaches "check" (the model reads
  "adults with disabilities" as either/or often enough to matter).
- Sorting covers the listings loaded so far; the server's order is kept
  within each label.

Runs entirely in the browser. The flow fetches the rules it needs
(`GET /resources/rules?county=camden`: program rules, poverty guidelines,
and the structured criteria for services in that county, a few hundred KB
gzipped, cacheable, identical for everyone) and evaluates locally.
**The answers never leave the device.** The search API takes only the
non-sensitive parts (category, county or rounded location, text query) and
returns services with their criteria; the browser tags and sorts them.

Screens (each skippable, "Prefer not to say" everywhere, a progress bar,
plain words, no red):

1. **Where** — town or ZIP (picker reuses the schoolz town list). Rounded
   to two decimals like `eventsNear.ts`.
2. **What's going on?** — chips, choose any: Lost a job or hours · Behind
   on rent or mortgage · Shutoff notice · Need food this week · New baby or
   expecting · Need health coverage · Need child care · Not safe at home ·
   Somewhere to stay tonight. ("Not safe at home" and "Somewhere to stay
   tonight" short-circuit to Help Now first, then continue.)
3. **Who do you live with or share money with?** — a count, then ages as
   bands (under 1, 1–4, 5–12, 13–17, 18–59, 60+). Phrased this way on
   purpose: no "head of household", no assumption about who's a parent.
   Covers grandparents raising grandkids, kinship and foster care, adult
   children, roommates, and kids who split time between two homes ("count
   them if they stay with you at least half the time").
4. **Money coming in** — monthly or yearly, a range picker, not an exact
   figure. "Before taxes. Include unemployment and child support. A guess
   is fine." Then: "Has it dropped recently?"
5. **A few things some programs ask about** (all optional): someone
   pregnant · someone 60+ · someone with a disability · veteran or military
   family · health insurance now.
6. **Programs open to everyone** — *not* an immigration question. Wording:
   "Some programs ask about immigration status and many don't. Want to see
   the ones that don't ask first?" A toggle, not a status. **We never ask
   for or store anyone's status.**
7. **Anything else that would help?** (optional) — language; "Show
   services that focus on…" with multi-select including LGBTQ+-affirming,
   women, men, people of any gender, survivors of violence, youth, seniors,
   specific cultural communities, and a free-text "something else".

### On identity, gender and culture

- **Gender is never asked as a demographic.** It's only relevant to which
  shelters or programs serve whom, so it's asked as "services that focus
  on…" (above), with "people of any gender" and self-description options.
  No "sex assigned at birth" question anywhere. No binary assumptions in
  household questions ("people", "adults", "kids", never "mother/father").
- **Sexual orientation, race and ethnicity are never asked.** No program in
  scope determines eligibility by them. People looking for LGBTQ+-affirming
  or culturally specific services get those as **filters**, which a person
  chooses, not demographics we hold.
- **Pronouns** are an optional field on the saved profile, used only to
  address them in emails. Never required, never inferred.
- **Services tagged as affirming** come from source data (Inform USA has
  target-population codes) or admin review, never inferred by the model.
- Copy reviewed by a community partner (a Family Success Center, a 211
  call specialist, an LGBTQ+ youth org) before launch. Spanish copy written
  in the established *usted* register, reviewed by a native speaker, not
  only machine-translated.

## Saved profile ("My services profile")

Two tiers, so "save it" doesn't have to mean "give us your data":

1. **On this device** (no account): stored in `localStorage` under a
   neutral key, auto-expires after 90 days, a visible "Forget this
   device" button. Lost if the browser is cleared, and that's acceptable.
2. **In my account** (schoolz account or a new one): enables re-running
   anywhere and email alerts. Account → **My services profile** section in
   `frontend/src/pages/account/` (next to Family, Notifications, Privacy).

### Consent

- A dedicated consent screen before the first account save, separate from
  signing up for schoolz, in plain language: what's saved, why (matching
  and alerts only), who can see it (only you; not other guardians, not
  schools, not admins), where it's processed, how long it's kept, how to
  delete it (one tap, immediate). Checkbox unticked by default.
- `consent_records(user_id, purpose, policy_version, granted_at,
  withdrawn_at)`: purposes `services_profile` and `services_alerts`
  separately. Changing what's collected bumps `policy_version` and asks
  again.
- Withdrawal deletes the profile immediately (hard delete), not a flag.
- `/privacy` gets a Localz section, and the New Jersey Data Privacy Act's
  "sensitive data" categories (financial information, health, status as
  transgender or non-binary, citizenship/immigration) apply in spirit even
  if schoolz is under its thresholds: opt-in consent, purpose limitation,
  and a written data protection assessment before launch.

### Storage

- `services_profiles(user_id PK, profile EncryptedText, updated_at,
  last_used_at, alerts_enabled, alert_frequency)`. The whole profile is
  **one encrypted JSON blob** using `crypto.py` with its own derived key
  (`derived_key("services_profile")`), so a dump, a pooler leak, or a
  `SELECT *` yields nothing usable, and nothing in it is queryable in SQL
  on purpose.
- **Keyed on `user_id`, never on a `Student` or a household.** A `Student`
  is shared by every linked guardian (CLAUDE.md, "per-account vs
  per-student keying"). A co-parent, including an abusive one, must never
  see or infer another guardian's services profile, matches, or alerts.
  Nothing from it appears in any shared view, `Notification`,
  `guardian_matched` flow, or the chatbot's personal tools for another
  user.
- Inactivity: 12 months without use → email asking to keep it; no answer
  in 30 days → deleted.
- **Backups:** the nightly `pg_dump` (docs/BACKUPS.md) contains the
  encrypted blob. It's still unreadable without `DATA_ENCRYPTION_KEYS`,
  but a deleted profile persists in old backups until they rotate out,
  and `/privacy` must say so with the retention period.

### Alerts

- A scheduled job (`resources.alerts`) decrypts each opted-in profile in
  memory, runs the same matcher against services first seen since the last
  run, and sends a digest (weekly by default, daily optional).
- **The backend has no outbound email today** (Supabase sends auth mail).
  This needs a transactional provider (Postmark, Resend, or SES) with
  open/click tracking **off**, and a 1Password secret.
- **Email content is deliberately generic**: subject "New on schoolz this
  week", sender "schoolz". The body says "There are 3 new programs that
  may fit your saved profile — sign in to see them" and lists no program
  names. A shared inbox or a lock-screen preview reveals nothing. People
  can opt in to have program names included (a separate consent purpose,
  `services_alerts_named`, off by default); the subject stays generic
  either way.

## Search analytics (anonymous)

Goal: know what people need (which categories, which filters, what words
they type, which counties) without being able to tie any of it to a person
or reconstruct one person's session.

- **New table `resource_search_tallies(day, dimension, value, county,
  count)`**, upserted the way `page_visits` is: an allowlist of
  dimensions (`category`, `filter:<key>`, `query_term`, `eligibility_run`,
  `result_click_category`, `zero_results_category`), no user id, no
  session id, no IP, no timestamp finer than a day, county never ZIP.
- **Marginals, not combinations.** Each filter is counted on its own.
  "Camden County + pregnant + under 130% FPL + LGBTQ+-affirming" stored
  together is a fingerprint; stored as four separate counts it isn't.
  Eligibility-check answers themselves are **never** sent (they never
  leave the browser); only "an eligibility check was completed in
  <county>" is counted.
- **Free-text queries are scrubbed before storage**: drop anything with
  an email, a phone number, a run of 3+ digits, a street-address pattern,
  or a capitalized name pair; lowercase; strip to known words. Then a
  **k-threshold**: a term is only shown in dashboards once it has appeared
  ≥5 times in a week; rarer terms count toward their mapped category
  (keyword → taxonomy map) and the text is discarded at the weekly rollup.
- **Zero-result searches** are the most useful signal (the gaps in what we
  offer): tally them by mapped category.
- Searches go in **POST bodies**, never URL query strings, so they never
  reach nginx/Fly access logs, Faro RUM, browser history, or a shared
  link. (Same reasoning as `POST /local-events/place`.) Category pages can
  have URLs; free text can't.
- Rate-limited per IP in memory (not stored) so a script can't pollute the
  tallies.
- Grafana panel off this table; no GA in Localz at all.

## Chatbot

- New public MCP tools: `search_resources(category, county, query)` and
  `get_resource(id)`, and an eligibility explainer that applies
  `program_rules` to numbers the user gives *in the conversation*. Nothing
  from chat writes to the profile.
- `_log_tool_call` logs tool inputs to Loki verbatim today. For Localz
  tools, **log only the category and county**, never the free text (it's
  where people write "my husband hits me").
- Chat goes to Anthropic. Say so in the chat panel ("Chats are processed
  by our AI provider and not saved by us"). Check that the account's data
  retention terms are acceptable for this content before launch; signed-in
  Localz chats should use the same provider setting as signed-in schoolz
  chats (children's data), not the anonymous one.
- The chatbot's prompt must route crisis disclosures to Help Now (988,
  211, DV hotline) before anything else, and must not ask follow-up
  questions about immigration status.

## Where breaches could happen, and the guard for each

| # | Surface | What could leak | Guard |
|---|---|---|---|
| 1 | **Database dump, backup, or pooler credential leak** | Saved profiles | Field-level encryption with a purpose-derived key held outside the DB (`crypto.py`); `ENCRYPTION_REQUIRE=1` before launch; backups are already age-encrypted; profile is one opaque blob, not columns. |
| 2 | **Account takeover** (reused password, phished Google account) | One person's profile and matches | Supabase auth; encourage the optional authenticator app for accounts with a saved profile; email on profile change ("Your saved info was updated"); short session for the profile page; no export of the raw profile except to the signed-in owner. |
| 3 | **Co-parent / household abuser** | That someone is seeking help, DV-related searches | `user_id` keying (never `Student`); nothing in shared views or notifications; generic email subjects; quick exit; no URLs with search text; device-only save is clearable; account setting "hide Localz from my menu". |
| 4 | **Shared or seized device** | Browser history, localStorage, open tab titles | POST searches; generic page titles; `location.replace` quick exit; device save opt-in, neutral key name, 90-day expiry. |
| 5 | **Server logs** (Loki, Fly, nginx) | Search text, eligibility answers, profile fields | Nothing sensitive in URLs; chatbot tool logging allowlisted per tool; a backend test that runs the profile/search endpoints and asserts no profile field or query text appears in captured log records; never log request bodies on these routes. |
| 6 | **Third-party scripts** (GA4, Faro RUM) | Page paths, URLs, interactions | No GA in Localz; Faro either off in Localz or limited to errors with `scrubUrl`; no session replay ever. |
| 7 | **AI providers** (chat, extraction, translation) | Free-text disclosures in chat | Extraction/translation only see public resource content; chat disclosure in the UI; provider retention checked; no profile data sent unless the signed-in user asks about their own matches. |
| 8 | **Email provider** | Who is receiving help alerts | Generic content, tracking off, minimal data to provider (address + generic body). |
| 9 | **Insider / admin / API keys** | Profiles | No endpoint returns another user's profile; no permission key in `permissions.py` grants it (so no role or API key can ever have it); the Data Audit portal excludes these tables; super admins see only counts ("N saved profiles"). |
| 10 | **Analytics re-identification** | A person's needs pieced together from tallies | Marginals only, county not ZIP, day granularity, scrubbed text with k≥5, no session ids. |
| 11 | **Content poisoning** (a scraped page or a submission with a scam phone number or link; prompt injection into the extraction or chat model) | Not a data leak but the same harm: vulnerable people sent to scammers | Source allowlist; changed phone/URL on an existing record held for review; new organizations from low-trust sources held for review; link domains checked against the org's known domain; never list services that charge up-front "application fees"; extraction output validated against the tool schema; "Something wrong?" report link. |
| 12 | **Legal demands** (subpoena, immigration enforcement request) | Whatever we hold | Data minimisation is the real defence: immigration status is never collected; profiles are deletable instantly; no search logs tied to people. Publish a short transparency note; have counsel review before launch. |
| 14 | **Provider portal** (hijacked or fake provider account; confidential shelter address exposure) | Scam listings; a survivor's shelter location | Verification before publishing; contact/address/phone changes held for review; change log with one-step revert; confidential addresses encrypted and excluded from every public schema, tool and export, enforced by a test. |
| 13 | **Shared students' data model** | Cross-guardian inference via schools/kids | Services profile never reads from or writes to `Student`, `GuardianStudentLink`, or `Notification`; enforced by a test. |

## Build order

0. **Before code:** draft the `/privacy` Localz section and the data
   protection assessment; pick an email provider. (NJ 211 outreach waits
   until there's usage to show.)
1. **Shell + public search:** `frontend/localz/` app, nav swap, category
   pages, Help Now strip, quick exit. `backend/resources/` with the
   **NJ 211 adapter first**, then `page_extract_sources` and `csv_sources`
   (Family Success Centers, county boards, HRSA sites, a curated list of ~30
   statewide programs entered by an admin). Search tallies. Translation.
1b. **Provider portal:** required core, claim + verification, the admin
   onboarding approval queue and change-review queue, quick updates, the 90-day confirmation email (needs the email
   provider from step 0).
2. **Eligibility check:** `program_rules`, `poverty_guidelines`, the
   criteria vocabulary, extraction + review queue, the in-browser matcher.
3. **Device save**, then **account profile** with consent records,
   encryption, the account section, deletion and expiry.
4. **Alerts** (email provider) and **chatbot tools**.
5. **Approach NJ 211** with usage numbers for a formal feed (HSDS via the
   National Data Platform); switch `nj211_sources` to `hsds_sources`.

## Owner decisions

- **Brand:** everyone calls it Localz. It stays at
  `schoolz.sitenaut.com/localz/` for months to come; its own site comes
  eventually, and the auth hand-off is planned then, not now.
- **Service area: 20 miles from the visitor's chosen location.** The radius
  is measured on the device (the point never leaves it, same as the
  county), so the server keeps receiving only a county; listings need
  coordinates for this, which ChildCareNJ records don't carry yet.
- **Reviewer role: "Localz reviewer"**, a `Role` holding `resources.view`
  and `resources.manage` (onboarding approvals, change review,
  verification, merges). Added to `permissions.py` with the first admin
  endpoint that checks it - the provider portal - not before.
- **Alert emails** stay generic by default; a separate opt-in (its own
  consent purpose, `services_alerts_named`) includes program names.

## Open questions for the owner

- Who reviews copy and categories from the community side before launch?
