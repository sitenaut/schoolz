"""The chatbot's get_district_budget: finding the district a visitor names, and
answering with what the district's /budgets page shows."""

import json
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from mcp_server import _budget_answer, _match_districts
from models import District, School, User
from services.chatbot import _run_tool


def _d(name: str, county: str = "Camden") -> dict:
    return {"slug": name.lower().replace(" ", "-"), "name": name, "county": county}


INDEX = [
    _d("Cherry Hill Public Schools"),
    _d("Medford Township School District", "Burlington"),
    _d("Medford Lakes Borough School District", "Burlington"),
    _d("Berlin Borough School District"),
    _d("Berlin Township Public Schools"),
    _d("Camden City School District"),
    _d("Camden County Technical Schools"),
    _d("Alloway Twp School District", "Salem"),
]


def _names(matches: list[dict]) -> list[str]:
    return sorted(d["name"] for d in matches)


def test_a_district_is_found_by_its_town_however_the_visitor_says_it():
    assert _names(_match_districts("Cherry Hill", INDEX)) == ["Cherry Hill Public Schools"]
    assert _names(_match_districts("Cherry Hill Township schools", INDEX)) == ["Cherry Hill Public Schools"]
    assert _names(_match_districts("Alloway Township", INDEX)) == ["Alloway Twp School District"]
    # A name that is exactly the town beats a longer one; Camden is the city's district.
    assert _names(_match_districts("Medford", INDEX)) == ["Medford Township School District"]
    assert _names(_match_districts("Camden", INDEX)) == ["Camden City School District"]


def test_a_town_with_two_districts_is_asked_about_unless_the_visitor_said_which():
    assert _names(_match_districts("Berlin", INDEX)) == ["Berlin Borough School District", "Berlin Township Public Schools"]
    assert _names(_match_districts("Berlin Township", INDEX)) == ["Berlin Township Public Schools"]
    assert _match_districts("Haddonfield", INDEX) == []
    assert _match_districts("school district", INDEX) == []


BUDGET = {
    "slug": "testville-school-district", "name": "Testville School District", "county": "Camden", "state": "NJ",
    "budget_year": "2026-27", "comparable": True, "schools": [{"slug": "testville-elementary", "name": "Testville Elementary"}],
    "benefits_prior": 1_000_000, "benefits_budget": 1_200_000, "other_spending_prior": 4_000_000, "other_spending_budget": 4_100_000,
    "prior_basis": "original", "formula_aid_change": -50_000, "levy_prior": 3_000_000, "levy_budget": 3_060_000, "levy_change_pct": 2.0,
    "fund_balance_prior": 300_000, "fund_balance_budget": 0, "budget_report_url": "https://www.nj.gov/report.pdf",
    "aid_source_url": "https://www.nj.gov/aid.xlsx",
    "health_costs": {"start": {"year": "2023-24", "value": 800_000, "url": "https://district.example/acfr24.pdf"},
                     "end": {"year": "2024-25", "value": 880_000, "url": "https://district.example/acfr25.pdf"}},
    "staffing": {"students_per_teacher": {"start": {"year": "2023-24", "value": 11.24}, "end": {"year": "2024-25", "value": 11.5}},
                 "median_teacher_salary": {"year": "2024-25", "value": 81_000}, "url": "https://rc.doe.state.nj.us/"},
    "statements": [{"topic": "Health benefits", "quote": "Health costs rose", "source": "Budget presentation",
                    "url": "https://district.example/budget.pdf", "date": "2026-03-17"}],
    "medians": {"benefits_change_pct": {"county": 8.0, "state": 7.5}, "levy_change_pct": {"county": None, "state": 2.0},
                "students_per_teacher": {"county": 11.8, "state": 12.0}},
    "imported_at": "2026-10-25T00:00:00Z",
}


