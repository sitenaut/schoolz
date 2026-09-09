# Improving communication between the district, schools, and families: findings and an invitation

**Prepared as the basis for a conversation with Cherry Hill Public Schools.** This started as an effort to build one tool that makes school information easier for a parent to find. Along the way, building that tool meant reading every school's website, every tracked Smore newsletter, and the district's own department pages closely enough to parse them programmatically — which surfaced a clear, consistent picture of where communication across the district already works well, and where it doesn't, not because any one school or office is doing something wrong, but because there's no shared standard for where this information lives or how current it stays. This document lays that picture out, and proposes a starting point: a free, open-source tool the district can look at, use, or simply take the findings from.

## The three kinds of information a family needs

Talking to parents about what's actually hard surfaced a consistent pattern — the information a family needs day to day splits cleanly into three categories, and they call for very different solutions:

1. **School processes and procedures** — the bell schedule, the lunch menu, how to report an absence, how the bus and late-bus system works, how after-school care operates. This information is *the same for every family at a given school* and *doesn't change often*. It's a natural fit for a single, consistent, public page per school.
2. **District and school events, initiatives, and deadlines** — Back to School Night, picture day order deadlines, PTA fundraisers, board meetings, early dismissals, the emergency-contact-form deadline. This is also public, shared information, but it changes constantly and is currently the single most common source of parent frustration: **missed deadlines and missed opportunities were the most frequently cited complaint** in conversations that shaped this project. A parent who misses a form deadline or doesn't hear about a fundraiser until it's over isn't failing to pay attention — the information genuinely wasn't in one predictable place.
3. **A child's individual educational world** — communication with their specific teachers, their assignments, how they're tracked and managed day to day. This is fundamentally different from the first two: it's personal, it's sensitive, and every teacher currently reaches for their own preferred tool to handle it (ClassDojo, Remind, Teaching Strategies, and others, alongside Google Classroom and Genesis, which students use directly).

**This project — schoolz — addresses the first two categories only, deliberately.** We've built a working framework that presents that shared, public information consistently, the same way, for every school in the district, whether a parent has one child or five spread across five schools. It's live, it's tested against real data from every Cherry Hill school we could reach, and it's offered as a free, open-source service — not a product being pitched, a tool being handed over.

The third category is where we stopped on purpose, and where we'd like the district's help — more on that at the end.

## What we found, school by school

Building this required reading every school's own website closely, not just linking to it. That process surfaced real, specific findings about how communication actually varies across the district today. We want to be clear about the spirit of this: **no single school or office is doing this "wrong."** Every school has clearly made reasonable, local decisions with the tools available to them. The pattern that emerges is that those decisions were never coordinated, so the *same* piece of information — a bell schedule, an absence policy, a PTA update — lives in a different place, in a different format, updated on a different rhythm, at every single school.

### Information that should be public and consistent, but isn't

A few concrete examples, because specifics are more useful than a general impression:

- **Bell schedules.** Both high schools publish a clean, detailed bell-schedule PDF, including delayed-opening and early-dismissal times down to the minute. As far as we could find, **no elementary or middle school publishes this at all** — a parent at any of the district's 12 elementary or 3 middle schools has no way to look up "what time does early dismissal actually let out today" the way a high school parent can.
- **Absence-reporting procedures.** We could only confirm a definite absence procedure (a specific email, phone number, or portal) for **3 of 28 schools**. The rest either don't state it clearly, state it somewhere that isn't easy to find, or state it in a newsletter that isn't consistently published. This is one of the most basic things a parent needs on a given morning.
- **Parent/student handbooks.** Findable for 13 of 28 schools. For the other 15 — disproportionately the district's youngest programs and preschools — there's no handbook to be found on the school's site or anywhere it links to.
- **Lunch menus for preschool programs.** The district's own lunch-menu pipeline covers elementary, middle, and high school tiers cleanly. It does not cover any of the district's listed preschool providers except where one embeds its own menu in a newsletter. A parent at most of those programs has nowhere to look this up.

### Bus and transportation information — a specific, important case

Parents need to know how to reach transportation about a late bus or an absence-related bus question, and what the late-bus system actually is. We found that **this information does exist and is genuinely well-organized** on the district's transportation department pages — office hours, staff contacts, a phone number, a clear late-bus contractor list by school, a bus-stop-change procedure, a lost-items policy. The gap here isn't that the information is missing; it's that **it lives on a district page most parents never think to look for**, disconnected entirely from their own school's page. We've now surfaced it directly on each school's own page and in the app's daily view — this is a case where the underlying information was already solid, and the fix was purely about *where a parent encounters it*.

One fact worth double-checking directly with the department, since we relied on their own published page for it: **there is no live bus-delay feed anywhere on the district's site.** Delays currently reach families only through automated messages sent to whatever contact info is on file in Genesis. If that's intentional, that's fine — but it's worth confirming, since a parent checking the website during a delay currently finds nothing there to check.

### Stale data and dead links

This is worth being specific and direct about, because a few of these are more than a passing annoyance:

- **One school's official PTA meeting-minutes page stops at March 2021** — over five years out of date, still live on the school's own site today.
- **Seven schools' official PTA pages** show only a raw, broken content-management placeholder ("PTA Active block - Client Enablement Consultant") instead of any real content — this reads as a publishing error that's gone unnoticed, not a deliberate choice.
- **At least one school's PTA link points to a URL that literally has "21-22" (the 2021-2022 school year) baked into its address**, strongly suggesting the page itself hasn't been touched in several years even where it still loads.
- **Only one of nineteen public school websites** (a high school) shows PTA officer information that looks genuinely current for the present school year.

