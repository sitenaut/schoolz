"""MCP server exposing schoolz's public, no-auth endpoints as remote tools.

Mounted directly into this same FastAPI app (see main.py) at `/mcp`, using
the Streamable HTTP transport - so the public endpoint is just
`https://schoolz-api.sitenaut.com/mcp`, no separate service to deploy and
nothing for a user to install. That's a deliberate choice: Claude, Gemini,
and ChatGPT are all converging on remote MCP (a URL added in a Connectors
setting) as the way regular people use MCP, as opposed to a local stdio
server that needs Python installed and a config file hand-edited - and
"make this easy for actual people to use" was the whole point of building
this.

Every tool here maps to an endpoint that requires no login at all - see
CLAUDE.md's "Access model" section: schools, districts, calendar, and
Smore-newsletter data are all public/bookmarkable by design. This module
adds no auth of its own and calls straight through to this same app's own
route handlers via an in-process ASGI transport (httpx.ASGITransport) -
not a real network request to itself, so there's no self-inflicted
network hop, no extra latency, and no dependency on this app's own public
hostname resolving back to itself.

Deliberately excluded: every admin-only endpoint (creating/editing a
School/District/SmoreNewsletter, any `run-now` scan trigger, `/scheduled-
jobs`) and everything under the authenticated-guardian layer (students,
invites, notifications, account settings, Gmail). Those need real
credentials this server never asks for or holds - see the "Access model"
section of the repo's CLAUDE.md for the three-tier split this mirrors.

One exception to the read-only posture: `submit_community_content`, which
wraps schoolz's public `POST /submissions` endpoint. It's included on
purpose - when a lookup tool comes back empty, its result carries a `note`
telling the caller (an LLM like Claude/Gemini/ChatGPT reached via MCP)
that the missing information is a genuine, fixable gap: ask the school to
publish it, or submit a link to something that already covers it. This
tool is the "submit a link" half of that loop. Nothing it submits goes
live automatically - every submission lands as "pending" for a schoolz
admin to review, the same as a submission through the website's own
/contact page. Unlike every other tool, this one validates an arbitrary
*external* URL, so it uses a real network client, not the in-process one.
"""

from typing import Any

import httpx
from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP


def _is_empty(data: Any) -> bool:
    return data is None or data == []


def _finalize(data: Any) -> Any:
    """The very last transform on every tool's return value, right before
    it goes back to the MCP client.

    The MCP SDK's own result-serialization (`_convert_to_content` in
    mcp.server.fastmcp.server) special-cases a bare top-level list: instead
    of one JSON blob, it splits it into one separate text content block
    *per item* (confirmed: a 28-school list_schools call came back as 28
    content blocks, not one array). A spec-following client is supposed to
    read every block, but plenty of real integrations reasonably assume
    "the result is content[0]" - which would silently show just the first
    school and drop the other 27, with nothing telling the caller that
    happened. Wrapping any list result in a single object sidesteps the
    SDK's special case entirely, so this doesn't depend on how carefully
    any particular client (or client version) is written.
    """
    if isinstance(data, list):
        return {"count": len(data), "items": data}
    return data


def _gap_note(subject: str, name: str, *, submittable: bool = True) -> str:
    """The advocacy nudge attached whenever a tool comes back with nothing.

    schoolz's entire model is that public school information should be
    freely accessible - when it isn't yet, the fix is either the school
    publishing it or a parent handing schoolz a link to something that
    already exists (a Smore newsletter, a handbook, a flier). This is
    written as guidance TO the calling chat app (Claude/Gemini/ChatGPT),
    not just to a human reading it - it names the concrete next actions
    (ask the school, or submit a link) so an assistant surfacing this to a
    parent can act on it directly rather than just reporting "no data."
    """
    possessive = f"{name}'" if name.endswith("s") else f"{name}'s"
    note = (
        f"{subject.capitalize()} is not currently available for {name} in schoolz. This isn't a dead end - "
        f"it usually means the school hasn't published this anywhere schoolz can find yet, most often because it has no "
        f"tracked Smore newsletter (schoolz's richest source for school-specific content). "
    )
    if submittable:
        note += (
            f"Two things actually move this forward: (1) ask {possessive} principal or front office to publish this "
            "information on their website or in their newsletter, and mention that schoolz can pick it up automatically "
            "once it's public; (2) if you already have a link to something that covers this (a Smore newsletter, a "
            "handbook, a flier, a webpage), submit it with the submit_community_content tool, or at "
            "https://schoolz.sitenaut.com/contact - a schoolz admin reviews every submission before it goes live. "
            "If you're an assistant relaying this to a parent: surface both options, don't just report the absence."
        )
    else:
        note += (
            "This particular data comes from the district's own configuration rather than a community submission, so "
            "the most effective ask is to the district's own office for this department, and flagging the gap to a "
            "schoolz admin so it can be added to that district's tracked sources."
        )
    return note


