"""localz: the help behind each holiday volunteer place, and Toys for Tots

The owner asked that every volunteering opportunity on the season pages
also be a Localz resource, since volunteers are what provide the meals,
food and gifts. So each volunteer place gets a listing for the help people
receive there, with "How you can help" saying what volunteers do and where
they sign up, and its season card links to that listing (0144's
seasonal_attractions.resource_id):

- Already on Localz from NJ 211, so only "How you can help" is added: the
  Food Bank of South Jersey, Joseph's House of Camden and MANNA.
- New listings, source "localz" (our own list, like the season pages):
  Cathedral Kitchen's free meals (NJ 211 lists only its job training),
  Center For Family Services' Holiday Gift Project, and in Philadelphia
  Philly House, Broad Street Love, St. Francis Inn, Caring for Friends,
  Cradles to Crayons, the Jewish Relief Agency and Operation Turkey.
- No listing, because nobody can come to them for help: Alloy
  Silverstein's Adopt A Family (its partner agencies pick the families,
  and it takes no requests), Love Your Park's cleanup, the Family
  Volunteer Day fair and Wreaths Across America Day.

Facts are from each organization's own pages, read by plain code with
schoolz's User-Agent (schoolz-localz/1.0) where robots.txt allows it,
checked 2026-11-04, and from 0139-0143's rows for the volunteer side. Only
general contacts are copied, never a staff member's. The Food Bank of
South Jersey's site now answers plain code with a bot challenge, so its
volunteer facts are 0140's from Nov 2.

Toys for Tots: every toysfortots.org campaign site refuses automated
reads, so no campaign's 2026 volunteer needs could be confirmed (one says,
in search results, that its volunteer slots are full). Its NJ 211 listings
get only what NJ 211 itself says they collect, new unwrapped toys, and the
Christmas page links to Toys for Tots to find your county's campaign.
Volunteer cards wait for someone to check the campaign pages by hand.

Only what's missing is added: a listing whose source and key already
exist, "How you can help" that's already filled, a card already linked
or a guide with the same season and url is left as it is.

Revision ID: 0145
Revises: 0144
Create Date: 2026-11-04 14:00:00
"""
import re
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0145"
down_revision: str | None = "0144"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKED = date(2026, 11, 4)
SOURCE = "localz"

# Localz service types (resources/provider_types.py, plus NJ 211's own
# holiday-gift code): taxonomy code, its name, and the Localz categories
# resources/categories.py gives it.
_TYPES = {
    "free_meals": ("BD-5000.8300", "Soup Kitchens", ("food",)),
    "food_pantry": ("BD-1800.2000", "Food Pantries", ("food",)),
    "home_meals": ("BD-5000.3500", "Home Delivered Meals", ("food",)),
    "clothing": ("BM-6500.1500-250", "General Clothing Provision", ("everyday-needs",)),
    "diapers": ("BM-6500.1500-150", "Diapers", ("everyday-needs", "kids-family")),
    "holiday_gifts": ("PH-2950.3200", "Holiday Gifts/Toys", ("everyday-needs",)),
}
_PHILADELPHIA = ["Philadelphia County, PA"]
_GREATER_PHILADELPHIA = [f"{c} County, PA" for c in ("Philadelphia", "Bucks", "Chester", "Delaware", "Montgomery")]


def _help(roles, how, url, donations=(), wishlist=None) -> dict:
    return {"volunteer_roles": list(roles), "volunteer_how": how, "volunteer_url": url, "donations": list(donations), "wishlist_url": wishlist}


def _listing(key: str, org: str, name: str, types: list[str], **fields) -> dict:
    defaults = dict(fees="Free.", cost_kind="free", email=None)
    return {**defaults, "source_record_id": key, "organization_name": org, "location_name": org, "name": name, "types": types, **fields}