def test_the_answer_reads_like_the_page():
    a = _budget_answer(BUDGET, "https://schoolz.example/budgets/testville-school-district")
    assert a["page"].endswith("/budgets/testville-school-district") and a["budget_year"] == "2026-27"
    assert a["day_to_day_spending"]["2025-26"] == "$5.0 million" and a["day_to_day_spending"]["2026-27"] == "$5.3 million"
    benefits = a["employee_benefits"]
    assert (benefits["change"], benefits["share_of_day_to_day_spending"]) == ("+20.0%", "22.6%")
    assert benefits["note"] == "The 2025-26 figure is the original budget; no revised one was filed."
    assert benefits["medians_of_the_change"] == {"Camden County median": "+8.0%", "New Jersey median": "+7.5%"}
    # The levy's change is the state's own percentage; a missing county median is left out.
    assert a["local_school_tax_levy"]["change"] == "+2.0%"
    assert a["local_school_tax_levy"]["medians_of_the_change"] == {"New Jersey median": "+2.0%"}
    assert a["state_school_aid"] == "Down $50,000 from last year"
    assert a["health_insurance_costs_audited"]["change"] == "+10.0%"
    assert a["students_per_teacher"]["2023-24"] == "11.2" and a["students_per_teacher"]["medians"]["New Jersey median"] == "12.0"
    assert a["median_teacher_salary"] == {"2024-25": "$81,000"}
    assert a["district_says"] == BUDGET["statements"] and a["schools_on_schoolz"] == ["Testville Elementary"]
    assert a["sources"]["audited_reports"] == ["https://district.example/acfr24.pdf", "https://district.example/acfr25.pdf"]
    assert "never rank" in a["about"]


AID = {
    "k12": {"start": {"year": "2025-26", "value": 28_592_928, "url": "https://www.nj.gov/aid26.xlsx"},
            "end": {"year": "2026-27", "value": 27_735_140, "url": "https://www.nj.gov/aid27.xlsx"}},
    "categories": [{"key": "equalization", "start": 0, "end": 5_413_149}, {"key": "special_education", "start": 19_431_379, "end": 15_154_725}],
    "limit_pct": -3.0,
    "preschool": {"start": {"year": "2025-26", "value": 7_489_660, "url": "https://www.nj.gov/pre26.xlsx"},
                  "end": {"year": "2026-27", "value": 12_634_490, "url": "https://www.nj.gov/pre27.xlsx"}},
}
IDEA = {"start": {"year": "2025-26", "value": 2_997_170, "url": "https://www.nj.gov/idea26.xlsx"},
        "end": {"year": "2026-27", "value": 2_967_017, "url": "https://www.nj.gov/idea27.xlsx"},
        "private_school_share": 310_427, "preliminary": True}


def test_state_aid_by_category_preschool_aid_and_the_idea_grant_read_like_the_page():
    medians = {**BUDGET["medians"], "state_aid_change_pct": {"county": -1.0, "state": 2.5}}
    a = _budget_answer({**BUDGET, "state_aid": AID, "idea_grant": IDEA, "medians": medians}, "https://schoolz.example/budgets/x")
    assert "state_school_aid" not in a
    k12 = a["state_school_aid_k12"]
    assert (k12["2025-26"], k12["2026-27"], k12["change"]) == ("$28.6 million", "$27.7 million", "-3.0%")
    assert k12["by_category"]["Equalization aid"] == {"2025-26": "$0", "2026-27": "$5.4 million"}
    assert "can fall by no more than 3% a year" in k12["limit"] and "cut them further" in k12["limit"]
    assert k12["medians_of_the_change"] == {"Camden County median": "-1.0%", "New Jersey median": "+2.5%"}
    assert a["state_preschool_aid"]["change"] == "+68.7%" and "only be spent on preschool" in a["state_preschool_aid"]["what"]
    idea = a["federal_special_education_grant_idea"]
    assert idea["change"] == "-1.0%" and idea["note"] == "The 2026-27 award is the state's preliminary figure."
    assert idea["set_aside_for_students_placed_in_private_schools_by_their_parents"] == "$310,427"
    assert a["sources"]["state_aid_files"] == ["https://www.nj.gov/aid26.xlsx", "https://www.nj.gov/aid27.xlsx",
                                               "https://www.nj.gov/pre26.xlsx", "https://www.nj.gov/pre27.xlsx"]
    assert a["sources"]["idea_award_files"] == ["https://www.nj.gov/idea26.xlsx", "https://www.nj.gov/idea27.xlsx"]


def test_a_district_that_isnt_comparable_gets_no_medians():
    a = _budget_answer({**BUDGET, "comparable": False}, "https://schoolz.example/budgets/x")
    assert "medians_of_the_change" not in a["employee_benefits"] and "medians" not in a["students_per_teacher"]
    assert "Don't compare it" in a["medians_note"]


