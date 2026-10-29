"""What Neighborz offers - the utilities a bill can be from, the avatars, the
thank-you emojis - and its limits. Fixed in code on purpose: a requester
picks from these and never types anything another person sees
(docs/NEIGHBORZ_DESIGN.md, principles 2 and 3)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Utility:
    key: str
    name: str
    # Words that identify the company on its own bill (matched case-blind).
    names_on_bill: tuple[str, ...]
    # Lengths an account number can have, digits only.
    account_digits: tuple[int, int]
    # Where and how a giver pays as a guest. Added only for a utility whose
    # guest payment needs nothing but account number, ZIP and amount.
    pay_url: str | None
    pay_phone: str | None


UTILITIES: tuple[Utility, ...] = (
    # Account number length and the phone line are to be confirmed against a
    # real bill and a real guest payment before launch (design, build order 0).
    Utility(
        key="pseg",
        name="PSE&G",
        names_on_bill=("pse&g", "pseg", "public service electric"),
        account_digits=(8, 12),
        pay_url="https://nj.myaccount.pseg.com/ViewMyBill/WaysToPay",
        pay_phone=None,
    ),
)
BY_KEY = {u.key: u for u in UTILITIES}

# Cartoon animals; the frontend ships one SVG per key
# (frontend/src/pages/localz/bills/avatars/).
AVATARS: tuple[str, ...] = (
    "fox", "owl", "panda", "cat", "dog", "rabbit", "bear", "koala",
    "tiger", "lion", "frog", "penguin", "turtle", "hedgehog", "raccoon", "otter",
    "unicorn", "monkey", "chick", "whale", "octopus", "butterfly", "bee", "elephant",
)

# The only thing a requester can send back: one of these, once.
EMOJIS: dict[str, str] = {
    "heart": "❤️",
    "pray": "\U0001f64f",
    "smile": "\U0001f60a",
    "party": "\U0001f389",
    "bulb": "\U0001f4a1",
    "sunflower": "\U0001f33b",
}

# Limits (design, "Limits"). The owner sets the numbers.
MIN_ASK_CENTS = 500
MAX_ASK_CENTS = 50_000
HOLD = timedelta(hours=24)
HOLD_WARNING = timedelta(hours=2)  # "your hold ends soon" email this long before
ANSWER_WAIT = timedelta(days=7)  # no answer from the requester: paid on the giver's word
LISTING_LIFE = timedelta(days=30)
DRAFT_LIFE = timedelta(hours=24)
REVIEW_WAIT = timedelta(days=7)  # a held bill nobody reviewed is rejected
PAID_SHOWN = timedelta(days=7)  # a paid bill stays on the public list this long
ERASE_AFTER = timedelta(days=30)  # account number, ZIP and image of a closed bill
ACCOUNT_REPEAT = timedelta(days=60)  # one paid listing per utility account
GIVER_MIN_AGE = timedelta(hours=24)
# Holds a giver can start in a day, whatever becomes of them: letting go is
# free, so without this hold-read-release could collect account numbers.
HOLDS_PER_DAY = 3
STRIKE_WINDOW = timedelta(days=90)
STRIKES_TO_PAUSE = 2
DISPUTES_TO_HOLD = 2  # a requester with this many disputes in STRIKE_WINDOW is reviewed
UPLOADS_PER_DAY = 5
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
OLDEST_DUE = timedelta(days=60)  # a due date further past than this is held

# Why a bill was held for a reviewer. Set in code, never by the model.
FLAGS = {
    "account_unreadable": "The account number couldn't be read or isn't the usual length",
    "edited_account": "The requester changed the account number or ZIP that was read",
    "zip_not_nj": "The service ZIP isn't a New Jersey ZIP",
    "amount_unreadable": "No amount due could be read",
    "due_date_old": "The due date is more than 60 days past",
    "not_residential": "The bill looks like a business account",
    "repeat_disputes": "This requester said a payment hadn't arrived twice in 90 days",
}
REJECT_REASONS = {
    "not_their_bill": "It doesn't look like the requester's own bill",
    "not_residential": "A business account",
    "unreadable": "The bill couldn't be checked",
    "other": "Something else didn't check out",
}