_LISTINGS = [
    _listing(
        "cathedral-kitchen-meals",
        "Cathedral Kitchen",
        "Free meals and groceries",
        ["free_meals", "food_pantry"],
        description=(
            "Free hot meals in a restaurant-style dining room or to go, free groceries from its Mini Market Stand, "
            "and hygiene items on Mondays. Its Empowerment Coaches help with ID documents, SNAP, housing, utility "
            "bills, health insurance and getting a phone."
        ),
        address="1514 Federal St",
        city="Camden",
        postal_code="08105",
        latitude=39.94415,
        longitude=-75.10285,
        phone="856-964-6771",
        email="info@cathedralkitchen.org",
        website="https://cathedralkitchen.org/get-help/",
        hours_text=(
            "Meals: Mon - Fri 3:15 pm - 5:00 pm (eat in or take out), Sat 12:00 pm - 1:00 pm (take out only); "
            "Groceries: Mon - Fri 2:45 pm - 5:00 pm; Hygiene items: Mon 2:30 pm - 5:00 pm; "
            "Empowerment Coaches: Mon - Fri 10:00 am - 5:00 pm"
        ),
        eligibility_text="Anyone in need. Meals and services are free.",
        application_process="Come during meal hours: no sign-up or referral.",
        service_areas=["Camden County, NJ"],
        ways_to_help=_help(
            ["Serve meals in the dining room", "Work the mini market", "Make sandwiches for to-go meals",
             "Make placemats, centerpieces or utensil packets at home"],
            "16 and up on site; younger kids can make the projects at home. Shifts are posted two months ahead.",
            "https://cathedralkitchen.volunteerhub.com/vv2/",
            ["Toilet paper", "Sealed sandwich bags", "Disinfecting wipes", "Hand wipes in packets", "Bottled water",
             "Pads and tampons", "Tissue packets", "Washcloths", "Travel-size baby wipes"],
        ),
    ),
    _listing(
        "cfs-holiday-gift-project",
        "Center For Family Services",
        "Holiday Gift Project",
        ["holiday_gifts"],
        description=(
            "Holiday gifts each December for children, teens and young adults in Center For Family Services' group "
            "homes and emergency shelters, and for the families its programs serve. Staff choose and wrap gifts from "
            "each child's wish list, and where they can, parents pick the gifts for their own children."
        ),
        address="1 Alpha Ave",
        city="Voorhees",
        postal_code="08043",
        latitude=39.8594,
        longitude=-75.0107,
        phone="877-922-2377",
        email="access@centerffs.org",
        website="https://www.centerffs.org/event/holiday-gift-project",
        hours_text="Gifts go out in December through its programs. Access Center: Mon - Thu 9:00 am - 5:00 pm, Fri 9:00 am - 4:00 pm",
        eligibility_text="Children and families already served by a Center For Family Services program, including its group homes and emergency shelters.",
        application_process=(
            "A family can't sign up for the gift project itself: the gifts reach families through a Center For Family "
            "Services program. To start with one of its programs, call its Access Center or use the form on its Get Help page."
        ),
        service_areas=["Camden County, NJ"],
        ways_to_help=_help(
            ["Give new, unwrapped gifts", "Sponsor the wish list of a whole safe home"],
            "Any age can give. Drop gifts at 1 Alpha Ave, Voorhees, Tue - Thu 10am - 3pm through Fri Dec 11, or at the Cherry Hill Mall or Moorestown Mall office, Mon - Fri 10am - 4pm.",
            "https://www.centerffs.org/event/holiday-gift-project",
            ["New, unwrapped gifts", "Gift cards: ShopRite, ACME, Amazon, Walmart, Target or Dollar Tree", "Wrapping paper and gift bags"],
        ),
    ),
    _listing(
        "philly-house-meals",
        "Philly House",
        "Free lunch and dinner",
        ["free_meals"],
        description=(
            "Free hot lunch and dinner every day of the year, served at tables in Center City, to anyone who walks in. "
            "Philly House (once the Sunday Breakfast Rescue Mission) also runs a 30-day emergency shelter for men and "
            "a free JeffHope medical clinic on Tuesdays, 5:00 pm - 9:30 pm."
        ),
        address="302 N 13th St",
        city="Philadelphia",
        postal_code="19107",
        latitude=39.95824,
        longitude=-75.16019,
        phone="215-922-6400",
        email="info@phillyhouse.org",
        website="https://www.phillyhouse.org/what-we-do/free-meals-for-all",
        hours_text="Every day: lunch 12:00 pm - 1:00 pm, dinner 5:00 pm - 6:00 pm",
        eligibility_text="Anyone, of any gender: women are welcome for meals. Breakfast is only for registered shelter guests.",
        application_process="Walk in at mealtime. For a shelter bed (men only), call ahead to make sure one is free.",
        service_areas=_PHILADELPHIA,
        ways_to_help=_help(
            ["Serve lunch or dinner, then share the meal with a guest", "Organize the food warehouse"],
            "18 and up on site; younger volunteers can help with its off-site projects.",
            "https://phillyhouse.volunteerhub.com/",
            wishlist="https://www.amazon.com/hz/wishlist/ls/3KPND4LS3TTXB",
        ),
    ),
    _listing(
        "broad-street-love-lunch",
        "Broad Street Love",
        "Free weekday lunch",
        ["free_meals", "clothing"],
        description=(
            "A sit-down, chef-prepared lunch served restaurant-style every weekday. Guests can also get a free mailing "
            "address (for ID and benefits), up to five items from its clothing boutique by appointment, toiletries, "
            "socks and underwear, and help from a concierge with jobs, benefits, health care and housing."
        ),
        address="315 S Broad St",
        city="Philadelphia",
        postal_code="19107",
        latitude=39.94615,
        longitude=-75.16479,
        phone="215-735-4847",
        email="info@broadstreetlove.org",
        website="https://broadstreetlove.org/our-services/",
        hours_text="Mon - Fri 11:30 am - 3:00 pm; lunch 11:30 am - 1:15 pm; closed weekends",
        eligibility_text="Anyone: lunch is open to all.",
        application_process=(
            "Walk in on a weekday. Mailbox sign-ups are Mon and Thu, 12:00 pm - 2:00 pm; clothing boutique "
            "appointments are made on Wednesday for Thursday or Friday."
        ),
        service_areas=_PHILADELPHIA,
        ways_to_help=_help(
            ["Serve the restaurant-style lunch", "Sort and hand out guests' mail", "Personal shopper in the clothing boutique",
             "Sort clothing donations"],
            "18 and up; groups of up to 16 adults, with training at the start of each shift.",
            "https://broadstreetlove.volunteerhub.com/vv2/",
            ["New toothbrushes and toothpaste", "Deodorant", "Body wash, bar soap and lotion", "New underwear",
             "Shampoo and conditioner", "Pads, tampons and liners", "Razors and shaving cream", "Hand sanitizer and wipes"],
        ),
    ),
    _listing(
        "st-francis-inn-meals",
        "St. Francis Inn",
        "Free daily meals",
        ["free_meals", "clothing", "diapers"],
        description=(
            "A restaurant-style soup kitchen in Kensington, open every day of the year, serving up to 350 plates a day. "
            "Diapers (child and adult) and feminine products every day, toiletries on Mon, Wed and Sat, and a weekly "
            "outfit from Marie's Closet next door, at 2439 Kensington Ave."
        ),
        address="2441 Kensington Ave",
        city="Philadelphia",
        postal_code="19125",
        latitude=39.98692,
        longitude=-75.13067,
        phone="215-423-5845",
        email="info@stfrancisinn.org",
        website="https://stfrancisinn.org/our-ministries",
        hours_text=(
            "Seated meals: Mon - Thu 4:30 pm - 6:00 pm, Fri - Sun 11:30 am - 1:00 pm; take-away breakfast: "
            "Tue - Thu 10:00 am - 11:00 am; Marie's Closet: Mon 9:30 am - 11:00 am (families with children), "
            "Wed - Thu 9:30 am - 11:30 am"
        ),
        eligibility_text="Anyone in need, including families with children.",
        application_process="Walk in at mealtime. Marie's Closet gives each guest clothes once a week.",
        service_areas=_PHILADELPHIA,
        ways_to_help=_help(
            ["Seat, serve and bus tables at meals", "Help the kitchen staff prepare meals", "Sort and hand out clothing at Marie's Closet"],
            "No age posted for meal service, so ask when you sign up; groups of fewer than eight.",
            "https://stfrancisinn.org/volunteer/",
            ["Ground coffee", "Paper towels", "Deodorant", "Body wash", "Hygiene kits", "Men's and women's underwear",
             "Blankets", "Men's pants, waist 30-36"],
            "https://www.amazon.com/hz/wishlist/ls/I74F0KEM2E97/",
        ),
    ),
    _listing(
        "caring-for-friends-meals",
        "Caring for Friends",
        "Home-delivered meals and visits",
        ["home_meals"],
        description=(
            "Volunteers bring prepared frozen meals to homebound seniors, veterans and people with disabilities, and "
            "stay for a short visit, weekly or every other week."
        ),
        address="12271 Townsend Rd",
        city="Philadelphia",
        postal_code="19154",
        latitude=40.10267,
        longitude=-74.98477,
        phone="215-464-2224",
        email="info@caringforfriends.org",
        website="https://caringforfriends.org/find-food/",
        hours_text="Office: Mon - Fri 9:00 am - 5:00 pm; visits are set up with each person",
        eligibility_text="Homebound seniors, veterans and people with disabilities in the Philadelphia area.",
        application_process=(
            "Fill out the referral form on its Find Food page, for yourself or for someone else. If it's a match, "
            "someone calls to set up the first visit; allow one to two weeks."
        ),
        service_areas=_GREATER_PHILADELPHIA,
        ways_to_help=_help(
            ["Deliver meals and visit a homebound neighbor", "Cook in its kitchen", "Pack snack bags",
             "Sort and pack food in the warehouse"],
            "Snack bags from age 8, the kitchen from 12; under 16 with an adult.",
            "https://volunteer.bloomerang.co/JE/y9z8wzmzp55c3x",
            ["Canned beans, chicken, fish and vegetables", "Canned fruit", "Canned soup, stew and chili",
             "Boxed rice and pasta", "Peanut butter and jelly"],
        ),
    ),
    _listing(
        "cradles-to-crayons-philadelphia",
        "Cradles to Crayons Philadelphia",
        "Children's clothing and essentials, through partner agencies",
        ["clothing", "diapers"],
        description=(
            "Free bundles for a child: seasonal clothing, coats, shoes, socks, underwear and pajamas, diapers and "
            "wipes, hygiene items and school supplies, packed by volunteers at its Giving Factory and handed out by "
            "more than 160 partner agencies, such as social service agencies and schools. Families don't pick up here."
        ),
        address="4700 Wissahickon Ave, Suite 142",
        city="Philadelphia",
        postal_code="19144",
        latitude=40.01658,
        longitude=-75.17122,
        phone="215-836-0958",
        website="https://www.cradlestocrayons.org/philadelphia/family-assistance/",
        hours_text="Through partner agencies only; nothing is handed out at its warehouse",
        eligibility_text="Children in families in need around Greater Philadelphia; each partner agency decides who qualifies.",
        application_process=(
            "A family can't apply to Cradles to Crayons directly. Find a partner agency by ZIP code on its Family "
            "Assistance page, or ask your social worker or case manager to place an order for you."
        ),
        service_areas=_GREATER_PHILADELPHIA,
        ways_to_help=_help(
            ["Sort and pack bundles in the Giving Factory", "Host a clothing drive"],
            "5 and up; anyone under 18 needs an adult volunteering alongside them. Register in its volunteer portal first.",
            "https://vms.cradlestocrayons.org/",
            ["New underwear and socks", "Baby clothes", "Winter coats, hats and gloves", "Shoes and snow boots", "School supplies"],
            "https://www.amazon.com/hz/wishlist/ls/1KLQZ04V2T96T",
        ),
    ),
    _listing(
        "jra-food-box",
        "Jewish Relief Agency",
        "Monthly food box delivered to your home",
        ["food_pantry"],
        description=(
            "A free monthly box of kosher pantry staples and produce, about 15 pounds, delivered to your door by "
            "volunteers, with holiday foods four times a year and an extra bag of kid-friendly food for families with "
            "children. Household items, diapers and a social worker's help are available by request."
        ),
        address="10980 Dutton Rd",
        city="Philadelphia",
        postal_code="19154",
        latitude=40.0912,
        longitude=-74.98729,
        phone="610-660-0190",
        email="gethelp@jewishrelief.org",
        website="https://jewishrelief.org/request-services",
        hours_text="Delivered once a month, Sunday to Tuesday (Nov 15 - 17 and Dec 13 - 15, 2026)",
        eligibility_text=(
            "Anyone in its delivery area (Greater Philadelphia and parts of South Jersey) with a household income at or "
            "below 185% of the federal poverty guideline, of any religion."
        ),
        application_process=(
            "Fill out the eligibility form on its Request Services page, which checks your ZIP code; staff contact you "
            "if you qualify. Call or text with questions."
        ),
        service_areas=_GREATER_PHILADELPHIA,
        ways_to_help=_help(
            ["Pack the monthly food boxes", "Deliver boxes to families' homes", "JRA Juniors: pack with kids under 10",
             "Make caring cards at home"],
            "The 10am packing shift is for all ages; register ahead.",
            "https://jewishrelief.org/register-to-volunteer",
            ["Kosher canned tuna", "Toilet paper", "Paper towels", "Tissues", "Laundry detergent",
             "Toothpaste and toothbrushes", "Baby wipes, diapers and pull-ups", "Adult incontinence supplies"],
        ),
    ),
    _listing(
        "operation-turkey-philadelphia",
        "Operation Turkey",
        "Thanksgiving Day meal delivery",
        ["home_meals"],
        description=(
            "Volunteers cook at The Common Place in West Philadelphia and deliver free plated Thanksgiving meals "
            "(turkey, stuffing and vegetables) to people who asked for them, and hand out meals, care packages and "
            "clothing to people who are homeless."
        ),
        address="5736 Chester Ave",
        city="Philadelphia",
        postal_code="19143",
        latitude=39.936,
        longitude=-75.22805,
        phone="866-678-8751",
        email="info@operationturkey.com",
        website="https://www.operationturkey.com/meal-request/",
        hours_text="Thanksgiving Day, Thu Nov 26, 2026: deliveries 10:00 am - 2:00 pm",
        eligibility_text="People who are homeless or in need in its delivery area; one plate per person.",
        application_process=(
            "Request meals with the form on its Meal Request page, open until the meals run out or Fri Nov 20, "
            "whichever comes first. To ask for someone else, email meals@operationturkey.com."
        ),
        service_areas=[f"{c} County, PA" for c in ("Philadelphia", "Chester", "Delaware")],
        ways_to_help=_help(
            ["The night before: smoke turkeys and sort donations", "Thanksgiving morning: cook, plate and pack meals",
             "Drive meals to people's homes"],
            "Kids are welcome with a parent or guardian; under 16, sign up by email.",
            "https://www.operationturkey.com/volunteer/",
            ["Toiletries for care packages", "Clothing", "Drinks and dinner rolls", "Thawed turkeys"],
        ),
    ),
]

