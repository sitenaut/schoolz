# Neighborz — neighbors paying each other's utility bills (design)

Backend built (`backend/bills/`, `routers/bills.py`, `routers/admin_bills.py`,
migration 0137, `tests/test_bills.py`); the frontend and the review screen
are next. Neighborz is a section of Localz
(`docs/LOCALZ_DESIGN.md`) where someone behind on a utility bill posts it,
anonymously, and a stranger pays it straight to the utility. It starts with
PSE&G; gas, water, heating and internet companies follow one at a time (see
"Utilities").

It lives inside the main app like the rest of Localz, so it shares accounts,
sign-in, translations and the Localz shell; no second site, no sign-in
hand-off. "Neighborz" is a display name only: code, tables and paths say
`bills`, so renaming it is one string in the frontend.

## Principles (these are rules, not styling)

1. **We never touch money.** A giver pays the utility directly through the
   utility's own guest payment (its website or phone line: account number,
   ZIP code, amount). Nothing on our side takes, holds or forwards a payment:
   no card form, no payouts, no balance. That is what keeps this out of
   money-transmitter licensing. Never add a "pay here" button that does.
2. **Anonymous both ways.** A giver never learns who they helped; a requester
   never learns who paid. A listing shows a chosen avatar, the utility, the
   amount asked, the due date, the county and whether it's a shutoff notice.
   Nothing else, ever.
3. **No text between people.** The only things that cross are the giver's
   "I paid it", the requester's "Paid" or "Not yet", and one emoji from a
   fixed set. No free-text field reaches the other side, including the
   confirmation number: the requester never sees it, because a "confirmation
   number" can carry a message.
4. **The account number is the one secret that has to travel, so it travels
   to one person at a time.** The giver needs it to pay. It is revealed only
   to the one giver holding the bill, only while they hold it, every reveal
   is in the audit log, and it's erased once the bill is closed (see
   "Guards").
5. **Browsing is public; acting needs an account.** Anyone can see the list.
   Posting a bill or saying "I'll pay this" needs a signed-in account.
6. **Localz's rules still apply**: neutral language ("Help with a bill",
   never "needy"), nothing in a URL or page title that reveals a need,
   Quick exit, translation from day one (es/zh/ko/hi), no GA.

## The journeys

**Someone who needs help (the requester):**

1. From Localz's bills category or the Neighborz page: **Get help with a
   bill**. First a short, skippable card: programs that can pay more than one
   bill (USF, LIHEAP, NJ SHARES, PAGE), straight from Localz's listings.
2. Sign in or register.
3. Upload a photo or PDF of the bill. The fields are read from it (see
   "Reading the bill").
4. Check what was read: account number, service ZIP, amount due, due date,
   shutoff notice. Choose how much to ask for: the amount due or less, up to
   the cap.
5. Pick an avatar.
6. Read and tick: "The person who pays will see your account number and ZIP
   code. That's all PSE&G needs. They won't see your name or address." Post.
7. On **My Neighborz**: "Waiting for a neighbor", then "Someone is paying
   this now", then "A neighbor says they paid. Check your PSE&G account: did
   it arrive?" **Paid** or **Not yet**. Then, if they like, one emoji.

**Someone who wants to help (the giver):**

1. Browse the list (public): filter by county; shutoff notices first, then
   by due date.