def _with_gap_note(data: Any, subject: str, name: str, *, submittable: bool = True) -> Any:
    """Wrap a result with an advocacy note only when it's actually empty.

    A populated result is returned exactly as the API sent it - the note
    only appears when there's something worth nudging about, so a normal
    lookup's shape never changes.
    """
    if isinstance(data, dict) and "error" in data:
        return data
    if not _is_empty(data):
        return data
    return {"result": data, "note": _gap_note(subject, name, submittable=submittable)}


def build_mcp_server(app: FastAPI) -> FastMCP:
    """Construct the FastMCP server bound to this app's own routes.

    Takes the FastAPI `app` instance as a parameter (rather than importing
    it) so main.py can build this after `app` exists and mount the result
    back onto that same `app` - avoiding a circular import between the two
    modules.
    """
    mcp = FastMCP("schoolz-public", stateless_http=True, streamable_http_path="/")

    # In-process only - no real socket, no DNS, no dependency on this
    # app's own public hostname being reachable from itself. Every tool
    # below is a normal request against this same app's route handlers.
    app_client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://schoolz-internal")
    # A *real* network client, used only to validate a third-party URL a
    # caller wants to submit in submit_community_content - that's an
    # external page, not one of this app's own routes.
    web_client = httpx.AsyncClient(timeout=15.0, follow_redirects=True)

    async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
        """GET one of this app's own public routes and return the parsed JSON body.

        No auth header of any kind - every path this is called with is a
        route that requires none. A non-2xx response is surfaced as the
        raw response text rather than swallowed, since a school ID typo
        should read as an explicit error to the MCP client, not a silent
        empty result.
        """
        params = {k: v for k, v in (params or {}).items() if v is not None}
        response = await app_client.get(path, params=params)
        if response.status_code >= 400:
            return {"error": f"{response.status_code} {response.reason_phrase}", "detail": response.text}
        return response.json()

    async def _check_url_is_live(url: str) -> str | None:
        """Reject anything that isn't a real, reachable http(s) page before
        it reaches the review queue - a garbage/typo'd link wastes an
        admin's time looking at it, and this tool is meant to be usable by
        any MCP client, not just careful humans. Returns an error message,
        or None if the URL checks out.

        No domain allowlist here on purpose - the whole point of this tool
        is covering sources beyond Smore (handbooks, fliers, lunch-menu
        PDFs live on all kinds of domains), so "is this real" is the bar,
        not "is this from a known host."
        """
        if not (url.startswith("http://") or url.startswith("https://")):
            return "URL must start with http:// or https://"
        try:
            response = await web_client.head(url)
            # Some hosts (and most CDNs) reject HEAD outright - a 405
            # there says nothing about whether the page itself is real,
            # so fall back to a ranged GET rather than trusting HEAD.
            if response.status_code in (403, 405) or response.status_code >= 500:
                response = await web_client.get(url, headers={"Range": "bytes=0-0"})
        except httpx.RequestError as exc:
            return f"Could not reach this URL ({exc.__class__.__name__}) - double-check it's correct and publicly accessible"
        if response.status_code >= 400:
            return f"This URL returned {response.status_code} {response.reason_phrase} - it doesn't look like a live page"
        return None

    async def _resolve_school(school_id_or_slug: str) -> dict | None:
        """Fetch a school's own record, for its display name / real id / type.

        Returns None on a lookup failure (already-surfaced 404/etc from
        `_get`) so callers can short-circuit instead of building a gap
        note around a school that doesn't exist.
        """
        school = await _get(f"/schools/{school_id_or_slug}")
        return school if isinstance(school, dict) and "error" not in school else None

    # -----------------------------------------------------------------
    # Schools
    # -----------------------------------------------------------------

    @mcp.tool()
    async def list_schools() -> Any:
        """List every tracked school in the district (public, no auth needed).

        Returns each school's id, slug, name, short_name, school_type
        (elementary/middle/high/alternative/other), address, phone, website,
        logo, and district_id. Use a school's `slug` (preferred, stable) or
        `id` as the `school_id_or_slug` argument to every other school tool.
        """
        return _finalize(await _get("/schools"))

    @mcp.tool()
    async def get_school(school_id_or_slug: str) -> Any:
        """Get one school's full record by id or slug (e.g. "bret-harte-elementary")."""
        return await _get(f"/schools/{school_id_or_slug}")

    @mcp.tool()
    async def get_school_today(school_id_or_slug: str) -> Any:
        """The same "Today" snapshot schoolz's home page shows for one school.

        Includes today's day status (open/closed/early_dismissal/delayed),
        bell hours, elementary/high-school rotation day, today's + tomorrow's
        lunch, SACC essentials, role-based contacts, the next 5 dated items,
        any closure/early-dismissal alert within 7 days, and a Mon-Fri week
        strip. The single richest call for "what does a parent need to know
        about this school right now."
        """
        return await _get(f"/schools/{school_id_or_slug}/today")

    @mcp.tool()
    async def list_school_staff(school_id_or_slug: str) -> Any:
        """List a school's staff directory (name, title, email, role classification).

        `role` is a deterministic classification (principal / assistant_principal
        / nurse / counselor / secretary / sacc / social_worker / psychologist /
        null) derived from each person's title, not a raw scrape field.

        If nothing's found, the result includes a `note` with concrete next
        steps (ask the school to publish a directory, or submit a link) rather
        than just an empty list - see submit_community_content.
        """
        school = await _resolve_school(school_id_or_slug)
        data = await _get(f"/schools/{school_id_or_slug}/staff")
        if not school:
            return _finalize(data)
        return _finalize(_with_gap_note(data, "a staff directory", school["short_name"] or school["name"]))

    @mcp.tool()
    async def list_school_documents(school_id_or_slug: str, include_superseded: bool = False) -> Any:
        """List a school's discovered reference documents (handbook, bell schedule, etc.).

        Each has a `doc_type`, an `academic_year` when one could be parsed, and
        `is_current` - by default only current-year documents are returned;
        pass include_superseded=True to see older versions too.

        If nothing's found, the result includes a `note` with concrete next
        steps (ask the school for a handbook link, or submit one) rather than
        just an empty list - see submit_community_content.
        """
        school = await _resolve_school(school_id_or_slug)
        data = await _get(f"/schools/{school_id_or_slug}/documents", {"include_superseded": include_superseded})
        if not school:
            return _finalize(data)
        return _finalize(_with_gap_note(data, "a handbook or other reference document", school["short_name"] or school["name"]))

    @mcp.tool()
    async def get_school_transportation(school_id_or_slug: str) -> Any:
        """Bus/transportation info for one school: office contacts, late-bus
        contractor and route numbers (only middle/high schools have a late
        bus - null for elementary), bus-stop-change procedure, lost-items
        policy. Rolled up from the school's district, since almost none of
        this is genuinely per-school.

        If null, the result includes a `note` pointing at the district's
        transportation office instead of a submission form - this data is
        admin-configured per district, not community-submittable.
        """
        school = await _resolve_school(school_id_or_slug)
        data = await _get(f"/schools/{school_id_or_slug}/transportation")
        if not school:
            return data
        return _with_gap_note(data, "transportation information", school["short_name"] or school["name"], submittable=False)

    @mcp.tool()
    async def get_school_sacc(school_id_or_slug: str) -> Any:
        """Before/after-school child care (SACC) info for one school, or null
        if the school doesn't host a SACC program.

        A null result for a middle/high school is expected (SACC is K-5 only)
        and returned as plain null with no note. A null result for an
        elementary school could genuinely mean no SACC program, or could mean
        it just isn't tracked yet - the result includes a `note` in that case
        since it's worth double-checking rather than assuming.
        """
        school = await _resolve_school(school_id_or_slug)
        data = await _get(f"/schools/{school_id_or_slug}/sacc")
        if not school or school.get("school_type") != "elementary":
            return data
        return _with_gap_note(data, "SACC (before/after-school care) information", school["short_name"] or school["name"])

    @mcp.tool()
    async def get_school_lunch_menu(school_id_or_slug: str, meal_type: str = "lunch") -> Any:
        """This school's lunch (or meal_type="breakfast") menu, with day-by-day
        items when available. Resolves the school's own newsletter-embedded
        menu first, falling back to the shared district+school_type PDF-based
        menu - the caller never needs to know which source it came from.

        If null, the result includes a `note` with concrete next steps (ask
        the school to publish a menu, or submit one) rather than just null -
        this is a real, documented gap for several preschools today.
        """
        school = await _resolve_school(school_id_or_slug)
        data = await _get(f"/schools/{school_id_or_slug}/lunch-menu", {"meal_type": meal_type})
        if not school:
            return data
        return _with_gap_note(data, f"a {meal_type} menu", school["short_name"] or school["name"])

    @mcp.tool()
    async def list_school_newsletters(school_id_or_slug: str) -> Any:
        """List the Smore newsletters tracked for one school (id, url, label, last_scanned_at).

        If none are tracked, the result includes a `note` - this is the single
        biggest lever on how much of schoolz's content exists for a school, so
        an empty list here is worth actively surfacing to a parent, not just
        reporting.
        """
        school = await _resolve_school(school_id_or_slug)
        data = await _get(f"/schools/{school_id_or_slug}/newsletters")
        if not school:
            return _finalize(data)
        return _finalize(_with_gap_note(data, "a tracked Smore newsletter (or equivalent)", school["short_name"] or school["name"]))

    @mcp.tool()
    async def list_school_content(
        school_id_or_slug: str,
        category: str | None = None,
        q: str | None = None,
        include_superseded: bool = False,
    ) -> Any:
        """List extracted content items for one school - events, deadlines,
        reminders, policies, PTA info, staff mentions, etc. - drawn from its
        own newsletters plus its district's district-wide items (e.g. holiday
        closures), so a caller never has to separately query the district.

        `category` filters to one of: event, deadline, initiative, reminder,
        policy_change, procedure, program, busing, funding, volunteer,
        org_club, merch_ad, pta, person, lunch_menu, marking_period.
        `q` does a text search across title/description.

        An empty result with no category/q filter includes a `note` - it
        usually means this school has no newsletter feeding schoolz yet. An
        empty result from a narrow category/q filter is just "nothing matched
        that filter" and gets no note, since that's the expected, correct
        answer most of the time.
        """
        school = await _resolve_school(school_id_or_slug)
        data = await _get(
            f"/schools/{school_id_or_slug}/content",
            {"category": category, "q": q, "include_superseded": include_superseded},
        )
        if not school or category or q:
            return _finalize(data)
        return _finalize(_with_gap_note(data, "any tracked events, deadlines, or other content", school["short_name"] or school["name"]))

    # -----------------------------------------------------------------
    # Districts
    # -----------------------------------------------------------------

    @mcp.tool()
    async def list_districts() -> Any:
        """List every tracked school district (id, name, config)."""
        return _finalize(await _get("/districts"))

    @mcp.tool()
    async def get_district_transportation(district_id: str) -> Any:
        """District-wide transportation info: office hours/staff, the
        late-bus contractor list, delay-notification policy, bus-stop-change
        and lost-items procedures. This is the same data
        get_school_transportation resolves down to one school - call this
        directly when you already have a district_id rather than a school.

        If null, the result includes a `note` pointing at the district's own
        transportation office rather than a submission form - this is
        admin-configured per district, not something a parent submits.
        """
        districts = await _get("/districts")
        name = district_id
        if isinstance(districts, list):
            match = next((d for d in districts if d.get("id") == district_id), None)
            if match:
                name = match.get("name", district_id)
        data = await _get(f"/districts/{district_id}/transportation")
        return _with_gap_note(data, "transportation information", name, submittable=False)

    # -----------------------------------------------------------------
    # Calendar
    # -----------------------------------------------------------------

    @mcp.tool()
    async def list_calendar_items(
        start: str | None = None,
        end: str | None = None,
        school_id: str | None = None,
        school_ids: str | None = None,
        category: str | None = None,
        q: str | None = None,
    ) -> Any:
        """Search dated calendar items (events/deadlines/initiatives/marking
        periods) across schools and districts. Entirely public data - called
        with no filters at all, it returns everything tracked system-wide.

        start/end: ISO-8601 datetimes bounding the search window (both optional).
        school_id: narrow to one school (id or slug).
        school_ids: comma-separated ids/slugs to narrow to several schools at once.
        category: one of event, deadline, initiative, marking_period.
        q: free-text search across title/description, unbounded by date -
           useful for finding something like "graduation" regardless of when
           start/end would otherwise cut the search off.
        """
        return _finalize(
            await _get(
                "/calendar",
                {"start": start, "end": end, "school_id": school_id, "school_ids": school_ids, "category": category, "q": q},
            )
        )

    # -----------------------------------------------------------------
    # Smore newsletters
    # -----------------------------------------------------------------

    @mcp.tool()
    async def list_newsletters() -> Any:
        """List every tracked Smore newsletter across all schools/districts
        (id, url, label, school_slug or district_id, last_scanned_at)."""
        return _finalize(await _get("/smore-newsletters"))

    @mcp.tool()
    async def list_newsletter_blocks(newsletter_id: str) -> Any:
        """List the raw parsed content blocks (text/image/link) for one
        tracked Smore newsletter, in publication order. This is the
        unextracted source material - for the structured events/deadlines/etc.
        already pulled from it, use list_school_content instead.

        An empty result here means the newsletter is tracked but hasn't been
        scanned yet (or its scan hasn't found blocks) - a scheduling/timing
        thing, not a missing-source thing, so the note (if any) points at
        waiting for the next scan rather than at submitting anything.
        """
        data = await _get(f"/smore-newsletters/{newsletter_id}/blocks")
        if isinstance(data, dict) and "error" in data:
            return data
        if _is_empty(data):
            return {
                "result": data,
                "note": (
                    "This newsletter is already tracked by schoolz but hasn't produced any parsed content yet - it may "
                    "not have been scanned yet, or the scan found nothing new. This isn't something to submit a link "
                    "for; if it persists, it's worth flagging to a schoolz admin as a possibly broken or outdated "
                    "newsletter URL."
                ),
            }
        return _finalize(data)

    # -----------------------------------------------------------------
    # Community submissions (the "add it yourself" half of the advocacy loop)
    # -----------------------------------------------------------------

    @mcp.tool()
    async def submit_community_content(
        url: str,
        description: str,
        school_id_or_slug: str | None = None,
        district_id: str | None = None,
        submitter_name: str | None = None,
        submitter_email: str | None = None,
    ) -> Any:
        """Submit a link (a Smore newsletter, a handbook, a flier, any page
        with real school/district information) for a schoolz admin to review
        and add. This is the concrete action behind every gap `note` returned
        by the other tools - use it when a user already has a link that would
        close a gap, rather than only telling them to submit it themselves.

        No login is required - this hits schoolz's public, no-auth submission
        endpoint - but nothing submitted here goes live automatically. Every
        submission lands as "pending" until a human admin reviews it, so treat
        this as "hand it to schoolz for review," not "publish this now."

        url: the link to submit. Required - this tool doesn't support
            uploading a file; for a printed flier with no online copy, direct
            the user to https://schoolz.sitenaut.com/contact instead. Checked
            for being a real, live http(s) page before submission - a
            dead/typo'd link is rejected with an error rather than queued.
        description: what this is and what gap it fills (e.g. "Bret Harte's
            current parent handbook" or "Chesterbrook's lunch menu for
            October"). Required - an admin reviewing a bare URL with no
            context is far less likely to act on it quickly.
        school_id_or_slug: the school this is about, if it's school-specific
            (id or slug, e.g. "bret-harte-elementary"). Resolved to the
            school's real id automatically. Omit for district-wide content.
        district_id: the district this is about, if it's district-wide rather
            than school-specific (e.g. a district calendar feed). Omit if
            school_id_or_slug is set - a submission is about one or the other,
            not both.
        submitter_name / submitter_email: optional, in case the admin wants to
            follow up. Never required, and never sent anywhere except to
            schoolz's own review queue.
        """
        url = url.strip()
        url_problem = await _check_url_is_live(url)
        if url_problem:
            return {"error": url_problem}

        resolved_school_id = None
        if school_id_or_slug:
            school = await _resolve_school(school_id_or_slug)
            if not school:
                return {"error": f"Unknown school: {school_id_or_slug}"}
            resolved_school_id = school["id"]

        form = {"url": url, "description": description[:2000]}
        if resolved_school_id:
            form["school_id"] = resolved_school_id
        if district_id:
            form["district_id"] = district_id
        if submitter_name:
            form["submitter_name"] = submitter_name[:200]
        if submitter_email:
            form["submitter_email"] = submitter_email[:255]

        response = await app_client.post("/submissions", data=form)
        if response.status_code >= 400:
            return {"error": f"{response.status_code} {response.reason_phrase}", "detail": response.text}

        result = response.json()
        result["note"] = (
            "Submitted for review - a schoolz admin looks at every submission before it becomes public, so this won't "
            "appear immediately. Thank the user for contributing; there's nothing further for them to do."
        )
        return result

    return mcp