# NJ 211 listings that are already on Localz: (organization, listing name) -> "How you can help".
_NJ211_HELP = {
    ("Food Bank of South Jersey (FBSJ)", "Food Bank Locator"): _help(
        ["Pack and sort donated food in the warehouse", "Assemble food boxes for partner pantries"],
        "13 and up; 13-17 with a parent, guardian or chaperone there. Daytime warehouse shifts; sign up ahead.",
        "https://foodbanksj.org/donate-time/#VolForm",
    ),
    ("Joseph's House", "Emergency Shelter"): _help(
        ["Prepare and serve breakfast or dinner", "Greet and talk with guests", "Sort food, clothes and toiletries",
         "Help guests in the computer room", "Lead a group activity"],
        "Breakfast 5:30-6:30am, dinner 8-9:30pm, or weekdays 9am-2pm in two-hour slots. Groups can bring a casserole ready to heat.",
        "https://www.jhoc.org/volunteer",
        ["Toiletries", "Clothing", "Food"],
    ),
    ("Metropolitan Area Neighborhood Nutrition Alliance (MANNA)", "Meals"): _help(
        ["Prepare food and pack meals in the kitchen", "Drive meals to people's homes"],
        "14 and up; under 18 needs a parent's signed consent form.",
        "https://mannapa.org/volunteer/volunteer-at-manna/",
    ),
}
# Every Toys for Tots campaign on NJ 211: what NJ 211 says it collects.
_TOYS_FOR_TOTS_ORG = "Toys for Tots"
_TOYS_FOR_TOTS_HELP = _help([], None, None, ["New, unwrapped toys"])