2. **I'll pay this** (sign-in needed). The bill is held for them for 24
   hours, and the page shows the account number, ZIP, amount, and how to pay
   (the utility's guest-pay link and phone number, step by step).
3. Pay the utility. Back on the page, enter the confirmation number, the
   amount paid and the date. The bill moves to "awaiting confirmation".
4. Or **I can't pay this after all**: it goes straight back on the list, no
   strike.
5. **My Neighborz → Bills I've paid**: date, amount, utility, confirmation
   number, the requester's avatar and emoji, and status. The confirmation
   number and the giver's own bank or card receipt are their record of the
   gift.

Both sides use the same page, `/localz/bills/mine`, so browser history on a
shared device doesn't tell a giver from a requester.

## States

| State | Meaning | Leaves when |
|---|---|---|
| `draft` | Uploaded, fields read, not yet posted | Requester posts (→ `available` or `held`); 24 h pass (deleted with its image) |
| `held` | A check flagged it; a reviewer decides | Approved (→ `available`); rejected (→ `rejected`); 7 days unreviewed (→ `rejected`) |
| `available` | On the public list | Claimed (→ `claimed`); withdrawn; 30 days unclaimed (→ `expired`) |
| `claimed` | A giver is holding it ("interested") | Giver reports paid (→ `reported`); releases it or 24 h pass (→ `available`) |
| `reported` | Giver says paid ("awaiting confirmation") | Requester says Paid (→ `paid`); says Not yet (→ `disputed`); 7 days of silence (→ `paid`) |
| `disputed` | Requester says the money didn't arrive | Reviewer: back on the list (giver gets a strike) or closed as paid |
| `paid` | Done; shows as paid on the list for 7 days, then drops off | — |
| `withdrawn`, `rejected`, `expired` | Closed | — |

A requester can withdraw any time before `reported`. Withdrawing while a
giver holds it tells the giver "This bill isn't needed any more" and closes
their hold, no strike.

Timers are applied when rows are read (a hold past its 24 hours is treated
as released at once) and made permanent by an hourly `bills.sweep` job, which
also records strikes, auto-confirms, erases account numbers and sends the
email nudges.

## Limits (defaults; the owner sets the numbers)

- **Amount:** at most the amount due on the bill, and at most **$500**. A
  bigger balance lists $500, and the requester can post again after it's
  paid. One giver pays the whole listing; splitting comes later, if ever.
- **Requester:** one open listing at a time.
- **Per utility account** (by fingerprint, across every user): one open
  listing, and one paid listing per **60 days**. Stops one bill being
  posted from several accounts.
- **Giver:** the account is at least **24 hours** old; one bill held at a
  time; can't hold their own bill, or any bill whose account fingerprint
  matches one they've posted. **Two strikes in 90 days** (a hold that ran
  out, or a dispute decided against them) pause holding until a reviewer
  lifts it.
- **Uploads:** 5 a day per account (each one is a model call), 10 MB, image
  or PDF judged from the bytes, as `/upload` does.

## Reading the bill

- **The model only reads; code decides** (the `services/submission_review.py`
  pattern). One vision call with a tool schema: `utility`, `account_number`,
  `service_zip`, `amount_due`, `due_date`, `statement_date`,
  `shutoff_notice`, `residential` (true/false/unknown), `is_utility_bill`,
  as structured output (`bills/reader.py`, Opus with the server-side refusal
  fallback). Every field is read with `.get()`: a schema's "required" isn't
  relied on.
- **Checks in code**, each a named flag: the utility is in the catalog; the
  account number matches that utility's format; the ZIP is in New Jersey
  (`resources/places.zip_county`); an amount due above zero; a due date not
  more than 60 days past; not marked non-residential. A flag holds the bill
  for review; it doesn't refuse it. Something that isn't a bill at all is
  refused with "This doesn't look like a PSE&G bill".
- **The requester confirms every field.** They can lower the amount, never
  raise it above what was read. Changing the account number or ZIP is
  allowed (models misread digits) but holds the bill for review, because a
  wrong digit would send a stranger's money to the wrong account.
- **Paid-for data:** the extraction is stored (encrypted) on the draft, keyed
  by the image's SHA-256 for that requester, so retrying the same upload
  reuses it. There is deliberately no shared cache across users: the result
  holds an account number.
- **The image** is stored encrypted on the draft only as long as it might be
  needed: deleted the moment a bill goes `available` or `rejected`, or when
  its draft expires. A held bill keeps it for the reviewer, 7 days at most.
- `/privacy` must say that an AI provider (Anthropic) reads the uploaded
  bill, and that the image is deleted once the bill is listed.

## Data model

- **`bill_requests`**: `id` (UUID), `requester_id` (users, set null),
  `utility`, `status`, `amount_cents` (asked), `amount_due_cents` (read),
  `due_date`, `shutoff_notice`, `county`, `avatar` (catalog key),
  `account_number` and `service_zip`
  (`EncryptedText(purpose="bill_account", required=True)`),
  `account_fingerprint` (HMAC-SHA256 of utility + digits with
  `crypto.derived_key("bill_account_fingerprint")`: a plain hash of a
  10-digit number is reversed by trying them all), `image` (encrypted,
  nullable), `image_sha256`, `extraction` (encrypted JSON), `flags`,
  `refused` (an upload that can't be posted, kept so a re-upload isn't read
  again), `reject_reason`, `thanks` (emoji key), and times: `created_at`,
  `posted_at`, `closed_at`, `answered_at`, `erased_at`.