None of this means the PTAs themselves are inactive — most clearly are, based on the newsletters and events we could find elsewhere. It means **the official school-website page is often not where that activity actually shows up**, which makes it a dead end for exactly the parent who goes looking there first.

### Use of third-party communication tools

Across the district, we found real, substantial reliance on third-party platforms rather than the district's own website for genuinely current information:

- **Newsletter platforms (Smore).** Several schools clearly treat a Smore newsletter, not their district website, as their real communication channel — this is where bell-schedule exceptions, PTA activity, fundraisers, policy reminders, and event flyers actually show up, often the same week they happen. We found this pattern at eight schools so far; it's very likely more schools use it under a link we haven't found yet, or use a different but equivalent tool. Notably, **most elementary and middle schools' actual school-year content lives in these newsletters, not on the official website** — the website's own pages, especially for PTA and general announcements, are frequently the stale ones described above.
- **PTA platforms are fragmented across at least five different services** — eboard.com, Givebacks, Google Sites, Linktree, and district-hosted pages — sometimes for schools right next to each other. There's no standard, which means a parent moving between schools (or a district staff member trying to check in on all of them) has to relearn a different platform and format every time.
- **Individual classroom communication tools** (ClassDojo, Remind, Teaching Strategies, and others) are chosen independently by individual teachers, which is the third information category described above and outside this report's scope — but it's the same underlying pattern: valuable communication is happening, just scattered across tools with no shared standard, each with its own login, its own notification behavior, and its own cost to the district.

### What we observed in the newsletters specifically

Having now parsed real content from every tracked school's Smore newsletter, a few patterns are worth reporting back:

- **Newsletters are the richest, most current source of school-specific information in the district**, consistently ahead of the school's own website for events, deadlines, PTA activity, and policy reminders. Several run 30-40 distinct content blocks per issue — genuinely substantial, well-maintained communication.
- **They're also image-heavy in a way that's easy to lose information in.** A large share of real content — full event flyers, "mark your calendar" lists, lunch-menu graphics — is published as a picture, not as text, which means it's invisible to anyone using a screen reader, invisible to search, and (until we specifically built around it) easy to silently drop in any automated processing of the newsletter, including, we'd guess, whatever a family's own email client or browser does with it.
- **Newsletter publishing habits vary in ways that matter for reliability.** Most schools publish to one stable, reusable web address that updates in place from issue to issue — the easy case. At least two schools instead publish an entirely new web address for every single issue, which means anyone (a parent bookmarking it, or a tool like ours trying to track it) following last month's link finds it dead or outdated, with no way to know a newer one exists without checking the publisher's page directly.
- **Adoption is real but partial** — we could only confirm 8 of 28 schools using this kind of newsletter at all. That's either a genuine gap for the other 20, or (just as likely) a case of us not yet having found their link — which is itself informative: if a district staff member or PTA doesn't know where to point us, an ordinary parent searching the school website is even less likely to find it.

## An actionable list

In rough priority order, based on what would most directly reduce the "I didn't know about that" problem parents describe:

1. **Publish (or confirm to us) each school's absence-reporting method** — an email, a phone number, or a portal, stated plainly. Currently confirmable for only 3 of 28 schools.
2. **Publish bell-schedule detail (including delayed-opening and early-dismissal times) for elementary and middle schools**, matching what both high schools already do well.
3. **Review and refresh each school's official PTA page**, or — more realistically, given how much PTA activity is clearly already happening elsewhere — designate one authoritative link per school (even if it's a newsletter or a third-party site) so the district website can point to it accurately instead of showing outdated or broken content.
4. **Adopt a single newsletter platform and publishing convention district-wide** (a stable, reusable link per school, not a new one per issue), so both parents and any tool trying to help them can rely on it.
5. **Confirm whether a live bus-delay status exists anywhere**, and if not, consider whether one should.
6. **Find (or confirm the absence of) a lunch menu for preschool programs**, which currently have no equivalent to the elementary/middle/high school district menu pipeline.

## Where this goes next — and why we're stopping here for now

The third information category — a child's actual educational world, their assignments, their teacher's day-to-day communication — is where the most acute parent frustration often lives, and it's also the most sensitive. It involves genuinely private, student-specific data, and it deserves real district policy and security review before any outside tool touches it. That's exactly why we've kept it out of this phase.

We believe there's already a straightforward answer sitting in front of the district: **Google Classroom already has the privacy safeguards needed for parent access to a student's own classroom — guardian summaries and view-only access exist today.** If the district enabled and encouraged that for parents, it would very likely solve the bulk of the "which app is my kid's teacher using this year" problem immediately, without needing every teacher to adopt yet another platform, and without this project (or any other outside tool) needing to touch student-specific data at all. It would also mean the district isn't paying for and administering as many separate third-party classroom tools, and it would concentrate student data inside a platform already built for it rather than spread across ClassDojo, Remind, Teaching Strategies, and whatever else any individual teacher picks — which is very likely a net improvement to the district's own data-security posture, not just a convenience.

That's the conversation we'd like to have next, once this first phase — the free, public, procedural-and-events layer this document describes — is something the district has looked at and is comfortable with.

## What we're asking for

Not funding, not a contract, and not access to anything sensitive. We're asking the district to:

- Look at what's built (happy to walk through it live),
- Tell us where the findings above are wrong or out of date, so we can fix them,
- Help fill the specific gaps listed above where the information exists but isn't published anywhere we could find it, and
- Consider, separately and later, enabling parent access to Google Classroom — the one change most likely to make the third category of information (the hardest one) largely solve itself.

This is offered as a free service to the Cherry Hill Public Schools community, and it's open source — every line of what it does, and exactly how it found the information described in this report, is inspectable in this repository.