# Each season card's listing: a key of _LISTINGS or of _NJ211_HELP. A
# volunteer place left out of this map must be in _NO_LISTING.
_CARD_LISTINGS = {
    "Food Bank of South Jersey": ("Food Bank of South Jersey (FBSJ)", "Food Bank Locator"),
    "Joseph's House of Camden": ("Joseph's House", "Emergency Shelter"),
    "MANNA": ("Metropolitan Area Neighborhood Nutrition Alliance (MANNA)", "Meals"),
    "Cathedral Kitchen": "cathedral-kitchen-meals",
    "Center For Family Services Holiday Gift Project": "cfs-holiday-gift-project",
    "Philly House": "philly-house-meals",
    "Broad Street Love": "broad-street-love-lunch",
    "St. Francis Inn": "st-francis-inn-meals",
    "Caring for Friends": "caring-for-friends-meals",
    "Cradles to Crayons Giving Factory": "cradles-to-crayons-philadelphia",
    "Jewish Relief Agency food box packing": "jra-food-box",
    "Operation Turkey Philadelphia": "operation-turkey-philadelphia",
}
_NO_LISTING = {
    "Alloy Silverstein's Adopt A Family": "Partner agencies pick the families; it takes no requests.",
    "Love Your Park Fall Weekend": "A park cleanup.",
    "Family Volunteer Day Fair": "A fair for volunteers.",
    "Wreaths Across America Day at Washington Crossing": "A wreath-laying for veterans.",
}