- **`bill_holds`**: `id`, `request_id`, `giver_id` (users, set null),
  `status` (`active` → `released` | `expired` (a strike) | `withdrawn` |
  `reported` → `confirmed` | `disputed` → `confirmed` or `struck` (a
  strike)), `held_at`, `expires_at`, `revealed_at`, `warned_at`,
  `reported_at`, `disputed_at`, `settled_at`, `paid_cents`, `paid_on`,
  `confirmation_number`
  (`EncryptedText(purpose="bill_confirmation", required=True)`). Partial
  unique indexes allow one live hold (`active`, `reported`, `disputed`) per
  bill and one `active` hold per giver.
- **`bill_givers`**: `user_id`, `strikes_cleared_at`. A reviewer lifting a
  pause sets it; strikes before it stop counting.
- **With no `DATA_ENCRYPTION_KEYS`, posting and holding are off** (503
  `encryption_unavailable`), the way the saved profile works. Set a local
  key to try it locally.
- **Retention:** a request's account number, ZIP, image and extraction are
  erased 30 days after it closes (`paid`, `withdrawn`, `rejected`,
  `expired`); the fingerprint, amounts and dates stay for the limits and the
  giver's history. A giver's confirmation number is their own record and
  stays until they delete it or their account. Backups hold only
  ciphertext for every encrypted column.
- **Account deletion** (`routers/auth.py` → `bills.flow.delete_user_data`):
  a requester's bill that a giver paid, or says they paid, stays, closed as
  paid, with `requester_id` cleared and the account erased, so the giver
  keeps that line in their history; every other bill of theirs is deleted
  (a giver holding one is told "not needed any more"). A giver's active
  hold is let go; their other holds keep the bill's record but lose
  `giver_id` and the confirmation number.

## API

Paths say `bills`, never anything about need. API keys are refused on every
route here, admin ones included (a key could otherwise open bill images).

- Public: `GET /bills` (the list: avatar, utility, amount, due date,
  shutoff, county, status; filters `county`, `utility`), `GET /bills/catalog`
  (utilities, avatars, emojis).
- Requester: `POST /bills/upload` (multipart → draft with the read fields),
  `POST /bills/{id}/post` (confirmed fields, amount, avatar, the tick),
  `DELETE /bills/{id}`, `POST /bills/{id}/answer` (`paid|not_yet`),
  `POST /bills/{id}/thanks` (emoji key).
- Giver: `POST /bills/{id}/hold`, `GET /bills/holds/{id}` (the payment
  details; reveals the account number, `audit.note("bills.account_revealed")`),
  `POST /bills/holds/{id}/paid`, `POST /bills/holds/{id}/release`.
- Both: `GET /bills/mine` → `{posted: [...], gifts: [...], hold_blocker}`.
- Review (`bills.manage`, browser sessions only): `GET /admin/bills`
  (held, disputed, paused givers), `GET /admin/bills/{id}/image`,
  `POST /admin/bills/{id}/decision` (`approve|reject` a held bill,
  `relist|close_paid` a dispute), `POST /admin/bills/givers/{id}/unpause`.
  The image, each decision and each unpause are in `AUDITED`.

## Review

- **New permission `bills.manage`, "Neighborz review"**, `sensitive=True`:
  it shows bill images (names, addresses) and dispute details. Not part of
  the Localz reviewer role by default; the owner gives it to whoever reviews
  bills.
- **Held bills:** the image, the read fields, what the requester changed,
  the flags. Approve or reject (with a fixed reason). The image is deleted
  on the decision.
- **Disputes:** the amount, date and confirmation number the giver entered,
  and both sides' history counts (never names). Put it back on the list
  (giver strike) or close it as paid. Either side may be lying, and the
  reviewer can't check with the utility either; the rule of thumb is a
  first dispute goes back on the list, a requester with two disputes in 90
  days is held for review on their next post.

## Email