def test_figures_the_page_leaves_out_are_left_out():
    bare = {**BUDGET, "other_spending_prior": None, "other_spending_budget": None, "levy_prior": None, "levy_budget": None,
            "health_costs": None, "staffing": None, "statements": [], "prior_basis": "revised"}
    a = _budget_answer(bare, "https://schoolz.example/budgets/x")
    assert "day_to_day_spending" not in a and "everything_else" not in a and "health_insurance_costs_audited" not in a
    assert "note" not in a["employee_benefits"] and "share_of_day_to_day_spending" not in a["employee_benefits"]
    assert a["local_school_tax_levy"] == {"change": "+2.0%", "medians_of_the_change": {"New Jersey median": "+2.0%"}}


async def _admin(client: AsyncClient) -> dict:
    run_id = uuid.uuid4().hex[:8]
    email = f"admin_{run_id}@example.com"
    reg = await client.post("/auth/register", json={"email": email, "username": f"admin_{run_id}", "password": "password123"})
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"authorization": f"Bearer {reg.json()['access_token']}"}


def _row(code: str, name: str, county: str) -> dict:
    return {"state_code": code, "name": name, "slug": f"district-{code.lower()}", "county": county, "comparable": True,
            "benefits_prior": 1_000_000, "benefits_budget": 1_200_000, "levy_change_pct": 4.5}


async def _ask(district: str, county: str | None = None) -> dict:
    args = {"district": district, **({"county": county} if county else {})}
    return json.loads(await _run_tool(app.state.mcp, "get_district_budget", args))


@pytest.mark.anyio
async def test_the_tool_finds_a_district_by_name_town_or_one_of_its_schools():
    tag = uuid.uuid4().hex[:8]
    town = f"Zedville{tag}"
    codes = [f"{c}{tag[:6].upper()}" for c in "TUV"]
    async with database.SessionLocal() as db:
        district = District(name=f"{town} Township Public Schools", state="NJ", state_code=codes[0])
        db.add(district)
        await db.flush()
        db.add_all([
            School(name=f"{town} Elementary", slug=f"zedville-elementary-{tag}", district_id=district.id, school_type="elementary"),
            School(name=f"{town} Middle", slug=f"zedville-middle-{tag}", district_id=district.id, school_type="middle"),
            # A private preschool filed under the district for the town picker.
            School(name=f"Little Sprouts {tag}", slug=f"little-sprouts-{tag}", district_id=district.id, school_type="other"),
        ])
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post("/admin/budget/import", headers=await _admin(client), json={
            "source_commit": "1af77f0", "budget_year": "2026-27",
            "districts": [_row(codes[0], f"{town} Township Public Schools", "Camden"),
                          _row(codes[1], f"{town} Borough School District", "Gloucester"),
                          _row(codes[2], f"{town} Borough School District", "Salem")]})
        assert r.status_code == 200, r.text

    # Several fit and schoolz tracks one: that one, naming the others.
    tracked = await _ask(town)
    assert tracked["district"] == f"{town} Township Public Schools"
    assert sorted(tracked["other_districts_with_this_name"]["districts"]) == [
        f"{town} Borough School District (Gloucester County)", f"{town} Borough School District (Salem County)"]
    # Several fit and none is tracked: ask which, unless the county says.
    both = await _ask(f"{town} Borough")
    assert {d["county"] for d in both["did_you_mean"]} == {"Gloucester", "Salem"} and "which one" in both["hint"]
    by_county = await _ask(f"{town} Borough", county="Gloucester County")
    assert by_county["district"] == f"{town} Borough School District" and "other_districts_with_this_name" not in by_county
    assert by_county["page"].endswith(f"/budgets/district-{codes[1].lower()}")
    assert by_county["employee_benefits"]["change"] == "+20.0%"

    assert (await _ask(f"{town} Township"))["district"] == f"{town} Township Public Schools"
    assert (await _ask(f"district-{codes[0].lower()}"))["district"] == f"{town} Township Public Schools"
    # A school, by slug or by name, answers for its district; so do two that fit, being one district's.
    assert (await _ask(f"zedville-elementary-{tag}"))["district"] == f"{town} Township Public Schools"
    assert (await _ask(f"{town} High School"))["schools_on_schoolz"] == [f"{town} Elementary", f"{town} Middle"]

    assert "isn't one of a New Jersey district's own" in (await _ask(f"Little Sprouts {tag}"))["error"]
    missing = await _ask(f"Nowhere{tag}")
    assert "No New Jersey school district" in missing["error"] and "town" in missing["hint"]