_GUIDES = [
    (
        "winter",
        "Find your Toys for Tots campaign",
        "Marine Toys for Tots",
        "https://www.toysfortots.org/",
        "Drop off a new, unwrapped toy for a child in need, or ask for toys for your own kids: each county's campaign posts its own drop-off sites and request dates.",
        date(2026, 11, 13),
        date(2026, 12, 24),
        57,  # after USPS Operation Santa, so the page's banner doesn't move
    ),
]


def name_key(name: str) -> str:
    """resources/refresh.py's organization key."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


# resources/categories.py's nav order, which a listing's categories follow.
_NAV = ("food", "english", "housing-bills", "health", "kids-family", "money-work", "legal-safety", "everyday-needs")


def categories(types: list[str]) -> list[str]:
    wanted = {c for t in types for c in _TYPES[t][2]}
    return [c for c in _NAV if c in wanted]


def missing_core(row: dict) -> list[str]:
    """resources/refresh.py's required core."""
    checks = {
        "name": row.get("name"),
        "address": row.get("address") or row.get("service_areas"),
        "hours": row.get("hours_text"),
        "phone": row.get("phone"),
        "services": row.get("types"),
    }
    return [field for field, value in checks.items() if not value]


_services = sa.table(
    "resource_services",
    *[sa.column(c) for c in ("id", "organization_id", "source", "source_record_id", "name", "organization_name", "location_name",
                             "description", "phone", "email", "website", "address", "city", "postal_code", "hours_text",
                             "eligibility_text", "application_process", "fees", "status", "address_kind", "cost_kind")],
    sa.column("latitude", sa.Float()),
    sa.column("longitude", sa.Float()),
    *[sa.column(c, sa.ARRAY(sa.Text())) for c in ("service_areas", "taxonomy_codes", "taxonomy_names", "categories", "missing_core")],
    sa.column("ways_to_help", JSONB()),
    sa.column("last_assured_on", sa.Date()),
    sa.column("first_seen_at", sa.DateTime(timezone=True)),
    sa.column("last_seen_at", sa.DateTime(timezone=True)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_orgs = sa.table(
    "resource_organizations",
    *[sa.column(c) for c in ("id", "name", "name_key", "url")],
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_attractions = sa.table("seasonal_attractions", sa.column("id"), sa.column("kind"), sa.column("name"), sa.column("resource_id"))
_guides = sa.table(
    "seasonal_guides",
    *[sa.column(c) for c in ("id", "season", "title", "publisher", "url", "note")],
    sa.column("starts_on", sa.Date()),
    sa.column("ends_on", sa.Date()),
    sa.column("sort_order", sa.Integer()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def _organization_id(conn, name: str, url: str | None, now: datetime) -> str:
    key = name_key(name)
    found = conn.execute(sa.select(_orgs.c.id).where(_orgs.c.name_key == key)).scalar()
    if found:
        return found
    org_id = str(uuid.uuid4())
    conn.execute(_orgs.insert().values(id=org_id, name=name, name_key=key, url=url, created_at=now, updated_at=now))
    return org_id


def _nj211_id(conn, org: str, name: str) -> str | None:
    s = _services.c
    return conn.execute(
        sa.select(s.id).where(s.source == "nj211", s.organization_name == org, s.name == name).order_by((s.status == "active").desc()).limit(1)
    ).scalar()


def upgrade() -> None:
    conn = op.get_bind()
    now = datetime.now(UTC)
    s = _services.c
    have = set(conn.execute(sa.select(s.source_record_id).where(s.source == SOURCE)).scalars())
    for row in _LISTINGS:
        if row["source_record_id"] in have:
            continue
        values = {k: v for k, v in row.items() if k != "types"}
        conn.execute(
            _services.insert().values(
                id=str(uuid.uuid4()),
                organization_id=_organization_id(conn, row["organization_name"], row["website"], now),
                source=SOURCE,
                status="active",
                address_kind="public",
                taxonomy_codes=[_TYPES[t][0] for t in row["types"]],
                taxonomy_names=[_TYPES[t][1] for t in row["types"]],
                categories=categories(row["types"]),
                missing_core=missing_core(row),
                last_assured_on=_CHECKED,
                first_seen_at=now,
                last_seen_at=now,
                created_at=now,
                updated_at=now,
                **values,
            )
        )

    for (org, name), ways in _NJ211_HELP.items():
        conn.execute(
            _services.update()
            .where(s.source == "nj211", s.organization_name == org, s.name == name, s.ways_to_help.is_(None))
            .values(ways_to_help=ways, updated_at=now)
        )
    conn.execute(
        _services.update()
        .where(s.source == "nj211", s.organization_name == _TOYS_FOR_TOTS_ORG, s.name.like("Holiday Toy Assistance%"), s.ways_to_help.is_(None))
        .values(ways_to_help=_TOYS_FOR_TOTS_HELP, updated_at=now)
    )

    for card, target in _CARD_LISTINGS.items():
        if isinstance(target, tuple):
            listing_id = _nj211_id(conn, *target)
        else:
            listing_id = conn.execute(sa.select(s.id).where(s.source == SOURCE, s.source_record_id == target)).scalar()
        if listing_id:
            a = _attractions.c
            conn.execute(
                _attractions.update().where(a.kind == "volunteer", a.name == card, a.resource_id.is_(None)).values(resource_id=listing_id)
            )

    g = _guides.c
    have_guides = {tuple(r) for r in conn.execute(sa.select(g.season, g.url))}
    rows = [
        dict(id=str(uuid.uuid4()), season=season, title=title, publisher=publisher, url=url, note=note,
             starts_on=starts, ends_on=ends, sort_order=order, created_at=now, updated_at=now)
        for season, title, publisher, url, note, starts, ends, order in _GUIDES
        if (season, url) not in have_guides
    ]
    if rows:
        op.bulk_insert(_guides, rows)


def downgrade() -> None:
    s = _services.c
    keys = [row["source_record_id"] for row in _LISTINGS]
    ids = sa.select(s.id).where(s.source == SOURCE, s.source_record_id.in_(keys))
    op.execute(_attractions.update().where(_attractions.c.resource_id.in_(ids)).values(resource_id=None))
    op.execute(_services.delete().where(s.source == SOURCE, s.source_record_id.in_(keys)))
    for season, _title, _publisher, url, *_rest in _GUIDES:
        op.execute(_guides.delete().where(_guides.c.season == season, _guides.c.url == url))