Through `services/mailer.py` (nothing sent where SMTP isn't set), generic
like Localz alerts: subject "An update on schoolz", body "Something on
your schoolz account needs a look. Sign in to see it" and the site's
address (not a `/bills` link), no amounts, no utility, no word about
bills.

- Requester: a giver reported paid; the listing expired.
- Giver: their hold has 2 hours left; the bill they held was withdrawn.

## Avatars and emojis

- **Avatars:** a fixed catalog of about 24 cartoon animals, shipped with the
  frontend as SVGs from an openly licensed set (Microsoft's Fluent Emoji is
  MIT; keep its license notice), stored on the request as a key. Shown as
  `<img>`, so an SVG can't run anything. No uploads, no colors picked freely.
- **Emojis:** a fixed set of six, stored as keys, shown to the giver on
  their paid list: ❤️ 🙏 😊 🎉 💡 🌻.

## Utilities

A catalog in code (`backend/bills/utilities.py`): key, name, account number
format, guest-pay URL and phone, the fields the guest payment needs.
A utility is added only if its guest payment needs nothing more than account
number, ZIP and amount: a utility that needs the customer's name or
address, or a login, would break principle 2.

- **PSE&G** first. A PSE&G account can cover electric and gas on one bill,
  so the listing says "PSE&G" and the amount is the account's.
- Then South Jersey Gas, New Jersey American Water, Atlantic City Electric,
  and internet providers, one at a time, each checked against the rule above.

## Guards

| # | Risk | Guard |
|---|---|---|
| 1 | **Account-number harvesting**: register, hold many bills, collect the numbers (for unwanted supplier switching, or a convincing "PSE&G is cutting you off" scam call) | One hold at a time; 24-hour accounts; strikes; every reveal in the audit log; numbers erased 30 days after close; a reveal count per giver the reviewer can see |
| 2 | **The utility's guest-pay page shows the customer's name or address** | Checked before launch (build order step 0). If it does, either the requester is told exactly what the giver will see or the utility isn't added |
| 3 | **Fake or someone else's bill** | Money only ever reaches the utility account on the bill, so a fake gains nothing but that account's credit; code checks; edited account numbers held for review; the per-account limit |
| 4 | **Asking for more than is owed** | Amount ≤ what was read and ≤ the cap; the requester can only lower it |
| 5 | **Holding a bill and never paying** | 24-hour hold; strikes; one hold at a time |
| 6 | **A false "I paid"**, or a requester denying a real payment to get it paid twice | The requester checks their own utility account; disputes go to a reviewer; strikes on either side |
| 7 | **A message smuggled between the two** | No free text crosses; the confirmation number is never shown to the requester; avatars and emojis are fixed keys |
| 8 | **Re-identification from the listing** | County, not town or ZIP; no free text; amounts are whatever the bill says |
| 9 | **Database dump, backup, pooler leak** | Account number, ZIP, image, extraction and confirmation number are encrypted with their own derived keys; fingerprints are keyed HMACs; `ENCRYPTION_REQUIRE=1` before launch |
| 10 | **Insider, admin, API key** | No endpoint returns an account number except to its current holder; review needs `bills.manage` and a browser session; keys refused; the Data Audit portal excludes these tables |
| 11 | **Server logs** | No account number, ZIP or confirmation number in a URL or a log record (a test asserts it, as for the saved profile) |
| 12 | **AI provider** | Only the uploaded bill is sent, once; disclosed on the page and in `/privacy` |
| 13 | **Shared device** | Neutral paths and titles; one `/localz/bills/mine` for both sides; Quick exit |
| 14 | **Tax confusion** | Paying a stranger's bill is a gift to a person, not to a charity: not deductible. The pages say the confirmation number and receipt are for the giver's own records, nothing more |

## Build order

0. **Before launch (owner):** do a guest payment on your own PSE&G account
   from a private window and note what the page shows after the account
   number and ZIP (row 2), any card fee, the exact guest-pay URL and phone
   number; set the numbers under "Limits"; write the `/privacy` Neighborz
   section and a data protection assessment addendum; counsel review, as
   for Localz.
1. **Backend:** tables and migration, utility catalog, bill reading,
   the endpoints and limits, encryption, audit notes, account deletion, the
   sweep job, tests.
2. **Frontend:** the public list, posting (upload → check → avatar →
   post), holding and paying, My Neighborz for both sides, emojis,
   translations.
3. **Review screen** in Admin.
4. **Email nudges.**
5. **More utilities.**

## Owner decisions

- No money handled: givers pay the utility directly by its guest payment.
- Listings are anonymous; the giver never learns who they helped; no text
  between giver and requester; the requester can answer only with an emoji
  from a fixed set.
- The list is public to browse; holding a bill needs an account.
- Requesters choose an avatar from a fixed catalog of cartoon avatars.
- PSE&G first.

## Open questions for the owner

- The name: Neighborz is proposed, not decided ("Billz" is taken by the
  owner's other app).
- The numbers under "Limits" (the $500 cap, 24-hour hold, 60-day
  per-account limit, two strikes) and the 7-day auto-confirm.
- Auto-list after the code checks, holding only flagged bills (proposed), or
  a reviewer approving every bill before it's listed?
- County on the listing (proposed), or town? Town needs a ZIP-to-town table
  and narrows who it could be.
