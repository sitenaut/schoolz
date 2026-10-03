"""How-to guide for schoolz itself, served to the chatbot by get_app_help.

The data tools answer "what's for lunch at Beck"; nothing answered "how do
I add my kid" - and the system prompt forbids answering from anything a
tool didn't return, so the bot could only refuse or guess. This is the
written answer instead: plain text a person maintains, deterministic, no
model call, and kept out of the system prompt so the cached prefix stays
small (the full guide only enters a conversation when someone asks).

Button and menu names are the English UI's. The chatbot answers in the
visitor's language and translates them; the localized UI uses the same
order and icons, so the steps still line up.

Keep this in step with the UI - a renamed button here is a wrong answer
there. Each topic: one-line `summary` (shown in the topic list) and `text`.
"""

SITE = "https://schoolz.sitenaut.com"

TOPICS: dict[str, dict[str, str]] = {
    "getting_started": {
        "summary": "What schoolz is, and picking your schools (no account needed)",
        "text": (
            "schoolz shows each of your kids' schools at a glance: today's status, bell times, lunch, "
            "buses, the calendar, and who to contact. Almost everything works without an account.\n"
            f"- First visit: pick your schools at {SITE}/start. Schools are grouped by town, so a family "
            "with an elementary and a high school in different districts finds both in one place.\n"
            "- Your picks are saved on this device. To change them later, tap **My schools** at the top, "
            "or the manage button at the end of the school ribbon.\n"
            "- Signing in is optional. It adds the personal layer: your own children, invites for the other "
            "parent, and notifications. A signed-in account's schools follow you to other devices."
        ),
    },
    "today": {
        "summary": "The Today page: each school's day at a glance",
        "text": (
            "**Today** (the home tab) shows one card per school you picked:\n"
            "- Whether school is open, closed, on early dismissal, or delayed\n"
            "- Bell times, and the rotation day (Day 1, Day 2...) where the school uses one\n"
            "- Today's and tomorrow's lunch, and the weather for the school day\n"
            "- What's coming up this week\n"
            "Use the school ribbon at the top to show one school or **All**. After school ends, "
            "the weather shows the next school day so you can plan clothes the night before."
        ),
    },
    "schools": {
        "summary": "A school's own page: absence, contacts, documents, buses, care",
        "text": (
            f"Open **Schools** and pick a school (or go straight to {SITE}/schools/<school>). "
            "Its page puts actions first:\n"
            "- **Report absence**, plus quick links to the nurse, counselor, after-school care (SACC) and office\n"
            "- This week, reminders, and what's coming up\n"
            "- **Who to contact**, with a link to the full staff directory\n"
            "- **Buses & transportation**: the bus office, late buses, and how to change a stop\n"
            "- **Documents** such as the handbook and bell schedule. One from a past school year is marked as possibly outdated.\n"
            "High schools also have a page per graduating class (\"Class of 2027\"): class events, the "
            "class advisor, and class dues and payment dates."
        ),
    },
    "absence": {
        "summary": "Reporting your child absent",
        "text": (
            "On your school's page, tap **Report absence**. What it does depends on how that school takes "
            "absences: it opens an email to the attendance office with a ready-made message (fill in the "
            "student name, teacher and reason), calls the attendance line, or opens the parent portal. "
            "schoolz itself never sends the report; it just gets you to the right place."
        ),
    },
    "calendar": {
        "summary": "The Calendar: closures, half days, events, filters",
        "text": (
            "**Calendar** shows the month for the schools you picked: closures, early dismissals, events, "
            "deadlines and grading dates, pulled from each school's newsletter and website and the district calendar.\n"
            "- Filter to **Events only**, **Deadlines only**, **Grading dates only** or **Initiatives only**, or search.\n"
            "- **Exclude district** hides board meetings and other district items, but never closures, half "
            "days or grading dates.\n"
            "- Rotation day markers (Day 1, Day 2...) can be switched on or off."
        ),
    },
    "lunch": {
        "summary": "Lunch menus",
        "text": (
            "**Lunch** shows the month's menu for one of your schools at a time, scrolled to today. Switch "
            "schools with the ribbon at the top. Today's lunch is also on each school's Today card. Menus "
            "come from the district or the school's food service, usually about a month ahead."
        ),
    },
    "directory": {
        "summary": "Finding a teacher or staff member's email",
        "text": (
            "**Directory** searches every staff member in the district at once, useful when you don't know "
            "which school someone is at. Each word you add narrows the search, so \"beck math\" finds math "
            "teachers at Beck. The chips filter by kind of role (nurse, counselor, and so on)."
        ),
    },
    "local": {
        "summary": "Local community events",
        "text": (
            "**Local** lists community events near you (library programs, town events, theatre, classes), "
            "with filters for category, free events, and dates. These come from local organizations, not the schools."
        ),
    },
    "account": {
        "summary": "Signing in, registering, password, settings",
        "text": (
            "Tap **Sign in** (top right) to sign in or **Register**, with email and password or with Google. "
            "Email sign-ups need you to click the confirmation link that's emailed to you first.\n"
            "Once signed in, **Account** has your profile, security (password, deleting your account), "
            "privacy, notifications, and family (your children and the schools on your Today page). Forgot your password? Use "
            "**Forgot password** on the sign-in screen."
        ),
    },
    "children": {
        "summary": "Adding your child, specials, graduating class",
        "text": (
            "Signed in, go to **Account → Family → My children**.\n"
            "- **Add a child** (first name, last name, student ID, school) only if nobody has invited you to "
            "them yet. If the other parent already added them, ask for an invite instead; it links you to the "
            "same child with nothing to type.\n"
            "- High school: set the **Graduating class** to see that class's page.\n"
            "- Elementary: **Specials** records which special (Art, PE, Music...) your child has on each "
            "rotation day, so it shows on the Today card. Every guardian of that child sees the same specials.\n"
            "- **Remove from my profile** removes only your view. The child stays for any other guardian."
        ),
    },
    "invites": {
        "summary": "Inviting the other parent, or giving your child their own login",
        "text": (
            "From **My children**, on your child's card:\n"
            "- **Invite another guardian**: enter their email and schoolz makes a link. Share or copy it to "
            "them. When they open it and sign in, the child appears on their profile. Invites expire after 7 days.\n"
            "- **Give <child> their own login**: invites your child by email. They must sign in with exactly "
            "that email. They then see the same schoolwork view, without the parent-only settings.\n"
            "Each guardian's own choices (like renaming or recoloring a class) stay private to them."
        ),
    },
    "kids_schoolwork": {
        "summary": "Seeing assignments, what's due or missing, and grades (Backpack Capture + Gradez)",
        "text": (
            "schoolz can show what's due, what's missing, grades and the class schedule, but only from data "
            "you bring in yourself with the **Backpack Capture** browser extension. schoolz never logs in to "
            "Google Classroom or Genesis for you.\n"
            "1. Install Backpack Capture in Chrome, then open Classroom/Genesis while signed in and press "
            "**Start capture**.\n"
            "2. Send the captures to schoolz: **Publish to schoolz** in the extension, or **Export capture** "
            "and upload the file under **Update data** on your child's page.\n"
            "3. Open **Gradez** in the menu (signed in). It has tabs for **Focus** (what to do next), "
            "**Schedule** and **Details**. You can mark work done yourself, record a class's late-work policy "
            "(or paste it from the syllabus), and note a teacher's extension for one assignment.\n"
            "Optional: the extension can walk every class and publish every 4 hours on a computer left on."
        ),
    },
    "student_help": {
        "summary": "For students: asking a teacher for help with an assignment",
        "text": (
            "In Gradez, open the assignment and choose **What's the trouble?**. Pick the kind of stuck you "
            "are, and schoolz writes the email to the teacher for you. It opens in your own mail app to send; "
            "schoolz never sends or stores it. Your parent is only told that you asked, never what you wrote."
        ),
    },
    "notifications": {
        "summary": "Notifications",
        "text": (
            "The bell at the top (signed in) shows notifications, for example when another guardian is linked "
            "to your child or when Backpack Capture needs you to sign in to Google again. "
            "**Account → Notifications** lists them all."
        ),
    },
    "language": {
        "summary": "Changing the language",
        "text": (
            "schoolz is available in English, Español, 中文, 한국어 and हिन्दी. Use the language switch at the "
            "bottom of any page. Signed in, your choice follows your account. This chat answers in the "
            "language the site is shown in."
        ),
    },
    "missing_info": {
        "summary": "Something's missing or wrong: sending a link or a correction",
        "text": (
            f"If you have a link with information schoolz is missing (a newsletter, handbook, flier, menu), "
            f"submit it at {SITE}/contact/submit, or give it to this chat to submit for you. An admin reviews "
            f"everything before it goes live. For anything else, use {SITE}/contact. The **Survey** link "
            "at the bottom of every page is the best place for ideas about what to add."
        ),
    },
    "privacy": {
        "summary": "Privacy, analytics opt-out, deleting your account",
        "text": (
            f"No account is needed to browse; your picked schools are stored on your own device. The privacy "
            f"page ({SITE}/privacy) explains what's collected and has a per-device analytics opt-out. Signed "
            "in, **Account → Security → Delete this account** removes your account. That removes only what's "
            "yours; a child another guardian also follows stays for them."
        ),
    },
}


def app_help(topic: str | None = None) -> dict:
    """The full guide entry for `topic`, or the topic list when it's
    missing or unknown (so the model can pick again rather than give up)."""
    index = {key: entry["summary"] for key, entry in TOPICS.items()}
    if not topic:
        return {"topics": index}
    key = topic.strip().lower().replace(" ", "_").replace("-", "_")
    entry = TOPICS.get(key)
    if entry is None:
        return {"error": f"Unknown topic {topic!r} - pick one of these", "topics": index}
    return {"topic": key, "text": entry["text"]}
